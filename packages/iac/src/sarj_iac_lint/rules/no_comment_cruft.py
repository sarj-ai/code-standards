"""SARJ202 flags commented-out HCL and section banners in IaC files.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/iac/tests/rules/test_no_comment_cruft.py
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, final, override

from sarj_iac_lint._hcl import heredoc_body_mask
from sarj_iac_lint.rule_base import Diagnostic, Rule


if TYPE_CHECKING:
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
    # attribute assignment whose RHS looks like an HCL value (not English prose
    # such as `deploy = provision the stack` or `retry = 3 attempts` in a comment
    # legend). A bare-number RHS must be the *whole* value (`ttl = 3600`), not the
    # start of a sentence, to match the same "needs a strong code signal" bar that
    # already excludes word-prose RHS.
    r'|^[A-Za-z_][\w-]*\s*=(?!=)\s*(?:["\'\[{]|true\b|false\b|null\b'
    r"|var\.|local\.|module\.|data\.|[A-Za-z_][\w]*\.|[a-z_][\w]*\("
    r"|\d+(?:\.\d+)?\s*,?\s*$)"
    r"|^[A-Za-z_][\w-]*\s*\{$"  # block opener
    r"|^\}\s*$"  # block closer
)


@final
class NoCommentCruft(Rule):
    """Commented-out HCL or a section-banner comment in an IaC file."""

    id = "no-comment-cruft"
    code = "SARJ202"
    description = (
        "Commented-out Terraform/IaC or a section-banner comment — delete it; "
        "code carries the what, comments only the why."
    )

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        # Commented-out-code detection runs on real HCL only. `.tfvars` is
        # excluded: a block of commented `key = ""` lines there is a conventional
        # menu of optional inputs, not dead code. Banners are flagged everywhere.
        detect_code = str(path).endswith((".tf", ".tf.json", ".hcl"))
        lines = source.splitlines()
        # Heredoc bodies are arbitrary text (scripts, JSON, docs) — a `# ...`
        # line there is data, not a real comment, so never classify it.
        in_heredoc = heredoc_body_mask(lines)
        # Annotated rather than a bare `frozenset()` on the else branch, whose
        # element type is unknown and widens the whole binding.
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


def _comment_runs(lines: list[str], in_heredoc: list[bool]) -> list[list[tuple[int, str]]]:
    """Group comment lines into runs split by HCL, blanks, or heredoc text."""
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


def _code_dominant_lines(lines: list[str], in_heredoc: list[bool]) -> frozenset[int]:
    """Return lines in runs where at least half the voting lines are HCL."""
    dominant: set[int] = set()
    for run in _comment_runs(lines, in_heredoc):
        voting = [(lineno, body) for lineno, body in run if body and not _is_directive(body)]
        if not voting:
            continue
        code = sum(1 for _, body in voting if _HCL_CODE_RE.match(body))
        if code * 2 >= len(voting):
            dominant.update(lineno for lineno, _ in voting)
    return frozenset(dominant)


def _banner_group_leaders(lines: list[str], in_heredoc: list[bool]) -> frozenset[int]:
    """Return the first rule line of each contiguous comment banner."""
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
