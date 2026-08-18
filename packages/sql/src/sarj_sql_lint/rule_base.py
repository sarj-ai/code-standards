"""Base types and shared SQL text utilities for sarj-sql-lint rules."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field, replace
from enum import StrEnum
from functools import lru_cache
from pathlib import Path, PurePosixPath
import re
from typing import ClassVar, Final, NamedTuple, Self


type Statement = list[tuple[int, str]]
"""A statement as `(lineno, text)` fragments — one per source line it spans."""


class SourceLocation(NamedTuple):
    """A one-based source position."""

    line: int
    column: int


class _ScanResult(NamedTuple):
    masked_source: str
    executable_spans: list[tuple[int, int]]
    comments: list[SourceComment]


class SourceComment(NamedTuple):
    """One real SQL comment outside strings and quoted identifiers."""

    line: int
    column: int
    body: str
    block: bool


class RuleCategory(StrEnum):
    """Small cross-engine taxonomy used by generated rule directories."""

    ARCHITECTURE = "architecture"
    CORRECTNESS = "correctness"
    MAINTAINABILITY = "maintainability"
    PERFORMANCE = "performance"
    SECURITY = "security"
    STYLE = "style"
    TESTING = "testing"


class AutofixPolicy(StrEnum):
    """Strongest source mutation a rule can safely offer."""

    NONE = "none"
    SUGGESTION = "suggestion"
    SAFE = "safe"


class ExampleOutcome(StrEnum):
    """Expected result when a rule checks one documentation example."""

    MATCH = "match"
    NO_MATCH = "no-match"


_KEBAB_CASE: Final = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_MAX_SUMMARY_LENGTH: Final = 160
_PUBLIC_PAIR_SIZE: Final = 2
type ExamplePath = str


@dataclass(frozen=True, slots=True)
class ExampleFile:
    """One virtual source file in a rule example."""

    path: PurePosixPath
    source: str = field(repr=False)

    def __post_init__(self) -> None:
        if self.path.is_absolute() or ".." in self.path.parts or not self.path.name:
            msg = "example file paths must be safe relative paths"
            raise ValueError(msg)
        if not self.source:
            msg = "example file source must not be empty"
            raise ValueError(msg)

    @classmethod
    def sql(cls, path: ExamplePath, source: str) -> Self:
        """Build a SQL example file without leaking path parsing into rules."""
        return cls(PurePosixPath(path), source)


@dataclass(frozen=True, slots=True)
class RuleExample:
    """A reviewed, executable example; examples are private unless opted in."""

    example_id: str
    outcome: ExampleOutcome
    files: tuple[ExampleFile, ...]
    focus_path: PurePosixPath
    expected_count: int
    title: str
    public: bool = False
    fixed_files: tuple[ExampleFile, ...] = ()
    scenario: str = "primary"

    def __post_init__(self) -> None:
        if not _KEBAB_CASE.fullmatch(self.example_id):
            msg = "example ID must be lowercase kebab-case"
            raise ValueError(msg)
        if not _KEBAB_CASE.fullmatch(self.scenario):
            msg = "example scenario must be lowercase kebab-case"
            raise ValueError(msg)
        if not self.title.strip():
            msg = "example title must not be empty"
            raise ValueError(msg)
        paths = tuple(item.path for item in self.files)
        if not paths or len(paths) != len(set(paths)):
            msg = "example files must have unique paths"
            raise ValueError(msg)
        if self.focus_path not in paths:
            msg = "example focus path must name one example file"
            raise ValueError(msg)
        fixed_paths = tuple(item.path for item in self.fixed_files)
        if len(fixed_paths) != len(set(fixed_paths)):
            msg = "fixed example files must have unique paths"
            raise ValueError(msg)
        if self.expected_count < 0:
            msg = "example expected count must not be negative"
            raise ValueError(msg)
        if self.outcome is ExampleOutcome.MATCH and self.expected_count < 1:
            msg = "matching examples must expect at least one diagnostic"
            raise ValueError(msg)
        if self.outcome is ExampleOutcome.NO_MATCH and self.expected_count != 0:
            msg = "non-matching examples must expect zero diagnostics"
            raise ValueError(msg)

    @property
    def focus_file(self) -> ExampleFile:
        """Return the file a single-file native checker should inspect."""
        return next(item for item in self.files if item.path == self.focus_path)


@dataclass(frozen=True, slots=True)
class RuleDocumentation:
    """Source-authored rule prose and reviewed examples."""

    summary: str
    rationale: str
    remediation: str
    category: RuleCategory
    autofix: AutofixPolicy = AutofixPolicy.NONE
    aliases: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    examples: tuple[RuleExample, ...] = ()

    def __post_init__(self) -> None:
        for label, value in (
            ("summary", self.summary),
            ("rationale", self.rationale),
            ("remediation", self.remediation),
        ):
            if not value.strip():
                msg = f"rule {label} must not be empty"
                raise ValueError(msg)
        if "\n" in self.summary or len(self.summary) > _MAX_SUMMARY_LENGTH:
            msg = f"rule summary must be one line of at most {_MAX_SUMMARY_LENGTH} characters"
            raise ValueError(msg)
        if len(self.aliases) != len(set(self.aliases)) or any(
            not _KEBAB_CASE.fullmatch(alias) for alias in self.aliases
        ):
            msg = "rule aliases must be unique lowercase kebab-case IDs"
            raise ValueError(msg)
        if any(not limitation.strip() for limitation in self.limitations):
            msg = "rule limitations must not be empty"
            raise ValueError(msg)
        example_ids = tuple(example.example_id for example in self.examples)
        if len(example_ids) != len(set(example_ids)):
            msg = "rule example IDs must be unique"
            raise ValueError(msg)
        public_scenarios = {example.scenario for example in self.examples if example.public}
        for scenario in public_scenarios:
            pair = tuple(example for example in self.examples if example.public and example.scenario == scenario)
            if len(pair) != _PUBLIC_PAIR_SIZE or {example.outcome for example in pair} != {
                ExampleOutcome.MATCH,
                ExampleOutcome.NO_MATCH,
            }:
                msg = f"published example scenario {scenario!r} must contain both matching and non-matching cases exactly once"
                raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class NativeRuleSpec:
    """Complete native rule record adapted from a rule class and its authored docs."""

    engine: str
    rule_id: str
    code: str
    summary: str
    rationale: str
    remediation: str
    category: RuleCategory
    autofix: AutofixPolicy
    aliases: tuple[str, ...]
    limitations: tuple[str, ...]
    examples: tuple[RuleExample, ...]

    @property
    def key(self) -> str:
        """Return the collision-free rule identity used by configuration and URLs."""
        return f"{self.engine}:{self.rule_id}"

    @property
    def public_examples(self) -> tuple[RuleExample, ...]:
        """Expose only fixtures explicitly reviewed for publication."""
        return tuple(example for example in self.examples if example.public)


_SARJ_NOQA_RE = re.compile(
    r"--\s*sarj-noqa(?::\s*([A-Za-z0-9_, ]+))?",
    re.IGNORECASE,
)
_NON_NEWLINE = re.compile(r"[^\n]")

# A dollar-quote delimiter (`$$` or `$tag$`) where `tag` cannot start with a digit, preventing match with `$1`/`$2` positional parameters.
_DOLLAR_DELIM_RE = re.compile(r"\$(?:[A-Za-z_][A-Za-z0-9_]*)?\$")
_IDENT_CHAR_RE = re.compile(r"[A-Za-z0-9_]")


def is_dump_file(source: str, path: Path | None = None) -> bool:
    """Report whether source text or path indicates an auto-generated schema dump file."""
    if path is not None:
        name = path.name.lower()
        if name in {"structure.sql", "schema.sql"} or name.endswith("_dump.sql") or "restore" in path.parts:
            return True
    first_chunk = source[:1024].lower()
    return (
        "postgresql database dump" in first_chunk
        or "dumped by pg_dump" in first_chunk
        or "dumped from database" in first_chunk
        or ("set statement_timeout = 0;" in first_chunk and "set lock_timeout = 0;" in first_chunk)
    )


# Tokens (like backticks or AUTO_INCREMENT) that exist in MySQL/SQLite and cannot appear in Postgres DDL.
_NON_POSTGRES_RE = re.compile(
    r"`[^`\n]+`"  # backtick-quoted identifier — MySQL, MariaDB, SQLite
    r"|\bAUTO_INCREMENT\b"  # MySQL column attribute
    r"|\bAUTOINCREMENT\b"  # SQLite column attribute
    r"|\bENGINE\s*="  # MySQL table option (`ENGINE=InnoDB`)
    r"|\bCOLLATE\s+utf8"  # MySQL collation family (`utf8mb4_unicode_ci`)
    r"|\bUNSIGNED\b",  # MySQL integer modifier
    re.IGNORECASE,
)

# Tokens exclusive to MySQL/MariaDB, intentionally narrower than _NON_POSTGRES_RE so SQLite files are not matched.
_MYSQL_RE = re.compile(
    r"\bAUTO_INCREMENT\b"
    r"|\bENGINE\s*="
    r"|\bCOLLATE\s+utf8"
    r"|\bUNSIGNED\b"
    r"|\bON\s+DUPLICATE\s+KEY\b"
    r"|\bMODIFY\s+COLUMN\b",
    re.IGNORECASE,
)

_DIALECT_DIRECTIVE_RE = re.compile(
    r"^\s*--\s*(?:sql-)?dialect\s*:\s*(postgres(?:ql)?|sqlite|mysql|mariadb)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_DBMATE_DIRECTIVE_RE = re.compile(
    r"^\s*--\s*migrate:(up|no-transaction)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_SQLITE_RE = re.compile(r"\bAUTOINCREMENT\b", re.IGNORECASE)

_MIGRATION_ROOT_NAMES = frozenset({"changesets", "drizzle", "migrate", "migration", "migrations"})
_NON_PRODUCTION_SQL_PARTS = frozenset(
    {
        "__fixtures__",
        "__mocks__",
        "__snapshots__",
        "example",
        "examples",
        "fixture",
        "fixtures",
        "mock",
        "mocks",
        "queries",
        "query",
        "script",
        "scripts",
        "snapshot",
        "snapshots",
        "testdata",
    }
)
_NON_POSTGRES_SQL_PARTS = frozenset({"clickhouse", "d1", "mariadb", "mysql", "sqlite"})
_FLYWAY_MIGRATION_RE = re.compile(r"^(?:B|R|V)(?:\d+(?:[._]\d+)*)?__.+\.sql$", re.IGNORECASE)
_MIGRATION_SOURCE_DIRECTIVE_RE = re.compile(
    r"^\s*--\s*(?:migrate:up(?:\s|$)|\+goose\s+up\s*$|liquibase\s+formatted\s+sql\s*$)",
    re.IGNORECASE | re.MULTILINE,
)
_POSTGRES_MIGRATION_EVIDENCE_RE = re.compile(
    r"::[A-Za-z_]"
    r"|\b(?:BIGSERIAL|BYTEA|CITEXT|JSONB|SERIAL|TIMESTAMPTZ|UUID)\b"
    r"|\bCREATE\s+EXTENSION\b"
    r"|\bCREATE\s+(?:UNIQUE\s+)?INDEX\s+CONCURRENTLY\b"
    r"|\bDO\s+\$(?:[A-Za-z_][A-Za-z0-9_]*)?\$"
    r"|\bSET\s+(?:(?:LOCAL|SESSION)\s+)?(?:lock_timeout|statement_timeout)\b"
    r"|\bUSING\s+(?:GIN|GIST|HASH|SPGIST)\b",
    re.IGNORECASE,
)


def declared_dialect(source: str) -> str | None:
    """Return an explicit dialect declared in a leading SQL line comment."""
    match = _DIALECT_DIRECTIVE_RE.search(source)
    if match is None:
        return None
    dialect = match.group(1).lower()
    if dialect in {"postgres", "postgresql"}:
        return "postgresql"
    if dialect == "mariadb":
        return "mysql"
    return dialect


def has_dbmate_directive(source: str, directive: str) -> bool:
    """Find an exact dbmate line directive outside dollar-quoted function bodies."""
    dollar_lines = dollar_quoted_lines(source)
    return any(
        match.group(1).lower() == directive and source.count("\n", 0, match.start()) + 1 not in dollar_lines
        for match in _DBMATE_DIRECTIVE_RE.finditer(source)
    )


# Drizzle writes this separator between statements in every migration it emits.
_GENERATED_MIGRATION_SENTINEL = "--> statement-breakpoint"

# A directory holding one of these is the root of a generator-owned migration
# tree: Prisma writes `migration_lock.toml`, Drizzle writes `meta/_journal.json`,
# Atlas writes `atlas.sum`.
_GENERATED_MIGRATION_MARKERS = ("migration_lock.toml", "atlas.sum")

_MAX_MARKER_ASCENT = 12


def is_postgres(source: str) -> bool:
    """Report whether `source` is free of any non-Postgres dialect marker."""
    dialect = declared_dialect(source)
    if dialect is not None:
        return dialect == "postgresql"
    return _NON_POSTGRES_RE.search(mask_sql(source)) is None


def is_postgres_source(path: Path, source: str) -> bool:
    """Require positive PostgreSQL evidence before offering dialect-specific advice."""
    parts = tuple(part.lower() for part in path.parts)
    if any(part in _NON_POSTGRES_SQL_PARTS for part in parts):
        return False
    dialect = declared_dialect(source)
    if dialect is not None:
        return dialect == "postgresql"
    return is_postgres(source) and ("supabase" in parts or _POSTGRES_MIGRATION_EVIDENCE_RE.search(source) is not None)


def is_mysql(source: str) -> bool:
    """Report whether `source` carries a MySQL/MariaDB-exclusive token."""
    dialect = declared_dialect(source)
    if dialect is not None:
        return dialect == "mysql"
    return _MYSQL_RE.search(mask_sql(source)) is not None


def is_sqlite(source: str) -> bool:
    """Report whether source explicitly declares or syntactically signals SQLite."""
    dialect = declared_dialect(source)
    if dialect is not None:
        return dialect == "sqlite"
    return _SQLITE_RE.search(mask_sql(source)) is not None


def is_postgres_migration(path: Path, source: str) -> bool:
    """Identify a production PostgreSQL migration from path plus positive dialect evidence."""
    parts = tuple(part.lower() for part in path.parts)
    if any(part in _NON_PRODUCTION_SQL_PARTS or part in _NON_POSTGRES_SQL_PARTS for part in parts):
        return False

    source_directive = _MIGRATION_SOURCE_DIRECTIVE_RE.search(source) is not None
    migration_path = (
        any(part in _MIGRATION_ROOT_NAMES for part in parts) or _FLYWAY_MIGRATION_RE.fullmatch(path.name) is not None
    )
    if not source_directive and not migration_path:
        return False

    dialect = declared_dialect(source)
    if dialect is not None:
        return dialect == "postgresql"
    # Dbmate/Goose/Liquibase directives establish migration intent even when a
    # small PostgreSQL seed uses no dialect-exclusive syntax. Supabase is a
    # PostgreSQL migration root by contract. Ambiguous plain SQL stays silent.
    return source_directive or is_postgres_source(path, source)


def is_migration_source(path: Path, source: str) -> bool:
    """Identify migration-intent SQL without guessing a database dialect."""
    parts = tuple(part.lower() for part in path.parts)
    if any(part in _NON_PRODUCTION_SQL_PARTS for part in parts):
        return False
    return (
        _MIGRATION_SOURCE_DIRECTIVE_RE.search(source) is not None
        or any(part in _MIGRATION_ROOT_NAMES for part in parts)
        or _FLYWAY_MIGRATION_RE.fullmatch(path.name) is not None
        or path.name.lower() == "migration.sql"
    )


@lru_cache(maxsize=2048)
def _has_generated_marker(directory: Path) -> bool:
    """Report whether `directory` or an ancestor is a generator-owned migration root."""
    for depth, parent in enumerate((directory, *directory.parents)):
        if depth > _MAX_MARKER_ASCENT:
            return False
        try:
            if any((parent / marker).is_file() for marker in _GENERATED_MIGRATION_MARKERS):
                return True
            if (parent / "meta" / "_journal.json").is_file():
                return True
            if (parent / ".git").exists():
                return False
        except OSError:
            return False
    return False


def is_generated_migration(path: Path, source: str) -> bool:
    """Identify generated migrations so schema fixes redirect while runtime-safety findings remain."""
    if _GENERATED_MIGRATION_SENTINEL in source:
        return True
    return _has_generated_marker(path.parent)


def clear_path_caches() -> None:
    """Clear filesystem-derived state before each independent lint run."""
    _has_generated_marker.cache_clear()


def is_suppressed(source_lines: list[str], line: int, code: str) -> bool:
    """Report whether the diagnostic's line carries a `-- sarj-noqa[: CODE]` comment."""
    if line < 1 or line > len(source_lines):
        return False
    m = _SARJ_NOQA_RE.search(source_lines[line - 1])
    if m is None:
        return False
    codes_str = m.group(1)
    if not codes_str:
        return True
    codes = {val.upper() for c in codes_str.split(",") if (val := c.strip())}
    return code.upper() in codes


