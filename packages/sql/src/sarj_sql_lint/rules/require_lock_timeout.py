r"""SARJ110: Require lock_timeout or statement_timeout before migration DDL.

DDL operations like ALTER TABLE or CREATE INDEX can hang waiting for heavy lock
acquisitions, blocking production queries. Migrations with DDL must set a positive lock_timeout
or statement_timeout prior to executing each DDL block.

Three corrections from a 25-finding seeded sample of the 4,537 findings this rule
produced over 2,133 deduped `.sql` files (TP 4 / FP 8 / duplicate-of-an-earlier-
finding-in-the-same-file 13 — 32% outright wrong, 52% redundant).

**The canonical spelling was invisible to the parser.** `ASSIGNMENT_PATTERN` read
`SET\s+(?:LOCAL|SESSION)?\s+`, with the second `\s+` mandatory. When the
optional group matched empty, that demanded *two* runs of whitespace after `SET`,
so the single-space form — which is how essentially everyone writes it — could not
match::

    SET LOCAL lock_timeout = '3s';    matched
    SET  lock_timeout = '3s';         matched (two spaces, by accident)
    SET lock_timeout = '3s';          DID NOT MATCH
    SET statement_timeout = '5s';     DID NOT MATCH
    SET lock_timeout TO '3s';         DID NOT MATCH
    SET lock_timeout='3s';            DID NOT MATCH

Every one of those is a migration that already complies, told it does not: 43
findings across 10 first-party files, 100% wrong. The optional keyword now carries
its own trailing whitespace (`(?:(?:LOCAL|SESSION)\s+)?`) so the single-space form
parses. This only starts recognising valid syntax, so it costs no recall. All six
spellings above are pinned as tests.

**The predicate is a property of the file, not of the statement.** "A positive
lock_timeout is in effect here" is session state. One `SET lock_timeout` at the
top of a migration silences every DDL statement in it at once, so the 2nd..nth
unprotected DDL under the *same* state is not a second defect — it is the same
defect counted again, and it was 13 of the 25 sampled findings. The rule now
reports once per contiguous run of DDL sharing one timeout state, re-arming
whenever an assignment or a `COMMIT`/`ROLLBACK` changes that state (so a migration
that protects its first half and forgets after the `COMMIT` is still told about the
second half). SARJ102 and SARJ108 are *correctly* per-statement and are
deliberately left that way — each `CREATE INDEX` needs its own `CONCURRENTLY`.

**`SET lock_timeout` does not exist in MySQL or SQLite** — 1,161 of 4,537 findings
(25.5%) were against non-Postgres migrations, where the advice is unfollowable.
See `is_postgres`; the marker and Postgres-only token populations are disjoint
across the corpus, so the guard costs no Postgres recall.

**Independently re-measured, 2026-07-31.** The three corrections above were
originally measured on a corpus with almost no SQL in it, which made the whole
44.5% SQL cut of #183 the least-evidenced change in that PR. Re-run over
**1,792 content-unique `.sql` files** sourced from cal.com, unkey, documenso,
formbricks, midday, papermark, openstatus, litellm, prefect, typeorm and
airflow, this rule goes **3,791 -> 1,045 (-72.4%)** and stays ALIVE: 1,040 of
the 1,156 files that reported before still report, and the maximum per file
falls from 76 to 4. 116 files clear entirely. Sampled removals read as the three
documented classes — subsequent DDL under one already-set timeout
(`cal.com/packages/prisma/migrations/20220628190334_adds_missing_oncascades/
migration.sql:11`, `documenso/.../20260604143030_add_email_transports/
migration.sql:8`) and ClickHouse/MySQL migrations where `SET lock_timeout` does
not exist (`unkey/pkg/clickhouse/migrations/20260429000000.sql:19`).
"""

from __future__ import annotations

import operator
import re
from typing import TYPE_CHECKING, final, override

from sarj_sql_lint.rule_base import Diagnostic, Rule, is_dump_file, is_postgres, mask_sql


if TYPE_CHECKING:
    from pathlib import Path


DDL_PATTERN = re.compile(r"\b(ALTER\s+TABLE|CREATE\s+(?:UNIQUE\s+)?INDEX|DROP\s+TABLE)\b", re.IGNORECASE)
TX_END_PATTERN = re.compile(r"\b(COMMIT|ROLLBACK)\b", re.IGNORECASE)

