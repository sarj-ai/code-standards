from __future__ import annotations

import re
from typing import TYPE_CHECKING

from sarj_rule_contracts import TextEdit, apply_edits
from sqlglot import exp
from sqlglot.errors import SqlglotError

from sarj_sql_lint._autofix_literals import literal_edits
from sarj_sql_lint._postgres import parse_postgres
from sarj_sql_lint.rule_base import (
    has_file_comment_match,
    is_generated_migration,
    is_mysql,
    is_sqlite,
    is_suppressed,
    mask_sql,
    physical_lines,
    source_location,
    sql_comments,
)
from sarj_sql_lint.rules import REGISTRY
from sarj_sql_lint.rules.idempotent_ddl import ddl_checks
from sarj_sql_lint.rules.no_comment_cruft import (
    COMMENT_DIRECTIVE_RE,
    COMMENT_REFERENCE_RE,
    ROLLBACK_CONTEXT_RE,
    is_decorative_banner,
    is_supported_disabled_statement,
    split_disabled_statements,
)


if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from sarj_sql_lint.rule_base import Diagnostic


_GENERATED_HEADER = re.compile(r"generated.{0,80}(?:do not edit|don't edit)", re.IGNORECASE)
_PRESERVED_COMMENT = re.compile(
    r"\b(?:copyright|spdx|licen[cs]e|sarj-noqa|noqa|tflint|checkov|tfsec|trivy|shellcheck|yamllint|markdownlint|prettier-ignore|eslint|ruff|pyright|sqlfluff|squawk-ignore)\b|(?:coding|encoding)\s*[:=]",
    re.IGNORECASE,
)


def fix_source(path: Path, source: str, *, rule_ids: Sequence[str] | None = None) -> str:
    selected = tuple(REGISTRY) if rule_ids is None else tuple(rule_ids)
    if unknown := set(selected) - REGISTRY.keys():
        message = f"unknown SQL rules: {', '.join(sorted(unknown))}"
        raise ValueError(message)
    if (
        is_generated_migration(path, source)
        or has_file_comment_match(source, _GENERATED_HEADER, limit=2048)
        or not _parseable(source)
    ):
        return source
    edits: list[TextEdit] = []
    for rule_id in selected:
        if rule_id not in {
            "idempotent-ddl",
            "no-migration-comment-cruft",
            "no-long-migration-narration",
            "prefer-text-over-varchar",
            "prefer-jsonb",
            "enforce-timestamptz",
        }:
            continue
        diagnostics = [
            diagnostic
            for diagnostic in REGISTRY[rule_id]().check(path, source)
            if not is_suppressed(source, diagnostic.line, diagnostic.code)
        ]
        if rule_id == "idempotent-ddl" and not (is_mysql(source) or is_sqlite(source)):
            edits.extend(_existence_guards(source, diagnostics))
        elif rule_id in {"no-migration-comment-cruft", "no-long-migration-narration"}:
            edits.extend(_comment_edits(source, diagnostics, banners=rule_id == "no-migration-comment-cruft"))
        else:
            edits.extend(literal_edits(source, diagnostics, rule_id))
    fixed = apply_edits(source, edits)
    return fixed if _parseable(fixed) else source


def _parseable(source: str) -> bool:
    try:
        statements = parse_postgres(source)
    except SqlglotError, RecursionError:
        return False
    return not any(statement is not None and statement.find(exp.Command) is not None for statement in statements)


def _existence_guards(source: str, diagnostics: Sequence[Diagnostic]) -> list[TextEdit]:
    positions = {diagnostic.line for diagnostic in diagnostics}
    masked = mask_sql(source, mask_dollar_literals=True)
    edits: list[TextEdit] = []
    for check in ddl_checks(source):
        for match in check.pattern.finditer(masked):
            if source_location(source, match.start()).line not in positions or not _ddl_statement(
                masked, match.start()
            ):
                continue
            end = match.end()
            if re.search(r"\bINDEX\s*$", match.group(), re.IGNORECASE) and (
                concurrently := re.match(r"CONCURRENTLY\b\s*", masked[end:], re.IGNORECASE)
            ):
                end += concurrently.end()
            guard = "IF EXISTS " if match.group().upper().startswith("DROP") else "IF NOT EXISTS "
            edits.append(TextEdit(end, end, guard))
    return edits


def _ddl_statement(masked: str, position: int) -> bool:
    start = masked.rfind(";", 0, position) + 1
    return re.match(r"\s*(?:CREATE|DROP|ALTER)\b", masked[start:], re.IGNORECASE) is not None


def _comment_edits(source: str, diagnostics: Sequence[Diagnostic], *, banners: bool) -> list[TextEdit]:
    edits: list[TextEdit] = []
    lines = physical_lines(source, keepends=True)
    standalone = _standalone_comment_lines(source, lines)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    for diagnostic in diagnostics:
        if diagnostic.line - 1 not in standalone:
            continue
        first = diagnostic.line - 1
        last = first + 1
        while first - 1 in standalone:
            first -= 1
        while last in standalone:
            last += 1
        edits.extend(_comment_group_edits(lines, offsets, first, last, banners=banners))
    return edits


def _standalone_comment_lines(source: str, lines: Sequence[str]) -> set[int]:
    return {
        comment.line - 1
        for comment in sql_comments(source, mask_dollar_literals=True)
        if not comment.block
        and 0 < comment.line <= len(lines)
        and not lines[comment.line - 1][: comment.column - 1].strip()
    }


def _comment_group_edits(
    lines: Sequence[str], offsets: Sequence[int], first: int, last: int, *, banners: bool
) -> list[TextEdit]:
    bodies = [line.lstrip()[2:].strip() for line in lines[first:last]]
    banner_lines = {
        first + index
        for index, body in enumerate(bodies)
        if banners and is_decorative_banner(body) and not _PRESERVED_COMMENT.search(body)
    }
    payload = "\n".join(body for index, body in enumerate(bodies) if first + index not in banner_lines)
    if _disabled_sql_only(payload, bodies):
        replacement = "".join(re.findall(r"\r\n|\r|\n", "".join(lines[first:last])))
        return [TextEdit(offsets[first], offsets[last], replacement)]
    return [
        TextEdit(offsets[index], offsets[index] + len(lines[index].rstrip("\r\n")), "")
        for index in sorted(banner_lines)
    ]


def _disabled_sql_only(payload: str, bodies: Sequence[str]) -> bool:
    statements = split_disabled_statements(payload)
    if (
        not payload.rstrip().endswith(";")
        or not statements
        or not all(is_supported_disabled_statement(statement) for statement in statements)
    ):
        return False
    return not (
        any(COMMENT_DIRECTIVE_RE.match(body) or COMMENT_REFERENCE_RE.search(body) for body in bodies)
        or ROLLBACK_CONTEXT_RE.search(payload)
        or _PRESERVED_COMMENT.search("\n".join(bodies))
    )
