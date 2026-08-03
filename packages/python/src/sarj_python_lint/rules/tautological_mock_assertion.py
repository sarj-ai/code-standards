"""SARJ060 — A test whose only assertion is the value it fed the mock verifies nothing

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_tautological_mock_assertion.py
"""

from __future__ import annotations

import ast
from collections import Counter
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none
from sarj_python_lint.rules._paths import is_test_path


if TYPE_CHECKING:
    from pathlib import Path


# The two `unittest.mock` knobs that decide what a stubbed call hands back.
_MOCK_VALUE_ATTRS = frozenset({"return_value", "side_effect"})

# A call whose name starts with this verifies something in its own right:
# `mock.assert_called_once_with(...)`, `self.assertEqual(...)`, `_assert_shape(...)`.
_ASSERT_PREFIX = "assert"

# Verification spelled without the `assert` prefix.
_VERIFICATION_NAMES = frozenset({"raises", "warns", "deprecated_call", "fail"})

# Calls that swap a real callable for a stand-in, so a `lambda` handed to one is
# a hand-rolled `return_value` (`monkeypatch.setattr(mod, "fn", lambda: X)`).
_REPLACEMENT_INSTALLERS = frozenset({"setattr", "setitem", "patch", "object"})

_FUNC_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)

_TEST_PREFIX = "test_"

# pytest's default `python_files`.
_COLLECTED_SUFFIX = "_test.py"

# Manual CLI probes carry `test_*.py` names but are never collected.
_UNCOLLECTED_DIR_NAMES = frozenset({"scripts"})

# Expression shapes that stand for "the whole thing the code under test
_WHOLE_RESULT_NODES = (ast.Name, ast.Call, ast.Await)

# Exactly two: the stub setup and the assertion.
_EXPECTED_OCCURRENCES = 2

# `0`/`1` double as False/True, counts, and indexes; stubbing one and asserting
# on it is usually a real code-path check.
_TRIVIAL_NUMBERS = frozenset({0, 1})

# Receiver roots that every attribute in a `TestCase` shares, so they prove nothing
# about which double a stub reaches.
_IMPLICIT_RECEIVERS = frozenset({"self", "cls"})


class TautologicalMockAssertion(Rule):
    id: str = "tautological-mock-assertion"
    code: str = "SARJ060"
    description: str = "Test's only assertion compares against the value it configured the mock to return."

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        """Flag tests that verify nothing but their own stub."""
        if not is_test_path(path) or not _is_collected_module(path):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []

        diags = [
            Diagnostic(
                path=path,
                line=node.lineno,
                col=node.col_offset + 1,
                code=self.code,
                message=(
                    "this is the test's only assertion and it compares against the value the test itself "
                    "configured the mock to return, so it holds however the code under test behaves — it "
                    "verifies `unittest.mock`, not this codebase. Assert on what the code *did*: the "
                    "arguments it passed, the transformation it applied, or the effect it performed."
                ),
            )
            for node in _tautological_assertions(tree)
        ]
        diags.sort(key=lambda d: (d.line, d.col))
        return diags


def _is_collected_module(path: Path) -> bool:
    name = path.name
    collected = name.startswith(_TEST_PREFIX) or name.endswith(_COLLECTED_SUFFIX)
    return collected and not any(part in _UNCOLLECTED_DIR_NAMES for part in path.parts)


def _tautological_assertions(tree: ast.Module) -> list[ast.Assert]:
    hits: list[ast.Assert] = []
    for func in _collectible_tests(tree):
        hit = _tautology_in(func)
        if hit is not None:
            hits.append(hit)
    return hits


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


def _tautology_in(func: ast.FunctionDef | ast.AsyncFunctionDef) -> ast.Assert | None:
    """Decide whether every assertion in `func` merely echoes a stubbed value."""
    asserts: list[ast.Assert] = []
    provided: dict[str, ast.expr] = {}
    stubbed_on: dict[str, list[ast.expr] | None] = {}
    receivers: set[int] = set()
    assigned: dict[str, ast.expr] = {}
    bindings: Counter[str] = Counter()
    for node in ast.walk(func):
        if isinstance(node, ast.Assert):
            asserts.append(node)
        elif isinstance(node, ast.Assign):
            _record_attribute_stub(node, provided, stubbed_on)
            _record_alias(node, assigned)
        elif isinstance(node, ast.Name):
            if isinstance(node.ctx, ast.Store):
                bindings[node.id] += 1
        elif isinstance(node, ast.Attribute | ast.Subscript):
            receivers.add(id(node.value))
        elif isinstance(node, ast.Call):
            if _is_verification_call(node):
                return None
            _record_call_stubs(node, provided, stubbed_on)
    if not asserts:
        return None

    aliases = {name: value for name, value in assigned.items() if bindings[name] == 1}
    signatures = {_signature(value) for value in provided.values()}
    handed_over: frozenset[str] | None = None
    matched: list[ast.Assert] = []
    for node in asserts:
        target = _echoed_operand(node, provided, signatures, aliases)
        if target is None or not _appears_only_at_the_stub(func, target, receivers):
            return None
        configured = stubbed_on.get(ast.dump(target))
        if configured is not None:
            if handed_over is None:
                handed_over = _names_handed_to_the_code(func)
            if not any(_double_reaches_the_code(recv, aliases, handed_over) for recv in configured):
                return None
        matched.append(node)
    return matched[0]


