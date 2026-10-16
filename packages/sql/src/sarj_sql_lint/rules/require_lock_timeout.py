from __future__ import annotations

from bisect import bisect_right
from functools import lru_cache
from itertools import starmap
import math
import operator
from pathlib import PurePosixPath
import re
from typing import TYPE_CHECKING, Final, NamedTuple, final, override

from sqlglot import exp
from sqlglot.errors import SqlglotError

from sarj_sql_lint._postgres import parse_postgres
from sarj_sql_lint.rule_base import (
    AutofixPolicy,
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    Rule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
    dbmate_section_boundaries,
    dbmate_transactional,
    dollar_quoted_lines,
    is_dump_file,
    is_postgres_migration,
    mask_sql,
    mask_sql_comments,
    source_location,
)


if TYPE_CHECKING:
    from pathlib import Path


class _SectionBoundaryEvent(NamedTuple):
    offset: int
    kind: str
    match: re.Match[str]


DDL_PATTERN = re.compile(
    r"\b(ALTER\s+(?:TABLE|TYPE)|CREATE\s+(?:UNIQUE\s+)?INDEX|DROP\s+(?:INDEX|TABLE)|REINDEX(?:\s+(?:DATABASE|INDEX|SCHEMA|SYSTEM|TABLE))?|TRUNCATE(?:\s+TABLE)?|REFRESH\s+MATERIALIZED\s+VIEW)\b",
    re.IGNORECASE,
)
TX_END_PATTERN = re.compile(r"\b(COMMIT|ROLLBACK)\b", re.IGNORECASE)
RESET_ALL_PATTERN = re.compile(r"\bRESET\s+ALL\b", re.IGNORECASE)
_CREATE_TABLE_PATTERN = re.compile(
    r"\bCREATE\s+(?:(?:GLOBAL|LOCAL)\s+)?(?:(?:TEMP(?:ORARY)?|UNLOGGED)\s+)?TABLE\b", re.IGNORECASE
)
SECTION_BOUNDARY_PATTERN = re.compile(
    r"^\s*--\s*\+goose\s+down\s*$",
    re.IGNORECASE | re.MULTILINE,
)

# Match SET/RESET/set_config assignments for lock_timeout or statement_timeout.
ASSIGNMENT_PATTERN = re.compile(
    r"\b(?:SET\s+(?:(?:LOCAL|SESSION)\s+)?|RESET\s+)((?:lock_timeout|statement_timeout)\b|\"(?:lock_timeout|statement_timeout)\")(?:\s*(?:=|\bTO\b)\s*('[\s\S]*?'|\"[^\"]*\"|[^\s;]+))?|set_config\s*\(\s*'?(lock_timeout|statement_timeout)'?\s*,\s*('[\s\S]*?'|\"[^\"]*\"|[^\s,;]+)\s*,\s*(true|false)\s*\)",
    re.IGNORECASE,
)
POSITIVE_VAL_PATTERN = re.compile(
    r"^['\"]?\s*(?P<number>[+-]?(?:0[xX][0-9a-fA-F]+|(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?))\s*(?P<unit>us|ms|s|min|h|d)?\s*['\"]?$"
)
# PostgreSQL converts to milliseconds, rounds to the next smaller time unit,
# then rounds to the integer setting. Zero disables both timeout parameters.
# https://www.postgresql.org/docs/current/config-setting.html
_TIMEOUT_UNITS: Final[dict[str, tuple[float, float | None]]] = {
    "": (1, None),
    "us": (0.001, None),
    "ms": (1, 0.001),
    "s": (1_000, 1),
    "min": (60_000, 1_000),
    "h": (3_600_000, 60_000),
    "d": (86_400_000, 3_600_000),
}
_MAXIMUM_TIMEOUT = 2_147_483_647


