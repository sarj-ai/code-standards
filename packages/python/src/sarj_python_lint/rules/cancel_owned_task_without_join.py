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


_BAD = "import asyncio\nfrom contextlib import asynccontextmanager\n\n@asynccontextmanager\nasync def lifespan():\n    task = asyncio.create_task(work())\n    try:\n        yield\n    finally:\n        task.cancel()\n"
_GOOD = _BAD + "        await asyncio.gather(task, return_exceptions=True)\n"


@final
class CancelOwnedTaskWithoutJoin(Rule):
    id = "cancel-owned-task-without-join"
    code = "SARJ536"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Join a cancelled locally owned task before releasing its lifecycle.",
        rationale="Task.cancel requests cancellation without waiting for the child to finish; an async lifespan can release resources while its child still runs cancellation cleanup.",
        remediation="Await the owned task or an appropriate gather/TaskGroup settlement before releasing resources. Preserve cancellation of the owner and choose an explicit policy for unexpected child errors and repeated cancellation.",
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only an import-proven asynccontextmanager async generator with one decorator, a unique direct local task assignment and a direct cancel call in a top-level try/finally finalizer is inspected.",
            "Recognizes a single positional coroutine argument to asyncio.create_task, or ensure_future of a proven local coroutine function call. Borrowed Futures passed to ensure_future are excluded because it can return the same task.",
            "Every read of the task must be a direct cancel method call in the same function. Any await, gather/wait, done/result observation, callback, alias, escape, unknown cleanup helper or transferred supervision conservatively abstains.",
            "Already-settled tasks, explicit eager_start other than literal False, opaque task keyword expansion, conditional/compound ownership, custom task factories, nested callbacks, namespace mutation/reflection, wildcard imports and generated files are not inferred. This advisory proves missing settlement, not a specific downstream resource failure.",
            "The rule offers no automatic cancellation handler: swallowing child cancellation can also swallow a new cancellation of the owner unless the lifecycle policy handles it explicitly.",
        ),
        examples=(
            RuleExample(
                example_id="cancel-without-settlement",
                title="Cancelling does not wait for the owned child",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.python("app/lifecycle.py", _BAD),),
                focus_path=PurePosixPath("app/lifecycle.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="join-owned-child",
                title="Wait for the child before the lifespan returns",
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
        if "cancel" not in context.symbol_source or context.generated or context.tree is None:
            return []
        if any(
            isinstance(call.func, ast.Attribute) and call.func.attr == "set_task_factory"
            for call in context.nodes(ast.Call)
        ):
            return []
        proof = AsyncApiProof(context)
        diagnostics: list[Diagnostic] = []
        reported: set[ast.Name] = set()
        for call in context.nodes(ast.Call):
            binding = _unjoined_child(proof, call)
            if binding is None or binding in reported or is_suppressed(context.source_lines, call.lineno, self.code):
                continue
            reported.add(binding)
            diagnostics.append(
                Diagnostic(
                    path=context.path,
                    line=call.lineno,
                    col=call.col_offset + 1,
                    code=self.code,
                    severity=Severity.WARNING,
                    message="cancel() does not settle this lifespan-owned task; join its completion before releasing the lifecycle's resources",
                )
            )
        return diagnostics


def _unjoined_child(proof: AsyncApiProof, call: ast.Call) -> ast.Name | None:
    receiver = method_receiver(call, frozenset({"cancel"}))
    owner = proof.provenance.scope(call)
    if receiver is None or not isinstance(owner, ast.AsyncFunctionDef) or len(owner.decorator_list) != 1:
        return None
    if not proof.imported(owner.decorator_list[0], "contextlib.asynccontextmanager"):
        return None
    statement = proof.context.parents.get(call)
    finalizer = proof.context.parents.get(statement) if statement is not None else None
    if (
        not isinstance(statement, ast.Expr)
        or not isinstance(finalizer, ast.Try)
        or statement not in finalizer.finalbody
        or proof.context.parents.get(finalizer) is not owner
    ):
        return None
    if not any(
        isinstance(node, ast.Yield | ast.YieldFrom) and proof.provenance.scope(node) is owner
        for node in ast.walk(finalizer)
    ):
        return None
    assigned = proof.assignment(receiver, call)
    if assigned is None:
        return None
    binding = assigned.binding
    value = assigned.value
    if proof.provenance.scope(binding) is not owner or not isinstance(value, ast.Call) or not _fresh_task(proof, value):
        return None
    for read in proof.provenance.binding_reads(binding.id, binding):
        parent = proof.context.parents.get(read)
        consumer = proof.context.parents.get(parent) if parent is not None else None
        if (
            proof.provenance.scope(read) is not owner
            or not isinstance(parent, ast.Attribute)
            or parent.attr != "cancel"
            or not isinstance(consumer, ast.Call)
            or consumer.func is not parent
        ):
            return None
    return binding


def _fresh_task(proof: AsyncApiProof, call: ast.Call) -> bool:
    if len(call.args) != 1 or isinstance(call.args[0], ast.Starred):
        return False
    for keyword in call.keywords:
        if keyword.arg is None:
            return False
        if keyword.arg == "eager_start" and not (
            isinstance(keyword.value, ast.Constant) and keyword.value.value is False
        ):
            return False
    if proof.imported(call.func, "asyncio.create_task"):
        return True
    if (
        not proof.imported(call.func, "asyncio.ensure_future")
        or not call.args
        or not isinstance(call.args[0], ast.Call)
    ):
        return False
    return proof.provenance.async_function(call.args[0].func, call) is not None
