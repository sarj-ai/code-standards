from __future__ import annotations

import ast
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, ClassVar, TypeGuard, final

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
    is_suppressed,
)
from sarj_python_lint.rules._ast_index import nodes
from sarj_python_lint.rules._paths import is_test_path


if TYPE_CHECKING:
    from pathlib import Path

    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rules._ast_index import NodeIndex


_MIN_INVARIANT_CALLS = 2

_REFLECTION = frozenset({"globals", "locals", "vars", "eval", "exec", "getattr", "__import__", "__all__"})


@final
class UnusedTestFactoryOption(Rule):
    id = "unused-test-factory-option"
    code = "SARJ443"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="A private test factory exposes an invariant literal or unexercised local callable option.",
        rationale="Unused customization obscures the values that actually distinguish test scenarios.",
        remediation="Consider keeping the invariant literal or stable local callable in the construction instead of exposing an unexercised option. Preserve intentional dependency contracts and callable default binding timing.",
        category=RuleCategory.TESTING,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Literal findings consider only private _make_ and _build_ helpers nested directly inside test functions, with at least two known direct callers and straight-line construction bodies.",
            "Callable findings consider module-level private helpers with the same construction shape and an earlier undecorated local function default, only when at least two known direct callers all omit that option.",
            "Conftest callable factories, explicit callable arguments, exports, decorators, escaping references, reflection, unpacking, rebinding, shadowing and ambiguous mutation or patch targets are excluded.",
            "Same-name declarations elsewhere in the file conservatively exclude a helper. No autofix: this warning identifies unexercised customization, not an invalid callable contract.",
            "Callable findings describe known callers in this file; cross-module and dynamic callers are not inferred. Retain intentional extension points with a reasoned exception, preserving definition-time default capture.",
        ),
        examples=(
            RuleExample(
                example_id="invariant-size-option",
                title="Repeated calls never vary the option",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_widget.py",
                        "def test_widgets():\n    def _make_widget(*, size=3):\n        return Widget(size=size)\n    _make_widget()\n    _make_widget(size=3)\n",
                    ),
                ),
                focus_path=PurePosixPath("tests/test_widget.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="unused-local-callable-option",
                scenario="callable-default",
                title="Known callers do not replace a stable local dependency",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_widget.py",
                        "def _read():\n    return 'ready'\n"
                        "def _make_widget(*, read=_read):\n    return Widget(read=read)\n"
                        "_make_widget()\n_make_widget()\n",
                    ),
                ),
                focus_path=PurePosixPath("tests/test_widget.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="exercised-local-callable-option",
                scenario="callable-default",
                title="An explicit callback preserves the dependency contract",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_widget.py",
                        "def _read():\n    return 'ready'\n"
                        "def _make_widget(*, read=_read):\n    return Widget(read=read)\n"
                        "_make_widget()\n_make_widget(read=_read)\n",
                    ),
                ),
                focus_path=PurePosixPath("tests/test_widget.py"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="exercised-size-option",
                title="Keep customization that a caller exercises",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_widget.py",
                        "def test_widgets():\n    def _make_widget(*, size=3):\n        return Widget(size=size)\n    _make_widget()\n    _make_widget(size=4)\n",
                    ),
                ),
                focus_path=PurePosixPath("tests/test_widget.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        path = context.path
        source = context.source
        if not is_test_path(path) or context.generated or not ("_make_" in source or "_build_" in source):
            return []
        tree = context.tree
        if tree is None or (
            any(node.id in _REFLECTION for node in context.nodes(ast.Name))
            or any(node.attr in _REFLECTION or node.attr == "__dict__" for node in context.nodes(ast.Attribute))
            or any(node.name in _REFLECTION or node.name == "*" for node in context.nodes(ast.alias))
        ):
            return []
        lines = context.source_lines
        findings: list[Diagnostic] = []
        for function in context.nodes(ast.FunctionDef):
            if not _is_factory(function):
                continue
            owner = context.parents.get(function)
            if isinstance(owner, ast.FunctionDef | ast.AsyncFunctionDef) and owner.name.startswith("test_"):
                findings.extend(
                    _factory_findings(tree, function, path, lines, self.code, node_index=context.node_index)
                )
            elif owner is tree and path.name != "conftest.py":
                findings.extend(_callable_factory_findings(context, function, self.code))
        return sorted(findings, key=lambda item: (item.line, item.col))


def _is_factory(node: ast.stmt) -> TypeGuard[ast.FunctionDef]:
    return (
        isinstance(node, ast.FunctionDef)
        and node.name.startswith(("_make_", "_build_"))
        and not node.decorator_list
        and node.args.vararg is None
        and node.args.kwarg is None
        and _returns_construction(node.body)
    )


def _returns_construction(body: list[ast.stmt]) -> bool:
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        body = body[1:]
    if not body or not isinstance(body[-1], ast.Return):
        return False
    assigned: dict[str, ast.expr] = {}
    for statement in body[:-1]:
        match statement:
            case ast.Assign(targets=[ast.Name(id=name)], value=value):
                assigned[name] = value
            case ast.AnnAssign(target=ast.Name(id=name), value=value) if value is not None:
                assigned[name] = value
            case _:
                return False
    value = body[-1].value
    seen: set[str] = set()
    while isinstance(value, ast.Name) and value.id not in seen:
        seen.add(value.id)
        value = assigned.get(value.id)
    return isinstance(value, ast.Call)


def _factory_findings(
    tree: ast.Module,
    function: ast.FunctionDef,
    path: Path,
    lines: list[str],
    code: str,
    *,
    node_index: NodeIndex | None = None,
) -> list[Diagnostic]:
    findings: list[Diagnostic] = []
    calls = _direct_calls(tree, function, node_index=node_index)
    if len(calls) < _MIN_INVARIANT_CALLS:
        return []
    bound = _bound_calls(function, calls)
    if bound is None:
        return []
    supplied = {name for arguments in bound for name in arguments}
    for argument, default in _literal_factory_options(function):
        explicitly_supplied = argument.arg in supplied
        if explicitly_supplied and not _factory_argument_is_invariant(argument, default, bound):
            continue
        if is_suppressed(lines, argument.lineno, code):
            continue
        findings.append(
            Diagnostic(
                path=path,
                line=argument.lineno,
                col=argument.col_offset + 1,
                code=code,
                severity=Severity.WARNING,
                message=(
                    f"Direct callers in this file always use the same literal for `{function.name}.{argument.arg}`; "
                    "consider keeping that value in the factory instead of repeating an invariant option. Keep the option if it expresses an intentional test contract."
                    if explicitly_supplied
                    else f"None of the test-local callers supplies `{function.name}.{argument.arg}`; keep its literal value in the factory instead of exposing an unused option. Keep the option if it expresses an intentional test contract."
                ),
            )
        )
    return findings


def _bound_calls(function: ast.FunctionDef, calls: list[ast.Call]) -> list[dict[str, ast.expr]] | None:
    positional = [*function.args.posonlyargs, *function.args.args]
    keywords = {arg.arg for arg in (*function.args.args, *function.args.kwonlyargs)}
    required = {arg.arg for arg in positional[: len(positional) - len(function.args.defaults)]}
    required.update(
        arg.arg
        for arg, default in zip(function.args.kwonlyargs, function.args.kw_defaults, strict=True)
        if default is None
    )
    bound: list[dict[str, ast.expr]] = []
    for call in calls:
        if len(call.args) > len(positional):
            return None
        arguments = {arg.arg: value for arg, value in zip(positional[: len(call.args)], call.args, strict=True)}
        for keyword in call.keywords:
            if keyword.arg not in keywords or keyword.arg in arguments:
                return None
            arguments[keyword.arg] = keyword.value
        if not required <= arguments.keys():
            return None
        bound.append(arguments)
    return bound


def _direct_calls(
    tree: ast.Module, function: ast.FunctionDef, *, node_index: NodeIndex | None = None
) -> list[ast.Call]:
    name = function.name
    if not _has_unambiguous_factory_name(tree, name, node_index=node_index):
        return []
    references = [node for node in nodes(tree, ast.Name, index=node_index) if node.id == name]
    calls = [
        node
        for node in nodes(tree, ast.Call, index=node_index)
        if isinstance(node.func, ast.Name) and node.func.id == name
    ]
    if not calls or len(references) != len(calls) or any(not isinstance(node.ctx, ast.Load) for node in references):
        return []
    if _has_dynamic_factory_arguments(calls):
        return []
    if any(function.lineno <= call.lineno <= (function.end_lineno or function.lineno) for call in calls):
        return []
    return calls


def _has_unambiguous_factory_name(tree: ast.Module, name: str, *, node_index: NodeIndex | None = None) -> bool:
    if (
        sum(
            node.name == name
            for node in nodes(tree, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, index=node_index)
        )
        != 1
    ):
        return False
    if any(node.arg == name for node in nodes(tree, ast.arg, index=node_index)):
        return False
    if any((node.asname or node.name.split(".")[0]) == name for node in nodes(tree, ast.alias, index=node_index)):
        return False
    if any(node.attr == name for node in nodes(tree, ast.Attribute, index=node_index)):
        return False
    if any(node.value == name for node in nodes(tree, ast.Constant, index=node_index)):
        return False
    if any(node.name == name for node in nodes(tree, ast.MatchAs, ast.MatchStar, ast.ExceptHandler, index=node_index)):
        return False
    return not any(node.rest == name for node in nodes(tree, ast.MatchMapping, index=node_index))


def _has_dynamic_factory_arguments(calls: list[ast.Call]) -> bool:
    return any(
        any(isinstance(arg, ast.Starred) for arg in call.args) or any(kw.arg is None for kw in call.keywords)
        for call in calls
    )


def _factory_argument_is_invariant(argument: ast.arg, default: ast.Constant, bound: list[dict[str, ast.expr]]) -> bool:
    values = [arguments.get(argument.arg, default) for arguments in bound]
    return not (
        len(values) < _MIN_INVARIANT_CALLS
        or any(not isinstance(value, ast.Constant) or ast.dump(value) != ast.dump(values[0]) for value in values)
    )


def _literal_factory_options(function: ast.FunctionDef) -> list[tuple[ast.arg, ast.Constant]]:
    return [
        (argument, default)
        for argument, default in _factory_options(function)
        if isinstance(default, ast.Constant)
        and (default.value is None or isinstance(default.value, (str, bytes, int, float)))
    ]


def _factory_options(function: ast.FunctionDef) -> list[tuple[ast.arg, ast.expr]]:
    positional = [*function.args.posonlyargs, *function.args.args]
    defaults = [
        *zip(positional[len(positional) - len(function.args.defaults) :], function.args.defaults, strict=True),
        *zip(function.args.kwonlyargs, function.args.kw_defaults, strict=True),
    ]
    used = {node.id for node in nodes(function, ast.Name) if isinstance(node.ctx, ast.Load)}
    return [(argument, default) for argument, default in defaults if argument.arg in used and default is not None]


def _callable_factory_findings(context: PythonFileContext, function: ast.FunctionDef, code: str) -> list[Diagnostic]:
    tree = context.tree
    if tree is None:
        return []
    options = [(argument, default) for argument, default in _factory_options(function) if isinstance(default, ast.Name)]
    if not options:
        return []
    calls = _direct_calls(tree, function, node_index=context.node_index)
    if len(calls) < _MIN_INVARIANT_CALLS:
        return []
    bound = _bound_calls(function, calls)
    if bound is None:
        return []
    supplied = {name for arguments in bound for name in arguments}
    rebound = {node.id for node in nodes(function, ast.Name) if not isinstance(node.ctx, ast.Load)}
    findings: list[Diagnostic] = []
    for argument, default in options:
        if (
            argument.arg in supplied | rebound
            or not _is_stable_local_callable(context, function, default.id)
            or is_suppressed(context.source_lines, argument.lineno, code)
        ):
            continue
        findings.append(
            Diagnostic(
                path=context.path,
                line=argument.lineno,
                col=argument.col_offset + 1,
                code=code,
                severity=Severity.WARNING,
                message=(
                    f"No known direct caller in this file supplies `{function.name}.{argument.arg}`; consider "
                    f"using the stable local callable `{default.id}` internally. Preserve default binding timing "
                    "and retain the option if external callers or an intentional test contract need it."
                ),
            )
        )
    return findings


def _is_stable_local_callable(context: PythonFileContext, factory: ast.FunctionDef, name: str) -> bool:
    tree = context.tree
    if tree is None or not any(
        isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        and node.name == name
        and node.lineno < factory.lineno
        and not node.decorator_list
        for node in tree.body
    ):
        return False
    if not _has_unambiguous_factory_name(tree, name, node_index=context.node_index):
        return False
    return not (
        any(node.id == name and not isinstance(node.ctx, ast.Load) for node in context.nodes(ast.Name))
        or any(
            not isinstance(node.ctx, ast.Load) and any(child.id == name for child in nodes(node.value, ast.Name))
            for node in context.nodes(ast.Attribute, ast.Subscript)
        )
        or any(
            isinstance(node.value, str) and (name in node.value.split(".") or factory.name in node.value.split("."))
            for node in context.nodes(ast.Constant)
        )
        or _provider_escapes(context, name)
    )


def _provider_escapes(context: PythonFileContext, name: str) -> bool:
    for node in context.nodes(ast.Name):
        if node.id != name or not isinstance(node.ctx, ast.Load):
            continue
        parent = context.parents.get(node)
        if not (isinstance(parent, ast.arguments) or (isinstance(parent, ast.Call) and parent.func is node)):
            return True
    return False
