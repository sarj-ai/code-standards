"""SARJ043 — A test that verifies nothing passes as long as the code doesn't raise.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_zero_assertion_test.py
Evidence: https://github.com/sarj-ai/standards/blob/main/docs/rules/SARJ043.md
"""

from __future__ import annotations

import ast
import re
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none
from sarj_python_lint.rules._ast_index import nodes, walk
from sarj_python_lint.rules._paths import is_test_path
from sarj_python_lint.rules._pytest import uses_benchmark_fixture


if TYPE_CHECKING:
    from pathlib import Path


# Names that verify something, however the project spells them. A snake_case
# TOKEN search, not a prefix: `invoke_and_assert` is prefect's primary CLI-test
# verifier and an anchored pattern could not see it.
_ASSERTION_NAME_RE = re.compile(r"(^|_)(assert|expect|verify|validate)", re.IGNORECASE)

# `raises`/`warns` as a token anywhere in the name: `pytest.deprecated_call`,
# `pytest.RaisesGroup`, `pytest.RaisesExc`, and project wrappers such as
# `pytest_raises_user_error_for_undefined_type` all verify by expecting a throw.
_RAISES_TOKEN_RE = re.compile(r"(^|_)(raises|warns|deprecated_call)", re.IGNORECASE)

_RAISES_NAMES = frozenset({"raises", "warns", "fail"})

_TEST_PREFIX = "test_"

# Fluent verification DSLs reached through an attribute rather than a call name.
_FLUENT_ATTRS = frozenset({"expect"})

_SKIP_MARKERS = frozenset({"skip", "skipif", "xfail"})

# The imperative twin of `@pytest.mark.skip`: `pytest.skip("...")` standing
# alone in the body aborts the test before anything could be asserted.
_PYTEST = "pytest"
_SKIP_CALL = "skip"

# `raise AssertionError(...)` states an expectation exactly as `assert` does; it
# is how a `match` statement spells "no other case is acceptable".
_ASSERTION_ERROR = "AssertionError"

_FIXTURE = "fixture"

_FUNC_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)

# Manual CLI probes live here under test_*.py names but are never collected.
_UNCOLLECTED_DIR_NAMES = frozenset({"scripts"})

# pytest's default `python_files`. `is_test_path` is broader on purpose (it
# accepts everything under `tests/`), and that breadth is wrong here: a module
# pytest never imports as a test cannot hold a weak test.
_COLLECTED_SUFFIX = "_test.py"


class ZeroAssertionTest(Rule):
    id: str = "zero-assertion-test"
    code: str = "SARJ043"
    has_evidence: bool = True
    description: str = "Test contains no assertion of any kind — it passes as long as nothing raises."

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        """Flag test functions containing no assertion, raises block, or helper call."""
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
                    f"`{node.name}` contains no assertion, `pytest.raises`, or assertion helper — it "
                    "passes whatever the code returns, as long as nothing throws. Assert on the result, "
                    "or if 'does not raise' really is the contract, say so with `# sarj-noqa: SARJ043`."
                ),
            )
            for node in _unverifying_tests(tree)
        ]
        diags.sort(key=lambda d: (d.line, d.col))
        return diags


def _is_collected_module(path: Path) -> bool:
    name = path.name
    matches_python_files = name.startswith(_TEST_PREFIX) or name.endswith(_COLLECTED_SUFFIX)
    return matches_python_files and not any(part in _UNCOLLECTED_DIR_NAMES for part in path.parts)


def _unverifying_tests(tree: ast.Module) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    defined_here = _function_defs(tree)
    module_callables = _module_level_callables(tree, defined_here)
    verifying_helpers = _verifying_local_names(defined_here, module_callables)
    hits: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
    for node in _collectible_tests(tree):
        if _is_skipped(node) or _is_fixture(node) or _is_placeholder(node) or uses_benchmark_fixture(node):
            continue
        if _skips_at_runtime(node):
            continue
        if _verifies_something(node, module_callables) or _delegates_verification(
            node, defined_here, verifying_helpers
        ):
            continue
        hits.append(node)
    return hits


def _module_level_callables(
    tree: ast.Module, defined_here: dict[str, ast.FunctionDef | ast.AsyncFunctionDef]
) -> frozenset[str]:
    """Collect the names bound by an import or a `def` at module scope.

    Used to tell a callable handed to a runner from a local variable that
    merely reads like one: `run_sync_in_worker_thread(invoke_and_assert, ...)`
    passes an imported verifier, while `compare(expected_value, actual)` passes
    a value computed two lines up.

    Returns:
        Every name this module imports or defines as a function.

    """
    imported = {
        alias.asname or alias.name.split(".")[0]
        for node in nodes(tree, ast.Import, ast.ImportFrom)
        for alias in node.names
    }
    return frozenset(imported | set(defined_here))


