"""SARJ086: an `Args:` block that only re-spells the parameter list.

    def delete(self, key: str) -> None:
        \"\"\"Drop the entry, and the tombstone the compactor would have read.

        Args:                                  <- everything below is ceremony
            key: The key of the value to delete
        \"\"\"

The summary earns its place — "the tombstone the compactor would have read" is
not readable off the signature. The `Args:` block does not: every content word
of every entry is already in the parameter's own name, its annotation, or the
function name. It is a table of contents for a list of one. (That entry is real:
`celery/celery/backends/azureblockblob.py:154`.)

**The fix is to delete the `Args:` section only**, leaving the summary. That is
safe, and it was checked against the shipped strict config rather than assumed:
ruff's D417 (`undocumented-param`) does **not** fire on a Google-style docstring
with no parameter section at all, so removing the block does not trade one
finding for another. It is also the whole reason this rule exists and the
sibling `Returns:` shape does not — deleting a `Returns:` section makes DOC201
fire, so the only compliant remedy there is deleting a docstring whose summary
may be the valuable part.

**Why SARJ050 cannot reach this.** SARJ050 tests every content word of the
docstring against the signature stems. The literal header word "args" is a
content word and no signature contains it, so the mere presence of an `Args:`
block makes a docstring permanently unflaggable by that rule, whatever the block
says. Across the first-party corpus **126** functions carry a parsed `Args:`
block; SARJ050 flags **0** of them.

**Never flagged**

- **One informative entry protects the whole block.** The test is over every
  entry: a block where three entries restate and the fourth carries a default, a
  unit, an example value or a constraint stays whole. Splitting a parameter
  table is worse than leaving it. Relaxing this to "any entry restates" raises
  the first-party count from 12 to 16 and immediately admits entries documenting
  defaults.
- **An entry with no description at all** — the bare `name (type):` stub. Every
  one of the 8 first-party instances came from an OpenAPI client generator whose
  output carries no generated-code marker, so `is_generated_source` cannot see
  it; judging a machine-emitted stub tells the author to edit a file that will
  be regenerated. Dropping them is what takes the raw 20 findings to 12.
- **An empty block, or one no entry parses out of.** Nothing to judge.
- **Prompt / CLI / route decorators.** For an agent tool the `Args:` block is
  part of the description shipped to the model; for click/typer it is the
  argument help text — the same hard exemption SARJ050 makes.
- **The protected class and the value markers**, evaluated over the block, so a
  parameter documented with a unit, a status code, an RFC, a ticket or a causal
  clause keeps its whole table.
- **NumPy-style parameter blocks** (`Parameters` under a `-----` underline).
  `_docstrings` parses Google style only; the first-party corpus holds 2 NumPy
  docstrings in total, which is not enough evidence to tune a second parser.

**What counts as "already in the signature".** The function's own name and its
owning class contribute stems, not just the parameter's. An entry reading
`token: JWT access token to verify` on a `JwtService.verify_access_token(token: str)`
shape is a restatement, because "JWT" is on the class the caller types. That is also the
loosest the test gets: of the 12 first-party findings, exactly one turned on a
word supplied by the function name rather than the parameter, and it was judged
borderline-true rather than false.

**Measured.** 20 raw findings across 2,440 reviewable first-party files, 8 of
them generator output that the empty-description guard removes, leaving **12**.
All 12 were read: **12 true positives, 0 false** (1 borderline, above). The
dominant shape is an ID parameter documented as its own name in title case.

Over 14 OSS repos the predicate finds **864** (langchain 257, mlflow 256,
dagster 137, litellm 107, prefect 87, celery 8, superset 8, airflow 4, and 0 in
django, fastapi, saleor, sentry-python, warehouse, zulip). 20 were sampled
across celery, superset and airflow and read: **20 true positives, 0 false**,
including `celery/celery/app/task.py:1030` ("sig (Signature): signature to
replace with."), `celery/celery/backends/cosmosdbsql.py:206`,
`superset/superset/utils/jinja_template_validator.py:38` ("template_str: The
template string to validate") and
`airflow/providers/openlineage/src/airflow/providers/openlineage/utils/spark.py:131`
("properties: Spark properties.").

Suppress an intentional case with `# sarj-noqa: SARJ086 — <reason>`.
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none
from sarj_python_lint.rules._ast_index import children
from sarj_python_lint.rules._comments import is_protected
from sarj_python_lint.rules._docstrings import (
    PROMPT_DECORATOR_MARKERS,
    VALUE_MARKER_RE,
    arg_entries,
    arg_section,
    decorator_markers,
    identifier_stems,
    restates,
    signature_stems,
)
from sarj_python_lint.rules._paths import is_generated_source


if TYPE_CHECKING:
    from pathlib import Path


class DocstringArgsRestateSignature(Rule):
    """An `Args:` block whose every entry only re-spells its own parameter."""

    id: str = "docstring-args-restate-signature"
    code: str = "SARJ086"
    description: str = (
        "`Args:` block adds nothing the signature does not already say — delete "
        "the section and keep the summary."
    )

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if is_generated_source(source):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        diags: list[Diagnostic] = []
        self._walk(tree, None, path, diags)
        return sorted(diags, key=lambda d: d.line)

    def _walk(self, node: ast.AST, class_name: str | None, path: Path, diags: list[Diagnostic]) -> None:
        for child in children(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._check_function(child, class_name, path, diags)
                self._walk(child, class_name, path, diags)
            elif isinstance(child, ast.ClassDef):
                self._walk(child, child.name, path, diags)
            else:
                self._walk(child, class_name, path, diags)

    def _check_function(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        class_name: str | None,
        path: Path,
        diags: list[Diagnostic],
    ) -> None:
        docstring = ast.get_docstring(node, clean=True)
        if not docstring:
            return
        block = arg_section(docstring)
        if block is None or VALUE_MARKER_RE.search(block) or is_protected(block):
            return
        if decorator_markers(node) & PROMPT_DECORATOR_MARKERS:
            return
        entries = arg_entries(block)
        if not entries:
            return
        known = signature_stems(node, class_name)
        for name, annotation, description in entries:
            if not description:
                return  # a machine-emitted `name (type):` stub — see the module docstring
            if not restates(description, known | identifier_stems(name) | identifier_stems(annotation)):
                return
        expr = node.body[0]
        diags.append(
            Diagnostic(
                path=path,
                line=expr.lineno,
                col=expr.col_offset + 1,
                code=self.code,
                message=self.description,
            )
        )