def _double_reaches_the_code(receiver: ast.expr, aliases: dict[str, ast.expr], handed_over: frozenset[str]) -> bool:
    """Report whether the test body shows the code under test can reach this stub."""
    keys = _configured_sub_object(receiver, aliases)
    return keys is None or bool(keys & handed_over)


def _configured_sub_object(receiver: ast.expr, aliases: dict[str, ast.expr]) -> frozenset[str] | None:
    """Name the double whose *sub-object* a `<receiver>.return_value = X` stub configures."""
    attrs: list[str] = []
    seen: set[str] = set()
    current = receiver
    while True:
        if isinstance(current, ast.Attribute):
            attrs.append(current.attr)
            current = current.value
        elif (
            isinstance(current, ast.Name)
            and current.id not in seen
            and isinstance(alias := aliases.get(current.id), ast.Attribute)
        ):
            seen.add(current.id)
            current = alias
        else:
            break
    if not isinstance(current, ast.Name):
        return frozenset()
    if not attrs:
        return None
    parts = [current.id, *reversed(attrs)]
    first = 2 if parts[0] in _IMPLICIT_RECEIVERS else 1
    return frozenset(".".join(parts[:count]) for count in range(first, len(parts) + 1))


def _names_handed_to_the_code(func: ast.AST) -> frozenset[str]:
    """Collect the names the body passes to something, rather than merely configures."""
    configuring: set[int] = set()
    for node in ast.walk(func):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Attribute):
                configuring.update(id(inner) for inner in ast.walk(target))
        if isinstance(node.value, ast.Attribute | ast.Subscript):
            configuring.update(id(inner) for inner in ast.walk(node.value))
    return frozenset(
        dotted
        for node in ast.walk(func)
        if isinstance(node, ast.Name | ast.Attribute)
        and isinstance(node.ctx, ast.Load)
        and id(node) not in configuring
        and (dotted := _dotted_name(node)) is not None
    )


def _dotted_name(node: ast.expr) -> str | None:
    parts: list[str] = []
    current = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if not isinstance(current, ast.Name):
        return None
    parts.append(current.id)
    return ".".join(reversed(parts))


def _record_alias(node: ast.Assign, assigned: dict[str, ast.expr]) -> None:
    """Note that `x = <expr>` binds a local to an expression."""
    for target in node.targets:
        if isinstance(target, ast.Name):
            assigned[target.id] = node.value


def _record_attribute_stub(
    node: ast.Assign, provided: dict[str, ast.expr], stubbed_on: dict[str, list[ast.expr] | None]
) -> None:
    for target in node.targets:
        if isinstance(target, ast.Attribute) and target.attr in _MOCK_VALUE_ATTRS:
            _record(node.value, provided, stubbed_on, target.value)


def _record_call_stubs(
    node: ast.Call, provided: dict[str, ast.expr], stubbed_on: dict[str, list[ast.expr] | None]
) -> None:
    for kw in node.keywords:
        if kw.arg in _MOCK_VALUE_ATTRS:
            _record(kw.value, provided, stubbed_on, None)
    if _installs_a_replacement(node):
        for arg in node.args:
            if isinstance(arg, ast.Lambda):
                _record(arg.body, provided, stubbed_on, None)


def _installs_a_replacement(node: ast.Call) -> bool:
    """Report whether this call swaps a real callable for a stand-in."""
    func = node.func
    name = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else ""
    return name in _REPLACEMENT_INSTALLERS


def _record(
    value: ast.expr,
    provided: dict[str, ast.expr],
    stubbed_on: dict[str, list[ast.expr] | None],
    receiver: ast.expr | None,
) -> None:
    """Note a stubbed value, and which double's attribute chain it was configured on."""
    if _is_trivial(value) or not _signature(value):
        return
    key = ast.dump(value)
    provided.setdefault(key, value)
    if receiver is None:
        stubbed_on[key] = None
    elif key not in stubbed_on:
        stubbed_on[key] = [receiver]
    elif (recorded := stubbed_on[key]) is not None:
        recorded.append(receiver)


