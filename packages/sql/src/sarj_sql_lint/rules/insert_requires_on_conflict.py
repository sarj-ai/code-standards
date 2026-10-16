from __future__ import annotations

from pathlib import PurePosixPath
import re
from typing import TYPE_CHECKING, NamedTuple, final, override

from sarj_sql_lint.rule_base import (
    AutofixPolicy,
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    Rule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
    dollar_quoted_lines,
    is_dump_file,
    locate,
    mask_sql,
    mask_sql_literals_and_comments,
    normalize_sql_identifier,
    split_statements,
    sql_code_matches,
)


if TYPE_CHECKING:
    from pathlib import Path


_IDENT = r'(?:[A-Za-z_][\w$]*|"(?:""|[^"\n])+")(?:\s*\.\s*(?:[A-Za-z_][\w$]*|"(?:""|[^"\n])+"))*'

# A real insert write pattern matching INSERT INTO with optional column list and write verb.
INSERT_PATTERN = re.compile(
    rf"\bINSERT\s+(?:OR\s+\w+\s+)?INTO\s+(?:{_IDENT}|[\w.`?$:@-]+)\s*"
    rf"(?:AS\s+{_IDENT}\s*)?(?:\([^)]*\)\s*)?"
    r"(?:OVERRIDING\s+(?:SYSTEM|USER)\s+VALUE\s+)?(?:VALUES|SELECT|DEFAULT\s+VALUES)\b",
    re.IGNORECASE,
)

_WRITE_EVENTS = re.compile(r"\bINSERT\b|\bON\s+CONFLICT\b|\bON\s+DUPLICATE\s+KEY\b|[()]", re.IGNORECASE)
_INSERT_OR_POLICY = re.compile(r"^INSERT\s+OR\s+(?:IGNORE|REPLACE)\b", re.IGNORECASE)

# A procedural replay guard inside a `DO $$ ... $$` seed block: the block checks
# for the row itself and skips, so `ON CONFLICT` would be dead code.
REPLAY_GUARD_PATTERN = re.compile(r"\bIF\s+(?:NOT\s+)?EXISTS\s*\(", re.IGNORECASE)
INSERT_SELECT_TARGET_PATTERN = re.compile(
    rf"\bINSERT\s+INTO\s+(?P<target>{_IDENT})(?=\s|\()[\s\S]*?\bSELECT\b",
    re.IGNORECASE,
)


class _WriteEvent(NamedTuple):
    offset: int
    lexeme: str
    depth: int


class _InsertWrite(NamedTuple):
    offset: int
    text: str
    has_conflict_policy: bool


def _insert_writes(text: str) -> list[_InsertWrite]:
    events = _write_events(text)
    inserts = list(sql_code_matches(INSERT_PATTERN, text))
    depths = {event.offset: event.depth for event in events if event.lexeme == "INSERT"}
    writes: list[_InsertWrite] = []
    for match in inserts:
        owner_depth = depths.get(match.start(), 0)
        end = next(
            (
                event.offset
                for event in events
                if event.offset >= match.end()
                and (
                    (event.lexeme == ")" and event.depth < owner_depth)
                    or (event.lexeme == "INSERT" and event.depth <= owner_depth)
                )
            ),
            len(text),
        )
        body = text[match.start() : end]
        conflict = _INSERT_OR_POLICY.match(body) is not None or any(
            event.lexeme.startswith("ON") and event.depth == owner_depth and match.end() <= event.offset < end
            for event in events
        )
        writes.append(_InsertWrite(match.start(), body, conflict))
    return writes


def _write_events(text: str) -> list[_WriteEvent]:
    events: list[_WriteEvent] = []
    depth = 0
    for match in sql_code_matches(_WRITE_EVENTS, text):
        lexeme = match.group().upper()
        if lexeme == ")":
            depth = max(0, depth - 1)
        events.append(_WriteEvent(match.start(), lexeme, depth))
        if lexeme == "(":
            depth += 1
    return events


