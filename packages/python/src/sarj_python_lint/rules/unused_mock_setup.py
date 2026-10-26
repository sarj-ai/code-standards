from __future__ import annotations

import ast
import builtins
from pathlib import PurePosixPath
from types import MappingProxyType
from typing import (
    TYPE_CHECKING,
    ClassVar,
    NamedTuple,
    override,
)

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
from sarj_python_lint.rules._ast_index import children, walk
from sarj_python_lint.rules._ast_names import dotted_name as _dotted
from sarj_python_lint.rules._closed_helpers import dynamic_namespace
from sarj_python_lint.rules._paths import is_test_path


if TYPE_CHECKING:
    from collections.abc import Iterator

    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rules._resource_provenance import ResourceProvenance


# The two attributes that *configure* what a mock does when called.
_CONFIG_ATTRS = frozenset({"return_value", "side_effect"})
_BUILTIN_NAMESPACE = MappingProxyType[str, object](vars(builtins))
_EXCEPTION_TYPES = frozenset(
    name for name, value in _BUILTIN_NAMESPACE.items() if isinstance(value, type) and issubclass(value, BaseException)
)

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
_PATCH_OBJECT_POSITIONAL_ARGUMENTS = 2

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
            "Delete the earlier inert configuration, retaining the mock constructor and binding when removing a keyword, or place the intended action before reconfiguration; "
            "delete behavior configuration contradicted by a terminal never-called assertion."
        ),
        category=RuleCategory.TESTING,
        autofix=AutofixPolicy.SAFE,
        limitations=(
            "Safe fixes remove only proven inert standalone configuration assignments; proven inert constructor keywords are removed while preserving the constructor, binding and annotation. Commented and annotated configuration writes remain review-only.",
            "Only non-generated test paths and stable local names unconditionally initialized from unittest.mock or an unshadowed pytest-mock fixture before configuration are analyzed. Dotted stores, auto-children, configured return-value chains, replacement or unpacked options, dynamic namespace access, and direct constructor-root or builtin namespace mutation are excluded. Unseen external mutations are not resolved.",
            "Only same-block overwrites and exact-path terminal never-called assertions are checked; uncertain evaluation, native setter/iteration effects, custom hash/equality, control flow, reads, and terminal receiver escapes are excluded. Configuration values require literal/native primitive provenance.",
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
            RuleExample(
                example_id="safe-autofix-subset",
                title="A proven subset has a convergent automatic fix",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_service.py",
                        (
                            "from unittest.mock import Mock\n"
                            "def test_value():\n"
                            "    value = Mock(return_value=1)\n"
                            "    value.return_value = 2\n"
                            "    assert value() == 2\n"
                        ),
                    ),
                ),
                fixed_files=(
                    ExampleFile.python(
                        "tests/test_service.py",
                        (
                            "from unittest.mock import Mock\n"
                            "def test_value():\n"
                            "    value = Mock()\n"
                            "    value.return_value = 2\n"
                            "    assert value() == 2\n"
                        ),
                    ),
                ),
                focus_path=PurePosixPath("tests/test_service.py"),
                expected_count=1,
            ),
        ),
        aliases=("unused-mock-setup",),
    )
    description: str = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        path = context.path
        if not is_test_path(path) or context.generated:
            return []
        tree = context.tree
        if tree is None or dynamic_namespace(context):
            return []

        provenance = context.resource_provenance
        if not provenance.builtin_namespace_untouched:
            return []
        seen: set[tuple[int, int]] = set()
        diags: list[Diagnostic] = []
        for fn in context.nodes(*_FUNC_NODES):
            for finding in _dead_setups(fn, provenance):
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
                        severity=Severity.ERROR,
                        message=finding.message,
                    )
                )
        diags.sort(key=lambda d: (d.line, d.col))
        return diags


