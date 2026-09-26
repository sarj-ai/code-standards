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
)
from sarj_python_lint.rules._ast_index import walk as walk_ast
from sarj_python_lint.rules._imports import ImportIndex


if TYPE_CHECKING:
    from collections.abc import Iterator

    from sarj_python_lint._file_context import PythonFileContext


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
_CALL_STATE: Final = frozenset({"called", "call_count"})
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
        default_level=Severity.ERROR,
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
            "Positive call-count and called-state assertions are covered as well as call-assertion methods. Await-state assertions must prove at least one await; argument equality and exact call/await counts are not compared.",
            "Boolean conjunctions combine evidence; disjunctions require evidence in every branch. Dynamic counts and call lists are not inferred.",
            "Custom assertion helpers and intentional scheduling contracts may require a reasoned local suppression.",
        ),
        examples=(
            RuleExample(
                example_id="numeric-call-with-vacuous-await-check",
                title="A nonnegative await count does not prove execution",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_delivery.py",
                        "from unittest.mock import AsyncMock\n\nasync def test_delivery():\n    send = AsyncMock()\n    await deliver(send)\n    assert send.call_count == 2\n    assert send.await_count >= 0\n",
                    ),
                ),
                focus_path=PurePosixPath("tests/test_delivery.py"),
                expected_count=1,
                public=False,
            ),
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
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        path = context.path
        source = context.source
        if (
            path.suffix != ".py"
            or "AsyncMock" not in source
            or not any(token in source for token in ("assert_called", "call_count", ".called"))
            or not (path.stem.startswith("test_") or path.stem.endswith("_test"))
            or context.generated
        ):
            return []
        tree = context.tree
        if tree is None:
            return []
        imports = context.module_imports
        writes = {
            _reference(node)
            for node in context.nodes(ast.AST)
            if isinstance(node, ast.Attribute) and isinstance(node.ctx, (ast.Store, ast.Del))
        }
        lines = context.source_lines
        return [
            Diagnostic(
                path=path,
                line=call.lineno,
                col=call.col_offset + 1,
                code=self.code,
                severity=Severity.ERROR,
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


def _uncovered_calls(
    imports: ImportIndex, test: _TestFunction, writes: set[_Reference]
) -> Iterator[ast.Call | ast.Attribute]:
    nodes = tuple(walk_ast(test))
    bindings = _mock_bindings(imports, test.body, writes)
    covered = _await_oracles(test.body)
    reported: set[_Reference] = set()
    for statement in test.body:
        for reference, oracle in _call_oracles(statement):
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
            yield oracle


def _call_oracles(statement: ast.stmt) -> Iterator[tuple[_Reference, ast.Call | ast.Attribute]]:
    match statement:
        case ast.Expr(value=ast.Call(func=ast.Attribute(value=receiver, attr=method)) as call) if (
            method in _CALL_ASSERTIONS
        ):
            yield _reference(receiver), call
        case ast.Assert(test=condition):
            for reference in sorted(_positive_states(condition, _CALL_STATE)):
                oracle = next(
                    node
                    for node in walk_ast(condition)
                    if isinstance(node, ast.Attribute)
                    and node.attr in _CALL_STATE
                    and _reference(node.value) == reference
                )
                yield reference, oracle
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
            case ast.Expr(value=ast.Call(func=ast.Attribute(value=receiver, attr=method)) as call) if (
                method in _AWAIT_ASSERTIONS
            ):
                if method != "assert_has_awaits" or _has_nonempty_calls_argument(call):
                    covered.add(_reference(receiver))
            case ast.Assert(test=condition):
                covered.update(_positive_states(condition, _AWAIT_STATE))
            case _:
                pass
    return covered


def _has_nonempty_calls_argument(call: ast.Call) -> bool:
    if call.args:
        return _nonempty_sequence(call.args[0])
    return any(item.arg == "calls" and _nonempty_sequence(item.value) for item in call.keywords)


def _positive_states(condition: ast.expr, states: frozenset[str]) -> set[_Reference]:
    if isinstance(condition, ast.UnaryOp) and isinstance(condition.op, ast.Not):
        operand = condition.operand
        if isinstance(operand, ast.Compare) and len(operand.ops) == 1:
            inverse = _negated_operator(operand.ops[0])
            if inverse is not None:
                return _comparison_states(operand.left, inverse, operand.comparators[0], states) | _comparison_states(
                    operand.comparators[0], _reversed_operator(inverse), operand.left, states
                )
        return set()
    if isinstance(condition, ast.BoolOp):
        branches = [_positive_states(value, states) for value in condition.values]
        return (
            branches[0].union(*branches[1:])
            if isinstance(condition.op, ast.And)
            else branches[0].intersection(*branches[1:])
        )
    if isinstance(condition, ast.Attribute) and condition.attr in states:
        return {_reference(condition.value)}
    if isinstance(condition, ast.Compare):
        result: set[_Reference] = set()
        for left, operator, right in zip(
            (condition.left, *condition.comparators[:-1]), condition.ops, condition.comparators, strict=True
        ):
            result.update(_comparison_states(left, operator, right, states))
            result.update(_comparison_states(right, _reversed_operator(operator), left, states))
        return result
    return set()


def _negated_operator(operator: ast.cmpop) -> ast.cmpop | None:
    inverse: dict[type[ast.cmpop], type[ast.cmpop]] = {
        ast.Eq: ast.NotEq,
        ast.NotEq: ast.Eq,
        ast.Is: ast.IsNot,
        ast.IsNot: ast.Is,
        ast.Lt: ast.GtE,
        ast.LtE: ast.Gt,
        ast.Gt: ast.LtE,
        ast.GtE: ast.Lt,
    }
    factory = inverse.get(type(operator))
    return factory() if factory is not None else None


def _reversed_operator(operator: ast.cmpop) -> ast.cmpop:
    match operator:
        case ast.Lt():
            return ast.Gt()
        case ast.LtE():
            return ast.GtE()
        case ast.Gt():
            return ast.Lt()
        case ast.GtE():
            return ast.LtE()
        case _:
            return operator


def _comparison_states(left: ast.expr, operator: ast.cmpop, right: ast.expr, states: frozenset[str]) -> set[_Reference]:
    if not isinstance(left, ast.Attribute):
        return set()
    if (
        states == _AWAIT_STATE
        and isinstance(left.value, ast.Attribute)
        and left.value.attr == "await_args"
        and left.attr in {"args", "kwargs"}
    ):
        return {_reference(left.value.value)}
    if left.attr not in states:
        return set()
    positive = False
    if left.attr in {"call_count", "await_count"} and isinstance(right, ast.Constant) and type(right.value) is int:
        positive = _proves_positive_count(operator, right.value)
    elif left.attr == "called" and isinstance(right, ast.Constant):
        positive = (isinstance(operator, (ast.Eq, ast.Is)) and right.value is True) or (
            isinstance(operator, (ast.NotEq, ast.IsNot)) and right.value is False
        )
    elif left.attr == "await_args" and isinstance(right, ast.Constant) and right.value is None:
        positive = isinstance(operator, (ast.NotEq, ast.IsNot))
    elif left.attr == "await_args_list":
        positive = (isinstance(operator, ast.Eq) and _nonempty_sequence(right)) or (
            isinstance(operator, ast.NotEq) and isinstance(right, ast.List) and not right.elts
        )
    return {_reference(left.value)} if positive else set()


def _proves_positive_count(operator: ast.cmpop, value: int) -> bool:
    match operator:
        case ast.Eq() | ast.GtE():
            return value > 0
        case ast.NotEq():
            return value == 0
        case ast.Gt():
            return value >= 0
        case _:
            return False


def _nonempty_sequence(node: ast.expr) -> bool:
    return isinstance(node, (ast.List, ast.Tuple)) and any(not isinstance(item, ast.Starred) for item in node.elts)


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
                reference[: len(changed)] == changed
                or (
                    changed[:-1] == reference
                    and (changed[-1].startswith("assert") or changed[-1] in _CALL_STATE | _AWAIT_STATE)
                )
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
