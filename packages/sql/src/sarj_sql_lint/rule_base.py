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

# A dollar-quote delimiter: `$$` or `$tag$`, where `tag` is an identifier. The tag
# may NOT start with a digit, which is what keeps `$1`/`$2` positional parameters
# from ever matching (there is no `$1$` delimiter in Postgres).
_DOLLAR_DELIM_RE = re.compile(r"\$(?:[A-Za-z_][A-Za-z0-9_]*)?\$")
_IDENT_CHAR_RE = re.compile(r"[A-Za-z0-9_]")


def is_dump_file(source: str, path: Path | None = None) -> bool:
    """Report whether source text or path indicates an auto-generated schema dump file.

    Returns:
        True if the file is a schema dump.

    """
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


# Tokens that exist in MySQL / MariaDB / SQLite and cannot appear in Postgres DDL.
# Backtick-quoted identifiers are the strongest single signal: Postgres has no
# backtick quoting at all, and both MySQL and SQLite (including everything Drizzle
# emits for either) use it by default.
_NON_POSTGRES_RE = re.compile(
    r"`[^`\n]+`"  # backtick-quoted identifier — MySQL, MariaDB, SQLite
    r"|\bAUTO_INCREMENT\b"  # MySQL column attribute
    r"|\bAUTOINCREMENT\b"  # SQLite column attribute
    r"|\bENGINE\s*="  # MySQL table option (`ENGINE=InnoDB`)
    r"|\bCOLLATE\s+utf8"  # MySQL collation family (`utf8mb4_unicode_ci`)
    r"|\bUNSIGNED\b",  # MySQL integer modifier
    re.IGNORECASE,
)

# Tokens exclusive to MySQL / MariaDB. Deliberately narrower than
# `_NON_POSTGRES_RE`: SQLite is *not* MySQL, and a rule whose premise fails only
# under MySQL (SARJ102 — SQLite does support `CREATE TABLE/INDEX IF NOT EXISTS`)
# must not be silenced by a backtick that only proves "not Postgres".
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
    """Return an explicit dialect declared in a leading SQL line comment.

    A narrow directive lets hand-written migrations state their dialect without
    relying on vendor-specific syntax happening to appear in every file. Free-form
    comments remain ignored, so prose cannot accidentally change rule scope.

    """
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
    """Report whether `source` is free of any non-Postgres dialect marker.

    Several rules encode a *Postgres* fact — `SET lock_timeout` (SARJ110),
    `CREATE INDEX CONCURRENTLY` (SARJ108), "VARCHAR(n) buys nothing over TEXT"
    (SARJ104). None of those is true of MySQL or SQLite, where the same advice is
    at best a no-op and at worst a syntax error or actively harmful (MySQL `TEXT`
    cannot carry a `DEFAULT`, is stored off-page, and has an index-prefix limit).

    Corpus measurement over 2,134 deduped `.sql` files: 337 carry at least one
    marker above, and **zero of those 337 also carry a Postgres-only token**
    (`JSONB`, `SERIAL`/`BIGSERIAL`, a `::` cast, `TIMESTAMPTZ`,
    `gen_random_uuid`, `uuid_generate_v4`, `USING gin|gist|btree|hash|brin`,
    `CREATE EXTENSION`, `TEXT[]`). The two populations are disjoint, so treating a
    marker as decisive costs no Postgres recall — it is a partition, not a
    heuristic. 288 of the 337 are caught by the backtick alone.

    Pass `mask_sql` output, or raw source when the rule has not masked yet; a
    backtick inside a comment or a `'...'` literal is blanked by the masker and so
    cannot fake a dialect.

    Returns:
        True when nothing in `source` contradicts Postgres.

    """
    dialect = declared_dialect(source)
    if dialect is not None:
        return dialect == "postgresql"
    return _NON_POSTGRES_RE.search(source) is None


