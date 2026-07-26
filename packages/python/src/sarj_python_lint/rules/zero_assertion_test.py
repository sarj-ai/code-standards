"""SARJ043: a test that verifies nothing passes as long as the code doesn't raise.

A `test_*` function with no assertion of any kind only proves the code under test
did not throw. That is occasionally the intent, but far more often it is a test
someone stopped writing halfway: the return value is computed and dropped on the
floor, so the test goes green no matter what the function returns. One real
example from the audited corpora calls `evaluate_conditions(...)`, discards the
result, and is named `test_equality_matches_name_in_jsonobject` — it asserts
nothing about equality, or about anything else.

Fires when a `test_*` function contains **none** of the following, anywhere in
its subtree:

* an `assert` statement,
* a `with pytest.raises(...)` / `pytest.warns(...)` block, or a bare call to
  either — including anything whose name merely *carries* the `raises`/`warns`
  token, which covers `pytest.deprecated_call(...)`, pytest 8.4's
  `pytest.RaisesGroup(pytest.RaisesExc(...))`, and project-local wrappers such
  as pydantic's `pytest_raises_user_error_for_undefined_type(...)`,
* a call to anything named like an assertion helper — `assert*`, `_assert*`,
  `self.assertEqual`, `expect*`, `verify*`, `validate*` — or any attribute chain
  passing through `.expect` (the fluent style used by the LiveKit test harness,
  `result.expect.contains_function_call(...)`),
* a call to `pytest.fail(...)`,
* a call to a **function defined in the same module that itself verifies**,
  directly or through another local helper,
* a call to some *other* `test_*` callable that this module does not define —
  the tutorial-runner shape, where the assertions live in the delegate.

**The guards are the rule.** A naive version of this check is overwhelmingly
wrong: of 264 assertion-free tests found across the two repos, **223 verify
through `pytest.raises`** and would have been false positives — an 84% error
rate. Of the remainder, a further tranche delegates to a local `_assert_default`
helper or a fluent `.expect` DSL. Only ~41 are genuinely bare. The rule
deliberately searches the whole subtree rather than the top level, because the
`async def _run(): ...; asyncio.run(_run())` wrapper puts the real assertions
inside a nested function that a top-level-only scan would miss.

Even so, this rule cannot see across a call boundary into a helper defined in
another module. A test whose only verification is a project-specific assertion
helper imported from elsewhere will be flagged; `# sarj-noqa: SARJ043` is the
intended escape, and the residual false-positive rate is the reason the message
asks rather than asserts.

Deliberately NOT flagged:

* a test marked `@pytest.mark.skip`/`skipif`/`xfail` — it is not expected to
  verify anything right now,
* **a file pytest would never collect.** `is_test_path` is deliberately broad —
  it accepts anything under a `tests/` directory — but pytest only collects
  modules matching `test_*.py` / `*_test.py`. `black/tests/data/cases/` holds
  formatter fixtures such as `class_blank_parentheses.py` and `fmtonoff5.py`
  whose *content* is arbitrary Python containing `def test_func(self)`; a
  third-party sweep produced 10 hits there (`black/tests/data/cases/
  fmtskip8.py:43`, `.../line_ranges_basic.py:37`, `.../comments4.py:52`), every
  one a false positive, because those functions are input data for a formatter,
  not tests,
* **a pytest-benchmark test** — one that declares a `benchmark` parameter and
  uses it, whether called (`benchmark(model_eq, m1, m2)`) or applied as a
  decorator (`@benchmark`). A benchmark measures wall time; asserting is not its
  job. This is the single largest cluster in the third-party sweep: 94 of 291
  hits, all of `pydantic/tests/benchmarks/` and
  `pydantic/pydantic-core/tests/benchmarks/` (e.g.
  `pydantic/tests/benchmarks/test_north_star.py:86`,
  `pydantic/pydantic-core/tests/benchmarks/test_micro_benchmarks.py`, 45 hits in
  that file alone),
* **a test that delegates to a verifying helper defined in the same module.**
  Resolving called names against the module's own `def`s — transitively, so a
  helper that delegates to another helper still counts — cleared 50 sweep hits:
  black's `self.invokeBlack(...)` / `self.check_features_used(...)` /
  `self.compare_results(...)` (`black/tests/test_black.py:1156`), flask's
  `common_object_test(app)` (`flask/tests/test_config.py:19`), pydantic's
  `inspect_type_hints(...)` (`pydantic/tests/test_type_hints.py:133`) and
  `url_test_case_helper(...)`
  (`pydantic/pydantic-core/tests/validators/test_url.py`), and sqlmodel's
  `check_calls(...)`,
* **a test that calls another `test_*` function this module does not define.**
  The fastapi/sqlmodel tutorial suites re-run a documented test module's own
  tests: `from docs_src.app_testing.tutorial002_py310 import test_read_main` and
  then `def test_main(): test_read_main()`
  (`fastapi/tests/test_tutorial/test_testing/test_tutorial002.py:4`), or
  `modules.test.test_create_hero()`
  (`sqlmodel/tests/test_tutorial/test_fastapi/test_app_testing/
  test_tutorial001_tests001.py:39`). The assertions are one import away. 17
  sweep hits,
* **a `test_*` function nested inside another function.** pytest only collects
  module-level functions and methods of `Test*` classes, so a nested one is not
  a test at all — it is a callback that happens to be named for what it does.
  Flask route handlers are the canonical case: `def test_index()` registered
  with `@app.route("/", subdomain="test")` inside a test that asserts on the
  response afterwards. A third-party sweep found 36 such hits, every one a false
  positive. Only functions whose parent is the module or a class are considered.
* **a `@pytest.fixture`**, whatever it is named — a `test_*`-named fixture in a
  collected module sets state up and yields, and asserting nothing is exactly
  right for it. (The original example, `test_apps` in `flask/tests/conftest.py`,
  no longer reaches this rule at all: `conftest.py` is not a collected module.)
* a helper, or any function not named `test_*`,
* an abstract or stub body (`...`, `pass`, docstring only) — an intentionally
  empty placeholder is a different problem from a half-written test,
* anything under a `scripts/` directory. `digital-bank/banking-ai/chat/scripts/`
  holds four `test_*.py` files that are manual CLI probes run as
  `uv run python chat/scripts/test_llm_providers.py`, not pytest modules — they
  sit outside every `testpaths` and are never collected. A file that is not
  collected cannot have a weak assertion, so flagging it is noise; this is the
  one rule where the distinction matters, because "no assertions" is definitional
  for a CLI script.
"""

