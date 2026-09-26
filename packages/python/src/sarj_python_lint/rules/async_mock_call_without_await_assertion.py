from __future__ import annotations

import ast
from pathlib import PurePosixPath
from types import MappingProxyType
from typing import TYPE_CHECKING, ClassVar, Final, final, override

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
    parse_or_none,
)
from sarj_python_lint.rules._imports import ImportIndex
from sarj_python_lint.rules._paths import is_generated


if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


_CALL_ASSERTIONS: Final = frozenset(
    {"assert_called", "assert_called_once", "assert_called_with", "assert_called_once_with"}
)
_AWAIT_ASSERTIONS: Final = frozenset(
    {
        "assert_awaited",
        "assert_awaited_once",
        "assert_awaited_with",
        "assert_awaited_once_with",
        "assert_any_await",
        "assert_has_awaits",
    }
)
_AWAIT_STATE: Final = frozenset({"await_count", "await_args", "await_args_list"})
_CONSTRUCTOR_KEYWORDS: Final = frozenset({"return_value", "side_effect", "name", "wraps", "unsafe", "spec", "spec_set"})
_MUTATORS: Final = frozenset({"reset_mock", "configure_mock", "attach_mock", "mock_add_spec"})
_IMMEDIATE_CHILD_PARTS: Final = 2
_MOCK_ATTRIBUTES: Final = (
    _MUTATORS
    | _AWAIT_STATE
    | frozenset(
        {
            "return_value",
            "side_effect",
            "called",
            "call_count",
            "call_args",
            "call_args_list",
            "mock_calls",
            "method_calls",
        }
    )
)
type _TestFunction = ast.FunctionDef | ast.AsyncFunctionDef
type _Reference = tuple[str, ...]


@final
class AsyncMockCallWithoutAwaitAssertion(Rule):
    id = "async-mock-call-without-await-assertion"
    code = "SARJ456"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Pair positive AsyncMock call assertions with evidence that the mock was awaited.",
        rationale=(
            "Calling an AsyncMock records a call before its coroutine is awaited. A positive call assertion can "
            "therefore pass when production code silently drops the coroutine. Await assertions cover that gap, "
            "while call assertions still detect extra calls whose coroutines were never awaited."
        ),
        remediation=(
            "Keep the call assertion and add an appropriate assert_awaited assertion. For a test that deliberately "
            "checks scheduling before execution, use an exact SARJ456 suppression explaining that contract."
        ),
        category=RuleCategory.TESTING,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only direct statements in collected test functions and methods are inspected; fixtures, helpers, nested blocks, and generated files are excluded.",
            "Requires a fresh local unittest.mock.AsyncMock constructor with unshadowed imports; aliases, reassignment, reset, and ambiguous configuration are excluded.",
            "Only the mock itself and unchanged immediate children of unspecced, unwrapped mocks are inferred; spec children, return values, and deeper chains are excluded.",
            "Any direct positive await assertion or explicit await-state assertion on the same mock is accepted; argument equality and assertion strength are not compared.",
            "Custom assertion helpers and intentional scheduling contracts may require a reasoned local suppression.",
        ),
        examples=(
            RuleExample(
                example_id="call-only-async-mock",
                title="A call assertion does not prove awaiting",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_delivery.py",
                        "from unittest.mock import AsyncMock\n\nasync def test_delivery():\n    send = AsyncMock()\n    await deliver(send)\n    send.assert_called_once_with('item')\n",
                    ),
                ),
                focus_path=PurePosixPath("tests/test_delivery.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="call-and-await-async-mock",
                title="Call and await assertions protect different contracts",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_delivery.py",
                        "from unittest.mock import AsyncMock\n\nasync def test_delivery():\n    send = AsyncMock()\n    await deliver(send)\n    send.assert_called_once_with('item')\n    send.assert_awaited_once_with('item')\n",
                    ),
                ),
                focus_path=PurePosixPath("tests/test_delivery.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if (
            path.suffix != ".py"
            or "AsyncMock" not in source
            or "assert_called" not in source
            or not (path.stem.startswith("test_") or path.stem.endswith("_test"))
            or is_generated(path, source)
        ):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        imports = ImportIndex.from_tree(tree, module_scope_only=True)
        writes = {
            _reference(node)
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute) and isinstance(node.ctx, (ast.Store, ast.Del))
        }
        lines = source.splitlines()
        return [
            Diagnostic(
                path=path,
                line=call.lineno,
                col=call.col_offset + 1,
                code=self.code,
                severity=Severity.WARNING,
                message="AsyncMock call assertions do not prove awaiting; keep this assertion and add an await assertion",
            )
            for test in _collected_tests(tree.body)
            if not _is_pytest_fixture(test, imports)
            for call in _uncovered_calls(_test_imports(imports, test), test, writes)
            if not is_suppressed(lines, call.lineno, self.code)
        ]


def _collected_tests(statements: list[ast.stmt]) -> Iterator[_TestFunction]:
    for statement in statements:
        match statement:
            case ast.FunctionDef() | ast.AsyncFunctionDef() if statement.name.startswith("test"):
                yield statement
            case ast.ClassDef() if statement.name.startswith("Test"):
                yield from _collected_tests(statement.body)
            case _:
                pass


def _is_pytest_fixture(test: _TestFunction, imports: ImportIndex) -> bool:
    return any(
        imports.resolved_qualified_name(decorator.func if isinstance(decorator, ast.Call) else decorator)
        == "pytest.fixture"
        for decorator in test.decorator_list
    )


