"""SARJ109: `gen_random_uuid()` in a migration — use `uuidv7()`.

`gen_random_uuid()` returns a UUIDv4: 122 random bits, no time component. As a
primary-key default that is the worst insert pattern a B-tree can be given —
every row lands in a random leaf page, so the index's hot write set is the
entire index rather than its right edge. While the index fits in shared buffers
this is invisible; once it does not, every insert pays a random read, and the
table that was fine at 10M rows is not fine at 100M. WAL amplifies it further:
scattered leaf writes mean full-page images for pages that would otherwise have
been dirtied once.

UUIDv7 keeps the same 128-bit shape and the same unguessability for practical
purposes, but puts a millisecond timestamp in the high bits: inserts append,
recently-written rows share pages, and `WHERE id > <recent>` becomes a range
scan. Postgres 18 ships `uuidv7()` in core, so no extension is needed.

Fires on any `gen_random_uuid(` in migration SQL, scanned against `mask_sql`
output so an occurrence inside a `--` comment, a `/* */` block, a quoted value
or a dollar-quoted body never matches.

This is the `.sql` half of a policy the stack states in two other places:
`ruff.strict.toml` bans `uuid.uuid4` in favour of `uuid.uuid7()`, and
`sarj-python-lint`'s SARJ053 `no-gen-random-uuid-in-sql` catches the same call
in SQL embedded in Python string literals.

Historical migrations are already applied and cannot be rewritten; pre-commit
only lints the files a commit touches, so the rule reaches new and edited
migrations rather than the archive. A deliberate v4 default (reproducing a
legacy column in a repair migration) is suppressed with
`-- sarj-noqa: SARJ109 — <reason>` on the offending line.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, final, override

from sarj_sql_lint.rule_base import Diagnostic, Rule, mask_sql


if TYPE_CHECKING:
    from pathlib import Path


PATTERN = re.compile(r"\bgen_random_uuid\s*\(", re.IGNORECASE)

_MESSAGE = (
    "`gen_random_uuid()` generates a random UUIDv4 — use `uuidv7()` (Postgres 18). "
    "Random keys scatter inserts across every B-tree leaf page; UUIDv7 is "
    "time-ordered, so inserts append to the index's right edge."
)


@final
class PreferUuidv7Default(Rule):
    """`gen_random_uuid()` default — use the time-ordered `uuidv7()`."""

    id = "prefer-uuidv7-default"
    code = "SARJ109"
    description = "`gen_random_uuid()` emits a random UUIDv4 — use `uuidv7()` so keys are time-ordered."

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        """Report every `gen_random_uuid(` call in real (unmasked) SQL.

        Returns:
            The diagnostics, in source order.

        """
        return [
            Diagnostic(
                path=path,
                line=lineno,
                col=match.start() + 1,
                code=self.code,
                message=_MESSAGE,
            )
            for lineno, line in enumerate(mask_sql(source).splitlines(), start=1)
            for match in PATTERN.finditer(line)
        ]