def is_mysql(source: str) -> bool:
    """Report whether `source` carries a MySQL/MariaDB-exclusive token.

    Narrower than `not is_postgres(...)` on purpose — see `_MYSQL_RE`. Corpus:
    143 of 2,134 deduped `.sql` files, none of which carries a Postgres-only
    token.

    Returns:
        True when `source` is MySQL/MariaDB.

    """
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
    """Report whether `directory` or an ancestor is a generator-owned migration root.

    Returns:
        True when a Prisma/Drizzle/Atlas marker file is found at or above `directory`.

    """
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
    """Report whether `path` is a migration emitted by a schema-migration generator.

    Prisma, Drizzle and Atlas compile a *model* (`schema.prisma`, a Drizzle schema
    module, an Atlas HCL schema) down to SQL. For a rule whose fix lives in that
    model — column type, enum choice, JSON vs JSONB, UUID default — the `.sql`
    file is a build artifact: hand-editing it is reverted by the next
    `prisma migrate` / `drizzle-kit generate`, and applied migrations are immutable
    by construction (Prisma checksums them in `_prisma_migrations` and
    `migrate deploy` errors on drift). Pointing a diagnostic there asks for a
    change that cannot be made and would not survive if it were.

    Detection is a marker file at or above the migration directory
    (`migration_lock.toml`, `meta/_journal.json`, `atlas.sum`) plus Drizzle's
    `--> statement-breakpoint` content sentinel for trees checked out without
    their metadata. Measured coverage: 9,799 of 12,614 pre-dedupe SQL findings.

    Deliberately **not** applied to SARJ108, SARJ110, SARJ111 or SARJ112. Those
    name a production lock or outage risk that survives regeneration, and a
    reviewer fixes them by hand-editing a `--create-only` migration *before* it
    ships — the diagnostic is actionable exactly when it matters. The generic
    Python `_paths.is_generated` is no substitute here: it matches 0 of these
    files, because Prisma and Drizzle emit no generated-file banner and their
    directories are not in `_GENERATED_DIR_NAMES`.

    Returns:
        True when `path` is inside a generator-owned migration tree.

    """
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
    """Replace every char with a space, keeping newlines so offsets are preserved.

    Returns:
        `segment` with every non-newline character turned into a space.

    """
    return _NON_NEWLINE.sub(" ", segment)


def _scan_quoted(source: str, start: int, quote: str) -> int:
    """Index just past a `quote`-delimited run starting at `start`, honoring `''`/`""`.

    Returns:
        The index one past the closing quote, or `len(source)` if unterminated.

    """
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
    """Return the dollar-quote delimiter opening at `i`, or None if one does not.

    Two things must hold. The text at `i` must look like `$$` or `$tag$` — the tag
    is an identifier, so a leading digit is impossible and `$1`/`$2` positional
    parameters can never match. And `i` must not sit inside an identifier: Postgres
    allows `$` as a non-leading identifier character, so the `$` in `total$amount`
    or `foo$bar$` is part of the name and opens nothing. The check is deliberately
    NOT applied when looking for a *closing* delimiter — once the lexer is inside a
    dollar-quoted body identifier rules no longer apply, so `END$$;` really does
    close a `$$` body.

    Returns:
        The delimiter text (`"$$"`, `"$func$"`, ...), or None.

    """
    if i > 0 and _IDENT_CHAR_RE.match(source, i - 1) is not None:
        return None
    m = _DOLLAR_DELIM_RE.match(source, i)
    return None if m is None else m.group(0)


def _closing_depth(source: str, i: int, open_tags: list[str]) -> int | None:
    """Index in `open_tags` of the outermost open delimiter that closes at `i`.

    Outermost wins: an inner `$b$` left unterminated inside a `$a$` body must not
    stop the `$a$` body from ending, so hitting `$a$` pops `$b$` along with it.

    Returns:
        The index into `open_tags`, or None when nothing closes here.

    """
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
    r"""Blank out comments, string literals and quoted identifiers; KEEP dollar-quoted bodies.

    The returned text has the same length and line structure as `source` — masking
    replaces characters with spaces and never deletes or reflows, so line numbers
    (and therefore `-- sarj-noqa`, which is line-keyed) survive unchanged.

    Blanked: `--` and `/* */` comment bodies, `'...'` literals, `"..."` identifiers,
    and the `$$` / `$tag$` *delimiters* themselves.

    NOT blanked: the body between dollar-quote delimiters. A `$$ ... $$` body in a
    migration is not string *data*, it is live SQL — a `DO $$ ... $$` block or a
    `CREATE FUNCTION ... AS $$ ... $$` body — and blanking it hid real DDL/DML from
    every rule. The body is re-scanned by this same masker, so strings and comments
    *inside* it are still masked and a nested `$inner$ ... $inner$` is handled.

    Corpus evidence (two first-party repos, 239 tracked `.sql` files, 9,108
    lines). Blanking the bodies hid **26 live DDL/DML keywords across 12 files**
    from all 8 rules — 19 `UPDATE`, 3 `ALTER TABLE`, 2 `DELETE FROM`,
    2 `INSERT INTO`. Named examples:

    * a tenant-reassignment data migration, 4 lines — four
      `UPDATE public.<parent>` / `UPDATE public.<child>` re-owning statements
      inside a `DO $$ ... $$` block,
    * a cascade-cleanup migration, 2 lines — `DELETE FROM <parent>` /
      `DELETE FROM <child>` inside a `DO $$ ... $$` block,
    * an add-column migration, 1 line —
      `ALTER TABLE <table> ADD CONSTRAINT ...` inside a `DO` block,
    * a reference-data seed migration, 1 line — `INSERT INTO <table> (...)`
      inside a `DO $$ ... $$` block.

    A raw-vs-masked keyword diff reports a larger 50 for the same corpus, but 24 of
    those are prose inside `--` comments *within* the bodies (`-- Step 1: Update the
    'batch' table`) which stay masked either way. 26 is the number of keywords that
    actually become visible to a rule.

    This was also a cross-language divergence: `strip_sql_noise` in the sibling
    Python package (`sarj_python_lint/rules/_sql.py`) has no dollar branch at all,
    so the *same* SQL text was judged when embedded in a `.py` string and unjudged
    when it lived in a `.sql` migration — the gap favoured the riskier file type.
    Keeping the body closes the gap from the `.sql` side.

    Net effect on the corpus (post-`sarj-noqa` findings before -> after):
    SARJ101 23 -> 23, SARJ102 250 -> 250, SARJ103 0 -> 0, SARJ104 140 -> 140,
    SARJ106 0 -> 0, SARJ107 0 -> 0, SARJ108 334 -> 334, and **SARJ105
    insert-requires-on-conflict 17 -> 19**. Nothing is lost anywhere. The two new
    SARJ105 hits — both reference-data seed migrations in one first-party repo
    — are both **false positives**: each
    `INSERT` sits in a `DO $$ ... $$` seed block already guarded by
    `IF EXISTS (SELECT 1 FROM <table> WHERE code = ...) THEN CONTINUE/RETURN`, which
    is a perfectly good replay guard, and `ON CONFLICT` there would be redundant.
    That is 2 of 2 new hits wrong, so SARJ105 wants a function-body exemption to
    go with this change — `if diagnostic_line in dollar_quoted_lines(source)`
    drops exactly those two and nothing else (19 -> 17). The other seven rules are
    line-local type/DDL checks whose premise holds inside a body just as it does
    outside, and none of them moved, so none needs an exemption.

    Known, deliberate divergences from the Postgres lexer, both in the safe
    direction: a `$$` sitting inside a `--`/`/* */` comment or inside a `'...'`
    literal *within* a body does not terminate that body (Postgres, which treats
    the body as raw text, would let it). Reading the body as SQL is what makes
    comments inside `DO` blocks stay masked, which is overwhelmingly the common
    case in the corpus. An unterminated delimiter keeps the rest of the file as
    SQL rather than swallowing it.

    Returns:
        A same-length copy of `source` with those spans blanked.

    """
    masked, _ = _scan(source)
    return masked