def _dead_setups(fn: ast.FunctionDef | ast.AsyncFunctionDef, provenance: ResourceProvenance) -> Iterator[_Finding]:
    origins = _mock_origins(fn, provenance)
    if not origins:
        return
    yield from _overwritten_before_use(fn, origins, provenance)
    yield from _asserted_never_called(fn, origins, provenance)


def _overwritten_before_use(
    fn: ast.FunctionDef | ast.AsyncFunctionDef,
    origins: frozenset[str],
    provenance: ResourceProvenance,
) -> Iterator[_Finding]:
    has_mocker_fixture = _has_unshadowed_mocker_fixture(fn)
    for block in _blocks(fn):
        yield from _overwritten_block_setups(block, origins, provenance, has_mocker_fixture=has_mocker_fixture)


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


def _mock_origins(fn: ast.FunctionDef | ast.AsyncFunctionDef, provenance: ResourceProvenance) -> frozenset[str]:
    has_mocker_fixture = _has_unshadowed_mocker_fixture(fn)
    origins: set[str] = set()
    for stmt in fn.body:
        match stmt:
            case ast.Assign(targets=[ast.Name() as target], value=ast.Call() as call):
                pass
            case ast.AnnAssign(target=ast.Name() as target, value=ast.Call() as call):
                pass
            case _:
                continue
        if provenance.binding(target.id, call) is target and _is_mock_configurator(
            call, provenance, has_mocker_fixture=has_mocker_fixture
        ):
            origins.add(target.id)
    return frozenset(origins)


def _is_mock_configurator(call: ast.Call, provenance: ResourceProvenance, *, has_mocker_fixture: bool) -> bool:
    func = call.func
    path = _dotted(func)
    if (
        path is None
        or path.partition(".")[0] in provenance.mutated
        or any(isinstance(argument, ast.Starred) for argument in call.args)
        or any(keyword.arg in {None, "new", "new_callable", "_mock_delegate"} for keyword in call.keywords)
    ):
        return False
    if has_mocker_fixture and isinstance(func, ast.Attribute):
        if isinstance(func.value, ast.Name) and func.value.id == _MOCKER:
            return func.attr in _MOCKER_CONFIGURATORS and (func.attr != "patch" or len(call.args) <= 1)
        if (
            func.attr == "object"
            and isinstance(func.value, ast.Attribute)
            and func.value.attr == "patch"
            and isinstance(func.value.value, ast.Name)
            and func.value.value.id == _MOCKER
        ):
            return len(call.args) <= _PATCH_OBJECT_POSITIONAL_ARGUMENTS
    return any(
        provenance.context.imports.resolves(func, sources=_UNITTEST_MOCK, symbol=symbol)
        for symbol in _MOCK_CONSTRUCTORS
    )


def _asserted_never_called(
    fn: ast.FunctionDef | ast.AsyncFunctionDef, origins: frozenset[str], provenance: ResourceProvenance
) -> Iterator[_Finding]:
    if not fn.name.startswith("test_") or _is_fixture(fn):
        return
    introspected = _introspected_paths(fn)
    loaded_configs = _loaded_config_paths(fn)
    last_effect = _last_effectful_line(fn, origins)
    loop_statements = _loop_statement_ids(fn)
    for block in _blocks(fn):
        not_called = _not_called_assertions(block, origins)
        for stmt in block:
            target = _config_target(stmt, origins, provenance)
            if (
                target is None
                or id(stmt) in loop_statements
                or target in loaded_configs
                or not _inert_configuration(stmt, target, provenance)
                or _receiver_escapes(target.rsplit(".", 1)[0], stmt, provenance)
            ):
                continue
            configured = target.rsplit(".", 1)[0]
            if any(_touches(configured, other) for other in introspected):
                continue
            yield from _unused_asserted_setup(stmt, target, configured, not_called, last_effect)