def _blank(segment: str) -> str:  # sarj-noqa: SARJ023 — scanner primitive stays above the cached engine.
    """Replace every char with a space, keeping newlines so offsets are preserved."""
    return _NON_NEWLINE.sub(" ", segment)


def _scan_quoted(  # sarj-noqa: SARJ023 — scanner primitive stays above the cached engine.
    source: str, start: int, quote: str
) -> int:
    """Index just past a `quote`-delimited run starting at `start`, honoring `''`/`""`."""
    n = len(source)
    j = start + 1
    while j < n:
        if source[j] == quote:
            if j + 1 < n and source[j + 1] == quote:
                j += 2
                continue
            return j + 1
        j += 1
    return n


def _dollar_open_tag(  # sarj-noqa: SARJ023 — scanner primitive stays above the cached engine.
    source: str, i: int
) -> str | None:
    """Return an opening dollar tag, rejecting identifier-adjacent `$` that cannot start a delimiter."""
    if i > 0 and _IDENT_CHAR_RE.match(source, i - 1) is not None:
        return None
    m = _DOLLAR_DELIM_RE.match(source, i)
    return None if m is None else m.group(0)


def _closing_depth(  # sarj-noqa: SARJ023 — scanner primitive stays above the cached engine.
    source: str, i: int, open_tag_depths: dict[str, list[int]]
) -> int | None:
    """Choose the outermost matching tag so an unterminated nested tag cannot swallow a valid outer close."""
    match = _DOLLAR_DELIM_RE.match(source, i)
    if match is None:
        return None
    depths = open_tag_depths.get(match.group(0))
    return depths[0] if depths else None


