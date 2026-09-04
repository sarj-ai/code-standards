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
    SourceComment,
    is_dump_file,
    is_generated_migration,
    is_migration_source,
    sql_comments,
)


if TYPE_CHECKING:
    from pathlib import Path


_SQL_HEAD_RE = re.compile(
    r"^(?:ALTER|BEGIN|CALL|COMMENT|COMMIT|COPY|CREATE|DELETE|DO|DROP|GRANT|INSERT|MERGE|REFRESH|REINDEX|"
    r"REVOKE|ROLLBACK|SELECT|SET|TRUNCATE|UPDATE|VACUUM|WITH)\b",
    re.IGNORECASE,
)
_IDENT = r'(?:[A-Za-z_][A-Za-z0-9_$]*|"(?:[^"]|"")+")(?:\s*\.\s*(?:[A-Za-z_][A-Za-z0-9_$]*|"(?:[^"]|"")+"))*'
_SCALAR = rf"(?:\*|{_IDENT}(?:\s*\.\s*\*)?|[-+]?\d+(?:\.\d+)?|NULL|TRUE|FALSE|'(?:[^']|'')*'|[$:@?][A-Za-z0-9_$]*|{_IDENT}\s*\([^)]*\))"
_SELECT_LIST = (
    rf"{_SCALAR}(?:\s+AS\s+[A-Za-z_][A-Za-z0-9_$]*)?(?:\s*,\s*{_SCALAR}(?:\s+AS\s+[A-Za-z_][A-Za-z0-9_$]*)?)*"
)
_DROP_RE = re.compile(
    rf"^DROP\s+(?:TABLE|TYPE|INDEX|VIEW|MATERIALIZED\s+VIEW|SCHEMA|SEQUENCE|FUNCTION|PROCEDURE|"
    rf"POLICY|TRIGGER|EXTENSION|DOMAIN)\s+(?:IF\s+EXISTS\s+)?{_IDENT}(?:\s+(?:CASCADE|RESTRICT))?$",
    re.IGNORECASE | re.DOTALL,
)
_ALTER_RE = re.compile(
    rf"^ALTER\s+(?:TABLE|TYPE|INDEX|VIEW|MATERIALIZED\s+VIEW|SCHEMA|SEQUENCE|FUNCTION|PROCEDURE|"
    rf"POLICY)\s+(?:IF\s+EXISTS\s+)?(?:ONLY\s+)?{_IDENT}\s+(?:"
    rf"(?:ADD|ALTER|DROP)\s+(?:COLUMN|CONSTRAINT)\s+{_IDENT}\b.+|"
    rf"RENAME\s+(?:(?:COLUMN|CONSTRAINT)\s+{_IDENT}\s+TO\s+{_IDENT}|TO\s+{_IDENT})|"
    rf"VALIDATE\s+CONSTRAINT\s+{_IDENT}|OWNER\s+TO\s+{_IDENT}|"
    rf"SET\s+(?:SCHEMA|TABLESPACE)\s+{_IDENT}|REPLICA\s+IDENTITY\s+.+)$",
    re.IGNORECASE | re.DOTALL,
)
_CREATE_TABLE_RE = re.compile(
    rf"^CREATE\s+(?:TEMP(?:ORARY)?\s+|UNLOGGED\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?{_IDENT}\s*\(.+\)$",
    re.IGNORECASE | re.DOTALL,
)
_CREATE_INDEX_RE = re.compile(
    rf"^CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:CONCURRENTLY\s+)?(?:IF\s+NOT\s+EXISTS\s+)?{_IDENT}\s+ON\s+{_IDENT}"
    rf"(?:\s+USING\s+{_IDENT})?\s*\(.+\)(?:\s+WHERE\s+.+)?$",
    re.IGNORECASE | re.DOTALL,
)
_CREATE_TRIGGER_RE = re.compile(
    rf"^CREATE\s+(?:OR\s+REPLACE\s+)?TRIGGER\s+{_IDENT}\s+.+\s+ON\s+{_IDENT}\s+.+\s+EXECUTE\s+"
    rf"(?:FUNCTION|PROCEDURE)\s+{_IDENT}\s*\(.+\)$",
    re.IGNORECASE | re.DOTALL,
)
_CREATE_SCHEMA_RE = re.compile(
    rf"^CREATE\s+SCHEMA\s+(?:IF\s+NOT\s+EXISTS\s+)?{_IDENT}(?:\s+AUTHORIZATION\s+{_IDENT})?$",
    re.IGNORECASE | re.DOTALL,
)
_CREATE_SEQUENCE_RE = re.compile(
    rf"^CREATE\s+SEQUENCE\s+(?:IF\s+NOT\s+EXISTS\s+)?{_IDENT}"
    r"(?:\s+(?:AS|INCREMENT(?:\s+BY)?|MINVALUE|MAXVALUE|START(?:\s+WITH)?|CACHE|OWNED\s+BY)\s+\S+|"
    r"\s+NO\s+(?:MINVALUE|MAXVALUE|CYCLE)|\s+CYCLE)+$|"
    rf"^CREATE\s+SEQUENCE\s+(?:IF\s+NOT\s+EXISTS\s+)?{_IDENT}$",
    re.IGNORECASE | re.DOTALL,
)
_CREATE_EXTENSION_RE = re.compile(
    rf"^CREATE\s+EXTENSION\s+(?:IF\s+NOT\s+EXISTS\s+)?{_IDENT}"
    rf"(?:\s+(?:WITH\s+)?(?:SCHEMA\s+{_IDENT}|VERSION\s+'[^']+'|CASCADE))*$",
    re.IGNORECASE | re.DOTALL,
)
_CREATE_DOMAIN_RE = re.compile(
    rf"^CREATE\s+DOMAIN\s+{_IDENT}\s+AS\s+{_IDENT}$",
    re.IGNORECASE | re.DOTALL,
)
_CREATE_TYPE_RE = re.compile(
    rf"^CREATE\s+TYPE\s+{_IDENT}\s+AS\s+(?:ENUM\s*\(.+\)|\(.+\)|RANGE\s*\(.+\))$",
    re.IGNORECASE | re.DOTALL,
)
_COMMENT_ON_RE = re.compile(
    rf"^COMMENT\s+ON\s+(?:TABLE|COLUMN|INDEX|VIEW|MATERIALIZED\s+VIEW|SCHEMA|SEQUENCE|FUNCTION|"
    rf"PROCEDURE|TYPE|DOMAIN|TRIGGER|POLICY)\s+{_IDENT}\s+IS\s+(?:NULL|'.*')$",
    re.IGNORECASE | re.DOTALL,
)
_DO_RE = re.compile(
    r"^DO(?:\s+LANGUAGE\s+[A-Za-z_][A-Za-z0-9_$]*)?\s+(?P<tag>\$(?:[A-Za-z_][A-Za-z0-9_]*)?\$)"
    r".+(?P=tag)$",
    re.IGNORECASE | re.DOTALL,
)
_BANNER_ONLY_RE = re.compile(r"^[-=#*~_.+ ]{4,}$")
_BANNER_HEADING_RE = re.compile(r"^[-=#*~_.+]{4,}\s*\S.*?\s*[-=#*~_.+]{4,}$")
_DEBT_MARKERS = ("TO" + "DO", "FIX" + "ME", "HACK", "X" + "XX")
_DEBT_RE = re.compile(r"^(?:" + "|".join(_DEBT_MARKERS) + r")\b", re.IGNORECASE)
_REFERENCE_RE = re.compile(r"https?://|\b(?:RFC|CVE)[- ]?\d+\b|\b[A-Z][A-Z0-9]{1,9}-\d+\b|#\d{2,6}\b")
_DIRECTIVE_RE = re.compile(
    r"^(?:sarj-noqa(?:\s*:|$)|sqlfluff(?:\s*:|\s+(?:disable|enable)\b)|squawk-ignore(?:\s*:|$)|"
    r"noqa(?:\s*:|$)|dialect\s*:|sql-dialect\s*:|migrate\s*:|\+goose\b|\+migrate\b|liquibase\b|"
    r"changeset\b|rollback\b|preconditions?\b|atlas\s*:|pgroll\s*:|flyway\s*:|pg_dump(?:\s*:|$))",
    re.IGNORECASE,
)
_ROLLBACK_CONTEXT_RE = re.compile(r"\b(?:roll\s*back|revert|undo)\b", re.IGNORECASE)
_TEST_PATH_PARTS = frozenset({"test", "tests"})


