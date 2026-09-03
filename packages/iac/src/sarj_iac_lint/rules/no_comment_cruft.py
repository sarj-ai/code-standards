from __future__ import annotations

from pathlib import PurePosixPath
import re
from typing import TYPE_CHECKING, NamedTuple, final, override

from sarj_iac_lint._hcl import heredoc_body_mask
from sarj_iac_lint.rule_base import (
    AutofixPolicy,
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    Rule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
)


if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

_COMMENT_RE = re.compile(r"^(\s*)(#|//)\s?(.*)$")

_DIRECTIVE_RE = re.compile(
    r"^(?:(?:sarj-noqa|tflint-ignore|tflint|checkov|tfsec|trivy|terrascan|"
    r"kics-scan|nosec|terraform|yaml-language-server|todo|fixme|hack|xxx|bug|noqa)"
    r"(?=$|[\s:=])|!)",
    re.IGNORECASE,
)


class _CommentLine(NamedTuple):
    line: int
    body: str


_BANNER_FULL_RE = re.compile(r"^[-=#*~_+.\s]{4,}$")
_BANNER_TITLE_RE = re.compile(r"^[-=#*~_+.]{4,}\s+\S(?:.*\S)?\s+[-=#*~_+.]{4,}$")
_GENERATED_RE = re.compile(r"generated.{0,80}(?:do not edit|don't edit)", re.IGNORECASE)
_YAML_SCALAR_RE = re.compile(r"[>|](?:[1-9][+-]?|[+-][1-9]?)?\s*(?:#.*)?$")
_BLOCK_COMMENT_START_RE = re.compile(r"^(\s*)/\*(.*)$")

_HCL_CODE_RE = re.compile(
    r'^[A-Za-z_][\w-]*(?:\s+(?:"(?:\\.|[^"\\])*"|[A-Za-z_][\w.-]*)){0,3}\s*\{\s*$'
    # Matches attribute assignments whose right-hand side represents a literal HCL value.
    r'|^[A-Za-z_][\w-]*\s*=(?!=)\s*(?:["\'\[{]|true\b|false\b|null\b'
    r"|var\.|local\.|module\.|data\.|[A-Za-z_][\w]*\.|[a-z_][\w]*\("
    r"|\d+(?:\.\d+)?\s*,?\s*$)"
    r"|^[A-Za-z_][\w-]*\s*\{$"  # block opener
    r"|^\}\s*$"  # block closer
)


@final
class NoCommentCruft(Rule):
    id = "no-comment-cruft"
    code = "SARJ202"
    documentation = RuleDocumentation(
        summary=(
            "Commented-out HCL declarations or decorative divider comments must be removed; retain comments that "
            "explain constraints or rationale."
        ),
        rationale=(
            "Disabled declarations drift from executable infrastructure, while decorative banners duplicate structure "
            "already expressed by modules and resource blocks."
        ),
        remediation=(
            "Delete disabled HCL and decorative dividers; use executable structure and concise rationale comments."
        ),
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Commented assignments in tfvars files are allowed because they commonly document optional inputs.",
            "Generated files, testdata, and fixture trees are excluded because comments may be intentional test input.",
            "Tool directives, heredoc bodies, YAML block scalars, and malformed block comments are excluded.",
            "Disabled HCL comment runs must be code-dominant and produce one finding per contiguous run.",
        ),
        examples=(
            RuleExample(
                example_id="commented-resource",
                title="Disabled HCL resource",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.iac(
                        "main.tf",
                        '# resource "google_storage_bucket" "old" {\n'
                        '#   name          = "legacy-artifacts"\n'
                        '#   location      = "US"\n'
                        "#   force_destroy = true\n"
                        "# }\n"
                        'resource "google_storage_bucket" "new" {}\n',
                    ),
                ),
                focus_path=PurePosixPath("main.tf"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="reason-comment",
                title="Comment explaining an infrastructure constraint",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.iac(
                        "main.tf",
                        "# Keep this bucket in us-central1 for data residency.\n"
                        'resource "google_storage_bucket" "records" {}\n',
                    ),
                ),
                focus_path=PurePosixPath("main.tf"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="decorative-divider",
                title="Decorative divider around a section title",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.iac("main.tf", '# ==== Networking ====\nmodule "networking" {}\n'),),
                focus_path=PurePosixPath("main.tf"),
                expected_count=1,
                scenario="divider",
                public=True,
            ),
            RuleExample(
                example_id="descriptive-section-comment",
                title="Section comment that explains a constraint",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.iac(
                        "main.tf",
                        '# Networking is isolated to preserve the production trust boundary.\nmodule "networking" {}\n',
                    ),
                ),
                focus_path=PurePosixPath("main.tf"),
                expected_count=0,
                scenario="divider",
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        fixture_input = any(part.lower() in {"fixture", "fixtures", "testdata"} for part in path.parts)
        if fixture_input or _generated_header(source):
            return []

        detect_code = str(path).endswith((".tf", ".tf.json", ".hcl"))
        lines = source.splitlines()
        data_lines = _data_line_mask(path, lines)
        empty: frozenset[int] = frozenset()
        code_run = _code_run_leaders(lines, data_lines) if detect_code else empty
        banner_leaders = _banner_group_leaders(lines, data_lines)
        diags: list[Diagnostic] = []
        for lineno, raw in enumerate(lines, start=1):
            if data_lines[lineno - 1]:
                continue
            m = _COMMENT_RE.match(raw)
            if m is None:
                continue
            indent, _marker, body = m.group(1), m.group(2), m.group(3).strip()
            if not body or _is_directive(body):
                continue
            msg = _classify(body, in_code_run=lineno in code_run)
            if msg is None:
                continue
            if _is_banner(body) and lineno not in banner_leaders:
                continue
            diags.append(
                Diagnostic(
                    path=path,
                    line=lineno,
                    col=len(indent) + 1,
                    code=self.code,
                    message=msg,
                )
            )
        if detect_code:
            diags.extend(_block_comment_diagnostics(path, lines, data_lines, code=self.code))
        return sorted(diags, key=lambda diagnostic: (diagnostic.line, diagnostic.col))


