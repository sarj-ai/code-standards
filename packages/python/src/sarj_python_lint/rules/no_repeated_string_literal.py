"""SARJ024: a structured string literal repeated across functions — extract a named constant.

The same long, *structured* string literal appearing in two or more different
functions of a module is a real maintenance hazard: when one copy is edited the
others silently drift, and (unlike SQL/log/prompt scaffolding) the strings that
qualify here cannot plausibly be equal by coincidence. Derived from the
magic-values audit corpus ("Repeated Complex String Literal").

The rule is deliberately narrow — it fires only where cross-site drift is a
genuine bug, never on coincidentally-equal prose. Three filters combine:

1. **Structured only.** A literal qualifies only if it carries structural signal
   that makes coincidental equality near-impossible:
   - it contains a newline (multi-line SQL / prompt templates), OR
   - it matches an *uppercase* SQL keyword (`SELECT`, `FROM`, `WHERE`, …) —
     matched case-sensitively so prose ("...criteria *from* the prompt") does
     not trip it, only real SQL does, OR
   - it is a bare snake_case / dotted identifier (`^[a-z_][a-z0-9_.]*$`), i.e. a
     DB constraint / index / key name reused across statements.
   Plain user-facing error messages, log lines, and spoken prompts carry none of
   these — two different-intent messages that happen to be equal (e.g. a
   `get_user_error_message` mapping two distinct error codes to one sentence) are
   *not* flagged, so a shared constant can never wrongly couple them.

2. **Cross-function only.** The occurrences must span at least two distinct
   enclosing functions/methods. Two uses inside one function (or several
   module-level constants) are edited together and moving them to the module top
   buys no drift protection — that is pure locality loss, so it is excluded.

   This is the *only* count threshold. An earlier revision also demanded three
   total occurrences, which made the rule fire on nothing at all: 0 findings in
   the 2,657-file third-party corpus and 0 across the whole first-party Python
   tree. Dropping to "two distinct functions" costs no precision — the corpus
   then yields exactly one finding, `fastapi/openapi/models.py:39`, where a
   two-line "email-validator not installed" warning is duplicated verbatim
   between `EmailStr.validate` and `EmailStr._validate` and would silently drift
   if either were reworded. Cross-function drift *begins* at two copies; the
   third was arbitrary, and precision here is carried by filter 1, not by counting.

3. **Exclusions.** f-string fragments (`ast.Constant` inside `JoinedStr`),
   docstrings (first statement of module/class/function), strings under an
   OpenAPI/pydantic scaffolding keyword (`examples=`, `description=`, `title=`,
   `summary=`), and strings in **type-annotation position** — parameter and
   return annotations, `x: T = ...` annotations, and anything inside an
   `Annotated[...]` subscript.

   The scaffolding-keyword and annotation exclusions cover the same category:
   documentation deliberately duplicated across sibling declarations. A string
   in annotation position is either a forward reference or PEP 593 metadata;
   neither is a value that can drift into a runtime bug, and a mismatch between
   copies is a type error the type checker already reports.

   Corpus evidence (2,657 files of fastapi / pydantic / black / sqlmodel / rich /
   flask / httpx / requests / anyio): **all 499** pre-guard findings were
   `Annotated[...]` metadata — 494 inside PEP 727 `Doc(...)` blocks and 5 inside
   `deprecated(...)`. fastapi documents every `APIRouter` verb with a verbatim
   copy of the same `Doc()` block, so one paragraph about `response_model`
   recurs once per HTTP method: `fastapi/applications.py:2018` (`put`),
   `:2396` (`post`), `:2774` (`delete`), `:3147` (`options`), `:3520` (`head`),
   `:3893` (`patch`), `:4271` (`trace`), and the same shape in
   `fastapi/param_functions.py:1657` (`Form`), `:1972` (`File`),
   `fastapi/security/api_key.py:186`. Hoisting those to a module constant would
   destroy the docs they exist to render. After the guard the corpus yields 0
   findings, and the only non-annotation repeats that survive every other filter
   are three prose strings the *structured* filter already rejects
   (`pydantic/main.py:786`, `rich/progress.py:148`, `sqlmodel/_compat.py:139`).

Each occurrence after the first gets its own diagnostic, so a deliberate
duplicate can be suppressed per-line with `# sarj-noqa: SARJ024 — <reason>`.

Skipped entirely: `conftest.py`, test files (`test_*.py` or under a `tests/`
directory) — fixtures legitimately repeat literal payloads.
* **generated files** (`_paths.is_generated_source`). Their layout is the
  generator's, and re-running the generator discards any edit, so a finding
  there can never be acted on in place. Measured on the 69 `DO NOT EDIT`
  files git-tracked across bulbul and noura-be — Speakeasy's
  `python/sdk/src/sarj_platform_sdk/` accounts for all of them.
"""

