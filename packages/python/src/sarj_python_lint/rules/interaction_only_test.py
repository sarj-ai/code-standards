"""SARJ063 — A test whose only assertions are about which calls landed on a mock.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_interaction_only_test.py
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

# pytest's default `python_files`.
_COLLECTED_SUFFIX = "_test.py"

# Manual CLI probes live here under `test_*.py` names but are never collected.
_UNCOLLECTED_DIR_NAMES = frozenset({"scripts"})

_SKIP_MARKERS = frozenset({"skip", "skipif", "xfail"})

_FIXTURE = "fixture"

_FUNC_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)

# --- the calibrated guards; see the module docstring for the measurements ---

# Minimum mocked collaborators required before wiring assertions dominate the test.
_MIN_INTERACTION_TARGETS = 2

# Callback registration is observable behavior rather than mere mock wiring.
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
        """Add another function's assertion counts to this one's."""
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
    id: str = "interaction-only-test"
    code: str = "SARJ063"
    description: str = "Test asserts only on mock call bookkeeping — it pins the call sequence, not the behaviour."

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        """Flag tests whose every assertion is a mock-interaction assertion."""
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
    """Apply the calibrated guards to the raw per-test assertion profiles."""
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
    """Count the assertions of every pytest-collected test in the module."""
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
    """Walk the module-local call graph outward from a test."""
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
    """Collect every function this module defines, methods and nested defs included."""
    return nodes(tree, *_FUNC_NODES)


def _collectible_tests(tree: ast.Module) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    """Collect the `test_*` functions pytest would actually run."""
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
    """Count the assertions written in this function's own subtree."""
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
    """Name the mocks whose call bookkeeping this assertion reads."""
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
    """Reduce dotted interaction targets to the objects they hang off."""
    return {target.split(".")[0] for target in targets}


def _dotted(expr: ast.expr) -> str:
    """Render an attribute chain as a dotted path."""
    parts: list[str] = []
    node = expr
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    parts.append(node.id if isinstance(node, ast.Name) else "?")
    return ".".join(reversed(parts))


def _classify(child: ast.AST, local: frozenset[str]) -> _Kind | None:
    """Decide what kind of assertion, if any, this node performs."""
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
    """Report whether an assert on mock state asserts an *absence* of calls."""
    if isinstance(expr, ast.UnaryOp) and isinstance(expr.op, ast.Not):
        return True
    if isinstance(expr, ast.Compare) and expr.comparators:
        return all(isinstance(cmp, ast.Constant) and _is_zeroish(cmp.value) for cmp in expr.comparators)
    return False


def _is_zeroish(value: object) -> bool:
    """Report whether a literal stands for "nothing happened"."""
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
