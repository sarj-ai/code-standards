from __future__ import annotations

from types import MappingProxyType
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel

from sarj_standards.libs.diagnostics import Diagnostic, Location, Region, Severity, SourceDocument


if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path


RULES = MappingProxyType(
    {
        "@sarj/no-modern-shorthand-reset": "Declare animation timelines/ranges and discrete transition behavior after resetting shorthands.",
        "color-no-invalid-hex": "Use syntactically valid hexadecimal colors.",
        "custom-property-no-missing-var-function": "Read custom property values through var().",
        "font-family-no-duplicate-names": "Avoid duplicate font families.",
        "function-calc-no-unspaced-operator": "Separate CSS calculation operators with required whitespace.",
        "function-linear-gradient-no-nonstandard-direction": "Use standard linear-gradient directions.",
        "keyframe-block-no-duplicate-selectors": "Avoid duplicate selectors within one keyframe definition.",
        "keyframe-declaration-no-important": "Avoid ignored important declarations in keyframes.",
        "media-query-no-invalid": "Use syntactically valid media queries.",
        "named-grid-areas-no-invalid": "Use rectangular and complete named grid areas.",
        "declaration-block-no-shorthand-property-overrides": (
            "Keep a shorthand from silently resetting an earlier longhand, including ordinary animation longhands."
        ),
        "declaration-property-value-disallowed-list": (
            "Prefer scalable typography over a plain nonzero pixel font size; preserve mixed-unit expressions."
        ),
    }
)


class _Warning(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)

    line: int = Field(ge=1)
    column: int = Field(ge=1)
    end_line: int | None = Field(default=None, ge=1, alias="endLine")
    end_column: int | None = Field(default=None, ge=1, alias="endColumn")
    rule: str | None
    severity: Literal["warning", "error"]
    text: str


class _Issue(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)

    text: str


class _Result(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)

    source: str
    warnings: list[_Warning]
    ignored: bool = False
    invalid_option_warnings: list[_Issue] = Field(default_factory=list, alias="invalidOptionWarnings")
    parse_errors: list[_Issue] = Field(default_factory=list, alias="parseErrors")


class _Results(RootModel[list[_Result]]):
    pass


def parse(payload: str, *, root: Path, selected: Sequence[str]) -> tuple[Diagnostic, ...]:
    repository = root.resolve()
    expected = {(repository / path).resolve() for path in selected}
    seen: set[Path] = set()
    diagnostics: list[Diagnostic] = []
    for result in _Results.model_validate_json(payload).root:
        path = (repository / result.source).resolve()
        if path not in expected or path in seen or not path.is_relative_to(repository):
            message = "Stylelint returned an unexpected or repeated source path"
            raise ValueError(message)
        if result.ignored or result.invalid_option_warnings or result.parse_errors:
            message = "Stylelint did not analyze a selected source or rejected its configuration"
            raise ValueError(message)
        seen.add(path)
        document = SourceDocument.read(path)
        diagnostics.extend(_diagnostic(warning, document, repository) for warning in result.warnings)
    if seen != expected:
        message = "Stylelint omitted selected CSS sources from its structured report"
        raise ValueError(message)
    return tuple(diagnostics)


def _diagnostic(warning: _Warning, document: SourceDocument, root: Path) -> Diagnostic:
    start = document.utf16_point(line=warning.line - 1, character=warning.column - 1)
    end = (
        document.utf16_point(line=warning.end_line - 1, character=warning.end_column - 1)
        if warning.end_line is not None and warning.end_column is not None
        else start
    )
    if start is None or end is None:
        message = "Stylelint returned a location outside its selected CSS source"
        raise ValueError(message)
    rule = warning.rule or "CssSyntaxError"
    if rule not in RULES and rule != "CssSyntaxError":
        message = "Stylelint reported a rule outside the managed preset"
        raise ValueError(message)
    return Diagnostic(
        rule,
        warning.text,
        Severity(warning.severity),
        "stylelint",
        Location(document.path.relative_to(root).as_posix(), region=Region(start, end)),
        rule_id=rule,
        help_url=(
            "https://github.com/sarj-ai/code-standards/tree/main/plugins/sarj-skills/skills/lint-rule-generator/references/modern-web-guidance.md"
            if rule.startswith("@sarj/")
            else f"https://stylelint.io/user-guide/rules/{rule}/"
            if rule in RULES
            else None
        ),
    )