def _receiver_escapes(name: str, at: ast.stmt, provenance: ResourceProvenance) -> bool:
    binding = provenance.binding(name, at)
    for read in provenance.reads.get(name, ()):
        if provenance.binding(name, read) is not binding:
            continue
        parent = provenance.context.parents.get(read)
        if not isinstance(parent, ast.Attribute) or parent.value is not read:
            return True
        if isinstance(parent.ctx, ast.Store) and parent.attr in _CONFIG_ATTRS:
            continue
        call = provenance.context.parents.get(parent)
        if not (isinstance(call, ast.Call) and call.func is parent and parent.attr in _NOT_CALLED_ASSERTIONS):
            return True
    return False


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


def _config_target(stmt: ast.stmt, origins: frozenset[str], provenance: ResourceProvenance) -> str | None:
    if not isinstance(stmt, ast.Assign) or len(stmt.targets) != 1:
        return None
    target = stmt.targets[0]
    if (
        not isinstance(target, ast.Attribute)
        or target.attr not in _CONFIG_ATTRS
        or not isinstance(target.value, ast.Name)
        or target.value.id not in origins
        or provenance.constructor(target.value, stmt) is None
    ):
        return None
    return f"{target.value.id}.{target.attr}"


def _is_safe_value(node: ast.expr, provenance: ResourceProvenance, *, hash_key: bool = False) -> bool:
    match node:
        case ast.Constant():
            return True
        case ast.Name():
            binding = provenance.binding(node.id, node)
            if binding is None:
                return node.id in _EXCEPTION_TYPES and provenance.context.imports.builtin_is_unshadowed(node.id)
            if not isinstance(binding, ast.Name) or provenance.scope(binding) is not provenance.scope(node):
                return False
            # Stable, already executed scalar assignments prove both initialization and native hashing.
            return isinstance(provenance.assignment_value(binding, node), ast.Constant)
        case ast.List() | ast.Tuple():
            return (not hash_key or isinstance(node, ast.Tuple)) and all(
                _is_safe_value(element, provenance, hash_key=hash_key) for element in node.elts
            )
        case ast.Set():
            return not hash_key and all(_is_safe_value(element, provenance, hash_key=True) for element in node.elts)
        case ast.Dict():
            return (
                not hash_key
                and all(key is not None and _is_safe_value(key, provenance, hash_key=True) for key in node.keys)
                and all(_is_safe_value(value, provenance) for value in node.values)
            )
        case _:
            return False


def _inert_configuration(stmt: ast.stmt, target: str, provenance: ResourceProvenance) -> bool:
    if not isinstance(stmt, ast.Assign | ast.AnnAssign):
        return False
    value = stmt.value
    assigned = stmt.targets[0] if isinstance(stmt, ast.Assign) else stmt.target
    if isinstance(assigned, ast.Name) and isinstance(value, ast.Call):
        attribute = target.rsplit(".", 1)[1]
        value = next((keyword.value for keyword in value.keywords if keyword.arg == attribute), None)
    return value is not None and _is_safe_value(value, provenance)


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


def _overwritten_block_setups(
    block: list[ast.stmt],
    origins: frozenset[str],
    provenance: ResourceProvenance,
    *,
    has_mocker_fixture: bool,
) -> Iterator[_Finding]:
    pending: dict[str, ast.stmt] = {}
    for stmt in block:
        target = _config_target(stmt, origins, provenance)
        if target is None:
            pending = _pending_after_statement(
                stmt, origins, pending, provenance, has_mocker_fixture=has_mocker_fixture
            )
            continue
        if not _inert_configuration(stmt, target, provenance):
            pending.clear()
            continue
        if _statement_observes_pending(stmt, pending, provenance):
            pending.clear()
        previous = pending.get(target)
        if previous is not None:
            yield _Finding(
                previous,
                (
                    f"`{target}` is set here and overwritten on line {stmt.lineno} with nothing in "
                    "between that could call the mock, so this value is never used. "
                    + (
                        "Remove the overwritten constructor keyword, retaining the mock constructor and binding"
                        if isinstance(previous, ast.Assign | ast.AnnAssign) and isinstance(previous.value, ast.Call)
                        else "Delete the dead setup, or move the code under test between the two configurations"
                    )
                ),
            )
        pending[target] = stmt


