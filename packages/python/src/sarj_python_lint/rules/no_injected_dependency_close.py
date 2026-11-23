from __future__ import annotations

import ast
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, final, override

from sarj_python_lint.rule_base import (
    AutofixPolicy,
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    Rule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
    Severity,
)
from sarj_python_lint.rules._paths import is_test_path, is_test_support_path


if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

    from sarj_python_lint._file_context import PythonFileContext

_CLEANUP_METHODS = frozenset({"close", "aclose", "__exit__", "__aexit__"})
_CLOSERS = frozenset({"close", "aclose", "shutdown", "__exit__", "__aexit__"})
_CALLBACK_REGISTRATIONS = frozenset({"callback", "push_async_callback"})
_EXIT_REGISTRATIONS = frozenset({"push", "push_async_exit"})
_MESSAGE = (
    "{owner}.{method} cleans up self.{attribute}, which __init__ receives from its caller; register that cleanup "
    "where it is constructed, such as the composition root or lifespan exit stack."
)

_CONSUMER = """\
from contextlib import AsyncExitStack

from openai import AsyncOpenAI


class Synthesizer:
    def __init__(self, *, client: AsyncOpenAI) -> None:
        self._client = client

{cleanup}
"""


@final
class NoInjectedDependencyClose(Rule):
    id = "no-injected-dependency-close"
    code = "SARJ599"
    documentation = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Leave closing an injected dependency to the owner that constructed it.",
        rationale=(
            "The code that constructs a resource owns its lifetime. When a consumer closes a client it received "
            "through __init__, other consumers sharing that client fail after the first one closes, the owner may "
            "close it twice, and shutdown order is no longer decided in one place."
        ),
        remediation=(
            "Register the resource's cleanup where it is created: for an application, in the composition root or "
            "the lifespan exit stack. Remove the consumer's close of what it was given. Objects the class constructs "
            "itself may still be closed by the class."
        ),
        category=RuleCategory.ARCHITECTURE,
        autofix=AutofixPolicy.NONE,
        limitations=(
            (
                "Only attributes assigned exactly once in the class, directly from an __init__ parameter at the top "
                "level of __init__, are tracked. Fallback construction such as `client or Client()`, copies, "
                "aliases through local variables and attributes reassigned elsewhere are not followed."
            ),
            (
                "Direct close, aclose, shutdown, __exit__ and __aexit__ calls are recognised in close, aclose, "
                "__exit__ and __aexit__. ExitStack or AsyncExitStack callback and push_async_callback registrations "
                "of such a method, and push or push_async_exit registrations of the attribute, are recognised in "
                "any method. enter_context and enter_async_context are not reported because entering an injected "
                "lock or transaction is legitimate. Helper methods, inherited cleanup and base-class __init__ are "
                "not followed."
            ),
            (
                "A class with a classmethod that constructs `cls(...)` is treated as a factory that transfers "
                "ownership and is skipped. Tests, test support and generated files are excluded."
            ),
        ),
        examples=(
            RuleExample(
                example_id="consumer-closes-injected-client",
                title="A consumer closes the client it was given",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "speech/synthesizer.py",
                        _CONSUMER.format(
                            cleanup=(
                                "    async def aclose(self) -> None:\n"
                                "        async with AsyncExitStack() as cleanup:\n"
                                "            cleanup.push_async_callback(self._client.close)"
                            )
                        ),
                    ),
                ),
                focus_path=PurePosixPath("speech/synthesizer.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="owner-closes-client",
                title="The owner that constructs the client registers its cleanup",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "speech/synthesizer.py",
                        _CONSUMER.format(
                            cleanup=(
                                "\nasync def serve(stack: AsyncExitStack) -> Synthesizer:\n"
                                "    client = await stack.enter_async_context(AsyncOpenAI())\n"
                                "    return Synthesizer(client=client)"
                            )
                        ),
                    ),
                ),
                focus_path=PurePosixPath("speech/synthesizer.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        source = context.symbol_source
        if "__init__" not in source or not any(word in source for word in ("close", "exit", "shutdown")):
            return []
        if context.generated or is_test_path(context.path) or is_test_support_path(context.path):
            return []
        if context.tree is None:
            return []
        diagnostics = [
            Diagnostic(
                path=context.path,
                line=site.lineno,
                col=site.col_offset + 1,
                code=self.code,
                message=_MESSAGE.format(owner=owner.name, method=method.name, attribute=attribute),
                severity=Severity.WARNING,
            )
            for owner in context.nodes(ast.ClassDef)
            for method, attribute, site in _injected_closes(owner)
            if not context.suppressions.is_suppressed(site.lineno, self.code)
        ]
        return sorted(diagnostics, key=lambda item: (item.line, item.col))


type _Method = ast.FunctionDef | ast.AsyncFunctionDef


def _injected_closes(owner: ast.ClassDef) -> Iterator[tuple[_Method, str, ast.Call]]:
    methods = [statement for statement in owner.body if isinstance(statement, ast.FunctionDef | ast.AsyncFunctionDef)]
    initializer = next((method for method in methods if method.name == "__init__"), None)
    if initializer is None or any(_constructs_cls(method) for method in methods):
        return
    injected = _injected_attributes(initializer, methods)
    if not injected:
        return
    for method in methods:
        for attribute, call in _method_cleanups(method):
            if attribute in injected:
                yield method, attribute, call


def _method_cleanups(method: _Method) -> Iterator[tuple[str, ast.Call]]:
    if (receiver := _receiver(method)) is None:
        return
    cleanup = method.name in _CLEANUP_METHODS
    for node in _local_nodes(method):
        if isinstance(node, ast.Call):
            closed = _closed_attribute(node, receiver, cleanup=cleanup)
            if closed is not None:
                yield closed, node


def _receiver(method: _Method) -> str | None:
    positional = [*method.args.posonlyargs, *method.args.args]
    if not positional or any(
        _decorator_name(decorator) in {"staticmethod", "classmethod"} for decorator in method.decorator_list
    ):
        return None
    return positional[0].arg


def _decorator_name(decorator: ast.expr) -> str | None:
    match decorator:
        case ast.Name(id=name):
            return name
        case _:
            return None


def _constructs_cls(method: _Method) -> bool:
    if not any(_decorator_name(decorator) == "classmethod" for decorator in method.decorator_list):
        return False
    positional = [*method.args.posonlyargs, *method.args.args]
    if not positional:
        return False
    factory = positional[0].arg
    return any(
        isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == factory
        for node in _local_nodes(method)
    )


def _injected_attributes(initializer: _Method, methods: list[_Method]) -> frozenset[str]:
    if (receiver := _receiver(initializer)) is None:
        return frozenset()
    arguments = initializer.args
    parameters = {argument.arg for argument in (*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs)} - {
        receiver
    }
    direct: dict[str, str] = {}
    for statement in initializer.body:
        match statement:
            case (
                ast.Assign(targets=[target], value=ast.Name(id=value))
                | ast.AnnAssign(target=target, value=ast.Name(id=value))
            ) if value in parameters:
                attribute = _self_attribute(target, receiver)
                if attribute is not None:
                    direct[attribute] = value
            case _:
                pass
    writes = _attribute_writes(methods)
    return frozenset(attribute for attribute in direct if writes.get(attribute, 0) == 1)


def _attribute_writes(methods: list[_Method]) -> Mapping[str, int]:
    writes: dict[str, int] = {}
    for method in methods:
        receiver = _receiver(method)
        if receiver is None:
            continue
        for node in _local_nodes(method):
            if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Store | ast.Del):
                attribute = _self_attribute(node, receiver)
                if attribute is not None:
                    writes[attribute] = writes.get(attribute, 0) + 1
    return writes


def _self_attribute(expression: ast.expr, receiver: str) -> str | None:
    match expression:
        case ast.Attribute(value=ast.Name(id=name), attr=attribute) if name == receiver:
            return attribute
        case _:
            return None


def _closed_attribute(node: ast.Call, receiver: str, *, cleanup: bool) -> str | None:
    if not isinstance(node.func, ast.Attribute):
        return None
    method = node.func.attr
    if method in _CLOSERS:
        return _self_attribute(node.func.value, receiver) if cleanup else None
    if not node.args:
        return None
    registered = node.args[0]
    if method in _CALLBACK_REGISTRATIONS and isinstance(registered, ast.Attribute) and registered.attr in _CLOSERS:
        return _self_attribute(registered.value, receiver)
    if method in _EXIT_REGISTRATIONS:
        return _self_attribute(registered, receiver)
    return None


def _local_nodes(method: _Method) -> Iterator[ast.AST]:
    stack: list[ast.AST] = list(reversed(method.body))
    while stack:
        node = stack.pop()
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef | ast.Lambda):
            continue
        yield node
        stack.extend(reversed(list(ast.iter_child_nodes(node))))
