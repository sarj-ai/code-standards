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
from sarj_python_lint.rules._paths import is_test_path


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext


@final
class NoMockedPydanticValueObject(ProjectRule):
    id = "no-mocked-pydantic-value-object"
    code = "SARJ479"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Build real Pydantic models when test doubles supply model field data.",
        rationale=(
            "Mocking a Pydantic value object bypasses validation, defaults, serialization, and field relationships. "
            "A specced mock still permits test data that the real model could never produce. Real model fixtures "
            "keep those contracts active while allowing services and external boundaries to remain mocked."
        ),
        remediation=(
            "Construct the real model, using a small typed factory for repeated valid defaults. Keep mock behavior "
            "at collaborator boundaries; a model method deliberately configured to raise remains a valid "
            "failure-injection test."
        ),
        category=RuleCategory.TESTING,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only non-generated test paths and statically resolved unittest.mock constructors are analyzed.",
            "The model's Pydantic ancestry and configured field data must be proven from source; application and SDK modules are never imported at runtime.",
            "Model-method use, child callable invocation or behavior configuration, wrapped real instances, non-instance create_autospec calls, and doubles without configured model fields are excluded.",
            "Unresolved model ancestry, ambiguous bindings, and indirect configuration beyond the supported provenance analysis are left unreported.",
        ),
        examples=(
            RuleExample(
                example_id="mocked-model-field-data",
                title="A mock bypasses the model's validated data contract",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_profile.py",
                        "from unittest.mock import Mock\n"
                        "from pydantic import BaseModel\n\n"
                        "class Profile(BaseModel):\n"
                        "    language: str\n\n"
                        "def test_profile():\n"
                        "    profile = Mock(spec=Profile)\n"
                        "    profile.language = 'ar'\n",
                    ),
                ),
                focus_path=PurePosixPath("tests/test_profile.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="real-model-field-data",
                title="Real model fixtures retain validation and defaults",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_profile.py",
                        "from pydantic import BaseModel\n\n"
                        "class Profile(BaseModel):\n"
                        "    language: str\n\n"
                        "def make_profile(*, language: str = 'en') -> Profile:\n"
                        "    return Profile(language=language)\n\n"
                        "def test_profile():\n"
                        "    profile = make_profile(language='ar')\n"
                        "    assert profile.language == 'ar'\n",
                    ),
                ),
                focus_path=PurePosixPath("tests/test_profile.py"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="model-method-failure-injection",
                title="Deliberate method failures remain valid test boundaries",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_profile.py",
                        "from unittest.mock import Mock\n"
                        "from pydantic import BaseModel\n\n"
                        "class Profile(BaseModel):\n"
                        "    language: str\n"
                        "    def get_language(self) -> str:\n"
                        "        return self.language\n\n"
                        "def test_profile_failure():\n"
                        "    profile = Mock(spec=Profile)\n"
                        "    profile.language = 'ar'\n"
                        "    profile.get_language.side_effect = RuntimeError('unavailable')\n",
                    ),
                ),
                focus_path=PurePosixPath("tests/test_profile.py"),
                expected_count=0,
                public=False,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if not is_test_path(context.path) or context.generated or context.tree is None:
            return []
        diagnostics = [
            Diagnostic(
                path=context.path,
                line=call.lineno,
                col=call.col_offset + 1,
                code=self.code,
                severity=Severity.WARNING,
                message=(
                    f"Mock supplies field data for Pydantic model `{model}`; construct the real model "
                    "or use a typed factory with valid defaults"
                ),
            )
            for call, model in context.test_provenance.model_data_mocks()
            if not is_suppressed(context.source_lines, call.lineno, self.code)
        ]
        diagnostics.sort(key=lambda diagnostic: (diagnostic.line, diagnostic.col))
        return diagnostics
