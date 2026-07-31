"""SARJ107: forbid `OFFSET` pagination — use cursor-based pagination.

`LIMIT/OFFSET` scans and discards every skipped row, so page N costs O(N)
and deep pages time out as tables grow; rows also shift between pages when
data changes underneath. Use keyset/cursor pagination instead:
`WHERE id > :cursor ORDER BY id LIMIT n`.

The rule flags an `OFFSET` keyword **immediately followed by a value/param
token** (`%s`, `%(name)s`, `?`, `?1`, `:name`, `@name`, `$1`, or a digit) — the
real pagination construct. Comments and string bodies are masked first, so a
`-- offset` note or an `'OFFSET 5'` value is never mistaken for the keyword.

CONVERGED WITH SARJ025 AND THE TS TWIN (2026-07). The concept is implemented
three times — here, in `packages/python/src/sarj_python_lint/rules/
no_offset_pagination.py` (SARJ025, for SQL embedded in Python store modules) and
in `packages/typescript/src/rules/no-offset-pagination.ts`. Both of those have
always required the following value token, and both documented why. This rule was
a bare word-boundary `OFFSET` match, i.e. the same keyword judged by a weaker
test — so identical SQL was clean in `.py` and a finding in `.sql`. Requiring the
value token excludes three shapes that are not pagination at all:

  - a column literally named `offset` — `ALTER TABLE t ADD COLUMN offset INTEGER
    NOT NULL DEFAULT 0`, or the same in a `CREATE TABLE`. This is the shape that
    made the divergence worth fixing: a migration adding an `offset` column was
    told to "use cursor pagination".
  - BigQuery's `UNNEST(...) WITH OFFSET AS col`, which is array indexing.
  - the English word in any surviving text.

A word-boundary keyword match already tolerated `offset_min`-style identifiers
(`_` is a word character), which is why the corpus never caught this: over the
239 `.sql` files of two first-party repos the rule yields **0 findings both
before and after**, and the only file containing the token — a timezone-
conversion migration — uses it solely as the identifier `offset_min` and inside
comments. So this change
is pure false-positive prevention with no true positive lost — verified by
re-running the sweep, not assumed.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, final, override

from sarj_sql_lint.rule_base import Diagnostic, Rule, mask_sql


if TYPE_CHECKING:
    from pathlib import Path


# `OFFSET` followed by a value/param token — the real pagination construct.
# The parameter alternatives are the UNION of every marker the three packages
# see, and are kept identical in SARJ025 and the TS twin.
PATTERN = re.compile(
    r"\bOFFSET\s+(?:%s|%\(\w+\)s|\?\d*|:\w+|@\w+|\$\d+|\d+)",
    re.IGNORECASE,
)


@final
class NoLimitOffset(Rule):
    """OFFSET pagination — use cursor pagination instead."""

    id = "no-limit-offset"
    code = "SARJ107"
    description = "OFFSET pagination — use cursor pagination (WHERE id > :cursor)."

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        diags: list[Diagnostic] = []
        for lineno, line in enumerate(mask_sql(source).splitlines(), start=1):
            diags.extend(
                Diagnostic(
                    path=path,
                    line=lineno,
                    col=match.start() + 1,
                    code=self.code,
                    message=(
                        "Use cursor pagination (WHERE id > :cursor ORDER BY id "
                        "LIMIT n) — OFFSET scans and discards every skipped row."
                    ),
                )
                for match in PATTERN.finditer(line)
            )
        return diags
