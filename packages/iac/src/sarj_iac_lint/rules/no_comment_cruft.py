from __future__ import annotations

from pathlib import PurePosixPath
import re
from typing import TYPE_CHECKING, final, override

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

_DIRECTIVE_PREFIXES = (
    "sarj-noqa",
    "tflint-ignore",
    "tflint:",
    "checkov:",
    "nosec",
    "terraform:",
    "yaml-language-server",
    "todo",
    "fixme",
    "hack",
    "noqa",
    "!",
)

_BANNER_FULL_RE = re.compile(r"^[-=#*~_+.\s]{4,}$")
_BANNER_RUN_RE = re.compile(r"={4,}|-{4,}|#{4,}|\*{4,}|~{4,}")

_HCL_CODE_RE = re.compile(
    r"^(?:resource|data|module|variable|output|provider|locals|terraform|"
    r'backend|dynamic|moved)\s+["{]'
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
            "Commented-out Terraform/IaC or a section-banner comment — delete it; "
            "code carries the what, comments only the why."
        ),
        rationale=(
            "Disabled declarations drift from executable infrastructure, while decorative banners duplicate structure "
            "already expressed by modules and resource blocks."
        ),
        remediation="Delete disabled HCL and decorative dividers; retain only comments that explain a non-obvious reason.",
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Commented assignments in tfvars files are allowed because they commonly document optional inputs.",
            "Testdata and fixture trees may encode removed configuration as test input, so only banners are checked there.",
            "Directives and heredoc bodies are excluded, and disabled HCL runs must be code-dominant.",
        ),
        examples=(
            RuleExample(
                example_id="commented-resource",
                title="Disabled Terraform resource",
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
                expected_count=5,
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
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        # HCL commented-out code checks exclude .tfvars, while section banners are checked in all files.
        fixture_input = any(part.lower() in {"fixture", "fixtures", "testdata"} for part in path.parts)
        detect_code = str(path).endswith((".tf", ".tf.json", ".hcl")) and not fixture_input
        lines = source.splitlines()
        # Heredoc lines are data rather than HCL line comments.
        in_heredoc = heredoc_body_mask(lines)
        empty: frozenset[int] = frozenset()
        code_run = _code_dominant_lines(lines, in_heredoc) if detect_code else empty
        banner_leaders = _banner_group_leaders(lines, in_heredoc)
        diags: list[Diagnostic] = []
        for lineno, raw in enumerate(lines, start=1):
            if in_heredoc[lineno - 1]:
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
        return diags


def _comment_runs(lines: list[str], in_heredoc: Sequence[bool]) -> list[list[tuple[int, str]]]:
    runs: list[list[tuple[int, str]]] = []
    current: list[tuple[int, str]] = []
    for lineno, raw in enumerate(lines, start=1):
        m = None if in_heredoc[lineno - 1] else _COMMENT_RE.match(raw)
        if m is None:
            if current:
                runs.append(current)
                current = []
            continue
        current.append((lineno, m.group(3).strip()))
    if current:
        runs.append(current)
    return runs


def _code_dominant_lines(lines: list[str], in_heredoc: Sequence[bool]) -> frozenset[int]:
    dominant: set[int] = set()
    for run in _comment_runs(lines, in_heredoc):
        voting = [(lineno, body) for lineno, body in run if body and not _is_directive(body)]
        if not voting:
            continue
        code = sum(1 for _, body in voting if _HCL_CODE_RE.match(body))
        if code * 2 >= len(voting):
            dominant.update(lineno for lineno, _ in voting)
    return frozenset(dominant)


def _banner_group_leaders(lines: list[str], in_heredoc: Sequence[bool]) -> frozenset[int]:
    leaders: set[int] = set()
    for run in _comment_runs(lines, in_heredoc):
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
        return "Section-banner / divider comment — use real structure, not ASCII rules."
    if in_code_run and _HCL_CODE_RE.match(body):
        return "Commented-out Terraform — delete it; state and git history remember."
    return None


def _is_directive(body: str) -> bool:
    low = body.lower()
    return any(low.startswith(p) for p in _DIRECTIVE_PREFIXES)


def _is_banner(body: str) -> bool:
    if _BANNER_FULL_RE.match(body):
        return True
    return bool(_BANNER_RUN_RE.search(body))