class _CommentLine(NamedTuple):
    comment: SourceComment
    line: int
    column: int
    text: str


class _Finding(NamedTuple):
    line: int
    column: int
    message: str


@final
class NoCommentCruft(Rule):
    id = "no-migration-comment-cruft"
    code = "SARJ113"
    documentation = RuleDocumentation(
        summary="Commented-out SQL, decorative banners, and untracked debt markers must be removed.",
        rationale=(
            "Disabled statements drift while version control preserves their history, decorative dividers obscure "
            "migration structure, and debt without a durable owner silently persists."
        ),
        remediation=(
            "Execute or delete disabled SQL, delete decorative dividers, and resolve debt or attach a durable issue "
            "reference. Retain concise operational constraints, rollback instructions, and tool directives."
        ),
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        aliases=("no-comment-cruft",),
        limitations=(
            "Only authored migration files are checked; dumps and generator-owned migrations are excluded.",
            "The scanner distinguishes SQL comments from strings, identifiers, templates, and executable dollar-quoted bodies.",
            "Commented-out SQL is reported only for a conservative complete-statement grammar; ambiguous prose and partial statements are preserved.",
            "Migration-tool directives, explicit rollback instructions, and debt with a durable URL or issue identifier are preserved.",
        ),
        examples=(
            RuleExample(
                example_id="commented-statement",
                title="Disabled SQL statement",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.sql("migrations/001.sql", "-- DROP TABLE legacy_events;\nSELECT 1;\n"),),
                focus_path=PurePosixPath("migrations/001.sql"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="rollback-instruction",
                title="Owned rollback instruction records an operational constraint",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.sql("migrations/001.sql", "-- Roll back by restoring snapshot OPS-812.\nSELECT 1;\n"),
                ),
                focus_path=PurePosixPath("migrations/001.sql"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        path_parts = frozenset(part.lower() for part in path.parts)
        if (
            path_parts & _TEST_PATH_PARTS
            or is_dump_file(source, path)
            or not is_migration_source(path, source)
            or is_generated_migration(path, source)
        ):
            return []
        findings: list[Diagnostic] = []
        for comments in _comment_groups(source):
            finding = _finding(comments)
            if finding is None:
                continue
            findings.append(Diagnostic(path, finding.line, finding.column, self.code, finding.message))
        return findings


def _finding(comments: list[SourceComment]) -> _Finding | None:
    lines = [line for comment in comments for line in _comment_lines(comment)]
    effective = [line for line in lines if line.text and _DIRECTIVE_RE.match(line.text) is None]
    if not effective:
        return None

    banner = next((line for line in effective if _is_banner(line.text)), None)
    if banner is not None:
        return _Finding(
            banner.line,
            banner.column,
            "Section-banner comment — delete the ASCII divider and let migration structure carry the boundary.",
        )

    debt = next(
        (
            line
            for line in effective
            if _DEBT_RE.match(line.text) is not None and _REFERENCE_RE.search(line.text) is None
        ),
        None,
    )
    if debt is not None:
        return _Finding(
            debt.line,
            debt.column,
            "Unowned SQL debt marker — resolve it or attach a durable URL or issue identifier.",
        )

    statement = "\n".join(line.text for line in effective)
    statement_line = _first_commented_sql_line(statement)
    if not any(_ROLLBACK_CONTEXT_RE.search(line.text) for line in lines) and statement_line is not None:
        first = effective[statement_line]
        return _Finding(
            first.line,
            first.column,
            "Commented-out SQL — execute it or delete it; version control preserves migration history.",
        )
    return None


def _comment_lines(comment: SourceComment) -> list[_CommentLine]:
    lines: list[_CommentLine] = []
    for offset, raw in enumerate(comment.body.splitlines()):
        text = raw.strip().lstrip("*").strip()
        lines.append(
            _CommentLine(
                comment,
                comment.line + offset,
                comment.column if offset == 0 else 1,
                text,
            )
        )
    return lines


def _is_banner(line: str) -> bool:
    return _BANNER_ONLY_RE.fullmatch(line) is not None or _BANNER_HEADING_RE.fullmatch(line) is not None


def _first_commented_sql_line(text: str) -> int | None:
    statements = _split_commented_statements(text)
    search_start = 0
    for statement in statements:
        statement_start = text.find(statement, search_start)
        if statement_start < 0:
            continue
        search_start = statement_start + len(statement)
        if _is_supported_statement(statement):
            return text.count("\n", 0, statement_start)
    return None


def _split_commented_statements(text: str) -> list[str]:
    statements: list[str] = []
    start = 0
    cursor = 0
    quote: str | None = None
    dollar_quote: str | None = None
    depth = 0
    while cursor < len(text):
        char = text[cursor]
        if dollar_quote is not None:
            if text.startswith(dollar_quote, cursor):
                cursor += len(dollar_quote)
                dollar_quote = None
                continue
            cursor += 1
            continue
        if quote is not None:
            if char == quote:
                if cursor + 1 < len(text) and text[cursor + 1] == quote:
                    cursor += 2
                    continue
                quote = None
            cursor += 1
            continue
        if char in {"'", '"'}:
            quote = char
        elif char == "$":
            delimiter = re.match(r"\$(?:[A-Za-z_][A-Za-z0-9_]*)?\$", text[cursor:])
            if delimiter is not None:
                dollar_quote = delimiter.group(0)
                cursor += len(dollar_quote)
                continue
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth < 0:
                return []
        elif char == ";" and depth == 0:
            statement = text[start:cursor].strip()
            if not statement:
                return []
            statements.append(statement)
            start = cursor + 1
        cursor += 1
    if not statements and (quote is not None or dollar_quote is not None or depth != 0):
        return []
    return statements


def _is_supported_statement(statement: str) -> bool:
    compact = " ".join(statement.split())
    if _SQL_HEAD_RE.match(compact) is None:
        return False
    if compact.upper() in {"BEGIN", "COMMIT", "ROLLBACK"}:
        return True
    if _DROP_RE.fullmatch(compact) or _ALTER_RE.fullmatch(compact):
        return True
    if _CREATE_TABLE_RE.fullmatch(compact) or _CREATE_INDEX_RE.fullmatch(compact):
        return True
    create_patterns = (
        _CREATE_TRIGGER_RE,
        _CREATE_SCHEMA_RE,
        _CREATE_SEQUENCE_RE,
        _CREATE_EXTENSION_RE,
        _CREATE_DOMAIN_RE,
        _CREATE_TYPE_RE,
    )
    if (
        _is_supported_create_view(compact)
        or any(pattern.fullmatch(compact) for pattern in create_patterns)
        or _COMMENT_ON_RE.fullmatch(compact)
        or _DO_RE.fullmatch(compact)
    ):
        return True
    return _is_supported_dml(compact)


def _is_supported_dml(statement: str) -> bool:
    if _is_supported_select(statement) or _is_supported_insert(statement) or _is_supported_with(statement):
        return True
    patterns = (
        rf"^UPDATE\s+{_IDENT}\s+SET\s+{_IDENT}\s*=\s*.+$",
        rf"^DELETE\s+FROM\s+{_IDENT}\s+(?:USING|WHERE|RETURNING)\b.+$",
        rf"^MERGE\s+INTO\s+{_IDENT}\s+USING\s+.+\s+ON\s+.+$",
        rf"^(?:GRANT|REVOKE)\s+(?:ALL(?:\s+PRIVILEGES)?|SELECT|INSERT|UPDATE|DELETE|TRUNCATE|REFERENCES|TRIGGER|USAGE|CREATE|CONNECT|TEMP|EXECUTE)(?:\s*,\s*(?:SELECT|INSERT|UPDATE|DELETE|TRUNCATE|REFERENCES|TRIGGER|USAGE|CREATE|CONNECT|TEMP|EXECUTE))*\s+ON\s+(?:(?:TABLE|SEQUENCE|SCHEMA|DATABASE|FUNCTION|PROCEDURE)\s+)?{_IDENT}\s+(?:TO|FROM)\s+{_IDENT}$",
        rf"^TRUNCATE(?:\s+TABLE)?\s+{_IDENT}(?:\s*,\s*{_IDENT})*(?:\s+(?:RESTART|CONTINUE)\s+IDENTITY)?(?:\s+(?:CASCADE|RESTRICT))?$",
        rf"^COPY\s+{_IDENT}(?:\s*\([^)]*\))?\s+(?:FROM|TO)\s+(?:STDIN|STDOUT|'[^']+'|PROGRAM\s+'[^']+')$",
        rf"^CALL\s+{_IDENT}\s*\(.*\)$",
        rf"^REFRESH\s+MATERIALIZED\s+VIEW\s+(?:CONCURRENTLY\s+)?{_IDENT}$",
        rf"^REINDEX(?:\s+(?:INDEX|TABLE|SCHEMA|DATABASE|SYSTEM))?\s+{_IDENT}$",
        rf"^VACUUM\s+\([^)]*\)(?:\s+{_IDENT}(?:\s*\([^)]*\))?)?$",
        rf"^VACUUM\s+(?:FULL|FREEZE|ANALYZE|VERBOSE)(?:\s+(?:FULL|FREEZE|ANALYZE|VERBOSE))*\s+{_IDENT}$",
        rf"^SET\s+[A-Za-z_][A-Za-z0-9_.]*\s*(?:=|TO)\s+(?:DEFAULT|{_SCALAR})$",
    )
    return any(re.fullmatch(pattern, statement, re.IGNORECASE | re.DOTALL) is not None for pattern in patterns)


def _is_supported_select(statement: str) -> bool:
    if re.fullmatch(
        rf"SELECT\s+(?:DISTINCT\s+)?{_SELECT_LIST}",
        statement,
        re.IGNORECASE | re.DOTALL,
    ):
        return True
    return (
        re.fullmatch(
            rf"SELECT\s+(?:DISTINCT\s+)?{_SELECT_LIST}\s+FROM\s+{_IDENT}"
            rf"(?:\s+(?:AS\s+)?[A-Za-z_][A-Za-z0-9_$]*)?"
            r"(?:\s+(?:WHERE|GROUP\s+BY|HAVING|ORDER\s+BY|LIMIT|OFFSET|FOR)\b.+)?",
            statement,
            re.IGNORECASE | re.DOTALL,
        )
        is not None
    )


def _is_supported_with(statement: str) -> bool:
    return (
        re.fullmatch(
            rf"WITH\s+(?:RECURSIVE\s+)?{_IDENT}(?:\s*\([^)]*\))?\s+AS\s*\(.+\)\s+"
            r"(?:SELECT|INSERT|UPDATE|DELETE|MERGE)\b.+",
            statement,
            re.IGNORECASE | re.DOTALL,
        )
        is not None
    )


def _is_supported_insert(statement: str) -> bool:
    match = re.fullmatch(
        rf"INSERT\s+INTO\s+{_IDENT}(?:\s*\([^)]*\))?\s+(?P<body>.+)",
        statement,
        re.IGNORECASE | re.DOTALL,
    )
    if match is None:
        return False
    body = match.group("body")
    return (
        re.fullmatch(r"DEFAULT\s+VALUES", body, re.IGNORECASE) is not None
        or re.fullmatch(r"VALUES\s*\(.+\)(?:\s*,\s*\(.+\))*", body, re.IGNORECASE | re.DOTALL) is not None
        or _is_supported_select(body)
        or _is_supported_with(body)
    )


def _is_supported_create_view(statement: str) -> bool:
    match = re.fullmatch(
        rf"CREATE\s+(?:OR\s+REPLACE\s+)?(?:VIEW|MATERIALIZED\s+VIEW)\s+{_IDENT}\s+AS\s+(?P<body>.+)",
        statement,
        re.IGNORECASE | re.DOTALL,
    )
    return match is not None and (_is_supported_select(match.group("body")) or _is_supported_with(match.group("body")))


def _comment_groups(source: str) -> list[list[SourceComment]]:
    comments = sql_comments(source)
    source_lines = source.splitlines()
    groups: list[list[SourceComment]] = []
    for comment in comments:
        if groups and _continues_group(source_lines, groups[-1][-1], comment):
            groups[-1].append(comment)
        else:
            groups.append([comment])
    return groups


def _continues_group(source_lines: list[str], previous: SourceComment, current: SourceComment) -> bool:
    return (
        not current.block
        and not previous.block
        and current.line == previous.line + 1
        and _is_standalone_comment(source_lines, current)
        and _is_standalone_comment(source_lines, previous)
    )


def _is_standalone_comment(source_lines: list[str], comment: SourceComment) -> bool:
    if comment.line < 1 or comment.line > len(source_lines):
        return False
    return not source_lines[comment.line - 1][: comment.column - 1].strip()
