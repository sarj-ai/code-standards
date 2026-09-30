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


if TYPE_CHECKING:
    from collections.abc import Iterator

    from sarj_python_lint._file_context import PythonFileContext


type _Function = ast.FunctionDef | ast.AsyncFunctionDef
_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
_COMPREHENSIONS = (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)
_REFLECTIVE_CALLS = frozenset({"locals", "globals", "vars", "eval", "exec", "setattr", "delattr"})


@final
class PreferMonotonicForElapsedTime(Rule):
    id = "prefer-monotonic-for-elapsed-time"
    code = "SARJ461"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Use a monotonic clock for a local wall-clock value used only to measure elapsed time.",
        rationale=(
            "System-clock corrections can make wall-clock differences negative or unexpectedly large. "
            "A monotonic clock measures elapsed intervals without these jumps."
        ),
        remediation=(
            "Use time.monotonic() or time.perf_counter() for both the start reading and its elapsed-time readings. "
            "Keep time.time() when measuring absolute timestamps or deliberate wall-clock adjustments."
        ),
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only an unconditional, single-assignment function-local start reading whose every read is the right operand of time.time() - start is reported.",
            "Only unshadowed module-level clock imports are resolved. Reassignment, additional timestamp uses, escapes, nested-scope reads, comprehensions, reflection, and mixed-clock expressions are excluded.",
            "Instance fields, process or persisted deadlines, indirect end-clock readings, and generated files are not inferred. No automatic rewrite is provided.",
        ),
        examples=(
            RuleExample(
                example_id="wall-clock-elapsed",
                title="A local wall clock measures duration",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/metrics.py",
                        "import time\n\ndef measure():\n    started = time.time()\n    work()\n    return time.time() - started\n",
                    ),
                ),
                focus_path=PurePosixPath("app/metrics.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="monotonic-elapsed",
                title="A monotonic clock measures duration",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/metrics.py",
                        "import time\n\ndef measure():\n    started = time.monotonic()\n    work()\n    return time.monotonic() - started\n",
                    ),
                ),
                focus_path=PurePosixPath("app/metrics.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if "time" not in context.source or context.generated or context.tree is None or _clock_is_mutated(context):
            return []
        findings: list[Diagnostic] = []
        for function in context.nodes(ast.FunctionDef, ast.AsyncFunctionDef):
            for start in _elapsed_starts(context, function):
                if is_suppressed(context.source_lines, start.lineno, self.code):
                    continue
                findings.append(
                    Diagnostic(
                        path=context.path,
                        line=start.lineno,
                        col=start.col_offset + 1,
                        code=self.code,
                        severity=Severity.WARNING,
                        message="this wall-clock reading is used only for elapsed time; use a monotonic clock for both the start and elapsed readings",
                    )
                )
        return sorted(findings, key=lambda finding: (finding.line, finding.col))


def _elapsed_starts(context: PythonFileContext, function: _Function) -> Iterator[ast.Call]:
    nodes = tuple(ast.walk(function))
    if any(_reflective_call(node) for node in nodes):
        return
    for statement in function.body:
        candidate = _start_assignment(statement)
        if candidate is None:
            continue
        target, call = candidate
        if not _wall_clock(context, call) or any(_rebinds(node, target) for node in nodes):
            continue
        reads = _reads_of(nodes, target.id)
        if reads and all(_elapsed_read(context, function, call, read) for read in reads):
            yield call


def _start_assignment(statement: ast.stmt) -> tuple[ast.Name, ast.Call] | None:
    match statement:
        case (
            ast.Assign(targets=[ast.Name() as target], value=ast.Call() as call)
            | ast.AnnAssign(target=ast.Name() as target, value=ast.Call() as call)
        ):
            return target, call
        case _:
            return None


def _reads_of(nodes: tuple[ast.AST, ...], name: str) -> list[ast.Name]:
    return [node for node in nodes if isinstance(node, ast.Name) and node.id == name and isinstance(node.ctx, ast.Load)]


def _wall_clock(context: PythonFileContext, call: ast.expr) -> bool:
    return (
        isinstance(call, ast.Call)
        and not call.args
        and not call.keywords
        and context.imports.resolved_qualified_name(call.func) == "time.time"
    )


def _elapsed_read(context: PythonFileContext, function: _Function, start: ast.Call, read: ast.Name) -> bool:
    if (read.lineno, read.col_offset) <= (start.lineno, start.col_offset):
        return False
    parent = context.parents.get(read)
    if not isinstance(parent, ast.BinOp) or not isinstance(parent.op, ast.Sub) or parent.right is not read:
        return False
    if not _wall_clock(context, parent.left):
        return False
    owner = context.parents.get(parent)
    while owner is not None and owner is not function:
        if isinstance(owner, (*_SCOPES, *_COMPREHENSIONS)):
            return False
        owner = context.parents.get(owner)
    return owner is function


def _rebinds(node: ast.AST, target: ast.Name) -> bool:
    match node:
        case ast.Name(id=name, ctx=ast.Store() | ast.Del()):
            return node is not target and name == target.id
        case ast.arg(arg=name) | ast.FunctionDef(name=name) | ast.AsyncFunctionDef(name=name) | ast.ClassDef(name=name):
            return name == target.id
        case ast.alias(name=name, asname=alias):
            return (alias or name.partition(".")[0]) == target.id
        case ast.Global(names=names) | ast.Nonlocal(names=names):
            return target.id in names
        case (
            ast.ExceptHandler(name=name)
            | ast.MatchAs(name=name)
            | ast.MatchStar(name=name)
            | ast.MatchMapping(rest=name)
        ):
            return name == target.id
        case _:
            return False


def _reflective_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    return (isinstance(node.func, ast.Name) and node.func.id in _REFLECTIVE_CALLS) or (
        isinstance(node.func, ast.Attribute) and node.func.attr in _REFLECTIVE_CALLS
    )


def _clock_is_mutated(context: PythonFileContext) -> bool:
    if any(
        isinstance(node.ctx, (ast.Store, ast.Del)) and context.imports.resolved_qualified_name(node) == "time.time"
        for node in context.nodes(ast.Attribute)
    ):
        return True
    clocks = _clock_imports(context)
    if context.tree is None:
        return False
    for node in ast.walk(context.tree):
        if isinstance(node, ast.alias):
            if node.name == "*":
                return True
            statement = context.parents.get(node)
            if _is_direct_clock_import(context, statement, node):
                continue
        if any(_rebinds(node, clock) for clock in clocks):
            return True
    return False


def _clock_imports(context: PythonFileContext) -> list[ast.Name]:
    return [
        ast.Name(id=name, ctx=ast.Load())
        for name in context.imports.bindings
        if context.imports.resolved_qualified_name(ast.Name(id=name, ctx=ast.Load())) == "time.time"
        or context.imports.resolved_qualified_name(
            ast.Attribute(value=ast.Name(id=name, ctx=ast.Load()), attr="time", ctx=ast.Load())
        )
        == "time.time"
    ]


def _is_direct_clock_import(context: PythonFileContext, statement: ast.AST | None, alias: ast.alias) -> bool:
    if statement is None or context.parents.get(statement) is not context.tree or alias.name != "time":
        return False
    return isinstance(statement, ast.Import) or (
        isinstance(statement, ast.ImportFrom) and statement.module == "time" and statement.level == 0
    )
