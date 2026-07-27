"""SARJ059: mock setup the test can never exercise is a lie about what is covered.

An arrange block that configures a collaborator the test never reaches misleads
every later reader — it says "this test depends on `refund` returning a receipt"
when the assertion has nothing to do with `refund`. It is also what a refactor
leaves behind: the call is deleted from the code under test, the `return_value`
line stays, and the test still passes while covering strictly less than its name
claims.

The rule only fires where deadness is **provable from the test itself**:

* **overwritten before use** — the same `<mock>.<attr>.return_value` /
  `.side_effect` target is assigned twice in one block with nothing in between
  that can execute code (other mock configuration, literal assignments, `pass`,
  imports). Nothing can have observed the first value, so it is dead,
* **asserted never called** — the test configures `<mock>.<attr>` and then
  asserts `<mock>.<attr>.assert_not_called()` (or `assert_not_awaited()`) on
  that path or a dotted prefix of it, with no further code afterwards that could
  invoke it. If the assertion passes, the configured return was never observed
  — the two statements contradict each other.

**Why the obvious version of this rule is not here.** The tempting formulation
is "a configured path that the function never mentions again": `gateway.refund.
return_value = X` where nothing else says `refund`. That was implemented and
measured first, and it is unusable. A mock reaches the code under test in ways
the test body does not spell out — it is handed over whole (`billing.charge(
gateway, 100)` and the SUT picks `.refund` off it), or it is installed by
`patch`, where the test never passes it anywhere at all. On the five audited
corpora that formulation produced 493 hits (bulbul 70, django 37, celery 386,
noura-be 0, fastapi 0), of which 17 were read line by line across all three
corpora that produced any: **17 false positives, 0 true**. The census explains
why — 196 of the 493 configured bases are `@patch`-decorator parameters, 29 are
`with patch(...) as m` bindings and 38 are fixture parameters, all wired into
the SUT where the test cannot see it, and the 126 locally constructed mocks are
handed to the SUT whole. Named examples, all false:
`django/tests/queries/test_sqlcompiler.py:31` (`cursor.execute.side_effect`, and
the cursor is patched onto the connection two lines later),
`django/tests/decorators/test_cache.py:147` (`mocked_time.return_value` — the
view calls `time.time()`), `celery/t/unit/app/test_app.py:1328`
(`router.route.return_value`, and `router` is passed to `send_task`),
`celery/t/unit/fixups/test_django.py:408`, and in bulbul
`agent/tests/test_agent_tools.py:1092` (`mock_datetime.now.return_value`),
`bulbul/tests/scenario_generation/test_scenario_generation_service.py:236`
(`llm_provider` is the injected fixture mock) and
`webserver/tests/public_api/test_calls.py:218`. The narrower salvage (fire only when the base
mock is a locally constructed `Mock()`/`MagicMock()` that escapes nowhere) is
sound but empty: of 966 locally constructed mocks and 982 configuration
statements across the same corpora, **0** were configured without the mock being
used elsewhere. A mock nobody hands to anything is a mock nobody writes.

The two shapes that survived are rare and always right: 5 hits across five
corpora, 1 in bulbul (`webserver/tests/audit/test_middleware.py:213`), 4 in
celery (`t/unit/utils/test_platforms.py:952` and `:981`, literally duplicated
`grp_module.getgrgid.return_value = [group_name]` lines;
`t/unit/backends/test_elasticsearch.py:340` and `:375`,
`x._server.update.return_value = {...}` under an `x._server.update.
assert_not_called()`), 0 in django/fastapi/noura-be, 0 false positives.

**Not duplicated from ruff.** `select = ["ALL"]` already covers the whole
"never used at all" family: `F841` flags `gateway = MagicMock()` with no later
use *and* `with patch(...) as m` with no use of `m`, `ARG001` flags an unused
`@patch`-injected parameter, and `PGH005` flags `mock.assert_called_once`
without parentheses. What none of them see is a mock that *is* used — used only
to configure something the test then throws away. That gap is this rule.

Deliberately NOT flagged:

* **a configured path the test simply never mentions again.** The dominant
  shape, and unknowable: see above,
* **a mid-test `assert_not_called()` checkpoint.** `pool_close.side_effect =
  ...` / `pool_close.assert_not_awaited()` / `await shutdown()` /
  `pool_close.assert_awaited_once()` asserts the collaborator has not fired
  *yet* — the setup is exercised two lines later
  (`bulbul/agent/tests/test_for_call_settings.py:1061`). Any positive call
  assertion or call introspection (`assert_called*`, `assert_awaited*`,
  `assert_has_calls`, `.called`, `.call_count`, `.call_args`, `reset_mock`) on
  the same path, its prefix or its extension, anywhere in the function,
  suppresses the diagnostic. Two of the six raw shape-B hits were this:
  `celery/t/unit/tasks/test_result.py:150` (`assert_not_called()` then
  `assert_called()` after a second act) and
  `celery/t/unit/worker/test_consumer.py:313`,
* **anything after the `assert_not_called()` that can run code.** A second act
  makes the configuration live again, so the rule requires no effectful call
  after the assertion line — only further `assert*` calls whose arguments do not
  themselves call anything,
* **a conditional or looped overwrite.** `m.get.return_value = A` followed by
  `if x: m.get.return_value = B` configures two different runs; only
  reassignments in the *same* block pair up,
* **a reassignment separated by anything that executes** — a call, an `await`,
  an attribute load, a subscript, a nested `def`. Celery's
  `t/unit/utils/test_platforms.py:230` sets `setuid.side_effect` inside a nested
  `raise_on_second_call` closure and again at module scope below it; the closure
  runs later, so the pair is not dead,
* **`side_effect = None` followed by `return_value = ...`.** Clearing
  `side_effect` re-enables `return_value`, so the two are not competing
  configurations of the same thing (`celery/t/unit/backends/test_gcs.py:414`).
  Only assignments to the *identical* target pair up,
* **`configure_mock(...)` / `attach_mock(...)` / `Mock(**{"a.return_value": …})`
  key strings.** Measured across the five corpora: 15 `configure_mock` /
  `attach_mock` calls and 116 `**{...}` call sites, none of which the two sound
  shapes above could be extended to reach without re-introducing the
  unknowable-reachability problem,
* non-test files.
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING, NamedTuple, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none
from sarj_python_lint.rules._paths import is_test_path


if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


# The two attributes that *configure* what a mock does when called. Assigning
# either is arrange, never act.
_CONFIG_ATTRS = frozenset({"return_value", "side_effect"})

# Assertions that the mock was never reached. If one of these passes, every
# configuration of that path is provably unobserved.
_NOT_CALLED_ASSERTIONS = frozenset({"assert_not_called", "assert_not_awaited"})

# Reads of the call record. Their presence means the test *does* care whether
# the path was called, so an `assert_not_called` elsewhere is a checkpoint
# rather than the final word.
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
    """Mock configuration the test provably never exercises."""

    id: str = "unused-mock-setup"
    code: str = "SARJ059"
    description: str = "Mock setup the test can never exercise — overwritten before use, or asserted never called."

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        """Flag mock configuration statements that nothing in the test can observe.

        Returns:
            One diagnostic per dead configuration statement, sorted by position.

        """
        if not is_test_path(path):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []

        seen: set[tuple[int, int]] = set()
        diags: list[Diagnostic] = []
        for fn in ast.walk(tree):
            if not isinstance(fn, _FUNC_NODES):
                continue
            for finding in _dead_setups(fn):
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


def _dead_setups(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> Iterator[_Finding]:
    yield from _overwritten_before_use(fn)
    yield from _asserted_never_called(fn)


def _overwritten_before_use(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> Iterator[_Finding]:
    """Find configurations reassigned before anything could read them.

    Yields:
        A finding per configuration statement whose value is replaced with no
        executable statement in between.

    """
    for block in _blocks(fn):
        pending: dict[str, ast.stmt] = {}
        for stmt in block:
            target = _config_target(stmt)
            if target is None:
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


def _asserted_never_called(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> Iterator[_Finding]:
    """Find configurations of a path the test then asserts was never called.

    Yields:
        A finding per configuration contradicted by an `assert_not_called`.

    """
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
    """Walk the statement blocks belonging to this function's own scope.

    Yields:
        Each list of statements, skipping bodies of nested functions and
        classes, which are processed as their own scopes.

    """
    stack: list[ast.AST] = [fn]
    while stack:
        node = stack.pop()
        for block in _child_blocks(node):
            yield block
            stack.extend(stmt for stmt in block if not isinstance(stmt, _NESTED_SCOPES))


def _child_blocks(node: ast.AST) -> list[list[ast.stmt]]:
    """List the statement blocks a compound statement owns.

    Returns:
        Every non-empty block, `except` handlers and `match` cases included.

    """
    blocks: list[list[ast.stmt]] = []
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        blocks.append(node.body)
    elif isinstance(node, (ast.If, ast.For, ast.AsyncFor, ast.While)):
        blocks.extend((node.body, node.orelse))
    elif isinstance(node, (ast.With, ast.AsyncWith, ast.ExceptHandler)):
        blocks.append(node.body)
    elif isinstance(node, (ast.Try, ast.TryStar)):
        blocks.extend((node.body, node.orelse, node.finalbody))
        blocks.extend(handler.body for handler in node.handlers)
    elif isinstance(node, ast.Match):
        blocks.extend(case.body for case in node.cases)
    return [block for block in blocks if block]


def _scope_statements(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> Iterator[ast.stmt]:
    """Walk every statement in the function's own scope.

    Yields:
        Statements, nested function and class bodies excluded.

    """
    for block in _blocks(fn):
        yield from block


def _own_expressions(stmt: ast.stmt) -> Iterator[ast.AST]:
    """Walk the expressions a statement owns, without descending into other statements.

    Yields:
        Every expression node belonging to `stmt` itself, so a nested block's
        contents are attributed to that block rather than to its header.

    """
    for child in ast.iter_child_nodes(stmt):
        if isinstance(child, (ast.stmt, ast.excepthandler, ast.match_case)):
            continue
        yield from ast.walk(child)


def _config_target(stmt: ast.stmt) -> str | None:
    """Read the dotted target of a mock configuration assignment.

    Returns:
        `"m.get.return_value"` for `m.get.return_value = ...`, else None.

    """
    if not isinstance(stmt, ast.Assign) or len(stmt.targets) != 1:
        return None
    target = stmt.targets[0]
    if not isinstance(target, ast.Attribute) or target.attr not in _CONFIG_ATTRS:
        return None
    return _dotted(target)


def _dotted(node: ast.expr) -> str | None:
    """Render a `Name`-rooted attribute chain as a dotted string.

    Returns:
        The dotted path, or None when the chain is rooted in a call or literal.

    """
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
    """Report whether a statement provably cannot execute user code.

    An inert statement between two configurations cannot have read the first
    one. Anything that calls, awaits, subscripts or reads an attribute is not
    inert: a property getter or a `__getitem__` can reach the mock.

    Returns:
        True when the statement runs no user code.

    """
    if isinstance(stmt, (ast.Pass, ast.Import, ast.ImportFrom)):
        return True
    if isinstance(stmt, ast.Expr):
        return isinstance(stmt.value, ast.Constant)
    if not isinstance(stmt, ast.Assign):
        return False
    if not all(isinstance(target, ast.Name) for target in stmt.targets):
        # `obj.attr = 1` can hit a property setter, `d[k] = 1` a `__setitem__`.
        return False
    return not any(isinstance(node, _EFFECTFUL_NODES) for node in ast.walk(stmt.value))


def _not_called_assertions(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> dict[str, int]:
    """Collect `x.y.assert_not_called()` calls made in this function's scope.

    Returns:
        Asserted dotted path to the line of its last such assertion.

    """
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


def _introspected_paths(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    """Collect every path the function reads the call record of.

    Searches the whole subtree, nested helpers included: a positive call
    assertion anywhere means the test does expect the call, so an
    `assert_not_called` on the same path is a mid-test checkpoint.

    Returns:
        Dotted paths carrying a call assertion or call-record read.

    """
    found: set[str] = set()
    for node in ast.walk(fn):
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
    """Find the last line of the function that can invoke a mock.

    Assertion calls are excluded — `m.assert_called_with(3)` inspects the mock
    rather than driving it — but only when their own arguments call nothing.

    Returns:
        The greatest such line number, or 0 when the function makes no calls.

    """
    last = 0
    for node in ast.walk(fn):
        if isinstance(node, ast.Call) and not _is_assertion_call(node):
            last = max(last, node.lineno)
    return last


def _is_assertion_call(node: ast.Call) -> bool:
    if not isinstance(node.func, ast.Attribute) or not node.func.attr.startswith(_ASSERT_PREFIX):
        return False
    return not any(isinstance(child, ast.Call) for arg in (*node.args, *node.keywords) for child in ast.walk(arg))


def _is_prefix(prefix: str, path: str) -> bool:
    return path == prefix or path.startswith(f"{prefix}.")


def _touches(path: str, other: str) -> bool:
    return _is_prefix(path, other) or _is_prefix(other, path)