@lru_cache(maxsize=32)
# ruff: ignore[too-many-locals] -- single-pass scanner state is kept local for speed and isolation.
def _scan(source: str) -> _ScanResult:
    # Preserve offsets while recursively masking comments and literals inside executable dollar-quoted bodies.
    out: list[str] = []
    open_tags: list[str] = []
    open_tag_depths: dict[str, list[int]] = {}
    spans: list[tuple[int, int]] = []
    comments: list[SourceComment] = []
    body_start = 0
    i = 0
    chunk_start = 0
    n = len(source)

    while i < n:
        ch = source[i]
        template_close = next(
            (closer for opener, closer in (("{#", "#}"), ("{%", "%}"), ("{{", "}}")) if source.startswith(opener, i)),
            None,
        )
        if template_close is not None:
            if i > chunk_start:
                out.append(source[chunk_start:i])
            close = source.find(template_close, i + 2)
            end = n if close < 0 else close + len(template_close)
            out.append(_blank(source[i:end]))
            i = end
            chunk_start = i
            continue
        if ch == "$" and open_tags:
            depth = _closing_depth(source, i, open_tag_depths)
            if depth is not None:
                if i > chunk_start:
                    out.append(source[chunk_start:i])
                tag = open_tags[depth]
                for removed_depth in range(len(open_tags) - 1, depth - 1, -1):
                    removed = open_tags[removed_depth]
                    depths = open_tag_depths[removed]
                    depths.pop()
                    if not depths:
                        del open_tag_depths[removed]
                del open_tags[depth:]
                out.append(" " * len(tag))
                i += len(tag)
                chunk_start = i
                if not open_tags:
                    spans.append((body_start, i))
                continue
        pair = source[i : i + 2]
        if pair == "--":
            end = source.find("\n", i)
            end = n if end == -1 else end
            comments.append(
                SourceComment(
                    line=source.count("\n", 0, i) + 1,
                    column=i - source.rfind("\n", 0, i),
                    body=source[i + 2 : end].strip(),
                    block=False,
                )
            )
        elif pair == "/*":
            close = source.find("*/", i + 2)
            end = n if close == -1 else close + 2
            body_end = end - 2 if close >= 0 else end
            comments.append(
                SourceComment(
                    line=source.count("\n", 0, i) + 1,
                    column=i - source.rfind("\n", 0, i),
                    body=source[i + 2 : body_end].strip(),
                    block=True,
                )
            )
        elif ch in {"'", '"'}:
            end = _scan_quoted(source, i, ch)
        elif ch == "$":
            tag = _dollar_open_tag(source, i)
            if tag is None:
                i += 1
                continue
            if i > chunk_start:
                out.append(source[chunk_start:i])
            if not open_tags:
                body_start = i
            open_tag_depths.setdefault(tag, []).append(len(open_tags))
            open_tags.append(tag)
            out.append(" " * len(tag))
            i += len(tag)
            chunk_start = i
            continue
        else:
            i += 1
            continue

        if i > chunk_start:
            out.append(source[chunk_start:i])
        out.append(_blank(source[i:end]))
        i = end
        chunk_start = i

    if chunk_start < n:
        out.append(source[chunk_start:n])

    if open_tags:
        spans.append((body_start, n))
    return _ScanResult("".join(out), spans, comments)


