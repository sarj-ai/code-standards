from __future__ import annotations

from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Final, final, override

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
)
from sarj_python_lint.rules._route_shapes import final_segment_words, route_decorators


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext


_CREATE_WORDS: Final = frozenset({"create", "add", "new"})
_MESSAGE = (
    "Name the collection (POST /tickets) instead of ending the path in create, add or new. "
    "Keep a reasoned exact exception for an external RPC contract."
)


@final
class NoCreateVerbInPostPath(Rule):
    id = "no-create-verb-in-post-path"
    code = "SARJ500"
    documentation = RuleDocumentation(
        default_level=Severity.ERROR,
        summary="POST routes name their collection instead of ending in a create, add or new segment.",
        rationale=(
            "The organization uses resource-oriented paths for predictable collection and item APIs. "
            "A trailing create, add or new segment repeats the operation in the path. HTTP POST itself supports "
            "resource-specific processing and does not require creation semantics."
        ),
        remediation="Use the collection path for resource creation. Preserve deliberate external RPC contracts with a reasoned exact suppression; review client compatibility before changing a published path.",
        category=RuleCategory.ARCHITECTURE,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only literal route paths on a FastAPI or APIRouter receiver created in the same file are checked.",
            "The final path segment is read; its first word (split on '-', '_' or '.') must be create, add or new.",
            "A final path parameter is accepted, and tests and generated files are excluded.",
            "Deliberate RPC-style integration endpoints exist; keep them with an exact suppression and its reason.",
        ),
        examples=(
            RuleExample(
                example_id="create-segment",
                title="A POST route repeats the verb in its path",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "api.py",
                        "from fastapi import APIRouter\n\nrouter = APIRouter()\n\n"
                        "@router.post('/tickets/create')\nasync def create_ticket() -> None:\n    return None\n",
                    ),
                ),
                focus_path=PurePosixPath("api.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="collection-path",
                title="A POST route names its collection",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "api.py",
                        "from fastapi import APIRouter\n\nrouter = APIRouter()\n\n"
                        "@router.post('/tickets')\nasync def create_ticket() -> None:\n    return None\n",
                    ),
                ),
                focus_path=PurePosixPath("api.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        return [
            Diagnostic(
                context.path,
                route.decorator.lineno,
                route.decorator.col_offset + 1,
                self.code,
                _MESSAGE,
                severity=Severity.ERROR,
            )
            for route in route_decorators(context)
            if "post" in route.methods
            and route.path is not None
            and _is_create_segment(final_segment_words(route.path))
        ]


def _is_create_segment(words: list[str]) -> bool:
    if not words or words[0] not in _CREATE_WORDS:
        return False
    if words[0] == "new":
        return len(words) == 1
    return words[:2] != ["add", "ons"]
