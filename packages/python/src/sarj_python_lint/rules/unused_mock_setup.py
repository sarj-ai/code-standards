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
    Severity,
    parse_or_none,
)
from sarj_python_lint.rules._ast_index import children, nodes, walk
from sarj_python_lint.rules._imports import ImportIndex
from sarj_python_lint.rules._paths import is_generated, is_test_path


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


class _Finding(NamedTuple):
    node: ast.stmt
    message: str


class UnusedMockSetup(Rule):
    id: str = "no-provably-dead-mock-configuration"
    code: str = "SARJ067"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="Remove mock behavior configuration proven unable to affect a test.",
        rationale=(
            "A mock behavior value is dead when a same-path write replaces it before observation, or when a "
            "terminal exact-path assertion proves the configured mock was never called."
        ),
        remediation=(
            "Delete the earlier overwritten configuration, or place the intended action before reconfiguration; "
            "delete behavior configuration contradicted by a terminal never-called assertion."
        ),
        category=RuleCategory.TESTING,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only non-generated test paths and mock values proven from unittest.mock or an unshadowed pytest-mock fixture are analyzed.",
            "Only same-block overwrites and exact-path terminal never-called assertions are checked; uncertain evaluation, control flow, reads, and escapes are excluded.",
        ),
        examples=(
            RuleExample(
                example_id="overwritten-mock-setup",
                title="Mock return value is overwritten before use",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_billing.py",
                        "from unittest.mock import Mock\n\ndef test_charge():\n    charge = Mock()\n    charge.return_value = 1\n    charge.return_value = 2\n    assert charge() == 2\n",
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
                        "from unittest.mock import Mock\n\ndef test_charge():\n    charge = Mock()\n    charge.return_value = 1\n    assert charge() == 1\n    charge.return_value = 2\n    assert charge() == 2\n",
                    ),
                ),
                focus_path=PurePosixPath("tests/test_billing.py"),
                expected_count=0,
                public=True,
            ),
        ),
        aliases=("unused-mock-setup",),
    )
    description: str = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if not is_test_path(path) or is_generated(path, source):
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
                        severity=Severity.WARNING,
                        message=finding.message,
                    )
                )
        diags.sort(key=lambda d: (d.line, d.col))
        return diags


def _dead_setups(fn: ast.FunctionDef | ast.AsyncFunctionDef, imports: ImportIndex) -> Iterator[_Finding]:
    origins = _mock_origins(fn, imports)
    if not origins:
        return
    yield from _overwritten_before_use(fn, imports, origins)
    yield from _asserted_never_called(fn, origins)


def _overwritten_before_use(
    fn: ast.FunctionDef | ast.AsyncFunctionDef, imports: ImportIndex, origins: frozenset[str]
) -> Iterator[_Finding]:
    has_mocker_fixture = _has_unshadowed_mocker_fixture(fn)
    for block in _blocks(fn):
        pending: dict[str, ast.stmt] = {}
        for stmt in block:
            target = _config_target(stmt, origins)
            if target is None:
                initial = _initial_mock_configs(stmt, imports, has_mocker_fixture=has_mocker_fixture)
                if initial and initial[0].partition(".")[0] in origins:
                    if _constructor_observes_pending(stmt, pending):
                        pending.clear()
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
            if _statement_observes_pending(stmt, pending):
                pending.clear()
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


def _has_unshadowed_mocker_fixture(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return _has_parameter(fn, _MOCKER) and not any(
        isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)) and node.id == _MOCKER
        for node in _owned_nodes(fn)
    )


def _has_parameter(fn: ast.FunctionDef | ast.AsyncFunctionDef, name: str) -> bool:
    args = fn.args
    return any(arg.arg == name for arg in (*args.posonlyargs, *args.args, *args.kwonlyargs))


def _owned_nodes(root: ast.AST) -> Iterator[ast.AST]:
    stack = [root]
    while stack:
        node = stack.pop()
        yield node
        if node is not root and isinstance(node, _NESTED_SCOPES):
            continue
        stack.extend(reversed(list(ast.iter_child_nodes(node))))