def _statement_observes_pending(stmt: ast.stmt, pending: dict[str, ast.stmt], provenance: ResourceProvenance) -> bool:
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
    return not _is_safe_value(value, provenance)


def _unused_asserted_setup(
    stmt: ast.stmt, target: str, configured: str, not_called: dict[str, int], last_effect: int
) -> Iterator[_Finding]:
    for asserted, line in not_called.items():
        if line > stmt.lineno and asserted == configured and last_effect <= line:
            yield _Finding(
                stmt,
                (
                    f"`{target}` is configured here, but the test ends by proving `{asserted}` was never "
                    "called, so its behavior cannot affect the test. Delete this inert configuration; retain the mock constructor and binding"
                ),
            )
            break


def _pending_after_statement(
    stmt: ast.stmt,
    origins: frozenset[str],
    pending: dict[str, ast.stmt],
    provenance: ResourceProvenance,
    *,
    has_mocker_fixture: bool,
) -> dict[str, ast.stmt]:
    initial = _initial_mock_configs(stmt, provenance, has_mocker_fixture=has_mocker_fixture)
    if initial and initial[0].partition(".")[0] in origins:
        if _constructor_observes_pending(stmt, pending, provenance):
            pending.clear()
        configured_name = initial[0].partition(".")[0]
        pending = {target: setup for target, setup in pending.items() if not target.startswith(f"{configured_name}.")}
        pending.update(
            (configured, stmt) for configured in initial if _inert_configuration(stmt, configured, provenance)
        )
        return pending
    if not _is_inert(stmt, provenance):
        pending.clear()
    return pending


def _constructor_observes_pending(stmt: ast.stmt, pending: dict[str, ast.stmt], provenance: ResourceProvenance) -> bool:
    value = stmt.value if isinstance(stmt, (ast.Assign, ast.AnnAssign)) else None
    if not isinstance(value, ast.Call):
        return True
    expressions = (*value.args, *(keyword.value for keyword in value.keywords))
    return any(
        not _is_safe_value(expression, provenance)
        or any(
            isinstance(node, (ast.Name, ast.Attribute))
            and isinstance(node.ctx, ast.Load)
            and (path := _dotted(node)) is not None
            and any(_touches(path, target.rsplit(".", 1)[0]) for target in pending)
            for node in walk(expression)
        )
        for expression in expressions
    )


def _is_inert(stmt: ast.stmt, provenance: ResourceProvenance) -> bool:
    if isinstance(stmt, (ast.Pass, ast.Import, ast.ImportFrom)):
        return True
    if isinstance(stmt, ast.Expr):
        return isinstance(stmt.value, ast.Constant)
    if not isinstance(stmt, ast.Assign):
        return False
    if not all(isinstance(target, ast.Name) for target in stmt.targets):
        # `obj.attr = 1` can hit a property setter, `d[k] = 1` a `__setitem__`.
        return False
    return _is_safe_value(stmt.value, provenance)


def _initial_mock_configs(
    stmt: ast.stmt, provenance: ResourceProvenance, *, has_mocker_fixture: bool
) -> tuple[str, ...]:
    match stmt:
        case ast.Assign(targets=[ast.Name(id=name)], value=ast.Call() as call):
            pass
        case ast.AnnAssign(target=ast.Name(id=name), value=ast.Call() as call):
            pass
        case _:
            return ()
    if not _is_mock_configurator(call, provenance, has_mocker_fixture=has_mocker_fixture):
        return ()
    return tuple(f"{name}.{keyword.arg}" for keyword in call.keywords if keyword.arg in _CONFIG_ATTRS)
