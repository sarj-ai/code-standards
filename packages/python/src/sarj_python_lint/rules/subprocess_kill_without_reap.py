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


_BAD = "import subprocess\ndef run(args):\n    process = subprocess.Popen(args)\n    try:\n        process.communicate(timeout=1)\n    except subprocess.TimeoutExpired:\n        process.kill()\n"
_REAP_METHODS = frozenset({"wait", "communicate", "poll"})


class SubprocessKillWithoutReap(Rule):
    id: str = "subprocess-kill-without-reap"
    code: str = "SARJ463"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Reap a locally owned subprocess after killing it on timeout.",
        rationale="Sending a kill signal does not wait for process termination or collect the exit status; deterministic cleanup still requires waiting or communication.",
        remediation="After kill(), call communicate() when owning captured pipes, or wait() when output is handled separately; an enclosing Popen context manager can also own cleanup.",
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Requires a unique, dominating local subprocess.Popen assignment and a resolved TimeoutExpired handler ending with a direct kill() after that process's wait or communicate.",
            "Borrowed processes, custom factories, context-managed ownership, aliases, escaped handles or cleanup callbacks, and any later wait/communicate/poll are excluded conservatively.",
            "Only direct timeout handlers are checked. Cross-function lifecycle, fields, dynamic mutation, arbitrary exit paths, and generated files are not analyzed. Choosing wait versus communicate requires reviewing output ownership.",
        ),
        examples=(
            RuleExample(
                example_id="unreaped-child",
                title="Killing does not complete cleanup",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.python("app/processes.py", _BAD),),
                focus_path=PurePosixPath("app/processes.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="reaped-child",
                title="Drain and wait after killing",
                outcome=ExampleOutcome.NO_MATCH,
                files=(ExampleFile.python("app/processes.py", _BAD + "        process.communicate()\n"),),
                focus_path=PurePosixPath("app/processes.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description: str = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if "kill" not in context.source or context.generated or context.tree is None:
            return []
        provenance = ResourceProvenance(context)
        findings: list[Diagnostic] = []
        for handler in context.nodes(ast.ExceptHandler):
            call = _unreaped_kill(context, provenance, handler)
            if call is None or is_suppressed(context.source_lines, call.lineno, self.code):
                continue
            findings.append(
                Diagnostic(
                    path=context.path,
                    line=call.lineno,
                    col=call.col_offset + 1,
                    code=self.code,
                    severity=Severity.WARNING,
                    message="this Popen timeout handler kills the child without a subsequent reap; call communicate() for owned pipes or wait() when output is handled separately",
                )
            )
        return findings


def _unreaped_kill(
    context: PythonFileContext, provenance: ResourceProvenance, handler: ast.ExceptHandler
) -> ast.Call | None:
    if handler.type is None or not provenance.imported(handler.type, "subprocess.TimeoutExpired"):
        return None
    last = handler.body[-1]
    if not isinstance(last, ast.Expr) or not isinstance(last.value, ast.Call):
        return None
    call = last.value
    receiver = _method_receiver(call, frozenset({"kill"}))
    if receiver is None or call.args or call.keywords or not provenance.unescaped(receiver, call):
        return None
    binding = provenance.binding(receiver.id, call)
    if not isinstance(binding, ast.Name) or provenance.scope(binding) is not provenance.scope(call):
        return None
    if not isinstance(context.parents.get(binding), ast.Assign | ast.AnnAssign):
        return None
    if not isinstance(provenance.scope(call), ast.FunctionDef | ast.AsyncFunctionDef):
        return None
    constructor = provenance.constructor(receiver, call)
    if constructor is None or not provenance.imported(constructor.func, "subprocess.Popen"):
        return None
    owner = context.parents.get(handler)
    if not isinstance(owner, ast.Try) or not _waits_for_process(owner.body, receiver.id):
        return None
    for other in context.nodes(ast.Call):
        other_receiver = _method_receiver(other, _REAP_METHODS)
        if (
            other_receiver is not None
            and other.lineno > call.lineno
            and provenance.binding(other_receiver.id, other) is binding
        ):
            return None
    return call


def _waits_for_process(body: list[ast.stmt], name: str) -> bool:
    for statement in body:
        value = statement.value if isinstance(statement, ast.Expr | ast.Assign | ast.AnnAssign) else None
        if (
            isinstance(value, ast.Call)
            and (receiver := _method_receiver(value, frozenset({"wait", "communicate"}))) is not None
            and receiver.id == name
        ):
            return True
    return False


def _method_receiver(call: ast.Call, methods: frozenset[str]) -> ast.Name | None:
    function = call.func
    if isinstance(function, ast.Attribute) and function.attr in methods and isinstance(function.value, ast.Name):
        return function.value
    return None