def _mock_origins(fn: ast.FunctionDef | ast.AsyncFunctionDef, imports: ImportIndex) -> frozenset[str]:
    has_mocker_fixture = _has_unshadowed_mocker_fixture(fn)
    binding_counts: dict[str, int] = {}
    for argument in (*fn.args.posonlyargs, *fn.args.args, *fn.args.kwonlyargs):
        binding_counts[argument.arg] = binding_counts.get(argument.arg, 0) + 1
    for node in _owned_nodes(fn):
        if isinstance(node, (ast.Name, ast.Attribute)) and isinstance(node.ctx, (ast.Store, ast.Del)):
            path = _dotted(node)
            if path is not None:
                binding_counts[path] = binding_counts.get(path, 0) + 1
    origins: set[str] = set()
    for stmt in _scope_statements(fn):
        match stmt:
            case ast.Assign(targets=[target], value=ast.Call() as call):
                pass
            case ast.AnnAssign(target=target, value=ast.Call() as call):
                pass
            case _:
                continue
        path = _dotted(target)
        if (
            path is not None
            and binding_counts.get(path) == 1
            and _is_mock_configurator(call.func, imports, has_mocker_fixture=has_mocker_fixture)
        ):
            origins.add(path)
    return frozenset(origins)


def _initial_mock_configs(stmt: ast.stmt, imports: ImportIndex, *, has_mocker_fixture: bool) -> tuple[str, ...]:
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


def _asserted_never_called(fn: ast.FunctionDef | ast.AsyncFunctionDef, origins: frozenset[str]) -> Iterator[_Finding]:
    if not fn.name.startswith("test_") or _is_fixture(fn):
        return
    introspected = _introspected_paths(fn)
    loaded_configs = _loaded_config_paths(fn)
    last_effect = _last_effectful_line(fn, origins)
    loop_statements = _loop_statement_ids(fn)
    for block in _blocks(fn):
        not_called = _not_called_assertions(block, origins)
        for stmt in block:
            target = _config_target(stmt, origins)
            if target is None or id(stmt) in loop_statements or target in loaded_configs:
                continue
            configured = target.rsplit(".", 1)[0]
            if any(_touches(configured, other) for other in introspected):
                continue
            for asserted, line in not_called.items():
                if line > stmt.lineno and asserted == configured and last_effect <= line:
                    yield _Finding(
                        stmt,
                        (
                            f"`{target}` is configured here, but the test ends by proving `{asserted}` was never "
                            "called, so its behavior cannot affect the test. Delete the contradictory configuration"
                        ),
                    )
                    break