from __future__ import annotations

import ast
from collections import defaultdict
import re
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none
from sarj_python_lint.rules._paths import is_generated_source


if TYPE_CHECKING:
    from pathlib import Path


_MIN_LENGTH = 40
_MIN_DISTINCT_SCOPES = 2
_PREVIEW_LENGTH = 40

_SCAFFOLDING_KWARGS = frozenset({"examples", "description", "title", "summary"})

_SQL_KEYWORD_RE = re.compile(
    r"\b(SELECT|INSERT|UPDATE|DELETE|FROM|WHERE|JOIN|VALUES|ON CONFLICT|RETURNING|GROUP BY|ORDER BY)\b"
)
_IDENTIFIER_RE = re.compile(r"^[a-z_][a-z0-9_.]*$")

_MODULE_SCOPE = -1


class NoRepeatedStringLiteral(Rule):
    """A structured string literal repeated across functions must become a named constant."""

    id: str = "no-repeated-string-literal"
    code: str = "SARJ024"
    description: str = "Structured string literal repeated across functions — extract a module-level constant."

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if is_generated_source(source):
            return []
        if _is_skipped_path(path):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []

        occurrences: dict[str, list[ast.Constant]] = defaultdict(list)
        scope_of: dict[int, int] = {}
        excluded: set[int] = set()

        def visit(node: ast.AST, scope: int) -> None:
            for annotation in _annotation_exprs(node):
                excluded.update(id(child) for child in ast.walk(annotation) if isinstance(child, ast.Constant))
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                body = node.body
                if (
                    body
                    and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)
                ):
                    excluded.add(id(body[0].value))
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    scope = id(node)
            elif isinstance(node, ast.JoinedStr):
                excluded.update(id(value) for value in node.values)
            elif isinstance(node, ast.Call):
                for kw in node.keywords:
                    if kw.arg in _SCAFFOLDING_KWARGS:
                        excluded.update(id(child) for child in ast.walk(kw.value) if isinstance(child, ast.Constant))
            elif (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and len(node.value) >= _MIN_LENGTH
                and id(node) not in excluded
                and _is_structured(node.value)
            ):
                occurrences[node.value].append(node)
                scope_of[id(node)] = scope
            for child in ast.iter_child_nodes(node):
                visit(child, scope)

        visit(tree, _MODULE_SCOPE)

        diags: list[Diagnostic] = []
        for value, nodes in occurrences.items():
            function_scopes = {scope for n in nodes if (scope := scope_of.get(id(n), _MODULE_SCOPE)) != _MODULE_SCOPE}
            if len(function_scopes) < _MIN_DISTINCT_SCOPES:
                continue
            nodes.sort(key=lambda n: (n.lineno, n.col_offset))
            first, *repeats = nodes
            diags.extend(
                Diagnostic(
                    path=path,
                    line=node.lineno,
                    col=node.col_offset + 1,
                    code=self.code,
                    message=(
                        f"structured string literal {_preview(value)} is repeated across "
                        f"functions (first use at line {first.lineno}) — extract a "
                        f"module-level constant so the copies cannot drift."
                    ),
                )
                for node in repeats
            )
        diags.sort(key=lambda d: (d.line, d.col))
        return diags


def _annotation_exprs(node: ast.AST) -> list[ast.expr]:
    """Find the sub-expressions of `node` that are type annotations, not runtime values.

    Covers parameter annotations, return annotations, `x: T = ...` annotations,
    and any `Annotated[...]` subscript wherever it appears (including a type
    alias assigned at module level).

    Returns:
        The annotation expressions owned by `node`, empty when it owns none.

    """
    if isinstance(node, ast.arg):
        return [node.annotation] if node.annotation is not None else []
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return [node.returns] if node.returns is not None else []
    if isinstance(node, ast.AnnAssign):
        return [node.annotation]
    if isinstance(node, ast.Subscript) and _is_annotated(node.value):
        return [node.slice]
    return []


def _is_annotated(expr: ast.expr) -> bool:
    if isinstance(expr, ast.Name):
        return expr.id == "Annotated"
    return isinstance(expr, ast.Attribute) and expr.attr == "Annotated"


def _is_structured(value: str) -> bool:
    return "\n" in value or _SQL_KEYWORD_RE.search(value) is not None or _IDENTIFIER_RE.match(value) is not None


def _preview(value: str) -> str:
    if len(value) <= _PREVIEW_LENGTH:
        return repr(value)
    return repr(value[:_PREVIEW_LENGTH] + "…")


def _is_skipped_path(path: Path) -> bool:
    if path.name == "conftest.py":
        return True
    if path.name.startswith("test_"):
        return True
    return "tests" in path.parts