def _guarded_dollar_body_lines(masked: str, source: str) -> frozenset[int]:
    inside = dollar_quoted_lines(source)
    if not inside:
        return frozenset()
    masked_lines = masked.splitlines()
    guarded: set[int] = set()
    run: list[int] = []

    def flush() -> None:
        if not run:
            return
        body = "\n".join(masked_lines[lineno - 1] for lineno in run if lineno <= len(masked_lines))
        if REPLAY_GUARD_PATTERN.search(body):
            guarded.update(run)
        run.clear()

    for lineno in sorted(inside):
        if run and lineno != run[-1] + 1:
            flush()
        run.append(lineno)
    flush()
    return frozenset(guarded)


def _select_filters_existing_target(statement: str) -> bool:
    match = next(sql_code_matches(INSERT_SELECT_TARGET_PATTERN, statement), None)
    if match is None:
        return False
    target = normalize_sql_identifier(match.group("target"), unqualified=True)
    guard = re.compile(rf"\bWHERE\s+NOT\s+EXISTS\s*\([\s\S]*?\bFROM\s+(?P<target>{_IDENT})(?=\s|\)|$)", re.IGNORECASE)
    for candidate in sql_code_matches(guard, statement[match.end() :]):
        existing = normalize_sql_identifier(candidate.group("target"), unqualified=True)
        if existing == target:
            return True
    return False


@final
class InsertRequiresOnConflict(Rule):
    id = "insert-requires-replay-policy"
    code = "SARJ105"
    documentation = RuleDocumentation(
        summary="Every INSERT must declare replay-safe upsert behavior or explicitly document intentional insert-only semantics.",
        rationale=(
            "Retries happen in migrations, jobs, commands, and application requests. An INSERT with no declared "
            "conflict behavior can duplicate state or turn a safe retry into a uniqueness failure."
        ),
        remediation=(
            "Prefer ON CONFLICT with an explicit DO NOTHING or DO UPDATE action. If duplicate failure is the "
            "intended contract, add an exact SARJ105 suppression on the INSERT line explaining why."
        ),
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.NONE,
        aliases=("insert-requires-on-conflict",),
        limitations=(
            "Developer-authored SQL files are checked regardless of path; database dumps are excluded.",
            "Known PostgreSQL, MySQL, and SQLite upsert forms and a target-specific NOT EXISTS replay guard are recognized.",
            "Target aliases and OVERRIDING clauses preserve detection. Each INSERT owns its conflict policy, including data-modifying CTEs; neighboring writes do not supply another write policy.",
        ),
        examples=(
            RuleExample(
                example_id="insert-without-replay-policy",
                title="Insert without declared replay behavior",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.sql("queries/create_plan.sql", "INSERT INTO plan (name) VALUES ('free');\n"),),
                focus_path=PurePosixPath("queries/create_plan.sql"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="insert-with-replay-policy",
                title="Upsert declares its conflict behavior",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.sql(
                        "queries/create_plan.sql",
                        "INSERT INTO plan (name) VALUES ('free') ON CONFLICT (name) DO NOTHING;\n",
                    ),
                ),
                focus_path=PurePosixPath("queries/create_plan.sql"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if is_dump_file(source, path):
            return []

        masked = mask_sql_literals_and_comments(source, mask_dollar_literals=True)
        exempt = _guarded_dollar_body_lines(mask_sql(source, mask_dollar_literals=True), source)
        diags: list[Diagnostic] = []
        for statement in split_statements(masked):
            text = "\n".join(line for _, line in statement)
            for write in _insert_writes(text):
                if write.has_conflict_policy or _select_filters_existing_target(write.text):
                    continue
                lineno, col = locate(statement, write.offset)
                if lineno in exempt:
                    continue
                diags.append(
                    Diagnostic(
                        path=path,
                        line=lineno,
                        col=col,
                        code=self.code,
                        message=(
                            "INSERT has no replay policy; add explicit upsert conflict behavior, or an exact SARJ105 "
                            "suppression explaining why insert-only failure semantics are intentional."
                        ),
                    )
                )
        return diags
