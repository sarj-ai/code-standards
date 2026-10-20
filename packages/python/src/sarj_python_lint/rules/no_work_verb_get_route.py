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


_WORK_VERBS: Final = frozenset({"run", "trigger", "send", "dispatch", "execute", "launch", "enqueue", "retry"})
_READ_NOUNS: Final = frozenset(
    {
        "status",
        "history",
        "policy",
        "config",
        "settings",
        "log",
        "logs",
        "count",
        "info",
        "result",
        "results",
        "summary",
        "stats",
        "types",
        "options",
    }
)
_MESSAGE = (
    "This GET route is named for dispatched work; any page can trigger a GET cross-site (for example an <img src>) "
    "and browsers do not apply CSRF protection to it. Make it a POST."
)


@final
class NoWorkVerbGetRoute(Rule):
    id = "no-work-verb-get-route"
    code = "SARJ502"
    documentation = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="GET routes must not end in a work verb such as run, send, trigger or retry.",
        rationale=(
            "GET must be safe. A GET that dispatches work can be fired cross-site by an image tag or link prefetch, "
            "bypasses CSRF protection, and is retried freely by proxies and clients."
        ),
        remediation="Change the operation to POST and keep GET for reads.",
        category=RuleCategory.SECURITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only literal route paths on a FastAPI or APIRouter receiver created in the same file are checked.",
            (
                "The final path segment is read; its first word (split on '-', '_' or '.') must be run, trigger, send, "
                "dispatch, execute, launch, enqueue or retry. Plural nouns such as runs are accepted."
            ),
            "A GET that dispatches work under any other name is not detected. Tests and generated files are excluded.",
        ),
        examples=(
            RuleExample(
                example_id="get-retry",
                title="A GET route retries a batch",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "api.py",
                        "from fastapi import APIRouter\n\nrouter = APIRouter()\n\n"
                        "@router.get('/batches/{batch_id}/retry')\nasync def retry(batch_id: str) -> None:\n"
                        "    return None\n",
                    ),
                ),
                focus_path=PurePosixPath("api.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="post-retry",
                title="The retry is a POST",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "api.py",
                        "from fastapi import APIRouter\n\nrouter = APIRouter()\n\n"
                        "@router.post('/batches/{batch_id}/retry')\nasync def retry(batch_id: str) -> None:\n"
                        "    return None\n",
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
                severity=Severity.WARNING,
            )
            for route in route_decorators(context)
            if "get" in route.methods and route.path is not None and _is_work_segment(final_segment_words(route.path))
        ]


def _is_work_segment(words: list[str]) -> bool:
    return bool(words) and words[0] in _WORK_VERBS and not (len(words) > 1 and words[-1] in _READ_NOUNS)
