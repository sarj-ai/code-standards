"""SARJ064 — An assertion whose outcome the test itself already decided.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_trivially_true_assertion.py
Evidence: https://github.com/sarj-ai/standards/blob/main/docs/rules/SARJ064.md
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none
from sarj_python_lint.rules._paths import is_test_path


if TYPE_CHECKING:
    from pathlib import Path


_FUNC_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)

_TEST_PREFIX = "test_"

# pytest's default `python_files`. `is_test_path` is broader on purpose.
_COLLECTED_SUFFIX = "_test.py"

# Manual CLI probes carry `test_*.py` names but are never collected.
_UNCOLLECTED_DIR_NAMES = frozenset({"scripts"})

_ISINSTANCE = "isinstance"

_ISINSTANCE_ARITY = 2

_DUNDER_PREFIX = "__"

# Class-name endings that mark a collaborator rather than a record. Such a class
# does work in `__init__` — celery's cache backends run `expires=` through
# `prepare_expires` — so reading a constructor argument back out of one is a
# coercion test, not a tautology. `Backend` and `Client` are the endings the
# corpus actually produced; the rest are the same idea, spelled differently.
_COLLABORATOR_SUFFIXES = (
    "backend",
    "client",
    "service",
    "manager",
    "handler",
    "server",
    "session",
    "pool",
    "engine",
    "runner",
    "worker",
    "store",
    "repository",
    "factory",
    "builder",
    "adapter",
    "connection",
    "transport",
    "receiver",
)

# `assert result.passed is False` is the pytest house spelling for a boolean
# field, and it is the same tautology as `== False`. A non-singleton `is`
# comparison is ruff's F632 and stays that rule's problem.
_ECHO_OPS = (ast.Eq, ast.Is)

_KWARG_DIAGNOSIS = (
    "this reads back the literal the test just handed the constructor, so it can only fail if attribute "
    "assignment stops working"
)

_ISINSTANCE_DIAGNOSIS = (
    "the value was produced by calling this very class a line above, so the `isinstance` check pins the "
    "language rather than the code"
)

# The advice when the test still has an assertion that can fail.
_ADVICE = ". Assert on something the code under test derived, or drop the assertion"

# The advice when it does not. Telling the author to drop the assertion would
# hand them a test SARJ043 (`zero-assertion-test`) immediately rejects, so the two
# rules have to agree: the repair is to assert the behaviour, or delete the test.
_ONLY_ASSERTION_ADVICE = (
    ". Every assertion this test makes is like it, so dropping them would leave a test that verifies "
    "nothing, which SARJ043 (`zero-assertion-test`) rejects in turn. Assert the behaviour the test name "
    "claims to cover, or delete the test"
)


@dataclass(frozen=True, slots=True)
class _KwargEcho:
    """One `assert name.field == <literal>` paired with how the name was built."""

    node: ast.Assert
    field: tuple[str, str]
    echoes: bool


@dataclass(slots=True)
class _Scope:
    """Everything one function body does with its local names."""

    asserts: list[ast.Assert]
    loads: dict[str, list[ast.Name]]
    binds: dict[str, int]
    calls: dict[str, ast.Call]
    shadowed: set[str]


@dataclass(frozen=True, slots=True)
class _Index:
    """One traversal's worth of facts about the module."""

    parents: dict[int, ast.AST]
    scopes: list[_Scope]
    owners: dict[int, _Scope]


class TriviallyTrueAssertion(Rule):
    id: str = "trivially-true-assertion"
    code: str = "SARJ064"
    has_evidence: bool = True
    description: str = "Assertion cannot fail — its outcome is decided by the test's own literals, not by the code."

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        """Flag assertions whose truth is settled by the test source itself."""
        if not is_test_path(path) or not _is_collected_module(path):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []

        index = _index_module(tree)
        findings: dict[int, tuple[ast.Assert, str]] = {}
        for node, diagnosis in _construction_findings(index):
            _ = findings.setdefault(id(node), (node, diagnosis))

        diags = [
            Diagnostic(
                path=path,
                line=node.lineno,
                col=node.col_offset + 1,
                code=self.code,
                message=diagnosis + _advice(index.owners.get(id(node)), findings),
            )
            for node, diagnosis in _one_per_test(index, findings)
        ]
        diags.sort(key=lambda d: (d.line, d.col))
        return diags