def dollar_quoted_lines(source: str) -> frozenset[int]:
    """1-based line numbers that fall inside a `$$ ... $$` / `$tag$ ... $tag$` body.

    `mask_sql` deliberately keeps those bodies as SQL, which is what lets rules see
    the DDL/DML inside `DO` blocks and function bodies. A rule whose premise is
    *migration-level* rather than statement-level can use this to exempt them:
    `if diagnostic.line in dollar_quoted_lines(source): continue`.

    SARJ105 insert-requires-on-conflict is the live case. Its premise is migration
    replay, but a `DO $$ ... $$` seed block guards its own replay with
    `IF EXISTS (...) THEN CONTINUE/RETURN` instead of `ON CONFLICT`, and both new
    SARJ105 findings unlocked by keeping bodies visible are that shape
    (two reference-data seed migrations in one first-party repo)
    — 2 of 2 wrong. Applying this exemption there takes SARJ105 from 19 back to 17
    over the corpus, removing exactly those two and nothing else. The other seven
    rules are line-local type/DDL checks that are equally true inside a body, and
    none of them changed count, so none should use this.

    The delimiter lines themselves are included when any part of the body shares
    the line.

    Returns:
        The 1-based line numbers covered by a dollar-quoted body.

    """
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
    """Split already-masked SQL into `;`-delimited statements.

    Operates on `mask_sql` output so a `;` inside a string/comment (now blank) never
    splits a statement. Each statement is a list of `(lineno, text)` fragments.

    Returns:
        One `Statement` per `;`-delimited run, in source order.

    """
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
    r"""Map a char `offset` into `"\n".join(text)` back to a 1-based `(line, col)`.

    Returns:
        The 1-based `(line, col)` for `offset`, clamped to the statement's end.

    """
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
    """Point a schema diagnostic at the model when the migration is generated.

    This deliberately REDIRECTS rather than suppresses. A wrong column type, a
    native enum, a `VARCHAR(n)` cap, a `json` column or a v4 UUID default is a
    property of the deployed database, and it survives regeneration exactly as
    the lock and outage risks in SARJ108/110/111/112 do — those are not exempted
    either, for the same reason.

    Suppressing instead was measured and rejected. On the 2,133-file corpus it
    took SARJ101 from 770 to 12, SARJ102 from 3,079 to 246 and SARJ103 from 283
    to **0** — while the genuine false-positive guards on those same rules were
    worth only 23, 79 and 0 findings respectively. Sampling had put SARJ101 at
    ~3% false positives and SARJ102 at 4.2%, so all but a sliver of what the
    exemption removed was true. A rule that fires zero times on 2,133 files is
    not precise, it is off.

    Returns:
        `diags` unchanged, or with the model-redirect note appended to each.

    """
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
