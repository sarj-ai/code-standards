from __future__ import annotations

from pathlib import PurePosixPath
from typing import TYPE_CHECKING, ClassVar, final, override

from sarj_python_lint.rule_base import (
    AutofixPolicy,
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    ProjectRule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
    Severity,
    is_suppressed,
)


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext


@final
class NoUnusedCopyResult(ProjectRule):
    id = "no-unused-copy-result"
    code = "SARJ483"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Use the replacement returned by a resolved copy API.",
        rationale="Copy-on-write replacement APIs return another value rather than updating the original. Discarding their result can silently leave subsequent operations using unchanged data.",
        remediation="Assign, return, or otherwise consume the replacement. A copy hook intentionally exercised for its effects or exceptions can use a narrow suppression; do not automatically delete the call.",
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Import-resolved pytest.raises blocks consume copy operations as exception assertions and are excluded.",
            "Only standalone calls to import-resolved dataclasses.replace, copy.replace, and source-proven inherited Pydantic model_copy methods are reported.",
            "Arbitrary copy/replace methods, shadowed imports, Pydantic method or copy-hook overrides, and unknown receivers are excluded.",
            "Assignments, returns, and passing the result to another call consume the result and are not reported. Copy hooks can run user code, so no deletion or assignment autofix is offered.",
            "Generated/vendor sources are excluded; maintained tests are checked.",
        ),
        examples=(
            RuleExample(
                example_id="discarded-model-copy",
                title="A replacement model is ignored",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/records.py",
                        "from pydantic import BaseModel\nclass Record(BaseModel):\n    name: str\ndef rename(record: Record):\n    record.model_copy(update={'name': 'new'})\n",
                    ),
                ),
                focus_path=PurePosixPath("app/records.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="discarded-dataclass-replacement",
                title="A standard-library replacement is ignored",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/records.py",
                        "from dataclasses import replace\ndef rename(record):\n    replace(record, name='new')\n",
                    ),
                ),
                focus_path=PurePosixPath("app/records.py"),
                expected_count=1,
                public=True,
                scenario="standard-replacement",
            ),
            RuleExample(
                example_id="returned-copy",
                title="Return the replacement to its caller",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/records.py",
                        "from pydantic import BaseModel\nclass Record(BaseModel):\n    name: str\ndef rename(record: Record):\n    return record.model_copy(update={'name': 'new'})\n",
                    ),
                ),
                focus_path=PurePosixPath("app/records.py"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="consumed-standard-copy",
                title="Capture the standard-library replacement",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/records.py",
                        "from copy import replace\ndef rename(record):\n    result = replace(record, name='new')\n    return result\n",
                    ),
                ),
                focus_path=PurePosixPath("app/records.py"),
                expected_count=0,
                public=True,
                scenario="standard-replacement",
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if context.generated or context.tree is None:
            return []
        return [
            Diagnostic(
                path=context.path,
                line=node.lineno,
                col=node.col_offset + 1,
                code=self.code,
                message="This copy API returns a replacement that is discarded; assign or return it, or document intentional copy-hook effects.",
                severity=Severity.WARNING,
            )
            for node in (context.copy_on_write.discarded)
            if not is_suppressed(context.source_lines, node.lineno, self.code)
        ]
