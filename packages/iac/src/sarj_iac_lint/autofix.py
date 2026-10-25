from __future__ import annotations

import re
from typing import TYPE_CHECKING

from sarj_rule_contracts import TextEdit, apply_edits

from sarj_iac_lint._hcl import (
    document,
    heredoc_body_mask,
    literal_string,
    literal_token,
    physical_lines,
    suppression_comment_lines,
    tokens,
)
from sarj_iac_lint._literal_conditional_fix import literal_conditional_edits
from sarj_iac_lint.rule_base import is_suppressed
from sarj_iac_lint.rules import REGISTRY
from sarj_iac_lint.rules.no_comment_cruft import is_comment_directive, is_decorative_banner
from sarj_iac_lint.rules.no_restated_comment import comment_candidates, has_generated_header


if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

    from sarj_iac_lint._hcl import Block
    from sarj_iac_lint.rule_base import Diagnostic
    from sarj_iac_lint.rules.no_restated_comment import CommentCandidate


_COMMENT = re.compile(r"\s*(?:#|//)\s?(.*)")
_ASSERTION_ATTRIBUTES = frozenset({"condition", "error_message"})
_FIXABLE = frozenset(
    {
        "no-comment-cruft",
        "no-restated-comment",
        "no-redundant-variable-validation",
        "no-terraform-data-condition",
        "no-nested-conditional",
    }
)
_PRESERVED_COMMENT = re.compile(
    r"\b(?:copyright|spdx|licen[cs]e|sarj-noqa|noqa|tflint|checkov|tfsec|trivy|shellcheck|yamllint|markdownlint|prettier-ignore|eslint|ruff|pyright|sqlfluff|squawk-ignore)\b|(?:coding|encoding)\s*[:=]",
    re.IGNORECASE,
)


def fix_source(path: Path, source: str, *, rule_ids: Sequence[str] | None = None) -> str:
    selected = tuple(REGISTRY) if rule_ids is None else tuple(rule_ids)
    if unknown := set(selected) - REGISTRY.keys():
        message = f"unknown IaC rules: {', '.join(sorted(unknown))}"
        raise ValueError(message)
    if (
        path.suffix.lower() not in {".tf", ".tfvars", ".hcl"}
        or any(part.lower() in {"fixture", "fixtures", "testdata", "generated"} for part in path.parts)
        or has_generated_header(source)
        or not _balanced(source)
    ):
        return source
    comments = suppression_comment_lines(source)
    lines = physical_lines(source, keepends=True)
    edits: list[TextEdit] = []
    comment_edits: list[TextEdit] = []
    for rule_id in selected:
        if rule_id not in _FIXABLE:
            continue
        diagnostics = _rule_diagnostics(path, source, comments, rule_id=rule_id)
        match rule_id:
            case "no-nested-conditional":
                edits.extend(literal_conditional_edits(source, diagnostics))
            case "no-redundant-variable-validation":
                edits.extend(_validation_edits(source, lines, diagnostics))
            case "no-terraform-data-condition":
                edits.extend(_true_condition_edits(source, lines, diagnostics))
            case _:
                comment_edits.extend(
                    _comment_edits(source, lines, diagnostics, restated=rule_id == "no-restated-comment")
                )
    if comment_edits:
        comment_plan = _nonoverlapping(comment_edits)
        if tokens(apply_edits(source, comment_plan)) == tokens(source):
            edits.extend(comment_plan)
    if not edits:
        return source
    fixed = apply_edits(source, _nonoverlapping(edits))
    return fixed if _balanced(fixed) else source


def _rule_diagnostics(path: Path, source: str, comments: Mapping[int, str], *, rule_id: str) -> list[Diagnostic]:
    return [
        diagnostic
        for diagnostic in REGISTRY[rule_id]().check(path, source)
        if not is_suppressed(physical_lines(source), diagnostic.line, diagnostic.code, comments=comments)
    ]


def _nonoverlapping(edits: Sequence[TextEdit]) -> list[TextEdit]:
    nonoverlapping: list[TextEdit] = []
    for edit in sorted(set(edits), key=lambda edit: (edit.start, -edit.end)):
        if not nonoverlapping or edit.start >= nonoverlapping[-1].end:
            nonoverlapping.append(edit)
    return nonoverlapping


def _balanced(source: str) -> bool:
    try:
        items = tokens(source)
    except ValueError:
        return False
    stack: list[str] = []
    for item in items:
        if item in {"{", "[", "("}:
            stack.append(item)
        elif item in {"}", "]", ")"} and (not stack or stack.pop() != {"}": "{", "]": "[", ")": "("}[item]):
            return False
    return not stack and _valid_attributes(document(source))


def _valid_attributes(block: Block) -> bool:
    names = [attribute.name for attribute in block.attributes]
    return (
        len(names) == len(set(names))
        and all(attribute.value.strip() for attribute in block.attributes)
        and all(_valid_attributes(child) for child in block.blocks)
    )


