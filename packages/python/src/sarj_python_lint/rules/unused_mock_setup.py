"""SARJ067 — Mock setup the test can never exercise is a lie about what is covered.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_unused_mock_setup.py
"""

from __future__ import annotations

import ast
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, ClassVar, NamedTuple, override

from sarj_python_lint.rule_base import (
    AutofixPolicy,
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    Rule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
    parse_or_none,
)
from sarj_python_lint.rules._ast_index import children, nodes, walk
from sarj_python_lint.rules._imports import ImportIndex
from sarj_python_lint.rules._paths import is_test_path


if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


# The two attributes that *configure* what a mock does when called.
_CONFIG_ATTRS = frozenset({"return_value", "side_effect"})

# Callables whose constructor keywords configure the returned double.  Import
# resolution is required for bare/module-qualified spellings; the pytest-mock
# spelling is accepted only when ``mocker`` is a parameter of the test.
_MOCK_CONSTRUCTORS = frozenset(
    {
        "AsyncMock",
        "MagicMock",
        "Mock",
        "NonCallableMagicMock",
        "NonCallableMock",
        "create_autospec",
    }
)
_MOCKER_CONFIGURATORS = _MOCK_CONSTRUCTORS | {"patch"}
_UNITTEST_MOCK = frozenset({"unittest.mock"})
_MOCKER = "mocker"

# Assertions that the mock was never reached.
_NOT_CALLED_ASSERTIONS = frozenset({"assert_not_called", "assert_not_awaited"})

# Reads of the call record.
_INTROSPECTION_ATTRS = frozenset(
    {
        "await_args",
        "await_args_list",
        "await_count",
        "call_args",
        "call_args_list",
        "call_count",
        "called",
        "method_calls",
        "mock_calls",
        "reset_mock",
    }
)

_ASSERT_PREFIX = "assert"

_FUNC_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)

# Bodies that belong to a different scope: they are visited when that scope is
# itself processed as a function.
_NESTED_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)

# Expression nodes that can run arbitrary user code, so a statement containing
# one may have observed a mock configuration written above it.
_EFFECTFUL_NODES = (
    ast.Attribute,
    ast.Await,
    ast.Call,
    ast.NamedExpr,
    ast.Subscript,
    ast.Yield,
    ast.YieldFrom,
)


class _Finding(NamedTuple):
    """One dead configuration statement and why it is dead."""

    node: ast.stmt
    message: str


