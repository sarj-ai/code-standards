from __future__ import annotations

from pathlib import PurePosixPath
from typing import TYPE_CHECKING, ClassVar, final, override

from sarj_python_lint.rule_base import (
    AutofixPolicy,
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    Rule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
    Severity,
    is_suppressed,
)


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext


@final
class NoBeforeValidatorInputMutation(Rule):
    id = "no-before-validator-input-mutation"
    code = "SARJ482"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Preserve caller-owned raw inputs in Pydantic before validators.",
        rationale="Before validators receive raw caller data. Mutating it leaks normalization into other aliases and can leave inputs changed even when validation subsequently fails or another union branch receives the value.",
        remediation="Return a normalized replacement mapping or collection. Copy the changed path before updating nested values; a fresh outer copy permits outer writes but retains shared descendants.",
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only import-resolved Pydantic model_validator and field_validator decorators with literal mode='before' are analyzed.",
            "The raw value parameter, stable aliases, direct item writes, and type-proven builtin container mutators are checked. isinstance narrowing and resolved typing.cast preserve provenance.",
            "After validators, ordinary methods, arbitrary same-named methods, unknown container mutators, captured closure aliases, and ambiguous control-flow bindings are excluded.",
            "Generated/vendor sources are excluded; maintained tests are checked. No autofix is offered because copying, validation, identity, and evaluation order can differ.",
        ),
        examples=(
            RuleExample(
                example_id="raw-input-write",
                title="Before-validation changes the original mapping",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/records.py",
                        "from pydantic import BaseModel, model_validator\nclass Record(BaseModel):\n    name: str\n    @model_validator(mode='before')\n    @classmethod\n    def normalize(cls, data: dict[str, object]):\n        data['name'] = 'new'\n        return data\n",
                    ),
                ),
                focus_path=PurePosixPath("app/records.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="raw-input-pop",
                title="Removing a raw entry changes caller data",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/records.py",
                        "from pydantic import BaseModel, model_validator\nclass Record(BaseModel):\n    name: str\n    @model_validator(mode='before')\n    @classmethod\n    def normalize(cls, data: dict[str, object]):\n        data.pop('legacy', None)\n        return data\n",
                    ),
                ),
                focus_path=PurePosixPath("app/records.py"),
                expected_count=1,
                public=True,
                scenario="local-builder",
            ),
            RuleExample(
                example_id="replacement-input",
                title="Return normalized data without changing the original",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/records.py",
                        "from pydantic import BaseModel, model_validator\nclass Record(BaseModel):\n    name: str\n    @model_validator(mode='before')\n    @classmethod\n    def normalize(cls, data: dict[str, object]):\n        return {**data, 'name': 'new'}\n",
                    ),
                ),
                focus_path=PurePosixPath("app/records.py"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="fresh-normalization-builder",
                title="A copied outer mapping can be updated locally",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/records.py",
                        "from pydantic import BaseModel, model_validator\nclass Record(BaseModel):\n    name: str\n    @model_validator(mode='before')\n    @classmethod\n    def normalize(cls, data: dict[str, object]):\n        data = dict(data)\n        data['name'] = 'new'\n        return data\n",
                    ),
                ),
                focus_path=PurePosixPath("app/records.py"),
                expected_count=0,
                public=True,
                scenario="local-builder",
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
                message="This before-validator changes its caller's raw input; return normalized replacements and copy each changed nesting level.",
                severity=Severity.WARNING,
            )
            for node in (mutation.node for mutation in context.copy_on_write.mutations if mutation.before_validator)
            if not is_suppressed(context.source_lines, node.lineno, self.code)
        ]
