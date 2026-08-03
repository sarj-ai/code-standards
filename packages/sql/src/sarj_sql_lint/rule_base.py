"""Base types and shared SQL text utilities for sarj-sql-lint rules."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path
import re


type Statement = list[tuple[int, str]]
"""A statement as `(lineno, text)` fragments — one per source line it spans."""


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
_SQLITE_RE = re.compile(r"\bAUTOINCREMENT\b", re.IGNORECASE)


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
    return _NON_POSTGRES_RE.search(source) is None


def is_mysql(source: str) -> bool:
    """Report whether `source` carries a MySQL/MariaDB-exclusive token."""
    dialect = declared_dialect(source)
    if dialect is not None:
        return dialect == "mysql"
    return _MYSQL_RE.search(source) is not None


def is_sqlite(source: str) -> bool:
    """Report whether source explicitly declares or syntactically signals SQLite."""
    dialect = declared_dialect(source)
    if dialect is not None:
        return dialect == "sqlite"
    return _SQLITE_RE.search(source) is not None


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
    """Identify generated migrations so findings redirect to models instead of disappearing."""
    if _GENERATED_MIGRATION_SENTINEL in source:
        return True
    return _has_generated_marker(path.parent)


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


def _blank(segment: str) -> str:
    """Replace every char with a space, keeping newlines so offsets are preserved."""
    return _NON_NEWLINE.sub(" ", segment)


def _scan_quoted(source: str, start: int, quote: str) -> int:
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


def _dollar_open_tag(source: str, i: int) -> str | None:
    """Return the dollar-quote delimiter opening at `i`, or None if one does not."""
    if i > 0 and _IDENT_CHAR_RE.match(source, i - 1) is not None:
        return None
    m = _DOLLAR_DELIM_RE.match(source, i)
    return None if m is None else m.group(0)


def _closing_depth(source: str, i: int, open_tags: list[str]) -> int | None:
    """Index in `open_tags` of the outermost open delimiter that closes at `i`."""
    for depth, tag in enumerate(open_tags):
        if source.startswith(tag, i):
            return depth
    return None


def _scan(source: str) -> tuple[str, list[tuple[int, int]]]:
    out: list[str] = []
    open_tags: list[str] = []
    spans: list[tuple[int, int]] = []
    body_start = 0
    i = 0
    chunk_start = 0
    n = len(source)

    while i < n:
        ch = source[i]
        if ch == "$" and open_tags:
            depth = _closing_depth(source, i, open_tags)
            if depth is not None:
                if i > chunk_start:
                    out.append(source[chunk_start:i])
                tag = open_tags[depth]
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
        elif pair == "/*":
            close = source.find("*/", i + 2)
            end = n if close == -1 else close + 2
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
    return "".join(out), spans


def mask_sql(source: str) -> str:
    r"""Blank comments, strings, identifiers, and dollar delimiters without shifting offsets while keeping procedural SQL bodies live."""
    masked, _ = _scan(source)
    return masked


def dollar_quoted_lines(source: str) -> frozenset[int]:
    """Locate dollar bodies for rules with an explicit procedural-migration exemption."""
    _, spans = _scan(source)
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


def locate(statement: Statement, offset: int) -> tuple[int, int]:
    r"""Map a char `offset` into `"\n".join(text)` back to a 1-based `(line, col)`."""
    pos = 0
    for lineno, text in statement:
        if offset <= pos + len(text):
            return lineno, offset - pos + 1
        pos += len(text) + 1
    last_lineno, last_text = statement[-1]
    return last_lineno, len(last_text) + 1


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

    @abstractmethod
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        raise NotImplementedError
