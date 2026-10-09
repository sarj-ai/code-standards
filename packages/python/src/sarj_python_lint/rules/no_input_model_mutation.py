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
class NoInputModelMutation(ProjectRule):
    id = "no-input-model-mutation"
    code = "SARJ481"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Return replacement values instead of mutating caller-owned Pydantic models.",
        rationale="Assignments through shared model inputs also change every caller alias. Copying only the outer list or model retains nested aliases and can make repeated transformations observe each other's changes.",
        remediation="Return replacement models and explicitly capture the result. Copy each changed ancestor; permit fresh local builders and use exact suppressions for documented in-place APIs. model_copy updates must already satisfy the complete model contract.",
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only source-proven Pydantic fields, typed model collections, stable local aliases, and recognized shallow copies are analyzed; application modules are never imported.",
            "Mutation of ordinary instance receivers and fresh owned values is excluded. Before-validator raw inputs belong to SARJ482.",
            "Ambiguous branch bindings, mixed-ownership literals, closures, opaque calls, custom copy hooks, dynamic update mappings, and deep-copy provenance are left unreported. Readonly collection interfaces do not imply immutable elements.",
            "Recursive or deeply nested annotation traversal is bounded. Constructor argument aliases are not propagated through potentially custom validation.",
            "Builtin list/dict/set mutators require a known container shape. Generated/vendor sources are excluded; maintained tests are checked. No automatic copying or validation rewrite is offered.",
        ),
        examples=(
            RuleExample(
                example_id="input-field-write",
                title="A transformation changes its caller's model",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/records.py",
                        "from pydantic import BaseModel\nclass Record(BaseModel):\n    name: str\ndef rename(record: Record):\n    record.name = 'new'\n",
                    ),
                ),
                focus_path=PurePosixPath("app/records.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="copied-list-shares-models",
                title="Copying a list retains its model elements",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/records.py",
                        "from pydantic import BaseModel\nclass Record(BaseModel):\n    name: str\ndef rename(records: list[Record]):\n    copied = list(records)\n    for record in copied:\n        record.name = 'new'\n",
                    ),
                ),
                focus_path=PurePosixPath("app/records.py"),
                expected_count=1,
                public=False,
            ),
            RuleExample(
                example_id="shallow-model-shares-child",
                title="A shallow model copy shares a nested model",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/records.py",
                        "from pydantic import BaseModel\nclass Attachment(BaseModel):\n    url: str\nclass Record(BaseModel):\n    attachment: Attachment\ndef sign(record: Record):\n    copied = record.model_copy()\n    copied.attachment.url = 'signed'\n",
                    ),
                ),
                focus_path=PurePosixPath("app/records.py"),
                expected_count=1,
                public=True,
                scenario="nested-copy",
            ),
            RuleExample(
                example_id="returned-replacement",
                title="Return a trusted replacement",
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
                example_id="copy-changed-ancestors",
                title="Replace the nested value and its parent",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/records.py",
                        "from pydantic import BaseModel\nclass Attachment(BaseModel):\n    url: str\nclass Record(BaseModel):\n    attachment: Attachment\ndef sign(record: Record):\n    attachment = record.attachment.model_copy(update={'url': 'signed'})\n    return record.model_copy(update={'attachment': attachment})\n",
                    ),
                ),
                focus_path=PurePosixPath("app/records.py"),
                expected_count=0,
                public=True,
                scenario="nested-copy",
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
                message="This write changes a caller-owned model or shared descendant; return replacements and copy each changed ancestor, or document an intentional in-place contract.",
                severity=Severity.WARNING,
            )
            for node in (mutation.node for mutation in context.copy_on_write.mutations if not mutation.before_validator)
            if not is_suppressed(context.source_lines, node.lineno, self.code)
        ]
