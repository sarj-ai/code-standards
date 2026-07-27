"""SARJ055: do not suppress Pyright call-shape failures.

Mined from noura-be PR #814: `# type: ignore[reportCallIssue]` masked a call
that needed an explicit keyword argument. A call-issue diagnostic means the
callee contract and call site disagree; hiding it behind a broad type-ignore
tends to preserve exactly the bug the type checker found.

Use the local `# sarj-noqa: SARJ055 — <reason>` escape hatch only after fixing
the call shape is impossible, e.g. at a bad third-party stub boundary.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from sarj_python_lint.rule_base import Diagnostic, Rule
from sarj_python_lint.rules._paths import is_generated_source


if TYPE_CHECKING:
    from pathlib import Path


_REPORT_CALL_ISSUE_IGNORE_RE = re.compile(r"#\s*type:\s*ignore\s*\[[^\]]*\breportCallIssue\b")


class NoReportCallIssueIgnore(Rule):
    """Reject `type: ignore[reportCallIssue]` call-contract suppressions."""

    id: str = "sarj-no-report-call-issue-ignore"
    code: str = "SARJ055"
    description: str = "ban type-ignore reportCallIssue suppressions; fix the call shape or isolate the stub boundary"

    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if is_generated_source(source):
            return []

        diags: list[Diagnostic] = []
        for line_no, line in enumerate(source.splitlines(), start=1):
            match = _REPORT_CALL_ISSUE_IGNORE_RE.search(line)
            if match is None:
                continue
            diags.append(
                Diagnostic(
                    path=path,
                    line=line_no,
                    col=match.start() + 1,
                    code=self.code,
                    message=(
                        "Do not hide Pyright `reportCallIssue` behind `type: ignore`; the call does not match the callee contract. "
                        "Fix the signature/call site, or use a narrow documented `pyright: ignore[reportCallIssue]` at a genuine third-party stub boundary."
                    ),
                )
            )
        return diags
