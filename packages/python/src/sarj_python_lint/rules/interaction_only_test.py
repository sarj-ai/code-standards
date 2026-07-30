"""SARJ063: a test whose only assertions are about which calls landed on a mock.

```python
def test_send_notification():
    mailer = MagicMock()
    notify(mailer, user)
    mailer.send.assert_called_once_with(user.email)   # the only assertion
```

A test like this passes exactly as long as `notify` keeps calling `mailer.send`
with that argument list. Reorder the two collaborators, inline a helper, batch
two sends into one — nothing observable changed, and the test goes red. Send the
wrong body, send to the wrong user, drop the record that was supposed to be
written — nothing the test checks moved, and it stays green. It records today's
implementation, not the behaviour. The fix is to assert the outcome the caller
can see (the returned value, the persisted row, the rendered message body) and
keep interaction assertions for the side effects that genuinely have no
observable result.

**How this divides the space with SARJ043 `zero-assertion-test`.** SARJ043 fires
on a test with *no* assertion of any kind; every `m.assert_called_*()` counts as
an assertion there, so SARJ043 is silent on this shape by construction. SARJ063
is the adjacent case: at least one assertion, and every one of them is mock call
bookkeeping. The two never fire on the same function. SARJ043's notion of "what
counts as an assertion" is re-stated privately in this module rather than shared,
so the two rules can drift apart without either editing the other.

Fires when ALL of these hold for a pytest-collected test function:

* it makes at least one assertion, counting `assert` statements, `pytest.raises`
  / `pytest.warns` blocks, `self.assert*` calls, `assert*` / `expect*` /
  `verify*` / `validate*` helpers, and `m.assert_called*()` — including
  assertions made inside a helper defined in the same module,
* **every** one of those assertions is mock call bookkeeping: an
  `assert_called*` / `assert_not_called` / `assert_any_call` / `assert_has_calls`
  / `assert_awaited*` call, or an assertion reading `.called`, `.call_count`,
  `.call_args`, `.call_args_list`, `.mock_calls`, `.method_calls`,
  `.await_count`, `.await_args`,
* it pins **two or more distinct root objects** — so the test is describing a
  call *sequence across collaborators*, not one collaborator asked several
  questions. `mock_hook.return_value.get_instance` and
  `mock_hook.return_value.start_pipeline` are one root, `mock_hook`,
* none of those assertions is negative,
* the test name does not declare the interaction as the contract, and the pinned
  targets are neither all callback registrations nor all patched free functions.

**The guards are the rule.** Across 49,363 collected tests in six repos, 4,361
tests assert only on mock bookkeeping. Shipping that population would have been
indefensible: 61 of django's 62 raw findings are legitimate. The funnel:

| corpus   |   raw | ≥2 roots | non-negative |  name | registration | free fn |
|----------|-------|----------|--------------|-------|--------------|---------|
| bulbul   |   107 |       16 |            7 |     7 |            5 |       5 |
| noura-be |     3 |        0 |            0 |     0 |            0 |       0 |
| django   |    62 |        6 |            2 |     2 |            2 |       1 |
| fastapi  |     4 |        0 |            0 |     0 |            0 |       0 |
| celery   |   473 |       78 |           52 |    50 |           50 |      38 |
| airflow  | 3,712 |      757 |          540 |   521 |          521 |     293 |

Counting *root objects* rather than dotted target paths at the second stage is
what makes the funnel hold on a large corpus. Before that reduction the rule
returned 1,261 findings over the 14-repo OSS sweep plus the first-party repos;
after it, 462 — 799 removed, 63%. It cost nothing on the calibration corpus
(bulbul 5→5, noura-be 0→0, django 1→1, fastapi 0→0, and 0→0 across
digital-bank, submissions and ai); airflow went 999→293. The removals are
adapter passthroughs asking one collaborator several questions —
`airflow/providers/google/tests/unit/google/cloud/hooks/test_dataproc_metastore.py:265`
pins `mock_client` and `mock_client.return_value.restore_service`,
`.../operators/test_datafusion.py:221` pins three methods of
`mock_hook.return_value` — and those tests are correct as written, because a
thin adapter has no observable output but the call it forwards. One true
positive goes with them, `celery/t/unit/tasks/test_result.py:504`: `test_get`
replaces `x.join` and `x.join_native` on the `ResultSet` it is testing and then
asserts they were called, so both roots are the system under test. That is
SARJ061 `no-patching-system-under-test`'s shape, not this rule's.

Treating a leading `self.` / `cls.` as transparent was tried and rejected: it
restores 20 findings, all airflow, all the same DBAPI-hook shape
(`self.conn.commit` + `self.cur.execute` in
`providers/common/sql/.../test_dbapi.py:116` and its siblings), and 0 anywhere
else. Those are the adapter passthroughs the guard exists to remove, so the
plain root split is the calibrated behaviour.

Manual read of 22 findings (5 bulbul, 1 django, 16 celery) classed 20 true
positives and 2 false positives (9%). The root reduction took one of those two
with it: `celery/t/unit/utils/test_debug.py:16` (`test_blockdetection`) pins
`signals.arm_alarm`, `signals.__setitem__` and `signals.reset_alarm`, one
object, and no longer fires. The one that remains is
`celery/t/unit/worker/test_autoscale.py:200` (`test_thread_crash` asserts
`os._exit` was called with 1, which cannot be observed without exiting). That is
"the effect is on process-global machinery"; a guard for that shape would be
overfitting to one corpus, so `# sarj-noqa: SARJ063` is the intended escape.

Deliberately NOT flagged:

* **a test pinning a single collaborator**, however many of its methods or
  bookkeeping attributes it reads. Asserting `call_count` *and* `call_args` on
  one mock is one fact — "this collaborator was told once, with this payload" —
  and for a notifier that is the whole contract; asking the same object two
  questions (`mock_source_db.backup` then `mock_source_db.close`) is still one
  fact about one object. A collaborator is an object, not one of its methods —
  the same reduction SARJ062 `over-mocked-test` applies when it counts
  substituted collaborators, and the two rules have to agree or a shape can be
  "one collaborator" to one rule and "two" to the other. This guard alone
  removed 56 of the 62 raw django findings and all four raw fastapi
  findings, without touching the motivating shape above. Every one of the ten
  file-watcher tests in `django/tests/utils_tests/test_autoreload.py` (`test_glob`
  at :642, `test_multiple_globs` at :655, and their siblings) reads
  `notify_mock.call_count` then `notify_mock.call_args`; the reloader's entire
  observable output *is* that callback. So do
  `django/tests/auth_tests/test_models.py:295` (`test_user_double_save`, whose
  docstring says "should trigger password_changed() once"),
  `django/tests/auth_tests/test_validators.py:164` and
  `django/tests/backends/base/test_base.py:204`,
* **any negative interaction assertion.** `assert_not_called`,
  `assert_not_awaited`, `assert not m.called`, `m.call_count == 0`,
  `self.assertFalse(m.called)`. Two shapes hide here and both are legitimate: the
  pure negative-space contract ("does not charge the card twice") has no outcome
  to assert on by construction, and the mixed positive/negative test is a
  *routing* claim — `django/tests/check_framework/test_multi_db.py:23` asserts
  `mock_check_field_default.called` and `not mock_check_field_other.called`,
  which is the only way to say "this went to the default database". 13 findings
  across bulbul and django, all legitimate,
* **a test whose name says the interaction is the contract** — `publish`,
  `emit`, `dispatch`, `broadcast`, `retry`, `backoff`, `cache`, `idempoten`,
  `debounce`, `throttl`, `not_called`, `only_once`. Measured, not guessed: this
  list removes 2 celery findings (`test_broadcast` and `test_broadcast_limit` in
  `celery/t/unit/app/test_control.py:213`/`:221`, where broadcasting the command
  *is* the contract) and 19 airflow ones — `retry`, `dispatch` and `emit`
  wrappers such as `airflow/providers/git/tests/unit/git/bundles/
  test_git.py:1348` (`test_clone_bare_repo_invalid_repository_error_retry`) —
  and none in bulbul, noura-be, django or fastapi. Any wider and it guts the
  rule — an earlier draft that also matched `never`, `does_not`, `lazy` and
  `memo` was cut back for that reason,
* **a test that only pins callback registration** — every target ends in
  `connect`, `on`, `off`, `subscribe`, `register`, `add_listener`, … Wiring a
  handler onto a collaborator returns nothing and changes nothing until the event
  fires, so the registration is the only checkable fact. bulbul's
  `agent/tests/test_silence_monitor.py:79`/`:95` (`room.on`/`session.on`, then
  `room.off`/`session.off`) are the shape, and the only two findings this guard
  still removes across the six repos: `celery/t/unit/fixups/test_django.py:183`
  (`test_install` asserts four `sigs.*.connect` calls) used to reach it and is
  now cut earlier, by the distinct-root guard, since all four hang off one
  `sigs` object,
* **a test where every pinned target is a patched free function** — a bare name
  with no receiver, which means the collaborator was swapped in by `@patch` at
  module scope rather than handed to the code as an object. There is no instance
  whose state the test could have asserted on instead.
  `celery/t/unit/utils/test_platforms.py:327` (`test_setuid` pins `parse_uid`
  and `os.setuid`), `celery/t/unit/concurrency/test_eventlet.py:47`
  (`monkey_patch`, `hub_blocking_detection`) and
  `django/tests/test_utils/test_simpletestcase.py:88` (`test_debug_cleanup`
  pins the patched `_pre_setup` / `_post_teardown` lifecycle hooks) are all
  cleared by it. A test that pins even one method on an object it holds
  (`mock_blob.download_as_bytes`, `client.delete_one`) still fires,
* a test that also asserts anything else — a returned value, a raised error, a
  row read back from a fixture. One non-interaction assertion is enough,
* **a file pytest would never collect**, and a skipped test, a fixture, a stub
  body, a `test_*` nested inside another function, or a test that re-runs another
  module's `test_*` — the same collection gating SARJ043 applies, for the same
  reasons.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from enum import Enum, auto
import re
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none
from sarj_python_lint.rules._ast_index import nodes, walk
from sarj_python_lint.rules._paths import is_test_path


if TYPE_CHECKING:
    from pathlib import Path


# --- what counts as an assertion at all (SARJ043's notion, re-stated privately) ---

# Names that verify something, however the project spells them.
_ASSERTION_NAME_RE = re.compile(r"^_?(assert|expect|verify|validate)", re.IGNORECASE)

# `raises` / `warns` as a token anywhere in the name, covering
# `pytest.deprecated_call`, `pytest.RaisesGroup` and project-local wrappers.
_RAISES_TOKEN_RE = re.compile(r"(^|_)(raises|warns|deprecated_call)", re.IGNORECASE)

_RAISES_NAMES = frozenset({"raises", "warns", "fail"})

# Fluent verification DSLs reached through an attribute rather than a call name.
_FLUENT_ATTRS = frozenset({"expect"})

# --- what counts as an *interaction* assertion specifically ---

# `unittest.mock` spells its call-bookkeeping assertions with these stems:
# `assert_called`, `assert_called_once_with`, `assert_awaited_with`, ...
_MOCK_ASSERT_PREFIXES = ("assert_called", "assert_awaited", "assert_not_called", "assert_not_awaited")

_MOCK_ASSERT_NAMES = frozenset({"assert_any_await", "assert_any_call", "assert_has_awaits", "assert_has_calls"})

# The negative-space assertions: "this must NOT have happened".
_MOCK_NEGATIVE_ASSERTS = frozenset({"assert_not_awaited", "assert_not_called"})

# unittest spellings of the same negative claim: `self.assertFalse(m.called)`.
_NEGATIVE_ASSERT_HELPERS = frozenset({"assertFalse", "assertIsNone", "assertNotCalled", "assert_false"})

# Mock attributes recording call bookkeeping and nothing about behaviour.
_MOCK_STATE_ATTRS = frozenset(
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
    }
)

# --- test-collection gating, matching SARJ043 ---

_TEST_PREFIX = "test_"

# pytest's default `python_files`. `is_test_path` is broader on purpose.
_COLLECTED_SUFFIX = "_test.py"

# Manual CLI probes live here under `test_*.py` names but are never collected.
_UNCOLLECTED_DIR_NAMES = frozenset({"scripts"})

_SKIP_MARKERS = frozenset({"skip", "skipif", "xfail"})

_FIXTURE = "fixture"

_FUNC_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)

# --- the calibrated guards; see the module docstring for the measurements ---

# Distinct mocked collaborators that must be pinned before the test is
# describing a *sequence* rather than a single notification. Counted by root
# object, matching SARJ062: a collaborator is an object, not one of its methods.
_MIN_INTERACTION_TARGETS = 2

# Wiring a callback onto a collaborator is the one side effect that genuinely
# has no observable result: nothing is returned and nothing changes until the
# event fires. A test that only pins registrations is checking the only thing
# it can check.
_REGISTRATION_METHODS = frozenset(
    {
        "add_done_callback",
        "add_event_handler",
        "add_listener",
        "add_signal_handler",
        "attach",
        "bind",
        "connect",
        "detach",
        "disconnect",
        "listen",
        "off",
        "on",
        "on_event",
        "once",
        "register",
        "remove_listener",
        "remove_signal_handler",
        "subscribe",
        "unbind",
        "unregister",
        "unsubscribe",
    }
)

# Test names declaring that the interaction *is* the contract under test.
_INTERACTION_CONTRACT_RE = re.compile(
    r"publish|emit|dispatch|broadcast|retr(y|ies|ied)|backoff|cach|idempoten|debounce|throttl|not_called|only_once",
    re.IGNORECASE,
)


class _Kind(Enum):
    """What a single assertion verifies."""

    OUTCOME = auto()
    INTERACTION = auto()
    NEGATIVE_INTERACTION = auto()


@dataclass(frozen=True, slots=True)
class _Counts:
    """How many assertions of each kind a function performs, and on what."""

    outcome: int
    interaction: int
    negative: int
    targets: frozenset[str]

    def merged(self, other: _Counts) -> _Counts:
        """Add another function's assertion counts to this one's.

        Returns:
            The element-wise sum, with the interaction targets unioned.

        """
        return _Counts(
            outcome=self.outcome + other.outcome,
            interaction=self.interaction + other.interaction,
            negative=self.negative + other.negative,
            targets=self.targets | other.targets,
        )


@dataclass(frozen=True, slots=True)
class _Profile:
    """A collected test function together with its assertion counts."""

    node: ast.FunctionDef | ast.AsyncFunctionDef
    counts: _Counts


class InteractionOnlyTest(Rule):
    """A test asserting only which calls hit a mock pins the implementation."""

    id: str = "interaction-only-test"
    code: str = "SARJ063"
    description: str = "Test asserts only on mock call bookkeeping — it pins the call sequence, not the behaviour."

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        """Flag tests whose every assertion is a mock-interaction assertion.

        Returns:
            One diagnostic per interaction-only test, sorted by position.

        """
        if not is_test_path(path) or not _is_collected_module(path):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []

        diags = [
            Diagnostic(
                path=path,
                line=profile.node.lineno,
                col=profile.node.col_offset + 1,
                code=self.code,
                message=(
                    f"every assertion in `{profile.node.name}` is about which calls landed on a mock, so it "
                    "pins today's call sequence and goes red on a refactor that changes nothing observable. "
                    "Assert on the outcome — the returned value, the persisted row, the rendered body — and "
                    "keep interaction assertions for side effects you genuinely cannot observe."
                ),
            )
            for profile in _interaction_only_tests(tree)
        ]
        diags.sort(key=lambda d: (d.line, d.col))
        return diags


def _interaction_only_tests(tree: ast.Module) -> list[_Profile]:
    """Apply the calibrated guards to the raw per-test assertion profiles.

    Returns:
        The profiles of the tests that should be reported.

    """
    hits: list[_Profile] = []
    for profile in _test_profiles(tree):
        counts = profile.counts
        if counts.outcome or not counts.interaction:
            # An outcome assertion clears the test; no assertion at all is
            # SARJ043's finding, not this rule's.
            continue
        if len(_root_objects(counts.targets)) < _MIN_INTERACTION_TARGETS:
            # Two methods of one mock are one collaborator asked two questions,
            # not a sequence across collaborators.
            continue
        if counts.negative:
            # A negative claim — "must not charge the card twice", "A is called
            # and B is not" — is a routing or negative-space contract with no
            # observable outcome to assert on instead.
            continue
        if _INTERACTION_CONTRACT_RE.search(profile.node.name):
            continue
        if all(target.rpartition(".")[2] in _REGISTRATION_METHODS for target in counts.targets):
            continue
        if all("." not in target for target in counts.targets):
            # Every pinned collaborator is a patched free function, so the code
            # under test orchestrates module-level procedures and the test holds
            # no object whose state it could have asserted on instead.
            continue
        hits.append(profile)
    return hits


def _test_profiles(tree: ast.Module) -> list[_Profile]:
    """Count the assertions of every pytest-collected test in the module.

    Assertions reached through a helper defined in the same module count too, so
    a test delegating to `_assert_saved(...)` is profiled by what that helper
    actually checks.

    Returns:
        One profile per collected, non-skipped, non-stub test function.

    """
    nodes = _function_defs(tree)
    defs: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}
    for node in nodes:
        defs.setdefault(node.name, node)
    local = frozenset(defs)
    # Keyed by identity so every body is walked exactly twice, then resolved
    # through `defs` when a call has to be matched to a definition by name.
    called_by = {id(node): _called_names(node) for node in nodes}
    direct = {id(node): _direct_counts(node, local) for node in nodes}

    profiles: list[_Profile] = []
    for node in _collectible_tests(tree):
        if _is_skipped(node) or _is_fixture(node) or _is_placeholder(node):
            continue
        called = called_by[id(node)] - {node.name}
        if any(name.startswith(_TEST_PREFIX) and name not in defs for name in called):
            # Re-runs another module's test; those assertions are out of reach.
            continue
        counts = direct[id(node)]
        for helper in _reachable_local_helpers(node, called, defs, called_by):
            counts = counts.merged(direct[id(helper)])
        profiles.append(_Profile(node=node, counts=counts))
    return profiles


def _reachable_local_helpers(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    called: set[str],
    defs: dict[str, ast.FunctionDef | ast.AsyncFunctionDef],
    called_by: dict[int, set[str]],
) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    """Walk the module-local call graph outward from a test.

    Returns:
        Every same-module function the test can reach, excluding itself.

    """
    seen: set[str] = {node.name}
    reached: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
    queue = [name for name in called if name in defs]
    while queue:
        name = queue.pop()
        if name in seen:
            continue
        seen.add(name)
        helper = defs[name]
        reached.append(helper)
        queue.extend(nxt for nxt in called_by[id(helper)] if nxt in defs and nxt not in seen)
    return reached


def _is_collected_module(path: Path) -> bool:
    name = path.name
    matches_python_files = name.startswith(_TEST_PREFIX) or name.endswith(_COLLECTED_SUFFIX)
    return matches_python_files and not any(part in _UNCOLLECTED_DIR_NAMES for part in path.parts)


def _function_defs(tree: ast.Module) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    """Collect every function this module defines, methods and nested defs included.

    Returns:
        The definitions, in `ast.walk` order.

    """
    return nodes(tree, *_FUNC_NODES)


def _collectible_tests(tree: ast.Module) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    """Collect the `test_*` functions pytest would actually run.

    Returns:
        Module-level test functions and `Test*`-class methods, in source order.

    """
    found: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
    containers: list[ast.Module | ast.ClassDef] = [tree]
    while containers:
        for stmt in containers.pop().body:
            if isinstance(stmt, ast.ClassDef):
                containers.append(stmt)
            elif isinstance(stmt, _FUNC_NODES) and stmt.name.startswith(_TEST_PREFIX):
                found.append(stmt)
    found.sort(key=lambda n: (n.lineno, n.col_offset))
    return found


def _is_fixture(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return any(_marker_name(dec) == _FIXTURE for dec in node.decorator_list)


def _is_skipped(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return any(_marker_name(dec) in _SKIP_MARKERS for dec in node.decorator_list)


def _marker_name(dec: ast.expr) -> str | None:
    target = dec.func if isinstance(dec, ast.Call) else dec
    return target.attr if isinstance(target, ast.Attribute) else None


def _is_placeholder(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return all(_is_inert(stmt) for stmt in node.body)


def _is_inert(stmt: ast.stmt) -> bool:
    if isinstance(stmt, ast.Pass):
        return True
    return isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant)


def _direct_counts(node: ast.FunctionDef | ast.AsyncFunctionDef, local: frozenset[str]) -> _Counts:
    """Count the assertions written in this function's own subtree.

    Calls to functions this module defines are skipped: their own bodies are
    merged in separately, so counting the call site too would let a helper named
    `_assert_wiring` pass as an outcome assertion on the strength of its name.

    Returns:
        Outcome, interaction and negative-interaction assertion counts.

    """
    outcome = 0
    interaction = 0
    negative = 0
    targets: set[str] = set()
    for child in walk(node):
        kind = _classify(child, local)
        if kind is None:
            continue
        if kind is _Kind.OUTCOME:
            outcome += 1
        else:
            interaction += 1
            negative += int(kind is _Kind.NEGATIVE_INTERACTION)
            targets |= _interaction_targets(child.test if isinstance(child, ast.Assert) else child)
    return _Counts(outcome=outcome, interaction=interaction, negative=negative, targets=frozenset(targets))


def _interaction_targets(expr: ast.AST) -> set[str]:
    """Name the mocks whose call bookkeeping this assertion reads.

    `notify_mock.call_count` and `notify_mock.call_args` both name
    `notify_mock`; `mailer.send.assert_called_once_with(...)` names
    `mailer.send`. Counting distinct targets is what separates "one collaborator
    must be told" from "this exact sequence of collaborator calls must happen".

    Returns:
        The dotted receiver path of every mock-state read in the expression.

    """
    targets: set[str] = set()
    for node in walk(expr):
        if isinstance(node, ast.Attribute) and node.attr in _MOCK_STATE_ATTRS:
            targets.add(_dotted(node.value))
        elif (
            isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and _is_mock_assert_name(node.func.attr)
        ):
            targets.add(_dotted(node.func.value))
    return targets


def _root_objects(targets: frozenset[str]) -> set[str]:
    """Reduce dotted interaction targets to the objects they hang off.

    `mock_hook.return_value.get_instance` and
    `mock_hook.return_value.start_pipeline` are two questions asked of one
    collaborator, so both reduce to `mock_hook`. This is SARJ062's reduction —
    a collaborator is an object, not one of its methods — and the two rules have
    to agree on it.

    Returns:
        The leading segment of every target.

    """
    return {target.split(".")[0] for target in targets}


def _dotted(expr: ast.expr) -> str:
    """Render an attribute chain as a dotted path.

    Returns:
        `a.b.c` for `a.b.c`; anything not a plain name chain becomes `?`.

    """
    parts: list[str] = []
    node = expr
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    parts.append(node.id if isinstance(node, ast.Name) else "?")
    return ".".join(reversed(parts))


def _classify(child: ast.AST, local: frozenset[str]) -> _Kind | None:
    """Decide what kind of assertion, if any, this node performs.

    Returns:
        The assertion kind, or None when the node verifies nothing.

    """
    if isinstance(child, ast.Assert):
        if not _mentions_mock_state(child.test):
            return _Kind.OUTCOME
        return _Kind.NEGATIVE_INTERACTION if _is_negative_test(child.test) else _Kind.INTERACTION
    if not isinstance(child, ast.Call):
        return None
    name = _call_name(child.func)
    if name in local:
        return None
    if name is not None and _is_mock_assert_name(name):
        return _Kind.NEGATIVE_INTERACTION if name in _MOCK_NEGATIVE_ASSERTS else _Kind.INTERACTION
    if not _names_verification(child.func):
        return None
    # `self.assertEqual(sender.call_count, 2)` is an interaction assertion in a
    # unittest coat; anything else a helper checks is treated as an outcome.
    if not any(_mentions_mock_state(arg) for arg in child.args):
        return _Kind.OUTCOME
    negative = name in _NEGATIVE_ASSERT_HELPERS or any(
        isinstance(arg, ast.Constant) and _is_zeroish(arg.value) for arg in child.args
    )
    return _Kind.NEGATIVE_INTERACTION if negative else _Kind.INTERACTION


def _is_mock_assert_name(name: str) -> bool:
    return name.startswith(_MOCK_ASSERT_PREFIXES) or name in _MOCK_ASSERT_NAMES


def _call_name(func: ast.expr) -> str | None:
    if isinstance(func, ast.Attribute):
        return func.attr
    return func.id if isinstance(func, ast.Name) else None


def _mentions_mock_state(expr: ast.expr) -> bool:
    return any(_is_mock_state_read(node) for node in walk(expr))


def _is_mock_state_read(node: ast.AST) -> bool:
    if isinstance(node, ast.Attribute):
        return node.attr in _MOCK_STATE_ATTRS
    if not isinstance(node, ast.Call):
        return False
    name = _call_name(node.func)
    return name is not None and _is_mock_assert_name(name)


def _is_negative_test(expr: ast.expr) -> bool:
    """Report whether an assert on mock state asserts an *absence* of calls.

    Returns:
        True for `assert not m.called`, `assert m.call_count == 0`, and friends.

    """
    if isinstance(expr, ast.UnaryOp) and isinstance(expr.op, ast.Not):
        return True
    if isinstance(expr, ast.Compare) and expr.comparators:
        return all(isinstance(cmp, ast.Constant) and _is_zeroish(cmp.value) for cmp in expr.comparators)
    return False


def _is_zeroish(value: object) -> bool:
    """Report whether a literal stands for "nothing happened".

    Returns:
        True for `None`, `False` and `0` (including empty containers' length).

    """
    return value is None or (isinstance(value, int) and not value)


def _names_verification(func: ast.expr) -> bool:
    if isinstance(func, ast.Name):
        return _reads_as_verification(func.id)
    if not isinstance(func, ast.Attribute):
        return False
    if func.attr in _RAISES_NAMES or _reads_as_verification(func.attr):
        return True
    # `result.expect.contains_function_call(...)` — the DSL marker sits partway
    # along the chain rather than at its end.
    return _chain_has_fluent_marker(func.value)


def _reads_as_verification(name: str) -> bool:
    return bool(_ASSERTION_NAME_RE.match(name) or _RAISES_TOKEN_RE.search(name))


def _chain_has_fluent_marker(node: ast.expr) -> bool:
    while isinstance(node, ast.Attribute):
        if node.attr in _FLUENT_ATTRS:
            return True
        node = node.value
    return False


def _called_names(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for child in walk(node):
        if isinstance(child, ast.Call):
            func = child.func
            if isinstance(func, ast.Attribute):
                names.add(func.attr)
            elif isinstance(func, ast.Name):
                names.add(func.id)
    return names