def _is_trivial(value: ast.expr) -> bool:
    """Report whether a stubbed value is too weak to build a tautology on."""
    if isinstance(value, ast.Constant):
        literal = value.value
        if literal is None or isinstance(literal, bool):
            return True
        if isinstance(literal, int | float) and literal in _TRIVIAL_NUMBERS:
            return True
        return isinstance(literal, str | bytes) and not literal
    if isinstance(value, ast.List | ast.Tuple | ast.Set):
        return not value.elts
    if isinstance(value, ast.Dict):
        return not value.keys
    return False


def _echoed_operand(
    node: ast.Assert,
    provided: dict[str, ast.expr],
    signatures: set[str],
    aliases: dict[str, ast.expr],
) -> ast.expr | None:
    """Find the operand of `node` that the test itself stubbed."""
    test = node.test
    if not isinstance(test, ast.Compare) or len(test.ops) != 1:
        return None
    if not isinstance(test.ops[0], ast.Eq | ast.Is):
        return None
    left, right = test.left, test.comparators[0]
    for value, other in ((right, left), (left, right)):
        if not _is_stubbed(value, provided, signatures):
            continue
        if not isinstance(other, _WHOLE_RESULT_NODES) or _reaches_into_the_result(other, aliases):
            continue
        if not _is_stubbed(other, provided, signatures):
            return value
    return None


def _reaches_into_the_result(node: ast.expr, aliases: dict[str, ast.expr]) -> bool:
    """Report whether `node` is a local bound to a piece of something bigger."""
    seen: set[str] = set()
    while isinstance(node, ast.Name) and node.id in aliases and node.id not in seen:
        seen.add(node.id)
        node = aliases[node.id]
    return isinstance(node, ast.Attribute | ast.Subscript)


def _is_stubbed(node: ast.expr, provided: dict[str, ast.expr], signatures: set[str]) -> bool:
    # The signature check is a cheap pre-filter so the vast majority of
    # assertions in a suite never pay for an `ast.dump`.
    if _reads_a_stub_attribute(node):
        return True
    return _signature(node) in signatures and ast.dump(node) in provided


def _reads_a_stub_attribute(node: ast.expr) -> bool:
    # `assert result == client.fetch.return_value` — the mock hands the test the
    # very object it hands the code under test.
    return isinstance(node, ast.Attribute) and node.attr in _MOCK_VALUE_ATTRS


def _appears_only_at_the_stub(func: ast.AST, target: ast.expr, receivers: set[int]) -> bool:
    """Report whether `target` occurs only twice: the stub and the assertion."""
    if _reads_a_stub_attribute(target):
        return True
    signature = _signature(target)
    dumped = ast.dump(target)
    count = 0
    for node in ast.walk(func):
        if not isinstance(node, ast.expr) or id(node) in receivers or not _is_read(node):
            continue
        if _signature(node) == signature and ast.dump(node) == dumped:
            count += 1
            if count > _EXPECTED_OCCURRENCES:
                return False
    return count == _EXPECTED_OCCURRENCES


def _is_read(node: ast.expr) -> bool:
    if isinstance(node, ast.Name | ast.Attribute | ast.Subscript | ast.List | ast.Tuple | ast.Starred):
        return isinstance(node.ctx, ast.Load)
    return True


def _signature(node: ast.expr) -> str:
    """Summarize `node` cheaply so full `ast.dump` comparisons stay rare."""
    if isinstance(node, ast.Name):
        return f"N:{node.id}"
    if isinstance(node, ast.Constant):
        return f"C:{node.value!r}"
    if isinstance(node, ast.Attribute):
        return f"A:{node.attr}"
    if isinstance(node, ast.Dict):
        return f"D:{len(node.keys)}"
    if isinstance(node, ast.List):
        return f"L:{len(node.elts)}"
    if isinstance(node, ast.Tuple):
        return f"T:{len(node.elts)}"
    if isinstance(node, ast.Set):
        return f"S:{len(node.elts)}"
    if isinstance(node, ast.Call):
        return f"K:{len(node.args)}"
    # `-1` parses as a unary minus over a constant, not as a negative literal.
    if isinstance(node, ast.UnaryOp):
        return f"U:{type(node.op).__name__}"
    return ""


def _is_verification_call(node: ast.Call) -> bool:
    """Report whether this call checks something the stub does not decide."""
    func = node.func
    if isinstance(func, ast.Attribute):
        name = func.attr
    elif isinstance(func, ast.Name):
        name = func.id
    else:
        return False
    return name.lstrip("_").startswith(_ASSERT_PREFIX) or name in _VERIFICATION_NAMES