class UnusedMockSetup(Rule):
    id: str = "unused-mock-setup"
    code: str = "SARJ067"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="Tests should remove mock configuration that cannot affect execution.",
        rationale="Overwritten or contradicted mock setup adds misleading, unreachable test behavior.",
        remediation="Delete the unused setup or exercise the mock before replacing or contradicting it.",
        category=RuleCategory.TESTING,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only test paths are analyzed.",
            "Potentially effectful statements between assignments prevent a finding.",
        ),
        examples=(
            RuleExample(
                example_id="overwritten-mock-setup",
                title="Mock return value is overwritten before use",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_billing.py",
                        "def test_charge():\n    gateway.charge.return_value = 1\n    gateway.charge.return_value = 2\n    assert billing.charge(gateway) == 2\n",
                    ),
                ),
                focus_path=PurePosixPath("tests/test_billing.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="mock-used-before-reset",
                title="Test uses each configured value",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_billing.py",
                        "def test_charge():\n    gateway.charge.return_value = 1\n    assert billing.charge(gateway) == 1\n    gateway.charge.return_value = 2\n    assert billing.charge(gateway) == 2\n",
                    ),
                ),
                focus_path=PurePosixPath("tests/test_billing.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description: str = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        """Flag mock configuration statements that nothing in the test can observe."""
        if not is_test_path(path):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []

        imports = ImportIndex.from_tree(tree)
        seen: set[tuple[int, int]] = set()
        diags: list[Diagnostic] = []
        for fn in nodes(tree, *_FUNC_NODES):
            for finding in _dead_setups(fn, imports):
                position = (finding.node.lineno, finding.node.col_offset + 1)
                if position in seen:
                    continue
                seen.add(position)
                diags.append(
                    Diagnostic(
                        path=path,
                        line=position[0],
                        col=position[1],
                        code=self.code,
                        message=finding.message,
                    )
                )
        diags.sort(key=lambda d: (d.line, d.col))
        return diags


def _dead_setups(fn: ast.FunctionDef | ast.AsyncFunctionDef, imports: ImportIndex) -> Iterator[_Finding]:
    yield from _overwritten_before_use(fn, imports)
    yield from _asserted_never_called(fn)


def _overwritten_before_use(fn: ast.FunctionDef | ast.AsyncFunctionDef, imports: ImportIndex) -> Iterator[_Finding]:
    """Find configurations reassigned before anything could read them."""
    has_mocker_fixture = _has_parameter(fn, _MOCKER)
    for block in _blocks(fn):
        pending: dict[str, ast.stmt] = {}
        for stmt in block:
            target = _config_target(stmt)
            if target is None:
                initial = _initial_mock_configs(stmt, imports, has_mocker_fixture=has_mocker_fixture)
                if initial:
                    configured_name = initial[0].partition(".")[0]
                    pending = {
                        target: setup
                        for target, setup in pending.items()
                        if not target.startswith(f"{configured_name}.")
                    }
                    pending.update((configured, stmt) for configured in initial)
                    continue
                if not _is_inert(stmt):
                    pending.clear()
                continue
            previous = pending.get(target)
            if previous is not None:
                yield _Finding(
                    previous,
                    (
                        f"`{target}` is set here and overwritten on line {stmt.lineno} with nothing in "
                        "between that could call the mock, so this value is never used. Delete the dead "
                        "setup, or move the code under test between the two configurations"
                    ),
                )
            pending[target] = stmt


def _has_parameter(fn: ast.FunctionDef | ast.AsyncFunctionDef, name: str) -> bool:
    args = fn.args
    return any(arg.arg == name for arg in (*args.posonlyargs, *args.args, *args.kwonlyargs))


def _initial_mock_configs(stmt: ast.stmt, imports: ImportIndex, *, has_mocker_fixture: bool) -> tuple[str, ...]:
    """Read configuration keywords supplied while binding a proven mock call."""
    match stmt:
        case ast.Assign(targets=[ast.Name(id=name)], value=ast.Call() as call):
            pass
        case ast.AnnAssign(target=ast.Name(id=name), value=ast.Call() as call):
            pass
        case _:
            return ()
    if not _is_mock_configurator(call.func, imports, has_mocker_fixture=has_mocker_fixture):
        return ()
    return tuple(f"{name}.{keyword.arg}" for keyword in call.keywords if keyword.arg in _CONFIG_ATTRS)


def _is_mock_configurator(func: ast.expr, imports: ImportIndex, *, has_mocker_fixture: bool) -> bool:
    """Resolve a constructor/patch call whose keywords configure its result."""
    if has_mocker_fixture and isinstance(func, ast.Attribute):
        if isinstance(func.value, ast.Name) and func.value.id == _MOCKER:
            return func.attr in _MOCKER_CONFIGURATORS
        if (
            func.attr == "object"
            and isinstance(func.value, ast.Attribute)
            and func.value.attr == "patch"
            and isinstance(func.value.value, ast.Name)
            and func.value.value.id == _MOCKER
        ):
            return True
    return any(imports.resolves(func, sources=_UNITTEST_MOCK, symbol=symbol) for symbol in _MOCK_CONSTRUCTORS)


def _asserted_never_called(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> Iterator[_Finding]:
    """Find configurations of a path the test then asserts was never called."""
    not_called = _not_called_assertions(fn)
    if not not_called:
        return
    introspected = _introspected_paths(fn)
    last_effect = _last_effectful_line(fn)
    for stmt in _scope_statements(fn):
        target = _config_target(stmt)
        if target is None:
            continue
        configured = target.rsplit(".", 1)[0]
        if any(_touches(configured, other) for other in introspected):
            continue
        for asserted, line in not_called.items():
            if line > stmt.lineno and _is_prefix(asserted, configured) and last_effect <= line:
                yield _Finding(
                    stmt,
                    (
                        f"`{target}` is configured here, but the test asserts `{asserted}` was never "
                        "called and nothing runs after that assertion — the configured value can never "
                        "be observed. Delete the setup, or assert on the call it was written for"
                    ),
                )
                break


def _blocks(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> Iterator[list[ast.stmt]]:
    """Walk the statement blocks belonging to this function's own scope."""
    stack: list[ast.AST] = [fn]
    while stack:
        node = stack.pop()
        for block in _child_blocks(node):
            yield block
            stack.extend(stmt for stmt in block if not isinstance(stmt, _NESTED_SCOPES))


def _child_blocks(node: ast.AST) -> list[list[ast.stmt]]:
    """List the statement blocks a compound statement owns."""
    blocks: list[list[ast.stmt]] = []
    match node:
        case ast.FunctionDef() | ast.AsyncFunctionDef():
            blocks.append(node.body)
        case ast.If() | ast.For() | ast.AsyncFor() | ast.While():
            blocks.extend((node.body, node.orelse))
        case ast.With() | ast.AsyncWith() | ast.ExceptHandler():
            blocks.append(node.body)
        case ast.Try() | ast.TryStar():
            blocks.extend((node.body, node.orelse, node.finalbody))
            blocks.extend(handler.body for handler in node.handlers)
        case ast.Match():
            blocks.extend(case.body for case in node.cases)
        case _:
            pass
    return [block for block in blocks if block]


def _scope_statements(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> Iterator[ast.stmt]:
    """Walk every statement in the function's own scope."""
    for block in _blocks(fn):
        yield from block


def _config_target(stmt: ast.stmt) -> str | None:
    """Read the dotted target of a mock configuration assignment."""
    if not isinstance(stmt, ast.Assign) or len(stmt.targets) != 1:
        return None
    target = stmt.targets[0]
    if not isinstance(target, ast.Attribute) or target.attr not in _CONFIG_ATTRS:
        return None
    return _dotted(target)


def _dotted(node: ast.expr) -> str | None:
    """Render a `Name`-rooted attribute chain as a dotted string."""
    parts: list[str] = []
    current = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if not isinstance(current, ast.Name):
        return None
    parts.append(current.id)
    return ".".join(reversed(parts))


def _is_inert(stmt: ast.stmt) -> bool:
    """Report whether a statement provably cannot execute user code."""
    if isinstance(stmt, (ast.Pass, ast.Import, ast.ImportFrom)):
        return True
    if isinstance(stmt, ast.Expr):
        return isinstance(stmt.value, ast.Constant)
    if not isinstance(stmt, ast.Assign):
        return False
    if not all(isinstance(target, ast.Name) for target in stmt.targets):
        # `obj.attr = 1` can hit a property setter, `d[k] = 1` a `__setitem__`.
        return False
    return not any(isinstance(node, _EFFECTFUL_NODES) for node in walk(stmt.value))


def _not_called_assertions(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> dict[str, int]:
    """Collect `x.y.assert_not_called()` calls made in this function's scope."""
    found: dict[str, int] = {}
    for stmt in _scope_statements(fn):
        for node in _own_expressions(stmt):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr not in _NOT_CALLED_ASSERTIONS:
                continue
            asserted = _dotted(node.func.value)
            if asserted is not None:
                found[asserted] = max(found.get(asserted, 0), node.lineno)
    return found


def _own_expressions(stmt: ast.stmt) -> Iterator[ast.AST]:
    """Walk the expressions a statement owns, without descending into other statements."""
    for child in children(stmt):
        if isinstance(child, (ast.stmt, ast.excepthandler, ast.match_case)):
            continue
        yield from walk(child)


def _introspected_paths(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    """Collect every path the function reads the call record of."""
    found: set[str] = set()
    for node in walk(fn):
        if not isinstance(node, ast.Attribute) or not _is_introspection(node.attr):
            continue
        path = _dotted(node.value)
        if path is not None:
            found.add(path)
    return found


def _is_introspection(attr: str) -> bool:
    if attr in _NOT_CALLED_ASSERTIONS:
        return False
    return attr in _INTROSPECTION_ATTRS or attr.startswith(_ASSERT_PREFIX)


def _last_effectful_line(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    """Find the last line of the function that can invoke a mock."""
    last = 0
    for node in walk(fn):
        if isinstance(node, ast.Call) and not _is_assertion_call(node):
            last = max(last, node.lineno)
    return last


def _is_assertion_call(node: ast.Call) -> bool:
    if not isinstance(node.func, ast.Attribute) or not node.func.attr.startswith(_ASSERT_PREFIX):
        return False
    return not any(isinstance(child, ast.Call) for arg in (*node.args, *node.keywords) for child in walk(arg))


def _is_prefix(prefix: str, path: str) -> bool:
    return path == prefix or path.startswith(f"{prefix}.")


def _touches(path: str, other: str) -> bool:
    return _is_prefix(path, other) or _is_prefix(other, path)
