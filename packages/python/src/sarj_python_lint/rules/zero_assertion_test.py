"""SARJ043 — A test that verifies nothing passes as long as the code doesn't raise.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_zero_assertion_test.py
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


# Match assertion tokens anywhere in a snake_case helper name.
_ASSERTION_NAME_RE = re.compile(r"(^|_)(assert|expect|verify|validate)", re.IGNORECASE)

# `raises`/`warns` as a token anywhere in the name: `pytest.deprecated_call`,
# `pytest.RaisesGroup`, `pytest.RaisesExc`, and project wrappers such as
# `pytest_raises_user_error_for_undefined_type` all verify by expecting a throw.
_RAISES_TOKEN_RE = re.compile(r"(^|_)(raises|warns|deprecated_call)", re.IGNORECASE)

_RAISES_NAMES = frozenset({"raises", "warns", "fail"})

# These pytest and SQLAlchemy helpers verify without an assertion token in their names.
# Keep the set exact so similarly named application helpers remain findings.
_LIBRARY_ASSERTION_NAMES = frozenset({
    # _pytest.pytester.LineMatcher
    "fnmatch_lines",
    "fnmatch_lines_random",
    "no_fnmatch_line",
    "no_re_match_line",
    "re_match_lines",
    "re_match_lines_random",
    # sqlalchemy.testing.assertions
    "eq_",
    "eq_ignore_whitespace",
    "eq_regex",
    "in_",
    "is_",
    "is_false",
    "is_instance_of",
    "is_none",
    "is_not",
    "is_not_",
    "is_not_none",
    "is_true",
    "ne_",
    "not_in",
    "not_in_",
})

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
    """Collect imported and locally defined callable names."""
    imported = {
        alias.asname or alias.name.split(".")[0]
        for node in nodes(tree, ast.Import, ast.ImportFrom)
        for alias in node.names
    }
    return frozenset(imported | set(defined_here))


def _skips_at_runtime(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Report whether the test body unconditionally calls `pytest.skip(...)`."""
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
    """Find same-module functions that verify directly or transitively."""
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
    """Report whether the statement raises `AssertionError`."""
    exc = node.exc.func if isinstance(node.exc, ast.Call) else node.exc
    match exc:
        case ast.Name(id=name) | ast.Attribute(attr=name):
            return name == _ASSERTION_ERROR
        case _:
            return False


def _hands_a_verifier_to_a_runner(call: ast.Call, module_callables: frozenset[str]) -> bool:
    """Report whether a call's first argument is a known assertion helper."""
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
    return name in _LIBRARY_ASSERTION_NAMES or bool(
        _ASSERTION_NAME_RE.search(name) or _RAISES_TOKEN_RE.search(name)
    )


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
    """Collect names called in callee position throughout a subtree."""
    names: set[str] = set()
    for child in walk(node):
        if isinstance(child, ast.Call):
            func = child.func
            if isinstance(func, ast.Attribute):
                names.add(func.attr)
            elif isinstance(func, ast.Name):
                names.add(func.id)
    return names
