"""SARJ064 — An assertion whose outcome the test itself already decided.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_trivially_true_assertion.py
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, ClassVar, override

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
from sarj_python_lint.rules._paths import is_test_path


if TYPE_CHECKING:
    from pathlib import Path


_FUNC_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)

_TEST_PREFIX = "test_"

# pytest's default `python_files`.
_COLLECTED_SUFFIX = "_test.py"

# Manual CLI probes carry `test_*.py` names but are never collected.
_UNCOLLECTED_DIR_NAMES = frozenset({"scripts"})

_ISINSTANCE = "isinstance"

_ISINSTANCE_ARITY = 2

_DUNDER_PREFIX = "__"

# Class-name endings that mark a collaborator rather than a record.
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

# Permit identity comparison only for boolean singleton assertions.
_ECHO_OPS = (ast.Eq, ast.Is)

_UNITTEST_ECHO_ASSERTS = frozenset({"assertEqual", "assertIs"})

_UNITTEST_ISINSTANCE_ASSERT = "assertIsInstance"

type _Assertion = ast.Assert | ast.Call

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

# The advice when it does not.
_ONLY_ASSERTION_ADVICE = (
    ". Every assertion this test makes is like it, so dropping them would leave a test that verifies "
    "nothing. Assert the behaviour the test name claims to cover, or delete the test"
)


@dataclass(frozen=True, slots=True)
class _KwargEcho:
    """One `assert name.field == <literal>` paired with how the name was built."""

    node: _Assertion
    field: tuple[str, str]
    echoes: bool


@dataclass(slots=True)
class _Scope:
    """Everything one function body does with its local names."""

    asserts: list[_Assertion]
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
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="Assertions should depend on behavior rather than echoing values supplied by the test.",
        rationale="Constructor keyword echoes and equivalent tautologies cannot reveal an application defect.",
        remediation="Assert a transformation, validation result, or other value produced independently of the fixture literal.",
        category=RuleCategory.TESTING,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Literal-only assertions owned by Ruff or SARJ057 are excluded.",
            "Constructor echoes with evidence of field coercion are excluded.",
        ),
        examples=(
            RuleExample(
                example_id="constructor-keyword-echo",
                title="Assertion repeats a constructor keyword",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_user.py",
                        'def test_user():\n    user = User(name="Ada")\n    assert user.name == "Ada"\n',
                    ),
                ),
                focus_path=PurePosixPath("tests/test_user.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="derived-value",
                title="Assertion checks a derived value",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_user.py",
                        'def test_user():\n    user = User(name="Ada Lovelace")\n    assert user.initials == "AL"\n',
                    ),
                ),
                focus_path=PurePosixPath("tests/test_user.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description: str = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        """Flag assertions whose truth is settled by the test source itself."""
        if not is_test_path(path) or not _is_collected_module(path):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []

        index = _index_module(tree)
        findings: dict[int, tuple[_Assertion, str]] = {}
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


def _one_per_test(index: _Index, findings: dict[int, tuple[_Assertion, str]]) -> list[tuple[_Assertion, str]]:
    """Keep the earliest finding in each test function and discard the rest."""
    anchors: dict[int, tuple[_Assertion, str]] = {}
    for node, diagnosis in findings.values():
        scope = index.owners.get(id(node))
        key = id(node) if scope is None else id(scope)
        earlier = anchors.get(key)
        if earlier is None or (node.lineno, node.col_offset) < (earlier[0].lineno, earlier[0].col_offset):
            anchors[key] = (node, diagnosis)
    return list(anchors.values())


def _advice(scope: _Scope | None, findings: dict[int, tuple[_Assertion, str]]) -> str:
    """Choose the repair based on whether any meaningful assertion remains."""
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
        if scope is not None:
            if isinstance(node, ast.Assert) or (isinstance(node, ast.Call) and _is_unittest_assertion(node)):
                scope.asserts.append(node)
                owners[id(node)] = scope
            else:
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


# Both shapes: what the test constructed a line earlier.                       #


def _construction_findings(index: _Index) -> list[tuple[_Assertion, str]]:
    """Find assertions that only read back what the test handed a constructor."""
    echoes: list[_KwargEcho] = []
    hits: list[tuple[_Assertion, str]] = []
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
    if isinstance(parent, ast.Call) and parent.args and parent.args[0] is node:
        if _is_isinstance_call(parent):
            return _under_assert(parent, parents)
        if (
            isinstance(parent.func, ast.Attribute)
            and parent.func.attr == _UNITTEST_ISINSTANCE_ASSERT
            and _is_unittest_assertion(parent)
        ):
            return True
    return False


def _under_assert(node: ast.AST, parents: dict[int, ast.AST]) -> bool:
    current: ast.AST | None = node
    while current is not None:
        if isinstance(current, ast.Assert) or _is_unittest_assertion(current):
            return True
        current = parents.get(id(current))
    return False


def _is_isinstance_call(node: ast.Call) -> bool:
    return isinstance(node.func, ast.Name) and node.func.id == _ISINSTANCE


def _is_unittest_assertion(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "self"
        and node.func.attr.startswith("assert")
    )


def _kwarg_echo(node: _Assertion, constructed: dict[str, ast.Call]) -> _KwargEcho | None:
    """Pair `x = C(field=<literal>)` with a later `assert x.field == <literal>`."""
    operands = _echo_operands(node)
    if operands is None:
        return None
    left, right = operands
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


def _echo_operands(node: _Assertion) -> tuple[ast.expr, ast.expr] | None:
    if isinstance(node, ast.Assert):
        test = node.test
        if not isinstance(test, ast.Compare) or len(test.ops) != 1 or not isinstance(test.ops[0], _ECHO_OPS):
            return None
        return test.left, test.comparators[0]
    if (
        isinstance(node.func, ast.Attribute)
        and node.func.attr in _UNITTEST_ECHO_ASSERTS
        and len(node.args) >= _ISINSTANCE_ARITY
    ):
        return node.args[0], node.args[1]
    return None


def _constructor_name(call: ast.Call) -> str | None:
    """Name the class this call instantiates, if it plausibly is one."""
    name = _called_name(call.func)
    if name is None or not name[:1].isupper():
        return None
    lowered = name.lower()
    return None if lowered.endswith(_COLLABORATOR_SUFFIXES) else name


def _called_name(func: ast.expr) -> str | None:
    if isinstance(func, ast.Name):
        return func.id
    return func.attr if isinstance(func, ast.Attribute) else None


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


def _is_isinstance_echo(node: _Assertion, constructed: dict[str, ast.Call], asserts: list[_Assertion]) -> bool:
    """Detect `x = Foo(...)` followed by `assert isinstance(x, Foo)`."""
    if isinstance(node, ast.Assert):
        test = node.test
        if not isinstance(test, ast.Call) or not _is_isinstance_call(test) or len(test.args) != _ISINSTANCE_ARITY:
            return False
        target, cls = test.args
    elif (
        isinstance(node.func, ast.Attribute)
        and node.func.attr == _UNITTEST_ISINSTANCE_ASSERT
        and len(node.args) >= _ISINSTANCE_ARITY
    ):
        target, cls = node.args[:_ISINSTANCE_ARITY]
    else:
        return False
    if not isinstance(target, ast.Name):
        return False
    call = constructed.get(target.id)
    if call is None or node.lineno <= call.lineno or ast.dump(call.func) != ast.dump(cls):
        return False
    return not _narrows_for_a_later_assertion(node, target.id, asserts)


def _narrows_for_a_later_assertion(node: _Assertion, name: str, asserts: list[_Assertion]) -> bool:
    """Report whether a following assertion uses the name this one narrows."""
    for other in asserts:
        if other.lineno <= node.lineno:
            continue
        if any(isinstance(child, ast.Name) and child.id == name for child in ast.walk(other)):
            return True
    return False
