"""SARJ015: flag `collections.namedtuple` — prefer `typing.NamedTuple` or a model.

`collections.namedtuple` produces an untyped, positionally-constructed tuple:
fields have no type annotations, the type checker can't catch a wrong-typed
field, and it silently supports tuple unpacking by position — the exact bug
class a named value object exists to prevent. `typing.NamedTuple` is the typed,
modern equivalent; a frozen pydantic `BaseModel` is better still when the value
crosses a boundary and needs validation.

    # flagged
    from collections import namedtuple
    Point = namedtuple("Point", ["x", "y"])
    Row = collections.namedtuple("Row", "id name")

    # preferred
    from typing import NamedTuple
    class Point(NamedTuple):
        x: float
        y: float

`typing.NamedTuple` is NOT flagged — it is the recommended form.

Test files are exempt (`_paths.is_test_path`): a `collections.namedtuple` in a
test is usually the *subject* — exercising code that must accept untyped
namedtuples (pydantic's validation tests were the sweep case) — not a value
object the test should model properly.

The famous-repo sweep (2,657 files of fastapi / pydantic / black / sqlmodel /
rich / flask / httpx / requests / anyio) produced exactly 2 hits and BOTH are
true positives, so no exemption was added:

- `httpx/httpx/_urls.py:409` — `RawURL = collections.namedtuple("RawURL",
  ["raw_scheme", "raw_host", "port", "raw_path"])`, built inside a deprecated
  `URL.raw` property. Four fields, no types, and the surrounding annotation is
  the positional `tuple[bytes, bytes, int, bytes]` this rule's sibling SARJ026
  flags; a `class RawURL(NamedTuple)` fixes both.
- `rich/rich/pretty.py:90` — `_dummy_namedtuple = collections.namedtuple(
  "_dummy_namedtuple", [])`, a probe used to locate the file of the generated
  `__repr__`. `class _DummyNamedTuple(NamedTuple): pass` produces the same
  generated `__repr__`, so the rewrite is available here too.

The rule stayed at 2 hits over 2,657 files: it is rare, precise, and cheap.

Suppress with `# sarj-noqa: SARJ015 — <reason>`.

References:
- https://docs.python.org/3/library/typing.html#typing.NamedTuple

"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none
from sarj_python_lint.rules._ast_index import nodes
from sarj_python_lint.rules._paths import is_test_path


if TYPE_CHECKING:
    from pathlib import Path


_MSG = (
    "collections.namedtuple is untyped and positionally constructed — prefer "
    "typing.NamedTuple, or a frozen pydantic BaseModel for boundary values."
)


class PreferStructOverNamedtuple(Rule):
    """`collections.namedtuple` — prefer typing.NamedTuple or a frozen model."""

    id: str = "prefer-struct-over-namedtuple"
    code: str = "SARJ015"
    description: str = (
        "collections.namedtuple is untyped/positional — prefer typing.NamedTuple or a frozen pydantic model."
    )

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if is_test_path(path):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        collections_names = {"collections"}
        candidates: list[tuple[ast.AST, str | None]] = []
        for node in nodes(tree, ast.ImportFrom, ast.Import, ast.Call):
            if isinstance(node, ast.ImportFrom):
                if node.module == "collections":
                    candidates.extend((node, None) for alias in node.names if alias.name == "namedtuple")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "collections":
                        collections_names.add(alias.asname or "collections")
            elif (
                isinstance(node.func, ast.Attribute)
                and node.func.attr == "namedtuple"
                and isinstance(node.func.value, ast.Name)
            ):
                candidates.append((node, node.func.value.id))
        return [self._diag(path, node) for node, name in candidates if name is None or name in collections_names]

    def _diag(self, path: Path, node: ast.AST) -> Diagnostic:
        return Diagnostic(
            path=path,
            line=getattr(node, "lineno", 1),
            col=getattr(node, "col_offset", 0) + 1,
            code=self.code,
            message=_MSG,
        )
