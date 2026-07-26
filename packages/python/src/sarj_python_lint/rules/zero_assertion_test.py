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
  either,
* a call to anything named like an assertion helper — `assert*`, `_assert*`,
  `self.assertEqual`, `expect*`, `verify*`, `validate*` — or any attribute chain
  passing through `.expect` (the fluent style used by the LiveKit test harness,
  `result.expect.contains_function_call(...)`),
* a call to `pytest.fail(...)`.

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
helper with an unrecognised name will be flagged; `# sarj-noqa: SARJ043` is the
intended escape, and the residual false-positive rate is the reason the message
asks rather than asserts.

Deliberately NOT flagged:

* a test marked `@pytest.mark.skip`/`skipif`/`xfail` — it is not expected to
  verify anything right now,
* **a `test_*` function nested inside another function.** pytest only collects
  module-level functions and methods of `Test*` classes, so a nested one is not
  a test at all — it is a callback that happens to be named for what it does.
  Flask route handlers are the canonical case: `def test_index()` registered
  with `@app.route("/", subdomain="test")` inside a test that asserts on the
  response afterwards. A third-party sweep found 36 such hits, every one a false
  positive. Only functions whose parent is the module or a class are considered.
* **a `@pytest.fixture`**, whatever it is named. `flask/tests/conftest.py`
  defines `def test_apps(monkeypatch)` as a fixture; it sets up `sys.path` and
  yields, and asserting nothing is exactly right for it,
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

_RAISES_NAMES = frozenset({"raises", "warns", "fail"})

# Fluent verification DSLs reached through an attribute rather than a call name.
_FLUENT_ATTRS = frozenset({"expect"})

_SKIP_MARKERS = frozenset({"skip", "skipif", "xfail"})

_FIXTURE = "fixture"

_FUNC_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)

# Manual CLI probes live here under test_*.py names but are never collected.
_UNCOLLECTED_DIR_NAMES = frozenset({"scripts"})


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
        if not is_test_path(path) or _is_uncollected(path):
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


def _is_uncollected(path: Path) -> bool:
    return any(part in _UNCOLLECTED_DIR_NAMES for part in path.parts)


def _unverifying_tests(tree: ast.Module) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    hits: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
    for node in _collectible_tests(tree):
        if _is_skipped(node) or _is_fixture(node) or _is_placeholder(node) or _verifies_something(node):
            continue
        hits.append(node)
    return hits


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
        return bool(_ASSERTION_NAME_RE.match(func.id))
    if not isinstance(func, ast.Attribute):
        return False
    if func.attr in _RAISES_NAMES or bool(_ASSERTION_NAME_RE.match(func.attr)):
        return True
    # `result.expect.contains_function_call(...)` — the DSL marker sits partway
    # along the chain rather than at its end.
    return _chain_has_fluent_marker(func.value)


def _chain_has_fluent_marker(node: ast.expr) -> bool:
    while isinstance(node, ast.Attribute):
        if node.attr in _FLUENT_ATTRS:
            return True
        node = node.value
    return False