@final
class RequireLockTimeout(Rule):
    id = "require-lock-timeout"
    code = "SARJ110"
    documentation = RuleDocumentation(
        summary="DDL migration missing positive SET [LOCAL] lock_timeout or statement_timeout prior to DDL.",
        rationale="Unbounded lock waits can stall production traffic indefinitely when migration DDL contends with active transactions.",
        remediation="Set a short positive lock_timeout or statement_timeout before the DDL statement.",
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only PostgreSQL migration paths and explicitly marked PostgreSQL migrations are checked.",
            "Materialized-view refreshes and parseable CREATE TABLE LIKE statements touch existing relations. Fresh CREATE TABLE definitions and LIKE comparisons do not establish this additional lock requirement.",
            "Literal session/local settings, RESET and RESET ALL are tracked, including intervening comments and case-insensitive parameter names. Defaults, rollback of session SET, savepoints and procedural configuration effects are not resolved.",
            "Literal timeout values must remain positive after PostgreSQL's unit conversion and integer rounding; submillisecond values that round to zero do not bound a lock wait.",
        ),
        examples=(
            RuleExample(
                example_id="unbounded-ddl-lock-wait",
                title="DDL without a positive timeout",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.sql("supabase/migrations/001_users.sql", "ALTER TABLE users ADD COLUMN note TEXT;\n"),
                ),
                focus_path=PurePosixPath("supabase/migrations/001_users.sql"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="bounded-ddl-lock-wait",
                title="DDL preceded by a positive lock timeout",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.sql(
                        "supabase/migrations/001_users.sql",
                        "SET lock_timeout = '3s';\nALTER TABLE users ADD COLUMN note TEXT;\n",
                    ),
                ),
                focus_path=PurePosixPath("supabase/migrations/001_users.sql"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="timeout-rounded-to-disabled",
                scenario="timeout-rounding",
                title="A fractional timeout can round to zero",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.sql(
                        "supabase/migrations/001_users.sql",
                        "SET lock_timeout = '0.1ms';\nALTER TABLE users ADD COLUMN note TEXT;\n",
                    ),
                ),
                focus_path=PurePosixPath("supabase/migrations/001_users.sql"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="fractional-timeout-remains-positive",
                scenario="timeout-rounding",
                title="A fractional timeout that remains enabled",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.sql(
                        "supabase/migrations/001_users.sql",
                        "SET lock_timeout = '0.6ms';\nALTER TABLE users ADD COLUMN note TEXT;\n",
                    ),
                ),
                focus_path=PurePosixPath("supabase/migrations/001_users.sql"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if is_dump_file(source, path) or not is_postgres_migration(path, source):
            return []

        diags: list[Diagnostic] = []
        masked = mask_sql(source, mask_dollar_literals=True)

        events = _timeout_events(source, masked)

        active_global_timeouts: dict[str, bool] = {"lock_timeout": False, "statement_timeout": False}
        active_local_timeouts: dict[str, bool] = {}
        # Report once per contiguous run of DDL under one timeout state, re-arming on state-changing events.
        reported_for_current_state = False

        for pos, event_type, match in events:
            nontransactional = dbmate_transactional(source, pos) is False
            if event_type != "DDL":
                reported_for_current_state = False
            if event_type == "ASSIGNMENT":
                _apply_timeout_assignment(
                    match, active_local_timeouts, active_global_timeouts, nontransactional=nontransactional
                )
            elif event_type == "TX_END":
                active_local_timeouts.clear()
            elif event_type in {"SECTION_BOUNDARY", "RESET_ALL"}:
                # A new runner invocation or RESET ALL removes prior explicit protection.
                active_global_timeouts = {"lock_timeout": False, "statement_timeout": False}
                active_local_timeouts.clear()
            elif event_type == "DDL":
                has_timeout = any(starmap(active_local_timeouts.get, active_global_timeouts.items()))
                if not has_timeout and not reported_for_current_state:
                    reported_for_current_state = True
                    lineno = source_location(source, pos).line
                    diags.append(
                        Diagnostic(
                            path=path,
                            line=lineno,
                            col=1,
                            code=self.code,
                            message=(
                                "A nontransactional migration containing DDL must set a positive session "
                                "`SET lock_timeout = ...` or `statement_timeout = ...` before DDL and `RESET` it afterward; "
                                "`SET LOCAL` has no effective transaction scope here."
                                if nontransactional
                                else "Migration containing DDL (`ALTER TABLE`/`CREATE INDEX`) must set a positive `SET [LOCAL] lock_timeout = ...` or `statement_timeout = ...` prior to DDL statements."
                            ),
                        )
                    )

        return diags


def _timeout_events(source: str, masked: str) -> list[tuple[int, str, re.Match[str]]]:
    events: list[tuple[int, str, re.Match[str]]] = []
    # Match raw quoted values, then require the assignment's offset to remain live after masking SQL noise.
    for match in ASSIGNMENT_PATTERN.finditer(mask_sql_comments(source)):
        start_pos = match.start()
        if masked[start_pos : start_pos + 3].strip():
            events.append((start_pos, "ASSIGNMENT", match))
    events.extend((match.start(), "TX_END", match) for match in TX_END_PATTERN.finditer(masked))
    events.extend((match.start(), "RESET_ALL", match) for match in RESET_ALL_PATTERN.finditer(masked))
    events.extend(_section_boundary_events(source))
    events.extend((match.start(), "DDL", match) for match in DDL_PATTERN.finditer(masked))
    events.extend(_create_table_like_events(source, masked))

    events.sort(key=operator.itemgetter(0))

    return events


@lru_cache(maxsize=8)
def _create_table_like_events(source: str, masked: str) -> tuple[tuple[int, str, re.Match[str]], ...]:
    if "LIKE" not in masked.upper():
        return ()
    candidates = tuple(_CREATE_TABLE_PATTERN.finditer(masked))
    if not candidates:
        return ()
    try:
        statements = parse_postgres(source)
    except SqlglotError, RecursionError:
        return ()
    starts = tuple(match.start() for match in candidates)
    events: list[tuple[int, str, re.Match[str]]] = []
    for statement in statements:
        position = _like_target_offset(statement)
        if position is None:
            continue
        index = bisect_right(starts, position) - 1
        if index >= 0:
            match = candidates[index]
            events.append((match.start(), "DDL", match))
    return tuple(events)


def _like_target_offset(statement: exp.Expr | None) -> int | None:
    if not isinstance(statement, exp.Create) or statement.args.get("kind") != "TABLE":
        return None
    schema = statement.find(exp.Schema)
    if schema is None or not any(isinstance(item, exp.LikeProperty) for item in schema.iter_expressions()):
        return None
    target = schema.find(exp.Table)
    identifier = target.find(exp.Identifier) if target is not None else None
    if identifier is None:
        return None
    position = identifier.meta.get("start")
    return position if isinstance(position, int) else None


def _section_boundary_events(source: str) -> list[_SectionBoundaryEvent]:
    dollar_lines = dollar_quoted_lines(source)
    events = [
        _SectionBoundaryEvent(boundary_offset, "SECTION_BOUNDARY", match)
        for match in SECTION_BOUNDARY_PATTERN.finditer(source)
        if source_location(source, (boundary_offset := match.start())).line not in dollar_lines
    ]
    events.extend(
        _SectionBoundaryEvent(offset, "SECTION_BOUNDARY", match) for offset, match in dbmate_section_boundaries(source)
    )
    return events


def _apply_timeout_assignment(
    match: re.Match[str],
    active_local_timeouts: dict[str, bool],
    active_global_timeouts: dict[str, bool],
    *,
    nontransactional: bool,
) -> None:
    cmd = match.group(0).upper()
    is_local = "LOCAL" in cmd or (match.group(5) or "").lower() == "true"
    target_var = (match.group(1) or match.group(3) or "").strip('"').lower()
    val = (match.group(2) or match.group(4) or "").strip().strip(";")

    is_active = False if "RESET" in cmd else (bool(val) and _positive_timeout(val))

    if is_local:
        if not nontransactional:
            active_local_timeouts[target_var] = is_active
    else:
        active_global_timeouts[target_var] = is_active
        active_local_timeouts.pop(target_var, None)


def _positive_timeout(value: str) -> bool:
    match = POSITIVE_VAL_PATTERN.fullmatch(value)
    if match is None:
        return False
    multiplier, smaller_unit = _TIMEOUT_UNITS[match.group("unit") or ""]
    try:
        milliseconds = _timeout_number(match.group("number")) * multiplier
    except ValueError, OverflowError:
        return False
    if not math.isfinite(milliseconds) or abs(milliseconds) > _MAXIMUM_TIMEOUT + 1:
        return False
    if smaller_unit is not None:
        milliseconds = round(milliseconds / smaller_unit) * smaller_unit
    return 0 < round(milliseconds) <= _MAXIMUM_TIMEOUT


def _timeout_number(value: str) -> float:
    unsigned = value.lstrip("+-")
    if unsigned.startswith(("0x", "0X")):
        return float(int(value, 16))
    if len(unsigned) > 1 and unsigned.startswith("0") and unsigned.isdecimal():
        return float(int(value, 8))
    return float(value)