def mask_sql(source: str) -> str:
    r"""Blank SQL noise without shifting offsets or hiding executable dollar-quoted bodies."""
    return _scan(source).masked_source


def sql_comments(source: str) -> tuple[SourceComment, ...]:
    """Return real SQL comments in source order without exposing scanner state."""
    return tuple(_scan(source).comments)


def dollar_quoted_lines(source: str) -> frozenset[int]:
    """Locate dollar bodies for rules with an explicit procedural-migration exemption."""
    spans = _scan(source).executable_spans
    if not spans:
        return frozenset()
    inside: set[int] = set()
    for start, end in spans:
        first = source.count("\n", 0, start) + 1
        # `end - 1` is the span's last character: an unterminated body runs to
        # end-of-file, and its trailing newline must not add a phantom line.
        last = first + source.count("\n", start, end - 1)
        inside.update(range(first, last + 1))
    return frozenset(inside)


def split_statements(masked: str) -> list[Statement]:
    """Split already-masked SQL into `;`-delimited statements."""
    statements: list[Statement] = []
    current: Statement = []
    for lineno, raw in enumerate(masked.splitlines(), start=1):
        line = raw
        while ";" in line:
            head, _, line = line.partition(";")
            current.append((lineno, head))
            statements.append(current)
            current = []
        if line:
            current.append((lineno, line))
    if current:
        statements.append(current)
    return statements


