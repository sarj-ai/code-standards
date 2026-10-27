from __future__ import annotations

import ast
from dataclasses import dataclass
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


_BAD = "import asyncio\n\nasync def run(args):\n    process = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)\n    return await process.communicate()\n"
_GOOD = "import asyncio\nfrom contextlib import suppress\n\nasync def run(args):\n    process = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)\n    try:\n        return await process.communicate()\n    except asyncio.CancelledError:\n        if process.returncode is None:\n            with suppress(ProcessLookupError):\n                process.kill()\n        await process.communicate()\n        raise\n"

_GLOBAL_REAPERS = frozenset({"wait", "waitpid", "waitid", "wait3", "wait4"})


@dataclass(frozen=True, slots=True)
class _AsyncChildWait:
    binding: ast.Name
    call: ast.Call


@final
class AsyncSubprocessCancellationCleanup(Rule):
    id: str = "async-subprocess-cancellation-cleanup"
    code: str = "SARJ537"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Settle locally owned asyncio subprocesses when their caller is cancelled.",
        rationale="Cancelling an asyncio process wait does not terminate its child; a locally owned subprocess can keep running with unsettled pipes and exit status.",
        remediation="Arrange cancellation cleanup that settles the owned child and preserves caller cancellation under the application's termination and pipe-handling policy.",
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Checks a unique direct local assignment from asyncio.create_subprocess_exec/shell followed by a direct, unguarded await of wait/communicate in the same async function.",
            "Handles must not escape or have reads other than direct awaited wait/communicate calls and later read-only returncode observations. Earlier status observations/polling, try/finally, cancellation handlers, managed wrappers, borrowed/aliased handles, earlier process settlement and unknown lifecycle helpers conservatively abstain.",
            "Visible os child-reaper imports/calls and SIGCHLD ownership exclude the file using the existing subprocess ownership proof. Native API replacement, frame/module introspection, code mutation and bound attribute setters invalidate provenance.",
            "Cross-function lifecycle, fields, dynamic mutation, arbitrary exit paths and generated files are not analyzed. Choosing termination, escalation, process groups and pipe handling requires the application's ownership policy; no automatic rewrite is provided.",
        ),
        examples=(
            RuleExample(
                example_id="async-wait-without-cancellation-cleanup",
                title="Cancelling communication can leave the owned child running",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.python("app/processes.py", _BAD),),
                focus_path=PurePosixPath("app/processes.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="async-child-cancellation-cleanup",
                title="Settle the owned child before propagating cancellation",
                outcome=ExampleOutcome.NO_MATCH,
                files=(ExampleFile.python("app/processes.py", _GOOD),),
                focus_path=PurePosixPath("app/processes.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description: str = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if (
            not any(symbol in context.symbol_source for symbol in ("create_subprocess_exec", "create_subprocess_shell"))
            or context.generated
            or context.tree is None
            or _global_child_owner(context)
        ):
            return []
        return sorted(_async_process_diagnostics(context, self.code), key=lambda finding: (finding.line, finding.col))


def _async_process_diagnostics(context: PythonFileContext, code: str) -> list[Diagnostic]:
    if not any(symbol in context.symbol_source for symbol in ("create_subprocess_exec", "create_subprocess_shell")):
        return []
    proof = AsyncApiProof(context)
    findings: list[Diagnostic] = []
    reported: set[ast.Name] = set()
    for awaited in context.nodes(ast.Await):
        candidate = _unsettled_async_child(proof, awaited)
        if candidate is None:
            continue
        binding = candidate.binding
        call = candidate.call
        if binding in reported or is_suppressed(context.source_lines, call.lineno, code):
            continue
        reported.add(binding)
        findings.append(
            Diagnostic(
                path=context.path,
                line=call.lineno,
                col=call.col_offset + 1,
                code=code,
                severity=Severity.WARNING,
                message="cancelling this unguarded wait can leave its locally owned subprocess unsettled; add cancellation cleanup that settles the child and preserves caller cancellation",
            )
        )
    return findings


def _unsettled_async_child(proof: AsyncApiProof, awaited: ast.Await) -> _AsyncChildWait | None:
    call = awaited.value
    if not isinstance(call, ast.Call):
        return None
    receiver = method_receiver(call, frozenset({"wait", "communicate"}))
    owner = proof.provenance.scope(awaited)
    statement = proof.context.parents.get(awaited)
    if (
        receiver is None
        or not isinstance(owner, ast.AsyncFunctionDef)
        or not isinstance(statement, ast.Expr | ast.Assign | ast.AnnAssign | ast.Return)
        or statement.value is not awaited
        or proof.context.parents.get(statement) is not owner
    ):
        return None
    binding = _created_child_binding(proof, receiver, awaited, owner)
    if binding is None or not _child_reads_are_unsettled_waits(proof, binding, awaited, owner):
        return None
    return _AsyncChildWait(binding=binding, call=call)


def _created_child_binding(
    proof: AsyncApiProof, receiver: ast.Name, awaited: ast.Await, owner: ast.AsyncFunctionDef
) -> ast.Name | None:
    assigned = proof.assignment(receiver, awaited)
    if assigned is None:
        return None
    binding = assigned.binding
    value = assigned.value
    if (
        proof.provenance.scope(binding) is not owner
        or not isinstance(value, ast.Await)
        or not isinstance(value.value, ast.Call)
        or not any(
            proof.imported(value.value.func, f"asyncio.{name}")
            for name in ("create_subprocess_exec", "create_subprocess_shell")
        )
    ):
        return None
    return binding


def _child_reads_are_unsettled_waits(
    proof: AsyncApiProof, binding: ast.Name, awaited: ast.Await, owner: ast.AsyncFunctionDef
) -> bool:
    for read in proof.provenance.binding_reads(binding.id, binding):
        member = proof.context.parents.get(read)
        if proof.provenance.scope(read) is not owner or not isinstance(member, ast.Attribute):
            return False
        if member.attr == "returncode" and isinstance(member.ctx, ast.Load):
            if member.lineno <= awaited.lineno:
                return False
            continue
        if not _is_same_or_later_wait(proof, member, awaited):
            return False
    return True


def _is_same_or_later_wait(proof: AsyncApiProof, member: ast.Attribute, awaited: ast.Await) -> bool:
    consumer = proof.context.parents.get(member)
    wait = proof.context.parents.get(consumer) if consumer is not None else None
    if member.attr not in {"wait", "communicate"} or not isinstance(consumer, ast.Call) or consumer.func is not member:
        return False
    return isinstance(wait, ast.Await) and wait.value is consumer and wait.lineno >= awaited.lineno


def _global_child_owner(context: PythonFileContext) -> bool:
    namespaces = _child_owner_namespaces(context)
    for node in context.nodes(ast.ImportFrom, ast.Attribute, ast.Name):
        if isinstance(node, ast.ImportFrom) and _imports_child_owner(node):
            return True
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id in namespaces:
            parent = context.parents.get(node)
            if not isinstance(parent, ast.Attribute) or parent.value is not node or parent.attr == "__dict__":
                return True
        elif isinstance(node, ast.Attribute) and _child_owner_member(node, namespaces):
            return True
    return False


def _child_owner_namespaces(context: PythonFileContext) -> dict[str, set[str]]:
    namespaces: dict[str, set[str]] = {}
    for node in context.nodes(ast.Import):
        for alias in node.names:
            if alias.name in {"os", "signal"}:
                namespaces.setdefault(alias.asname or alias.name, set()).add(alias.name)
    return namespaces


def _child_owner_member(node: ast.Attribute, namespaces: dict[str, set[str]]) -> bool:
    root: ast.expr = node.value
    while isinstance(root, ast.Attribute):
        root = root.value
    if not isinstance(root, ast.Name):
        return False
    modules = namespaces.get(root.id, set())
    return ("os" in modules and node.attr in _GLOBAL_REAPERS) or ("signal" in modules and node.attr == "SIGCHLD")


def _imports_child_owner(node: ast.ImportFrom) -> bool:
    return (node.module == "os" and any(alias.name in _GLOBAL_REAPERS for alias in node.names)) or (
        node.module == "signal" and any(alias.name == "SIGCHLD" for alias in node.names)
    )
