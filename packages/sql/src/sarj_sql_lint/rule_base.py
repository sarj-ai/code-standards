"""Base types and shared SQL text utilities for sarj-sql-lint rules."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
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


def is_suppressed(source_lines: list[str], line: int, code: str) -> bool:
    """Report whether the diagnostic's line carries a `-- sarj-noqa[: CODE]` comment.

    Returns:
        True when the line is suppressed for `code`.

    """
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

    Corpus evidence (bulbul + noura-be, 239 tracked `.sql` files, 9,108 lines).
    Blanking the bodies hid **26 live DDL/DML keywords across 12 files** from all
    8 rules — 19 `UPDATE`, 3 `ALTER TABLE`, 2 `DELETE FROM`, 2 `INSERT INTO`.
    Named examples:

    * `bulbul/.../20250817124731_migrate_rewaa_calls_to_their_org.sql:21,31,60,70`
      — four `UPDATE public.batch` / `UPDATE public.call` re-owning statements
      inside a `DO $$ ... $$` block,
    * `bulbul/.../20251214112241_delete_batch_and_related_calls.sql:18,22`
      — `DELETE FROM batch` / `DELETE FROM call` inside a `DO $$ ... $$` block,
    * `bulbul/.../20260112190150_add_character_count_to_kb_files.sql:32`
      — `ALTER TABLE knowledge_base_file ADD CONSTRAINT ...` inside a `DO` block,
    * `noura-be/digital-bank/banking-be/migrations/028_seed_ajb_bank.sql:21`
      — `INSERT INTO banks (...)` inside a `DO $$ ... $$` block.

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
    SARJ105 hits — `noura-be/.../022_seed_banks.sql:34` and
    `noura-be/.../028_seed_ajb_bank.sql:21` — are both **false positives**: each
    `INSERT` sits in a `DO $$ ... $$` seed block already guarded by
    `IF EXISTS (SELECT 1 FROM banks WHERE code = ...) THEN CONTINUE/RETURN`, which
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
    (`noura-be/.../022_seed_banks.sql:34`, `noura-be/.../028_seed_ajb_bank.sql:21`)
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


class Rule(ABC):
    id: str
    code: str
    description: str

    @abstractmethod
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        raise NotImplementedError