# `(?:(?:LOCAL|SESSION)\s+)?` — the optional keyword owns the whitespace that
# follows it. Writing the space outside the group (the previous spelling) makes it
# mandatory even when the group matches empty, which is what hid `SET lock_timeout
# = '3s'` from the rule entirely. `\b` after the variable name keeps
# `lock_timeout_ms` from matching as `lock_timeout`.
ASSIGNMENT_PATTERN = re.compile(
    r"\b(?:SET\s+(?:(?:LOCAL|SESSION)\s+)?|RESET\s+)(lock_timeout|statement_timeout)\b(?:\s*(?:=|\bTO\b)\s*('[\s\S]*?'|\"[^\"]*\"|[^\s;]+))?|set_config\s*\(\s*'?(lock_timeout|statement_timeout)'?\s*,\s*('[\s\S]*?'|\"[^\"]*\"|[^\s,;]+)",
    re.IGNORECASE,
)
POSITIVE_VAL_PATTERN = re.compile(
    r"^['\"]?\s*(?:[0-9]*\.?[0-9]+\s*(?:[a-zA-Z]+\s*)?|[1-9]\d*)\s*['\"]?$", re.IGNORECASE
)


@final
class RequireLockTimeout(Rule):
    """DDL migration missing statement or lock timeout setting prior to DDL."""

    id = "require-lock-timeout"
    code = "SARJ110"
    description = "DDL migration missing positive SET [LOCAL] lock_timeout or statement_timeout prior to DDL."

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if is_dump_file(source, path):
            return []

        diags: list[Diagnostic] = []
        masked = mask_sql(source)
        if not is_postgres(source):
            return []

        events: list[tuple[int, str, re.Match[str]]] = []
        for match in ASSIGNMENT_PATTERN.finditer(source):
            start_pos = match.start()
            if masked[start_pos : start_pos + 3].strip():
                events.append((start_pos, "ASSIGNMENT", match))
        events.extend((match.start(), "TX_END", match) for match in TX_END_PATTERN.finditer(masked))
        events.extend((match.start(), "DDL", match) for match in DDL_PATTERN.finditer(masked))

        events.sort(key=operator.itemgetter(0))

        active_global_timeouts: dict[str, bool] = {"lock_timeout": False, "statement_timeout": False}
        active_local_timeouts: dict[str, bool] = {"lock_timeout": False, "statement_timeout": False}
        # One diagnostic per contiguous run of DDL under one timeout state. Any
        # event that can change that state re-arms the report, so a migration
        # that sets a timeout, commits (dropping the LOCAL setting) and then runs
        # more DDL is still told about the unprotected tail.
        reported_for_current_state = False

        for pos, event_type, match in events:
            if event_type != "DDL":
                reported_for_current_state = False
            if event_type == "ASSIGNMENT":
                cmd = match.group(0).upper()
                is_local = "LOCAL" in cmd
                target_var = (match.group(1) or match.group(3) or "").lower()
                val = (match.group(2) or match.group(4) or "").strip().strip(";")

                is_active = (
                    False
                    if "RESET" in cmd
                    else (
                        bool(val)
                        and POSITIVE_VAL_PATTERN.match(val) is not None
                        and val not in {"0", "'0'", "'0s'", "'0ms'"}
                    )
                )

                if is_local:
                    active_local_timeouts[target_var] = is_active
                else:
                    active_global_timeouts[target_var] = is_active
            elif event_type == "TX_END":
                active_local_timeouts = {"lock_timeout": False, "statement_timeout": False}
            elif event_type == "DDL":
                has_timeout = any(active_global_timeouts.values()) or any(active_local_timeouts.values())
                if not has_timeout and not reported_for_current_state:
                    reported_for_current_state = True
                    lineno = masked[:pos].count("\n") + 1
                    diags.append(
                        Diagnostic(
                            path=path,
                            line=lineno,
                            col=1,
                            code=self.code,
                            message=(
                                "Migration containing DDL (`ALTER TABLE`/`CREATE INDEX`) must set "
                                "a positive `SET [LOCAL] lock_timeout = ...` or `statement_timeout = ...` prior to DDL statements."
                            ),
                        )
                    )

        return diags