from __future__ import annotations

import ast
import re
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none
from sarj_python_lint.rules._paths import is_test_path


if TYPE_CHECKING:
    from pathlib import Path


# Names that verify something, however the project spells them.
_ASSERTION_NAME_RE = re.compile(r"^_?(assert|expect|verify|validate)", re.IGNORECASE)

# `raises`/`warns` as a token anywhere in the name: `pytest.deprecated_call`,
# `pytest.RaisesGroup`, `pytest.RaisesExc`, and project wrappers such as
# `pytest_raises_user_error_for_undefined_type` all verify by expecting a throw.
_RAISES_TOKEN_RE = re.compile(r"(^|_)(raises|warns|deprecated_call)", re.IGNORECASE)

_RAISES_NAMES = frozenset({"raises", "warns", "fail"})

_TEST_PREFIX = "test_"

# The pytest-benchmark fixture: the test measures time, it does not verify.
_BENCHMARK = "benchmark"

# Fluent verification DSLs reached through an attribute rather than a call name.
_FLUENT_ATTRS = frozenset({"expect"})

_SKIP_MARKERS = frozenset({"skip", "skipif", "xfail"})

_FIXTURE = "fixture"

_FUNC_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)

# Manual CLI probes live here under test_*.py names but are never collected.
_UNCOLLECTED_DIR_NAMES = frozenset({"scripts"})