def _comment_runs(lines: list[str], data_lines: Sequence[bool]) -> list[list[_CommentLine]]:
    runs: list[list[_CommentLine]] = []
    current: list[_CommentLine] = []
    for lineno, raw in enumerate(lines, start=1):
        m = None if data_lines[lineno - 1] else _COMMENT_RE.match(raw)
        if m is None:
            if current:
                runs.append(current)
                current = []
            continue
        current.append(_CommentLine(lineno, m.group(3).strip()))
    if current:
        runs.append(current)
    return runs


def _code_run_leaders(lines: list[str], data_lines: Sequence[bool]) -> frozenset[int]:
    leaders: set[int] = set()
    for run in _comment_runs(lines, data_lines):
        voting = [(lineno, body) for lineno, body in run if body and not _is_directive(body)]
        if not voting:
            continue
        code = sum(1 for _, body in voting if _HCL_CODE_RE.match(body))
        if code * 2 >= len(voting):
            leaders.add(next(lineno for lineno, body in voting if _HCL_CODE_RE.match(body)))
    return frozenset(leaders)


def _banner_group_leaders(lines: list[str], data_lines: Sequence[bool]) -> frozenset[int]:
    leaders: set[int] = set()
    for run in _comment_runs(lines, data_lines):
        seen_banner = False
        for lineno, body in run:
            if not body or _is_directive(body) or not _is_banner(body):
                continue
            if not seen_banner:
                leaders.add(lineno)
                seen_banner = True
    return frozenset(leaders)


def _classify(body: str, *, in_code_run: bool) -> str | None:
    if _is_banner(body):
        return "Decorative divider comment — remove it or replace it with a concise explanation."
    if in_code_run and _HCL_CODE_RE.match(body):
        return "Commented-out HCL — delete it; recover prior source from version control if needed."
    return None


def _is_directive(body: str) -> bool:
    return _DIRECTIVE_RE.match(body) is not None


def _is_banner(body: str) -> bool:
    return _BANNER_FULL_RE.fullmatch(body) is not None or _BANNER_TITLE_RE.fullmatch(body) is not None


def _generated_header(source: str) -> bool:
    header_lines = source.splitlines()[:20]
    header = "\n".join(line for line in header_lines if line.lstrip().startswith(("#", "//", "/*", "*")))
    return _GENERATED_RE.search(header) is not None


def _data_line_mask(path: Path, lines: list[str]) -> tuple[bool, ...]:
    mask = list(heredoc_body_mask(lines))
    if path.suffix.lower() not in {".yaml", ".yml"}:
        return tuple(mask)

    scalar_indent: int | None = None
    for index, raw in enumerate(lines):
        stripped = raw.strip()
        indent = len(raw) - len(raw.lstrip())
        if scalar_indent is not None:
            if not stripped or indent > scalar_indent:
                mask[index] = True
                continue
            scalar_indent = None
        if stripped and not raw.lstrip().startswith("#") and _YAML_SCALAR_RE.search(raw):
            scalar_indent = indent
    return tuple(mask)


def _block_comment_diagnostics(
    path: Path,
    lines: list[str],
    data_lines: Sequence[bool],
    *,
    code: str,
) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    index = 0
    while index < len(lines):
        match = None if data_lines[index] else _BLOCK_COMMENT_START_RE.match(lines[index])
        if match is None:
            index += 1
            continue

        indent = match.group(1)
        comment_lines: list[_CommentLine] = []
        cursor = index
        fragment = match.group(2)
        balanced = False
        while cursor < len(lines) and not data_lines[cursor]:
            before_close, separator, _after_close = fragment.partition("*/")
            body = re.sub(r"^\s*\*\s?", "", before_close).strip()
            comment_lines.append(_CommentLine(cursor + 1, body))
            if separator:
                balanced = True
                break
            cursor += 1
            if cursor < len(lines):
                fragment = lines[cursor]

        if balanced:
            voting = [(lineno, body) for lineno, body in comment_lines if body and not _is_directive(body)]
            code_lines = [(lineno, body) for lineno, body in voting if _HCL_CODE_RE.match(body)]
            if code_lines and len(code_lines) * 2 >= len(voting):
                diagnostics.append(
                    Diagnostic(
                        path=path,
                        line=code_lines[0][0],
                        col=len(indent) + 1,
                        code=code,
                        message="Commented-out HCL — delete it; recover prior source from version control if needed.",
                    )
                )
            index = cursor + 1
        else:
            index += 1
    return diagnostics