def _skips_at_runtime(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Report whether the body unconditionally calls `pytest.skip(...)`.

    The imperative twin of `@pytest.mark.skip`, and exempt for the same reason:
    everything after it is unreachable, so there was never anything to assert.
    Only a statement sitting directly in the body counts — a `pytest.skip()`
    guarded by an `if` leaves the rest of the test running.

    Returns:
        True when the test aborts itself before it can verify anything.

    """
    return any(
        isinstance(stmt, ast.Expr)
        and isinstance(call := stmt.value, ast.Call)
        and isinstance(func := call.func, ast.Attribute)
        and func.attr == _SKIP_CALL
        and isinstance(func.value, ast.Name)
        and func.value.id == _PYTEST
        for stmt in node.body
    )


def _function_defs(tree: ast.Module) -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    """Index every function this module defines, methods and nested defs included."""
    defs: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}
    for node in nodes(tree, *_FUNC_NODES):
        defs.setdefault(node.name, node)
    return defs


def _verifying_local_names(
    defined_here: dict[str, ast.FunctionDef | ast.AsyncFunctionDef],
    module_callables: frozenset[str],
) -> frozenset[str]:
    """Find the same-module functions that verify, directly or by delegation.

    Transitive because assertion helpers stack: black's `compare_results` calls
    `check_ast_equivalence`, and only the latter holds the `assert`.

    Returns:
        Every local function name whose body reaches a verification.

    """
    verifying = {name for name, node in defined_here.items() if _verifies_something(node, module_callables)}
    pending = {name: _called_names(node) for name, node in defined_here.items() if name not in verifying}
    while True:
        promoted = {name for name, called in pending.items() if called & verifying}
        if not promoted:
            return frozenset(verifying)
        verifying |= promoted
        pending = {name: called for name, called in pending.items() if name not in promoted}


def _collectible_tests(tree: ast.Module) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    """Collect the `test_*` functions pytest would actually run."""
    found: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
    containers: list[ast.Module | ast.ClassDef] = [tree]
    while containers:
        for stmt in containers.pop().body:
            if isinstance(stmt, ast.ClassDef):
                containers.append(stmt)
            elif isinstance(stmt, _FUNC_NODES) and stmt.name.startswith("test_"):
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
    # A body of only a docstring, `...` and/or `pass` is an intentional stub.
    return all(_is_inert(stmt) for stmt in node.body)


def _is_inert(stmt: ast.stmt) -> bool:
    if isinstance(stmt, ast.Pass):
        return True
    return isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant)


def _verifies_something(node: ast.FunctionDef | ast.AsyncFunctionDef, module_callables: frozenset[str]) -> bool:
    # Search the whole subtree, nested functions included: the common
    # `async def _run(): assert ...` + `asyncio.run(_run())` wrapper keeps its
    # assertions one scope down from the test body.
    return any(_is_verification(child, module_callables) for child in walk(node))


def _is_verification(child: ast.AST, module_callables: frozenset[str]) -> bool:
    if isinstance(child, ast.Assert):
        return True
    if isinstance(child, ast.Raise):
        return _raises_assertion_error(child)
    if isinstance(child, ast.Call):
        return _names_verification(child.func) or _hands_a_verifier_to_a_runner(child, module_callables)
    return False


def _raises_assertion_error(node: ast.Raise) -> bool:
    """Report whether the statement raises `AssertionError`.

    `case _: raise AssertionError("unexpected variant")` is the `match`
    statement's way of stating an expectation; refusing to count it flagged
    tests that verify strictly more precisely than an `assert` would.

    Returns:
        True when the raised exception is an `AssertionError`.

    """
    exc = node.exc.func if isinstance(node.exc, ast.Call) else node.exc
    match exc:
        case ast.Name(id=name) | ast.Attribute(attr=name):
            return name == _ASSERTION_ERROR
        case _:
            return False


def _hands_a_verifier_to_a_runner(call: ast.Call, module_callables: frozenset[str]) -> bool:
    """Report whether the call passes an assertion helper as a bare callable.

    `run_sync_in_worker_thread(invoke_and_assert, "work-pool create ''",
    expected_code=1)` verifies through the helper it hands over, but the helper
    never appears in callee position, so reading `Call.func` alone cannot see
    it. Only the FIRST argument — the callable slot every runner and
    `functools.partial` uses — is read, and only when the name is one this
    module imports or defines, which is what separates a callable from a local
    variable that happens to be named `expected_rows`.

    Returns:
        True when a verifying callable is being handed to a runner.

    """
    if not call.args:
        return False
    match call.args[0]:
        case ast.Name(id=name):
            return name in module_callables and _reads_as_verification(name)
        case ast.Attribute(value=ast.Name(id=receiver), attr=attr):
            return receiver in module_callables and _reads_as_verification(attr)
        case _:
            return False


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
    return bool(_ASSERTION_NAME_RE.search(name) or _RAISES_TOKEN_RE.search(name))


def _chain_has_fluent_marker(node: ast.expr) -> bool:
    while isinstance(node, ast.Attribute):
        if node.attr in _FLUENT_ATTRS:
            return True
        node = node.value
    return False


def _delegates_verification(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    defined_here: dict[str, ast.FunctionDef | ast.AsyncFunctionDef],
    verifying_helpers: frozenset[str],
) -> bool:
    called = _called_names(node) - {node.name}
    if called & verifying_helpers:
        return True
    # A `test_*` callable this module does not define is another suite's test,
    # imported or fetched off a module object; its assertions are out of reach.
    return any(name.startswith(_TEST_PREFIX) and name not in defined_here for name in called)


def _called_names(node: ast.AST) -> set[str]:
    """Collect the names this subtree calls, in callee position.

    Deliberately NOT widened to the callable slot the way `_is_verification` is.
    These names are resolved against `test_*`-ness as well as against the
    module's own helpers, and a first argument named `test_client` — a fixture,
    not a delegate — would otherwise read as "this test re-runs another
    module's test" and silence the rule.

    Returns:
        Every name invoked in the subtree.

    """
    names: set[str] = set()
    for child in walk(node):
        if isinstance(child, ast.Call):
            func = child.func
            if isinstance(func, ast.Attribute):
                names.add(func.attr)
            elif isinstance(func, ast.Name):
                names.add(func.id)
    return names