def _one_per_test(index: _Index, findings: dict[int, tuple[ast.Assert, str]]) -> list[tuple[ast.Assert, str]]:
    """Keep the earliest finding in each test function and discard the rest."""
    anchors: dict[int, tuple[ast.Assert, str]] = {}
    for node, diagnosis in findings.values():
        scope = index.owners.get(id(node))
        key = id(node) if scope is None else id(scope)
        earlier = anchors.get(key)
        if earlier is None or (node.lineno, node.col_offset) < (earlier[0].lineno, earlier[0].col_offset):
            anchors[key] = (node, diagnosis)
    return list(anchors.values())


def _advice(scope: _Scope | None, findings: dict[int, tuple[ast.Assert, str]]) -> str:
    """Choose the repair to recommend, which SARJ043 constrains."""
    if scope is None or any(id(node) not in findings for node in scope.asserts):
        return _ADVICE
    return _ONLY_ASSERTION_ADVICE


def _is_collected_module(path: Path) -> bool:
    name = path.name
    matches_python_files = name.startswith(_TEST_PREFIX) or name.endswith(_COLLECTED_SUFFIX)
    return matches_python_files and not any(part in _UNCOLLECTED_DIR_NAMES for part in path.parts)


def _index_module(tree: ast.Module) -> _Index:
    """Walk the module once, recording everything both shapes need."""
    parents: dict[int, ast.AST] = {}
    scopes: list[_Scope] = []
    owners: dict[int, _Scope] = {}
    stack: list[tuple[ast.AST, _Scope | None]] = [(tree, None)]
    while stack:
        node, scope = stack.pop()
        if scope is None and isinstance(node, _FUNC_NODES):
            scope = _Scope(asserts=[], loads={}, binds={}, calls={}, shadowed=set())
            scopes.append(scope)
        if isinstance(node, ast.Assert) and scope is not None:
            scope.asserts.append(node)
            owners[id(node)] = scope
        elif scope is not None:
            _record_local(node, scope)
        for child in ast.iter_child_nodes(node):
            parents[id(child)] = node
            stack.append((child, scope))
    return _Index(parents=parents, scopes=scopes, owners=owners)


def _record_local(node: ast.AST, scope: _Scope) -> None:
    if isinstance(node, ast.Name):
        if isinstance(node.ctx, ast.Load):
            scope.loads.setdefault(node.id, []).append(node)
        else:
            scope.binds[node.id] = scope.binds.get(node.id, 0) + 1
    elif isinstance(node, ast.arg):
        scope.shadowed.add(node.arg)
    elif isinstance(node, (ast.Global, ast.Nonlocal)):
        scope.shadowed.update(node.names)
    elif isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.value, ast.Call):
        target = node.targets[0]
        if isinstance(target, ast.Name):
            scope.calls[target.id] = node.value


def _called_name(func: ast.expr) -> str | None:
    if isinstance(func, ast.Name):
        return func.id
    return func.attr if isinstance(func, ast.Attribute) else None


# --------------------------------------------------------------------------- #
# Both shapes: what the test constructed a line earlier.                       #
# --------------------------------------------------------------------------- #


def _construction_findings(index: _Index) -> list[tuple[ast.Assert, str]]:
    """Find assertions that only read back what the test handed a constructor."""
    echoes: list[_KwargEcho] = []
    hits: list[tuple[ast.Assert, str]] = []
    for scope in index.scopes:
        if not scope.asserts or not scope.calls:
            continue
        constructed = _constructed_locals(scope, index.parents)
        if not constructed:
            continue
        for node in scope.asserts:
            echo = _kwarg_echo(node, constructed)
            if echo is not None:
                echoes.append(echo)
            elif _is_isinstance_echo(node, constructed, scope.asserts):
                hits.append((node, _ISINSTANCE_DIAGNOSIS))

    coercing = {echo.field for echo in echoes if not echo.echoes}
    hits.extend((echo.node, _KWARG_DIAGNOSIS) for echo in echoes if echo.echoes and echo.field not in coercing)
    return hits


