"""SARJ045: a domain object built with many kwargs inline belongs in a builder.

A test that constructs `SarjBeneficiary(id=..., name=..., iban=..., bank=...,
status=..., created_at=..., updated_at=..., owner=..., currency=...)` in its own
body states nine facts, and typically only one of them is the thing under test.
The other eight are noise the reader must scan past to find the interesting
field, and every one of them has to be revisited when the model gains a required
column — across every test that spells the object out. A builder or factory with
defaults collapses that to `build_beneficiary(status="frozen")`, which says what
the test is about.

Fires when ALL of these hold:

* the file is a test file, and the **nearest enclosing function** of the call is
  named `test_*`,
* and the call passes more than eight keyword arguments.

The nearest-enclosing-function guard is what makes this rule worth having rather
than noise. A blind sweep of both corpora found 113 kwarg-heavy constructions,
but 96 of them sit inside a module-level `_make_*`/`_build_*` helper — which is
precisely the factory this rule asks for, already written. Counting those would
have meant nagging at the well-factored code and rewarding the sloppy kind.
Scoped to calls directly in a test body, the population drops to 17.

The threshold is deliberately high. Eight keywords is well past the point where
a constructor call is self-explanatory, and it was chosen so the rule fires only
where the audited corpora showed a genuine builder was missing — in at least
three cases (`digital-bank/banking-ai/chat/tests/test_chat_store.py`) the fix is
a one-line import of a `build_sarj_beneficiary` helper that already exists in
`common/testing/builders.py`.

Deliberately NOT flagged:

* **a callee constructed only once in the whole file.** The message promises
  "every other test repeats the same boilerplate" — so the rule now checks that
  premise instead of asserting it. A single construction of a domain model with
  many required fields has no duplication to extract, and telling the author to
  build a factory for one call site trades real ceremony for nothing. Found in
  bulbul PR #4111: removing one `# pyright: ignore` forced
  `python/bulbul/tests/observability/test_analytics_events.py:227` to build a
  real `Batch(...)` with 12 required fields — the only `Batch(` in the file —
  and the rule blocked CI over it. Two or more constructions of the same callee
  still fire: that is the shape a builder actually fixes.
* calls inside a fixture, a `_make_*` helper, or any non-test function — that is
  the factory, and it is allowed to be verbose exactly once,
* positional arguments — a call with many positionals is a different smell, and
  ruff's own rules already discourage it,
* `dict(...)` and literal dict displays — those are data, not a domain object,
  and naming their keys is the point rather than the problem,
* `<mapping>.update(...)` — the same data case one call further on. The keywords
  are mapping entries being spread, not constructor fields, so there is no
  object for a builder to build. A 2,657-file third-party sweep produced 14
  findings and the widest of them (29 keywords) was rich's
  `table.box.__dict__.update(top_left="a", top="b", ...)`, which relabels box
  characters wholesale.
"""

from __future__ import annotations

import ast
from collections import Counter
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none
from sarj_python_lint.rules._paths import is_test_path


if TYPE_CHECKING:
    from pathlib import Path


_MAX_KEYWORDS = 8

# A builder only pays for itself once the same callee is built more than once.
_MIN_CONSTRUCTIONS = 2

# `dict(a=1, b=2, ...)` is a mapping literal, not a domain object.
_DATA_CALLABLES = frozenset({"dict"})

# `<mapping>.update(a=1, b=2, ...)` spreads mapping entries — data again, and no
# object a builder could construct.
_DATA_METHODS = frozenset({"update"})


class KwargHeavyConstructionInTest(Rule):
    """A >8-keyword construction directly in a test body wants a builder."""

    id: str = "kwarg-heavy-construction-in-test"
    code: str = "SARJ045"
    description: str = "Object built with many keywords inline in a test — extract a builder with defaults."

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        """Flag kwarg-heavy constructions sitting directly in a test body.

        Returns:
            One diagnostic per over-wide construction, sorted by position.

        """
        if not is_test_path(path):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []

        visitor = _KwargHeavyVisitor()
        visitor.visit(tree)
        diags = [
            Diagnostic(
                path=path,
                line=node.lineno,
                col=node.col_offset + 1,
                code=self.code,
                message=(
                    f"this call passes {count} keywords inline, so the one field under test is buried "
                    "and every other test repeats the same boilerplate. Extract a builder with "
                    "defaults and override only what this test is about."
                ),
            )
            for node, count in visitor.repeated_hits(tree)
        ]
        diags.sort(key=lambda d: (d.line, d.col))
        return diags


class _KwargHeavyVisitor(ast.NodeVisitor):
    """Flag wide keyword calls whose nearest enclosing function is a test.

    Mirrors SARJ031's enclosing-function stack so a construction inside a
    `_make_*` helper or fixture declared anywhere in the file is attributed to
    that helper — the factory is allowed to be verbose.
    """

    def __init__(self) -> None:
        super().__init__()
        self._func_names: list[str | None] = []
        self.hits: list[tuple[ast.Call, int]] = []

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self._func_names.append(node.name)
        self.generic_visit(node)
        self._func_names.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        self._func_names.append(None)
        self.generic_visit(node)
        self._func_names.pop()

    def visit_Call(self, node: ast.Call) -> None:
        if self._in_test_function() and not _is_data_callable(node.func):
            named = [kw for kw in node.keywords if kw.arg is not None]
            if len(named) > _MAX_KEYWORDS:
                self.hits.append((node, len(named)))
        self.generic_visit(node)

    def repeated_hits(self, tree: ast.Module) -> list[tuple[ast.Call, int]]:
        """Keep only hits whose callee is constructed more than once in the file.

        Returns:
            The wide constructions that actually have duplication to extract.

        """
        counts = Counter(
            name for n in ast.walk(tree) if isinstance(n, ast.Call) and (name := _callee_name(n.func)) is not None
        )
        return [
            (node, count)
            for node, count in self.hits
            # A callee with no stable name (a subscript, a call result) cannot be
            # counted, so it can never clear the repetition bar.
            if (name := _callee_name(node.func)) is not None and counts[name] >= _MIN_CONSTRUCTIONS
        ]

    def _in_test_function(self) -> bool:
        nearest = self._func_names[-1] if self._func_names else None
        return nearest is not None and nearest.startswith("test_")


def _is_data_callable(func: ast.expr) -> bool:
    if isinstance(func, ast.Name):
        return func.id in _DATA_CALLABLES
    return isinstance(func, ast.Attribute) and func.attr in _DATA_METHODS


def _callee_name(func: ast.expr) -> str | None:
    """Render the callee as a comparable name, so repeats can be counted.

    Returns:
        The bare or dotted-final name, or None when the callee is an expression
        with no stable name (a subscript, a call result).

    """
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None
