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
from sarj_python_lint.rules._ast_position import ast_position
from sarj_python_lint.rules._paths import is_test_path


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext


@final
class NoTestMethodGrafting(ProjectRule):
    id = "no-test-method-grafting"
    code = "SARJ478"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Avoid assigning replacement implementations directly onto resolved methods in tests.",
        rationale=(
            "Grafting a function onto a collaborator or mock hides the boundary's callable contract and bypasses "
            "the mock's call and await records. An injected fake makes behavior explicit; configuring an existing "
            "contract-aware mock preserves its observation API. Scoped patches also restore real objects reliably."
        ),
        remediation=(
            "Inject a concrete fake or configure the existing autospecced mock method's return_value or side_effect. "
            "Preserve the real method's synchronous or asynchronous contract, including synchronous awaitable "
            "returns. Explain other intentional runtime interception with an exact-code local suppression."
        ),
        category=RuleCategory.TESTING,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only non-generated test paths are analyzed; a destination method and replacement callable must have statically resolved provenance.",
            "Inference uses source declarations and conservative constructor, annotation, fixture, and helper relationships; it never imports application or SDK code at runtime.",
            "Data fields, callable-valued fields, mock configuration attributes, whole-object fake injection, and scoped patch calls are excluded.",
            "Wrappers visibly forwarding a captured original of the same receiver and member, and matching saved-original restorations in finally, are excluded.",
            "Unknown types, ambiguous bindings, unresolved decorators or inheritance, and dynamically chosen members are left unreported; canonical typing.final class decorators are transparent.",
        ),
        examples=(
            RuleExample(
                example_id="method-implementation-assignment",
                title="A test replaces a mock's resolved collaborator method",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_delivery.py",
                        "from unittest.mock import Mock\n\n"
                        "class Sender:\n"
                        "    def send(self, text: str) -> None:\n"
                        "        pass\n\n"
                        "def test_delivery():\n"
                        "    sender = Mock(spec=Sender)\n"
                        "    messages = []\n"
                        "    def record(text: str) -> None:\n"
                        "        messages.append(text)\n"
                        "    sender.send = record\n",
                    ),
                ),
                focus_path=PurePosixPath("tests/test_delivery.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="mock-method-side-effect",
                title="Configure behavior through an existing mock method",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_delivery.py",
                        "from unittest.mock import create_autospec\n\n"
                        "class Sender:\n"
                        "    def send(self, text: str) -> None:\n"
                        "        pass\n\n"
                        "def test_delivery():\n"
                        "    sender = create_autospec(Sender, instance=True, spec_set=True)\n"
                        "    messages = []\n"
                        "    sender.send.side_effect = messages.append\n"
                        "    sender.send('hello')\n"
                        "    sender.send.assert_called_once_with('hello')\n",
                    ),
                ),
                focus_path=PurePosixPath("tests/test_delivery.py"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="callable-data-field",
                title="Callback fields remain valid configuration",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_pool.py",
                        "from collections.abc import Callable\n\n"
                        "class Pool:\n"
                        "    on_close: Callable[[], None] | None = None\n\n"
                        "def test_pool():\n"
                        "    pool = Pool()\n"
                        "    events = []\n"
                        "    pool.on_close = lambda: events.append('closed')\n",
                    ),
                ),
                focus_path=PurePosixPath("tests/test_pool.py"),
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
        diagnostics: list[Diagnostic] = []
        for target, method in context.test_provenance.method_grafts():
            position = ast_position(target, missing=1)
            if is_suppressed(context.source_lines, position.line, self.code):
                continue
            diagnostics.append(
                Diagnostic(
                    path=context.path,
                    line=position.line,
                    col=position.column + 1,
                    code=self.code,
                    severity=Severity.WARNING,
                    message=(
                        f"Test assigns an implementation directly to resolved method `{method}`; inject a fake, "
                        "or configure the existing autospecced mock method's side_effect"
                    ),
                )
            )
        diagnostics.sort(key=lambda diagnostic: (diagnostic.line, diagnostic.col))
        return diagnostics