def locate(statement: Statement, offset: int) -> SourceLocation:
    r"""Map a char `offset` into `"\n".join(text)` back to a 1-based `(line, col)`."""
    pos = 0
    for lineno, text in statement:
        if offset <= pos + len(text):
            return SourceLocation(lineno, offset - pos + 1)
        pos += len(text) + 1
    last_lineno, last_text = statement[-1]
    return SourceLocation(last_lineno, len(last_text) + 1)


@dataclass(frozen=True, slots=True)
class Diagnostic:
    path: Path
    line: int
    col: int
    code: str
    message: str

    def format(self) -> str:
        return f"{self.path}:{self.line}:{self.col}: {self.code} {self.message}"


_MODEL_OWNED_SUFFIX = (
    " This migration is generator-owned, so the edit belongs in the schema model "
    "(`schema.prisma`, the Drizzle schema module, the Atlas HCL) followed by a new "
    "migration — editing this file directly is reverted by the next generate."
)


def redirect_to_model(diags: list[Diagnostic], *, model_owned: bool) -> list[Diagnostic]:
    """Retain generated-migration findings while directing the fix to the source model."""
    if not model_owned:
        return diags
    return [replace(d, message=d.message + _MODEL_OWNED_SUFFIX) for d in diags]


class Rule(ABC):
    id: str
    code: str
    description: str
    documentation: ClassVar[RuleDocumentation | None] = None

    @abstractmethod
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        raise NotImplementedError

    @classmethod
    def native_spec(cls) -> NativeRuleSpec | None:
        """Adapt source-owned documentation while deriving engine, ID, and code."""
        authored = cls.documentation
        if authored is None:
            return None
        if cls.id in authored.aliases:
            msg = f"{cls.id}: a live rule ID cannot also be a historical alias"
            raise ValueError(msg)
        if authored.summary != cls.description:
            msg = f"{cls.id}: description must be the authored documentation summary"
            raise ValueError(msg)
        return NativeRuleSpec(
            engine="sql",
            rule_id=cls.id,
            code=cls.code,
            summary=authored.summary,
            rationale=authored.rationale,
            remediation=authored.remediation,
            category=authored.category,
            autofix=authored.autofix,
            aliases=authored.aliases,
            limitations=authored.limitations,
            examples=authored.examples,
        )

    @classmethod
    def public_examples(cls) -> tuple[RuleExample, ...]:
        """Return the rule's explicitly publishable canonical fixtures."""
        spec = cls.native_spec()
        return () if spec is None else spec.public_examples