def _constructed_locals(scope: _Scope, parents: dict[int, ast.AST]) -> dict[str, ast.Call]:
    """Keep the locals bound exactly once to a call and never touched since."""
    return {
        name: call
        for name, call in scope.calls.items()
        if name not in scope.shadowed
        and scope.binds.get(name) == 1
        and all(_is_assertion_read(load, parents) for load in scope.loads.get(name, []))
    }


def _is_assertion_read(node: ast.Name, parents: dict[int, ast.AST]) -> bool:
    """Report whether this mention of the name only reads it inside an assertion."""
    parent = parents.get(id(node))
    if isinstance(parent, ast.Attribute):
        grandparent = parents.get(id(parent))
        if isinstance(grandparent, ast.Call) and grandparent.func is parent:
            return False
        return _under_assert(parent, parents)
    if isinstance(parent, ast.Call) and _is_isinstance_call(parent) and parent.args and parent.args[0] is node:
        return _under_assert(parent, parents)
    return False


def _under_assert(node: ast.AST, parents: dict[int, ast.AST]) -> bool:
    current: ast.AST | None = node
    while current is not None:
        if isinstance(current, ast.Assert):
            return True
        current = parents.get(id(current))
    return False


def _is_isinstance_call(node: ast.Call) -> bool:
    return isinstance(node.func, ast.Name) and node.func.id == _ISINSTANCE


def _constructor_name(call: ast.Call) -> str | None:
    """Name the class this call instantiates, if it plausibly is one."""
    name = _called_name(call.func)
    if name is None or not name[:1].isupper():
        return None
    lowered = name.lower()
    return None if lowered.endswith(_COLLABORATOR_SUFFIXES) else name


def _kwarg_echo(node: ast.Assert, constructed: dict[str, ast.Call]) -> _KwargEcho | None:
    """Pair `x = C(field=<literal>)` with a later `assert x.field == <literal>`."""
    test = node.test
    if not isinstance(test, ast.Compare) or len(test.ops) != 1 or not isinstance(test.ops[0], _ECHO_OPS):
        return None
    left, right = test.left, test.comparators[0]
    for attribute, literal in ((left, right), (right, left)):
        if not isinstance(attribute, ast.Attribute) or not isinstance(attribute.value, ast.Name):
            continue
        if attribute.attr.startswith(_DUNDER_PREFIX):
            continue
        call = constructed.get(attribute.value.id)
        if call is None or node.lineno <= call.lineno:
            continue
        name = _constructor_name(call)
        if name is None or not _is_pure_literal(literal):
            continue
        for keyword in call.keywords:
            if keyword.arg == attribute.attr and _is_pure_literal(keyword.value):
                echoes = ast.dump(keyword.value) == ast.dump(literal)
                return _KwargEcho(node=node, field=(name, attribute.attr), echoes=echoes)
    return None


def _is_pure_literal(node: ast.expr) -> bool:
    """Report whether `node` is a literal built entirely out of source text."""
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        return _is_pure_literal(node.operand)
    if isinstance(node, (ast.List, ast.Set, ast.Tuple)):
        return all(_is_pure_literal(elt) for elt in node.elts)
    if isinstance(node, ast.Dict):
        keys_ok = all(key is not None and _is_pure_literal(key) for key in node.keys)
        return keys_ok and all(_is_pure_literal(value) for value in node.values)
    return False


def _is_isinstance_echo(node: ast.Assert, constructed: dict[str, ast.Call], asserts: list[ast.Assert]) -> bool:
    """Detect `x = Foo(...)` followed by `assert isinstance(x, Foo)`."""
    test = node.test
    if not isinstance(test, ast.Call) or not _is_isinstance_call(test) or len(test.args) != _ISINSTANCE_ARITY:
        return False
    target, cls = test.args
    if not isinstance(target, ast.Name):
        return False
    call = constructed.get(target.id)
    if call is None or node.lineno <= call.lineno or ast.dump(call.func) != ast.dump(cls):
        return False
    return not _narrows_for_a_later_assertion(node, target.id, asserts)


def _narrows_for_a_later_assertion(node: ast.Assert, name: str, asserts: list[ast.Assert]) -> bool:
    """Report whether a following assertion uses the name this one narrows."""
    for other in asserts:
        if other.lineno <= node.lineno:
            continue
        if any(isinstance(child, ast.Name) and child.id == name for child in ast.walk(other)):
            return True
    return False