def _test_imports(module: ImportIndex, test: _TestFunction) -> ImportIndex:
    local = ImportIndex.from_tree(ast.Module(body=[test, *test.body], type_ignores=[]))
    bindings = {name: target for name, target in module.bindings.items() if name not in local.shadowed_names}
    bindings.update(local.bindings)
    return ImportIndex(MappingProxyType(bindings), module.shadowed_names | local.shadowed_names)


def _uncovered_calls(imports: ImportIndex, test: _TestFunction, writes: set[_Reference]) -> Iterator[ast.Call]:
    nodes = tuple(ast.walk(test))
    bindings = _mock_bindings(imports, test.body, writes)
    covered = _await_oracles(test.body)
    reported: set[_Reference] = set()
    for statement in test.body:
        match statement:
            case ast.Expr(value=ast.Call(func=ast.Attribute(value=receiver, attr=method)) as call) if (
                method in _CALL_ASSERTIONS
            ):
                reference = _reference(receiver)
                if not reference or reference in covered or reference in reported:
                    continue
                binding = bindings.get(reference[0])
                if (
                    binding is None
                    or not _is_async_reference(reference, binding[1])
                    or any(_invalidates_reference(node, reference, binding[0]) for node in nodes)
                ):
                    continue
                reported.add(reference)
                yield call
            case _:
                pass


def _mock_bindings(
    imports: ImportIndex, statements: list[ast.stmt], writes: set[_Reference]
) -> dict[str, tuple[ast.Name, ast.Call]]:
    bindings: dict[str, tuple[ast.Name, ast.Call]] = {}
    for statement in statements:
        match statement:
            case (
                ast.Assign(targets=[ast.Name() as target], value=ast.Call() as call)
                | ast.AnnAssign(target=ast.Name() as target, value=ast.Call() as call)
            ):
                if _is_async_constructor(call.func, imports, writes) and all(
                    keyword.arg in _CONSTRUCTOR_KEYWORDS for keyword in call.keywords
                ):
                    bindings[target.id] = (target, call)
            case _:
                pass
    return bindings


def _is_async_constructor(node: ast.expr, imports: ImportIndex, writes: set[_Reference]) -> bool:
    reference = _reference(node)
    if any(reference[:length] in writes for length in range(1, len(reference) + 1)):
        return False
    return imports.resolved_qualified_name(node) == "unittest.mock.AsyncMock" or (
        isinstance(node, ast.Attribute)
        and node.attr == "AsyncMock"
        and imports.resolved_qualified_name(node.value) == "unittest.mock"
    )


def _reference(node: ast.AST) -> _Reference:
    match node:
        case ast.Name(id=name):
            return (name,)
        case ast.Attribute(value=parent, attr=attribute):
            prefix = _reference(parent)
            return (*prefix, attribute) if prefix else ()
        case _:
            return ()


def _is_async_reference(reference: _Reference, constructor: ast.Call) -> bool:
    if len(reference) == 1:
        return True
    return (
        len(reference) == _IMMEDIATE_CHILD_PARTS
        and not constructor.args
        and not any(keyword.arg in {"spec", "spec_set", "wraps"} for keyword in constructor.keywords)
        and reference[1] not in _MOCK_ATTRIBUTES
        and not reference[1].startswith(("_", "assert"))
    )


def _await_oracles(statements: list[ast.stmt]) -> set[_Reference]:
    covered: set[_Reference] = set()
    for statement in statements:
        match statement:
            case ast.Expr(value=ast.Call(func=ast.Attribute(value=receiver, attr=method))) if (
                method in _AWAIT_ASSERTIONS
            ):
                covered.add(_reference(receiver))
            case ast.Assert(test=condition):
                covered.update(
                    _reference(node.value)
                    for node in ast.walk(condition)
                    if isinstance(node, ast.Attribute) and node.attr in _AWAIT_STATE
                )
            case _:
                pass
    return covered


def _invalidates_reference(node: ast.AST, reference: _Reference, binding: ast.Name) -> bool:
    match node:
        case ast.Name(id=name, ctx=ast.Store() | ast.Del()):
            return node is not binding and name == reference[0]
        case ast.arg(arg=name):
            return name == reference[0]
        case ast.Global(names=names) | ast.Nonlocal(names=names):
            return reference[0] in names
        case ast.Attribute(ctx=ast.Store() | ast.Del()):
            changed = _reference(node)
            return bool(changed) and (
                reference[: len(changed)] == changed or (changed[:-1] == reference and changed[-1].startswith("assert"))
            )
        case ast.Call(func=ast.Attribute(value=receiver, attr=method)) if method in _MUTATORS:
            changed = _reference(receiver)
            return bool(changed) and reference[: len(changed)] == changed
        case ast.Call(func=ast.Name(id="setattr" | "delattr"), args=[receiver, *_]):
            return _reference(receiver)[:1] == reference[:1]
        case ast.Assign(value=value) | ast.AnnAssign(value=value) if value is not None:
            return reference[0] in _alias_roots(value)
        case _:
            return False


def _alias_roots(node: ast.expr) -> Iterator[str]:
    match node:
        case ast.Name() | ast.Attribute():
            if reference := _reference(node):
                yield reference[0]
        case ast.Tuple(elts=elements) | ast.List(elts=elements) | ast.Set(elts=elements):
            for element in elements:
                yield from _alias_roots(element)
        case ast.Dict(keys=keys, values=values):
            for element in (*keys, *values):
                if element is not None:
                    yield from _alias_roots(element)
        case _:
            pass
