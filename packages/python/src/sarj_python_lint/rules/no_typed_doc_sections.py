from __future__ import annotations

from pathlib import PurePosixPath
from typing import TYPE_CHECKING, final, override

from sarj_python_lint.rule_base import (
    AutofixPolicy,
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    Rule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
)
from sarj_python_lint.rules._prose_budget import groups


if TYPE_CHECKING:
    from pathlib import Path


@final
class NoTypedDocSections(Rule):
    id = "no-typed-doc-sections"
    code = "SARJ092"
    documentation = RuleDocumentation(
        summary="Docstring sections must not repeat types already present in a fully typed signature.",
        rationale="Duplicated type spellings drift from annotations and add noise without strengthening the behavioral contract.",
        remediation="Remove the repeated type while retaining behavioral facts, constraints, units, and error conditions.",
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only fully typed functions are checked, and a documented type must match the signature before it is reported.",
            "Runtime-consumed prompt, CLI, and route docstrings and untyped or partially typed signatures are excluded.",
        ),
        examples=(
            RuleExample(
                example_id="parameter-type-restatement",
                title="Parameter type repeats the annotation",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app.py",
                        'def decode(value: str) -> dict[str, object]:\n    """Decode the value.\n\n    Args:\n        value (str): Text to decode.\n    """\n    return {}\n',
                    ),
                ),
                focus_path=PurePosixPath("app.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="behavioral-parameter-contract",
                title="Argument section records behavior",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app.py",
                        'def decode(value: str) -> dict[str, object]:\n    """Decode the value.\n\n    Args:\n        value: Text to decode.\n    """\n    return {}\n',
                    ),
                ),
                focus_path=PurePosixPath("app.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        return [
            Diagnostic(
                path,
                line,
                group.col,
                self.code,
                self.description,
                column_encoding=group.column_encoding,
            )
            for group in groups(path, source)
            for line in group.typed_restatements
        ]
