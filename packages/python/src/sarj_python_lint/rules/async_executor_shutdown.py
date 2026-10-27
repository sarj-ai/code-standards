from __future__ import annotations

import ast
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
from sarj_python_lint.rules._async_lifecycle import AsyncApiProof, method_receiver


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext


_EXECUTORS = ("concurrent.futures.ThreadPoolExecutor", "concurrent.futures.ProcessPoolExecutor")
_BAD = "from concurrent.futures import ThreadPoolExecutor\n\nasync def close():\n    executor = ThreadPoolExecutor()\n    executor.shutdown(wait=True)\n"
_GOOD = "import asyncio\nfrom concurrent.futures import ThreadPoolExecutor\n\nasync def close():\n    executor = ThreadPoolExecutor()\n    await asyncio.to_thread(executor.shutdown, wait=True)\n"


@final
class AsyncExecutorShutdown(Rule):
    id = "async-executor-shutdown"
    code = "SARJ540"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Run waiting executor shutdown outside the async event-loop thread.",
        rationale="Executor.shutdown waits for workers by default; invoking it directly in an async function can block the event loop and delay unrelated service work or cancellation.",
        remediation="Await asyncio.to_thread(executor.shutdown, wait=True), or use the application's explicit nonblocking shutdown policy after arranging worker ownership and completion.",
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Requires a stable direct assignment from an import-proven concurrent.futures ThreadPoolExecutor or ProcessPoolExecutor constructor and a direct shutdown call in an executing async function body.",
            "Only omitted wait or literal wait=True is reported. Literal wait=False, dynamic arguments, nested synchronous callbacks, custom factories, borrowed receivers, context-managed bindings and explicit receiver/API mutation are excluded.",
            "Stable enclosing-function and module bindings are recognized. Ordinary argument passing does not erase the constructor identity; external monkey-patching inside opaque consumers and runtime replacement of stdlib modules are not inferred.",
            "Unknown bound-method consumers, receiver aliases/storage, conditional imports, namespace escapes, reflection, wildcard imports and generated files conservatively abstain. No automatic shutdown-policy change is offered.",
        ),
        examples=(
            RuleExample(
                example_id="waiting-shutdown-in-async",
                title="Waiting shutdown runs on the event-loop thread",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.python("app/lifecycle.py", _BAD),),
                focus_path=PurePosixPath("app/lifecycle.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="shutdown-in-worker-thread",
                title="Await waiting shutdown outside the event-loop thread",
                outcome=ExampleOutcome.NO_MATCH,
                files=(ExampleFile.python("app/lifecycle.py", _GOOD),),
                focus_path=PurePosixPath("app/lifecycle.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if "shutdown" not in context.symbol_source or context.generated or context.tree is None:
            return []
        proof = AsyncApiProof(context)
        diagnostics: list[Diagnostic] = []
        for call in context.nodes(ast.Call):
            receiver = method_receiver(call, frozenset({"shutdown"}))
            if receiver is None or not isinstance(proof.provenance.scope(call), ast.AsyncFunctionDef):
                continue
            if not _waiting_shutdown(call):
                continue
            assigned = proof.assignment(receiver, call)
            if assigned is None:
                continue
            binding = assigned.binding
            value = assigned.value
            if not isinstance(value, ast.Call) or not any(proof.imported(value.func, name) for name in _EXECUTORS):
                continue
            if not _unchanged_receiver(proof, binding) or is_suppressed(context.source_lines, call.lineno, self.code):
                continue
            diagnostics.append(
                Diagnostic(
                    path=context.path,
                    line=call.lineno,
                    col=call.col_offset + 1,
                    code=self.code,
                    severity=Severity.WARNING,
                    message="waiting Executor.shutdown runs on the event-loop thread; await an offloaded shutdown after arranging worker ownership",
                )
            )
        return diagnostics


def _waiting_shutdown(call: ast.Call) -> bool:
    if len(call.args) > 1 or any(keyword.arg not in {"wait", "cancel_futures"} for keyword in call.keywords):
        return False
    values = [*call.args, *(keyword.value for keyword in call.keywords if keyword.arg == "wait")]
    return not values or (len(values) == 1 and isinstance(values[0], ast.Constant) and values[0].value is True)


def _unchanged_receiver(proof: AsyncApiProof, binding: ast.Name) -> bool:
    for read in proof.provenance.binding_reads(binding.id, binding):
        parent = proof.context.parents.get(read)
        if isinstance(parent, ast.Call) and read in parent.args:
            continue
        if isinstance(parent, ast.keyword) and isinstance(proof.context.parents.get(parent), ast.Call):
            continue
        if (
            not isinstance(parent, ast.Attribute)
            or parent.value is not read
            or parent.attr in {"__dict__", "__setattr__", "__delattr__", "__getattribute__"}
        ):
            return False
        consumer = proof.context.parents.get(parent)
        if isinstance(consumer, ast.Call) and consumer.func is parent:
            continue
        if (
            isinstance(consumer, ast.Call)
            and parent in consumer.args
            and proof.imported(consumer.func, "asyncio.to_thread")
        ):
            continue
        return False
    return True
