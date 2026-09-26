from __future__ import annotations

import ast
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, ClassVar, override

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
from sarj_python_lint.rules._resource_provenance import ResourceProvenance


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext


_BAD = "from contextlib import AsyncExitStack\nasync def close():\n    await release()\nasync def run():\n    async with AsyncExitStack() as stack:\n        stack.callback(close)\n"


class AsyncCleanupRegisteredSynchronously(Rule):
    id: str = "async-cleanup-registered-synchronously"
    code: str = "SARJ462"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Do not register a proven async cleanup function with ExitStack.callback.",
        rationale="The synchronous callback API discards the returned coroutine without awaiting it, so the cleanup body never runs.",
        remediation="Use AsyncExitStack and register the coroutine function with push_async_callback.",
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Requires a proven contextlib ExitStack or AsyncExitStack constructor and an undecorated, visible async function, optionally through simple function aliases.",
            "Unknown methods/callables, decorated functions, async generators, conditional bindings, transferred stacks, wildcard imports, and generated files are excluded.",
            "Resource aliases and interprocedural mutation are not inferred. No autofix is offered because executing previously dropped cleanup can raise new exceptions.",
        ),
        examples=(
            RuleExample(
                example_id="dropped-cleanup",
                title="Synchronous callbacks do not await cleanup",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.python("app/resources.py", _BAD),),
                focus_path=PurePosixPath("app/resources.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="awaited-cleanup",
                title="Register cleanup with the async API",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python("app/resources.py", _BAD.replace("stack.callback", "stack.push_async_callback")),
                ),
                focus_path=PurePosixPath("app/resources.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description: str = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if "callback" not in context.source or context.generated or context.tree is None:
            return []
        provenance = ResourceProvenance(context)
        findings: list[Diagnostic] = []
        for call in context.nodes(ast.Call):
            if not _wrong_callback(call, provenance) or is_suppressed(context.source_lines, call.lineno, self.code):
                continue
            findings.append(
                Diagnostic(
                    path=context.path,
                    line=call.lineno,
                    col=call.col_offset + 1,
                    code=self.code,
                    severity=Severity.WARNING,
                    message="synchronous ExitStack.callback does not await this async cleanup function; use AsyncExitStack.push_async_callback",
                )
            )
        return findings


def _wrong_callback(call: ast.Call, provenance: ResourceProvenance) -> bool:
    if not isinstance(call.func, ast.Attribute) or call.func.attr != "callback" or not call.args:
        return False
    receiver = call.func.value
    if not isinstance(receiver, ast.Name) or not provenance.unescaped(receiver, call, allow_context=True):
        return False
    constructor = provenance.constructor(receiver, call)
    if constructor is None or constructor.args or constructor.keywords:
        return False
    known = any(provenance.imported(constructor.func, f"contextlib.{name}") for name in ("ExitStack", "AsyncExitStack"))
    return known and provenance.async_function(call.args[0], call) is not None
