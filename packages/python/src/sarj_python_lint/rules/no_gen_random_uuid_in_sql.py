"""SARJ053: `gen_random_uuid()` in SQL embedded in Python — use `uuidv7()`.

`gen_random_uuid()` returns a UUIDv4: 122 random bits with no time component.
As a primary-key default that is the worst possible insert pattern for a B-tree
— every row lands in a random leaf page, so the index's write set is the whole
index rather than its right edge, and a table that no longer fits in shared
buffers pays a random read per insert. UUIDv7 puts a millisecond timestamp in
the high bits, so inserts append, recent rows cluster on the same pages, and
range scans over "recent" become sequential. Postgres 18 ships `uuidv7()` in
core.

This is the embedded-SQL half of a policy the stack already states in two other
places: `ruff.strict.toml` bans `uuid.uuid4` ("use `uuid.uuid7()` — time-ordered,
aligns with the DB `uuidv7()` default"), and `sarj-sql-lint`'s SARJ109
`prefer-uuidv7-default` enforces it in `.sql` migration files. Neither can see
SQL that lives inside a Python string, which is where `CREATE TABLE` statements
in test fixtures, ad-hoc DDL and store-layer `INSERT`s actually sit.

Fires when a Python string literal both:

* contains `gen_random_uuid(` outside a SQL comment or a quoted SQL value
  (checked against `_sql.strip_sql_noise`-masked text, so a `--` remark or a
  literal `'gen_random_uuid()'` value never counts), and
* looks like SQL at all — it must also contain one of the structural keywords
  `CREATE` / `ALTER` / `INSERT` / `UPDATE` / `SELECT` / `DEFAULT` / `VALUES`.

That second condition is what keeps prose out: a docstring, a comment string or
an error message that merely *names* the function is not a SQL statement, and
this rule is about the DDL, not the word.

Generated files are exempt — they mirror whatever their generator emits.

A deliberate use (reproducing a legacy default in a data-migration test,
asserting on an existing column's `pg_get_expr`) is suppressed with
`# sarj-noqa: SARJ053 — <reason>`.
"""

from __future__ import annotations

import ast
import re
from typing import TYPE_CHECKING, final, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none
from sarj_python_lint.rules._paths import is_generated_source
from sarj_python_lint.rules._sql import strip_sql_noise


if TYPE_CHECKING:
    from pathlib import Path


_GEN_RANDOM_UUID_RE = re.compile(r"\bgen_random_uuid\s*\(", re.IGNORECASE)

# A string only counts as SQL when it carries a structural keyword. Without this
# the rule fires on prose that names the function — including this module's own
# docstring.
_SQL_SHAPE_RE = re.compile(
    r"\b(?:CREATE|ALTER|INSERT|UPDATE|SELECT|DEFAULT|VALUES)\b",
    re.IGNORECASE,
)

_MESSAGE = (
    "`gen_random_uuid()` generates a random UUIDv4 — use `uuidv7()` (Postgres 18) "
    "so keys are time-ordered and inserts append to the index's right edge "
    "instead of scattering across every leaf page."
)


@final
class NoGenRandomUuidInSql(Rule):
    """`gen_random_uuid()` in embedded SQL — use the time-ordered `uuidv7()`."""

    id: str = "no-gen-random-uuid-in-sql"
    code: str = "SARJ053"
    description: str = (
        "`gen_random_uuid()` in SQL embedded in Python emits a random UUIDv4 — "
        "use `uuidv7()` so primary keys are time-ordered."
    )

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        """Report every embedded SQL literal defaulting to `gen_random_uuid()`.

        Returns:
            The diagnostics, sorted by (line, col).

        """
        if is_generated_source(source):
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
                message=_MESSAGE,
            )
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and _is_offending_sql(node.value)
        ]
        diags.sort(key=lambda d: (d.line, d.col))
        return diags


def _is_offending_sql(value: str) -> bool:
    """Report whether a string literal is SQL that calls `gen_random_uuid()`.

    Returns:
        True when the masked text is SQL-shaped and names the function outside a
        comment or quoted value.

    """
    masked = strip_sql_noise(value)
    return bool(_GEN_RANDOM_UUID_RE.search(masked) and _SQL_SHAPE_RE.search(masked))
