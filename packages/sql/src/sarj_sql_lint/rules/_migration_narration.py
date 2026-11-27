from __future__ import annotations

import re
from typing import TYPE_CHECKING, NamedTuple

from sarj_sql_lint._postgres_ctas import mask_copy_input
from sarj_sql_lint.rule_base import (
    Diagnostic,
    SourceComment,
    dollar_quoted_lines,
    is_dump_file,
    is_generated_migration,
    is_migration_source,
    physical_lines,
    sql_comments,
)


if TYPE_CHECKING:
    from pathlib import Path


_MIN_LINES = 4
_MIN_WORDS = 28
_MIN_NARRATION_CUES = 2
_TEST_PATH_PARTS = frozenset({"test", "tests", "__tests__", "testing", "fixture", "fixtures", "snapshot", "snapshots"})
_GENERATED_PATH_PARTS = frozenset({"generated", "gen"})
_REFERENCE_RE = re.compile(
    r"https?://|`[^`]+`|->|@>|\b(?:RFC[- ]?\d+|CVE-\d{4}-\d+)\b|#\d+",
    re.IGNORECASE,
)
_PROJECT_TICKET_RE = re.compile(r"\b[A-Z][A-Z0-9]{1,9}-\d+\b")
_DIRECTIVE_RE = re.compile(
    r"^(?:sarj-noqa|sqlfluff|noqa|squawk-ignore|dialect\s*:|migrate:|\+migrate|\+goose|"
    r"liquibase|changeset\b|rollback\b|preconditions?\b|atlas:|pgroll:|flyway:|pg_dump:)",
    re.IGNORECASE,
)
_LIST_ITEM_RE = re.compile(r"^(?:[-*+] |\d+[.)] )")
_DURABLE_CONSTRAINT_RE = re.compile(
    r"\b(?:roll\s*back|restore|lock(?:ing|ed|s)?|deadlock|timeout|data[- ]loss|security|permission|"
    r"compatibility|backfill|replica|transaction|invariant|constraint|drift|idempoten\w*|concurren\w*|"
    r"deploy\w*|cutover|transition|writer|reader|provenance|compare-and-swap|key rotation|row-level security|RLS)\b|"
    r"\b(?:because|otherwise|therefore|rather than|so that|in order to|to (?:avoid|prevent)|"
    r"(?:avoid|prevent|preserve|protect|permit)s?|only after|once|until|unless|throughout)\b|"
    r"\b\d+\s*(?:ms|s|seconds?|minutes?|hours?|rows?|bytes?|kb|mb|gb)\b",
    re.IGNORECASE,
)
_IMPLEMENTATION_VERB = (
    r"(?:create(?:s|d|ing)?|add(?:s|ed|ing)?|define(?:s|d|ing)?|store(?:s|d|ing)?|"
    r"contain(?:s|ed|ing)?|hold(?:s|ing)?|set(?:s|ting)?|update(?:s|d|ing)?|delete(?:s|d|ing)?|"
    r"drop(?:s|ped|ping)?|rename(?:s|d|ing)?|alter(?:s|ed|ing)?|insert(?:s|ed|ing)?|"
    r"grant(?:s|ed|ing)?|use(?:s|d|ing)?|represent(?:s|ed|ing)?|reference(?:s|d|ing)?)"
)
_SCHEMA_OBJECT = r"(?:table|column|index|type|constraint|row|field|schema|record)s?"
_NARRATION_RE = re.compile(
    r"^(?:(?:this|the|a|an|each|every)\s+(?:next\s+|following\s+|final\s+|previous\s+)?"
    r"(?:migration|statement|table|column|index|type|constraint|row)\s+"
    r"(?:(?:must|will|does|can)\s+)?"
    rf"{_IMPLEMENTATION_VERB}\b|"
    r"(?:this|it|we|these|those)\s+(?:(?:also|then|finally)\s+)?"
    rf"{_IMPLEMENTATION_VERB}\b|"
    rf"finally,?\s+(?:this\s+)?{_IMPLEMENTATION_VERB}\b|"
    r"(?:the\s+)?(?:next|following|final|previous|above|below)\s+"
    r"(?:statement|query|declaration|definition|step)\b|"
    rf"{_IMPLEMENTATION_VERB}\s+(?:(?:the|a|an|this|these|those|each|every)\s+)?"
    rf"(?:[A-Za-z][\w-]*\s+){{0,3}}{_SCHEMA_OBJECT}\b)",
    re.IGNORECASE,
)


class _CommentLine(NamedTuple):
    line: int
    column: int
    text: str


def migration_narration(path: Path, source: str, code: str) -> list[Diagnostic]:
    source = mask_copy_input(source)
    path_parts = frozenset(part.lower() for part in path.parts)
    if (
        not path_parts.isdisjoint(_TEST_PATH_PARTS | _GENERATED_PATH_PARTS)
        or is_dump_file(source, path)
        or not is_migration_source(path, source)
        or is_generated_migration(path, source)
    ):
        return []
    findings: list[Diagnostic] = []
    executable_lines = dollar_quoted_lines(source)
    for group in _comment_groups(source):
        for run in _narrative_runs(group, executable_lines):
            words = sum(len(line.text.split()) for line in run)
            findings.append(
                Diagnostic(
                    path,
                    run[0].line,
                    run[0].column,
                    code,
                    f"Narrative migration comment repeats implementation across {len(run)} lines/{words} words; "
                    "delete it or retain only the specific operational constraint.",
                )
            )
    return findings


def _comment_groups(source: str) -> list[list[SourceComment]]:
    source_lines = physical_lines(source)
    groups: list[list[SourceComment]] = []
    for comment in sql_comments(source):
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
        and _is_standalone_comment(source_lines, previous)
        and _is_standalone_comment(source_lines, current)
    )


def _is_standalone_comment(source_lines: list[str], comment: SourceComment) -> bool:
    if comment.line < 1 or comment.line > len(source_lines):
        return False
    return not source_lines[comment.line - 1][: comment.column - 1].strip()


def _narrative_runs(group: list[SourceComment], executable_lines: frozenset[int]) -> list[list[_CommentLine]]:
    findings: list[list[_CommentLine]] = []
    candidate: list[_CommentLine] = []
    for line in (item for comment in group for item in _comment_lines(comment)):
        if line.line in executable_lines or not line.text:
            _append_if_long(findings, candidate)
            candidate = []
            continue
        if _is_protected(line.text):
            continue
        candidate.append(line)
    _append_if_long(findings, candidate)
    return findings


def _comment_lines(comment: SourceComment) -> list[_CommentLine]:
    return [
        _CommentLine(
            comment.line + offset,
            comment.column if offset == 0 else 1,
            raw.strip().lstrip("*").strip(),
        )
        for offset, raw in enumerate(physical_lines(comment.body))
    ]


def _is_protected(text: str) -> bool:
    return bool(
        _DIRECTIVE_RE.match(text)
        or _LIST_ITEM_RE.match(text)
        or _REFERENCE_RE.search(text)
        or _PROJECT_TICKET_RE.search(text)
        or _DURABLE_CONSTRAINT_RE.search(text)
    )


def _append_if_long(findings: list[list[_CommentLine]], candidate: list[_CommentLine]) -> None:
    if (
        len(candidate) >= _MIN_LINES
        and sum(len(line.text.split()) for line in candidate) >= _MIN_WORDS
        and sum(_NARRATION_RE.match(line.text) is not None for line in candidate) >= _MIN_NARRATION_CUES
    ):
        findings.append(candidate.copy())