# pytest's default `python_files`. `is_test_path` is broader on purpose (it
# accepts everything under `tests/`), and that breadth is wrong here: a module
# pytest never imports as a test cannot hold a weak test.
_COLLECTED_SUFFIX = "_test.py"


class ZeroAssertionTest(Rule):
    """A `test_*` function with no assertion only proves the code did not raise."""

    id: str = "zero-assertion-test"
    code: str = "SARJ043"
    description: str = "Test contains no assertion of any kind — it passes as long as nothing raises."

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        """Flag test functions containing no assertion, raises block, or helper call.

        Returns:
            One diagnostic per unverifying test, sorted by position.

        """
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
    verifying_helpers = _verifying_local_names(defined_here)
    hits: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
    for node in _collectible_tests(tree):
        if _is_skipped(node) or _is_fixture(node) or _is_placeholder(node) or _uses_benchmark_fixture(node):
            continue
        if _verifies_something(node) or _delegates_verification(node, defined_here, verifying_helpers):
            continue
        hits.append(node)
    return hits


def _function_defs(tree: ast.Module) -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    """Index every function this module defines, methods and nested defs included.

    Returns:
        Name to definition; the first definition of a shadowed name wins.

    """
    defs: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}
    for node in ast.walk(tree):
        if isinstance(node, _FUNC_NODES):
            defs.setdefault(node.name, node)
    return defs


def _verifying_local_names(defined_here: dict[str, ast.FunctionDef | ast.AsyncFunctionDef]) -> frozenset[str]:
    """Find the same-module functions that verify, directly or by delegation.

    Transitive because assertion helpers stack: black's `compare_results` calls
    `check_ast_equivalence`, and only the latter holds the `assert`.

    Returns:
        Every local function name whose body reaches a verification.

    """
    verifying = {name for name, node in defined_here.items() if _verifies_something(node)}
    pending = {name: _called_names(node) for name, node in defined_here.items() if name not in verifying}
    while True:
        promoted = {name for name, called in pending.items() if called & verifying}
        if not promoted:
            return frozenset(verifying)
        verifying |= promoted
        pending = {name: called for name, called in pending.items() if name not in promoted}


def _collectible_tests(tree: ast.Module) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    """Collect the `test_*` functions pytest would actually run.

    Only module-level functions and methods of a class qualify. A `test_*`
    nested inside another function is a callback, not a test — pytest never
    collects it — so descending into function bodies would invent findings.

    Returns:
        The test functions in the order they appear.

    """
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


def _uses_benchmark_fixture(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    # pytest-benchmark: `def test_x(benchmark)` then `benchmark(fn, arg)` or
    # `@benchmark` on a nested function. The fixture times the callable; a
    # benchmark that asserted on the result would be measuring the assertion.
    args = node.args
    declared = any(arg.arg == _BENCHMARK for arg in (*args.posonlyargs, *args.args, *args.kwonlyargs))
    return declared and any(isinstance(child, ast.Name) and child.id == _BENCHMARK for child in ast.walk(node))


def _verifies_something(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    # Search the whole subtree, nested functions included: the common
    # `async def _run(): assert ...` + `asyncio.run(_run())` wrapper keeps its
    # assertions one scope down from the test body.
    return any(_is_verification(child) for child in ast.walk(node))


def _is_verification(child: ast.AST) -> bool:
    if isinstance(child, ast.Assert):
        return True
    if isinstance(child, ast.Call):
        return _names_verification(child.func)
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
    return bool(_ASSERTION_NAME_RE.match(name) or _RAISES_TOKEN_RE.search(name))


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
    names: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            func = child.func
            if isinstance(func, ast.Attribute):
                names.add(func.attr)
            elif isinstance(func, ast.Name):
                names.add(func.id)
    return names
