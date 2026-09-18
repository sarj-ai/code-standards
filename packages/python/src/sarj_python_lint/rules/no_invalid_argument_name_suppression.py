from __future__ import annotations

from pathlib import PurePosixPath
import re
from typing import TYPE_CHECKING, ClassVar, final, override

from sarj_python_lint.rule_base import (
    ColumnEncoding,
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    Rule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
)
from sarj_python_lint.rules._paths import is_generated
from sarj_python_lint.rules._suppression_comments import scan_comments_or_none


if TYPE_CHECKING:
    from pathlib import Path


_FORBIDDEN = re.compile(r"(?:^|[,:\s\[])\s*(?:N803|invalid-argument-name)(?=$|[,\]\s])", re.IGNORECASE)


@final
class NoInvalidArgumentNameSuppression(Rule):
    id = "no-invalid-argument-name-suppression"
    code = "SARJ448"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="External parameter spelling must use framework aliases instead of disabling snake_case naming.",
        rationale="Naming suppressions leak an external wire vocabulary into Python APIs and normalize future exceptions.",
        remediation=(
            "Keep the Python parameter snake_case and preserve the external spelling with FastAPI `Query`/`Path` aliases "
            "or Pydantic `Field` aliases."
        ),
        category=RuleCategory.MAINTAINABILITY,
        limitations=("Generated source is excluded.",),
        examples=(
            RuleExample(
                example_id="camel-case-parameter-suppression",
                title="A wire parameter disables Python naming",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/routes.py",
                        "def route(businessFunction: str):  # ruff: ignore[invalid-argument-name]\n    ...\n",
                    ),
                ),
                focus_path=PurePosixPath("app/routes.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="snake-case-wire-alias",
                title="A framework alias preserves external spelling",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/routes.py",
                        "from fastapi import Query\ndef route(business_function: str = Query(alias='businessFunction')): ...\n",
                    ),
                ),
                focus_path=PurePosixPath("app/routes.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if is_generated(path, source):
            return []
        comments = scan_comments_or_none(source)
        if comments is None:
            return []
        return [
            Diagnostic(
                path=path,
                line=comment.line,
                col=comment.col,
                code=self.code,
                message=(
                    "do not suppress Python argument naming; use a snake_case parameter and an explicit wire alias"
                ),
                column_encoding=ColumnEncoding.CODEPOINTS,
            )
            for comment in comments
            if _FORBIDDEN.search(comment.body)
        ]