def _is_fixture(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return any(
        (isinstance(decorator, ast.Name) and decorator.id == "fixture")
        or (isinstance(decorator, ast.Attribute) and decorator.attr == "fixture")
        or (
            isinstance(decorator, ast.Call)
            and isinstance(decorator.func, (ast.Name, ast.Attribute))
            and (decorator.func.id if isinstance(decorator.func, ast.Name) else decorator.func.attr) == "fixture"
        )
        for decorator in fn.decorator_list
    )


def _loop_statement_ids(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> set[int]:
    found: set[int] = set()
    for node in _owned_nodes(fn):
        if not isinstance(node, (ast.For, ast.AsyncFor, ast.While)):
            continue
        for child in (*node.body, *node.orelse):
            found.update(id(descendant) for descendant in _owned_nodes(child) if isinstance(descendant, ast.stmt))
    return found


def _loaded_config_paths(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    found: set[str] = set()
    for node in _owned_nodes(fn):
        if not isinstance(node, ast.Attribute) or not isinstance(node.ctx, ast.Load) or node.attr not in _CONFIG_ATTRS:
            continue
        path = _dotted(node)
        if path is not None:
            found.add(path)
    return found


def _blocks(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> Iterator[list[ast.stmt]]:
    stack: list[ast.AST] = [fn]
    while stack:
        node = stack.pop()
        for block in _child_blocks(node):
            yield block
            stack.extend(stmt for stmt in block if not isinstance(stmt, _NESTED_SCOPES))


def _child_blocks(node: ast.AST) -> list[list[ast.stmt]]:
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
    for block in _blocks(fn):
        yield from block


def _config_target(stmt: ast.stmt, origins: frozenset[str]) -> str | None:
    if not isinstance(stmt, ast.Assign) or len(stmt.targets) != 1:
        return None
    target = stmt.targets[0]
    if not isinstance(target, ast.Attribute) or target.attr not in _CONFIG_ATTRS:
        return None
    path = _dotted(target)
    if path is None:
        return None
    configured = path.rsplit(".", 1)[0]
    return path if any(_is_prefix(origin, configured) for origin in origins) else None


def _dotted(node: ast.expr) -> str | None:
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
    if isinstance(stmt, (ast.Pass, ast.Import, ast.ImportFrom)):
        return True
    if isinstance(stmt, ast.Expr):
        return isinstance(stmt.value, ast.Constant)
    if not isinstance(stmt, ast.Assign):
        return False
    if not all(isinstance(target, ast.Name) for target in stmt.targets):
        # `obj.attr = 1` can hit a property setter, `d[k] = 1` a `__setitem__`.
        return False
    return _is_safe_value(stmt.value)


def _is_safe_value(node: ast.expr) -> bool:
    match node:
        case ast.Constant() | ast.Name():
            return True
        case ast.List() | ast.Tuple() | ast.Set():
            return all(not isinstance(element, ast.Starred) and _is_safe_value(element) for element in node.elts)
        case ast.Dict():
            return all(key is not None and _is_safe_value(key) for key in node.keys) and all(
                _is_safe_value(value) for value in node.values
            )
        case _:
            return False


def _statement_observes_pending(stmt: ast.stmt, pending: dict[str, ast.stmt]) -> bool:
    if not pending:
        return False
    value = stmt.value if isinstance(stmt, (ast.Assign, ast.AnnAssign)) else None
    if value is None:
        return False
    for node in walk(value):
        if not isinstance(node, (ast.Name, ast.Attribute)) or not isinstance(node.ctx, ast.Load):
            continue
        path = _dotted(node)
        if path is not None and any(_touches(path, target.rsplit(".", 1)[0]) for target in pending):
            return True
    return not _is_safe_value(value)


def _constructor_observes_pending(stmt: ast.stmt, pending: dict[str, ast.stmt]) -> bool:
    value = stmt.value if isinstance(stmt, (ast.Assign, ast.AnnAssign)) else None
    if not isinstance(value, ast.Call):
        return True
    expressions = (*value.args, *(keyword.value for keyword in value.keywords))
    return any(
        not _is_safe_value(expression)
        or any(
            isinstance(node, (ast.Name, ast.Attribute))
            and isinstance(node.ctx, ast.Load)
            and (path := _dotted(node)) is not None
            and any(_touches(path, target.rsplit(".", 1)[0]) for target in pending)
            for node in walk(expression)
        )
        for expression in expressions
    )


def _not_called_assertions(statements: list[ast.stmt], origins: frozenset[str]) -> dict[str, int]:
    found: dict[str, int] = {}
    for stmt in statements:
        for node in _own_expressions(stmt):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr not in _NOT_CALLED_ASSERTIONS:
                continue
            asserted = _dotted(node.func.value)
            if asserted is not None and any(_is_prefix(origin, asserted) for origin in origins):
                found[asserted] = max(found.get(asserted, 0), node.lineno)
    return found


def _own_expressions(stmt: ast.stmt) -> Iterator[ast.AST]:
    for child in children(stmt):
        if isinstance(child, (ast.stmt, ast.excepthandler, ast.match_case)):
            continue
        yield from walk(child)


def _introspected_paths(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
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


def _last_effectful_line(fn: ast.FunctionDef | ast.AsyncFunctionDef, origins: frozenset[str]) -> int:
    last = 0
    for node in walk(fn):
        if isinstance(node, ast.Call) and not _is_assertion_call(node, origins):
            last = max(last, node.lineno)
    return last


def _is_assertion_call(node: ast.Call, origins: frozenset[str]) -> bool:
    if not isinstance(node.func, ast.Attribute) or not node.func.attr.startswith(_ASSERT_PREFIX):
        return False
    asserted = _dotted(node.func.value)
    return (
        asserted is not None
        and any(_is_prefix(origin, asserted) for origin in origins)
        and not any(isinstance(child, ast.Call) for arg in (*node.args, *node.keywords) for child in walk(arg))
    )


def _is_prefix(prefix: str, path: str) -> bool:
    return path == prefix or path.startswith(f"{prefix}.")


def _touches(path: str, other: str) -> bool:
    return _is_prefix(path, other) or _is_prefix(other, path)