def _line_edit(lines: list[str], first: int, last: int) -> TextEdit:
    start = sum(map(len, lines[: first - 1]))
    original = "".join(lines[first - 1 : last])
    replacement = "".join(re.findall(r"\r\n|\r|\n", original))
    return TextEdit(start, start + len(original), replacement)


def _validation_edits(source: str, lines: list[str], diagnostics: Sequence[Diagnostic]) -> list[TextEdit]:
    allowed = {diagnostic.line for diagnostic in diagnostics}
    comments = suppression_comment_lines(source)
    edits: list[TextEdit] = []
    for variable in document(source).blocks:
        for validation in variable.blocks:
            condition = validation.attribute("condition")
            if validation.type != "validation" or condition is None or condition.line not in allowed:
                continue
            if not _removable_assertion(validation, lines, comments):
                continue
            edits.append(_line_edit(lines, validation.line, validation.end_line))
    return edits


def _true_condition_edits(source: str, lines: list[str], diagnostics: Sequence[Diagnostic]) -> list[TextEdit]:
    allowed = {diagnostic.line for diagnostic in diagnostics}
    comments = suppression_comment_lines(source)
    edits: list[TextEdit] = []
    for resource in document(source).blocks:
        if resource.line not in allowed or (lifecycle := resource.child("lifecycle")) is None:
            continue
        for block in lifecycle.blocks:
            condition = block.attribute("condition")
            if (
                block.type not in {"precondition", "postcondition"}
                or condition is None
                or literal_token(condition.value) != "true"
            ):
                continue
            if not _removable_assertion(block, lines, comments):
                continue
            edits.append(_line_edit(lines, block.line, block.end_line))
    return edits


def _removable_assertion(block: Block, lines: list[str], comments: Mapping[int, str]) -> bool:
    if block.blocks or len(block.attributes) != len(_ASSERTION_ATTRIBUTES):
        return False
    if {attribute.name for attribute in block.attributes} != _ASSERTION_ATTRIBUTES or any(
        line in comments for line in range(block.line, block.end_line + 1)
    ):
        return False
    message = block.attribute("error_message")
    return (
        message is not None
        and literal_string(message.value) is not None
        and re.fullmatch(rf"{block.type}\s*\{{", lines[block.line - 1].strip()) is not None
        and lines[block.end_line - 1].strip() == "}"
    )


def _comment_edits(
    source: str, lines: list[str], diagnostics: Sequence[Diagnostic], *, restated: bool
) -> list[TextEdit]:
    edits: list[TextEdit] = []
    candidates = (
        {
            candidate.line: candidate
            for candidate in comment_candidates(physical_lines(source), heredoc_body_mask(physical_lines(source)))
        }
        if restated
        else {}
    )
    for diagnostic in diagnostics:
        candidate = _diagnosed_comment_edit(lines, diagnostic.line, candidates, restated=restated)
        if candidate is None:
            continue
        removed = source[candidate.start : candidate.end]
        if _PRESERVED_COMMENT.search(removed) or any(
            is_comment_directive(line.strip().removeprefix("#").removeprefix("//").strip())
            for line in physical_lines(removed)
        ):
            continue
        edits.append(candidate)
    return edits


def _diagnosed_comment_edit(
    lines: list[str], first: int, candidates: Mapping[int, CommentCandidate], *, restated: bool
) -> TextEdit | None:
    raw = lines[first - 1]
    if (match := _COMMENT.fullmatch(raw.rstrip("\r\n"))) is not None:
        if not restated and not is_decorative_banner(match.group(1).strip()):
            return _disabled_hcl_edit(lines, first)
        last = first
        if restated:
            if (proven := candidates.get(first)) is None:
                return None
            last = proven.declaration_index
        return _line_edit(lines, first, last)
    if not restated or not raw.lstrip().startswith("/*"):
        return None
    if (proven := candidates.get(first)) is None:
        return None
    last = proven.declaration_index
    if last > len(lines) or lines[last - 1].partition("*/")[2].strip():
        return None
    return _line_edit(lines, first, last)


def _disabled_hcl_edit(lines: list[str], first: int) -> TextEdit | None:
    while first > 1 and _COMMENT.fullmatch(lines[first - 2].rstrip("\r\n")) is not None:
        first -= 1
    last = first
    while last < len(lines) and _COMMENT.fullmatch(lines[last].rstrip("\r\n")) is not None:
        last += 1
    bodies = [match.group(1) for line in lines[first - 1 : last] if (match := _COMMENT.match(line)) is not None]
    if any(is_comment_directive(body.strip()) for body in bodies):
        return None
    payload = "\n".join(bodies)
    if _PRESERVED_COMMENT.search(payload):
        return None
    if not _balanced(payload):
        return None
    parsed = document(payload)
    if not parsed.attributes and not parsed.blocks:
        return None
    # Requiring every nonempty line to be code avoids deleting adjacent rationale.
    if any(
        body.strip()
        and re.fullmatch(r"\s*(?:[A-Za-z_][\w-]*(?:\s+\"[^\"]+\")*\s*\{|[A-Za-z_][\w-]*\s*=.+|})\s*", body) is None
        for body in bodies
    ):
        return None
    return _line_edit(lines, first, last)
