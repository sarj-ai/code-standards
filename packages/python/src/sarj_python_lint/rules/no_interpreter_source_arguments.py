from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, ClassVar, final, override

from sarj_python_lint.interpreter_argv import classify_interpreter
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


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext


_SUBPROCESS = frozenset(
    {"subprocess.run", "subprocess.call", "subprocess.check_call", "subprocess.check_output", "subprocess.Popen"}
)
_EXEC_VECTOR = frozenset({"os.execv", "os.execve", "os.execvp", "os.execvpe", "os.posix_spawn", "os.posix_spawnp"})
_EXEC_LIST = frozenset({"os.execl", "os.execle", "os.execlp", "os.execlpe"})
_SPAWN_VECTOR = frozenset({"os.spawnv", "os.spawnve", "os.spawnvp", "os.spawnvpe"})
_SPAWN_LIST = frozenset({"os.spawnl", "os.spawnle", "os.spawnlp", "os.spawnlpe"})


@dataclass(frozen=True, slots=True)
class ProcessArguments:
    argv: ast.expr | None
    executable: ast.expr | None = None


@final
class NoInterpreterSourceArguments(ProjectRule):
    id = "no-interpreter-source-arguments"
    code = "SARJ462"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        default_level=Severity.ERROR,
        summary="Keep interpreter programs in linted files or modules, outside process argv.",
        rationale="Moving deployment logic from YAML into Python still bypasses language checks when the Python wrapper passes program source through interpreter flags or jq/awk argv.",
        remediation="Invoke a repository-owned file or module covered by the normal language checks; pass configuration as arguments rather than interpreter source.",
        category=RuleCategory.ARCHITECTURE,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only import-proven subprocess process APIs, asyncio.create_subprocess_exec, and os exec/spawn argv APIs with literal string vectors are checked. Import aliases are followed; shadowed or reassigned imports and methods abstain.",
            "Script/module and interpreter option boundaries use the shared dependency-free classifier, including env/sudo/timeout wrappers and jq/awk file flags.",
            "Dynamic argv, shell strings and shell=True, recursive shell payloads, receiver-based remote execution, and unknown interpreter option grammars are outside this narrow rule. A clean result does not prove those programs are linted.",
            "Generated/vendor sources are excluded; maintained tests are checked. Source-checker fixtures may use an exact reasoned suppression.",
        ),
        examples=(
            RuleExample(
                example_id="interpreter-source-argument",
                title="Process argv contains unchecked Python source",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "tools/check.py",
                        "import subprocess\nsubprocess.run(['python3', '-c', 'print(1)'], check=True)\n",
                    ),
                ),
                focus_path=PurePosixPath("tools/check.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="external-interpreter-module",
                title="Process argv invokes a checked module",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "tools/check.py",
                        "import subprocess\nsubprocess.run(['python3', '-m', 'tools.verify', '-c', 'strict'], check=True)\n",
                    ),
                ),
                focus_path=PurePosixPath("tools/check.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if context.generated or context.tree is None:
            return []
        imports = context.imports
        replaced = {
            name
            for node in context.nodes(ast.Attribute)
            if isinstance(node.ctx, (ast.Store, ast.Del))
            and (name := imports.resolved_qualified_name(node)) is not None
        }
        findings: list[Diagnostic] = []
        for call in context.nodes(ast.Call):
            sink = imports.resolved_qualified_name(call.func)
            if sink is None or sink in replaced or is_suppressed(context.source_lines, call.lineno, self.code):
                continue
            argv = _literal_argv(call, sink)
            if argv is None or classify_interpreter(argv).kind != "inline":
                continue
            findings.append(
                Diagnostic(
                    path=context.path,
                    line=call.lineno,
                    col=call.col_offset + 1,
                    code=self.code,
                    message="Interpreter source is embedded in process argv; invoke a linted repository-owned file or module instead.",
                    severity=Severity.ERROR,
                )
            )
        return findings


def _literal_argv(call: ast.Call, sink: str) -> tuple[str, ...] | None:
    if any(keyword.arg is None for keyword in call.keywords):
        return None  # Expanded options can replace the executable or enable shell=True.
    projected = _process_arguments(call, sink)
    if projected is None:
        return None
    argv = _vector(projected.argv)
    if not argv:
        return None
    return _override_executable(argv, projected.executable)


def _override_executable(argv: tuple[str, ...], executable: ast.expr | None) -> tuple[str, ...] | None:
    if executable is None:
        return argv
    resolved = _string(executable)
    return None if resolved is None else (resolved, *argv[1:])


def _process_arguments(call: ast.Call, sink: str) -> ProcessArguments | None:
    if sink in _SUBPROCESS:
        return _subprocess_arguments(call)
    if sink == "asyncio.create_subprocess_exec":
        return _asyncio_arguments(call)
    if sink in _EXEC_VECTOR | _SPAWN_VECTOR:
        offset = 1 if sink in _SPAWN_VECTOR else 0
        return ProcessArguments(
            _argument(call, "argv" if "posix_spawn" in sink else "args", offset + 1), _argument(call, "path", offset)
        )
    if sink in _EXEC_LIST | _SPAWN_LIST:
        offset = 1 if sink in _SPAWN_LIST else 0
        arguments = call.args[offset + 1 : -1] if sink.endswith("e") else call.args[offset + 1 :]
        return ProcessArguments(ast.Tuple(elts=arguments, ctx=ast.Load()), _argument(call, "path", offset))
    return None


def _subprocess_arguments(call: ast.Call) -> ProcessArguments | None:
    shell = _argument(call, "shell", len(call.args))
    if shell is not None and not (isinstance(shell, ast.Constant) and shell.value is False):
        return None
    return ProcessArguments(_argument(call, "args", 0), _argument(call, "executable", len(call.args)))


def _asyncio_arguments(call: ast.Call) -> ProcessArguments:
    arguments = call.args
    if not arguments:
        program = _argument(call, "program", 0)
        arguments = [program] if program is not None else []
    return ProcessArguments(ast.Tuple(elts=arguments, ctx=ast.Load()), _argument(call, "executable", len(call.args)))


def _argument(call: ast.Call, name: str, index: int) -> ast.expr | None:
    return (
        call.args[index]
        if index < len(call.args)
        else next((keyword.value for keyword in call.keywords if keyword.arg == name), None)
    )


def _vector(node: ast.expr | None) -> tuple[str, ...] | None:
    if not isinstance(node, (ast.List, ast.Tuple)):
        return None
    words = tuple(_string(item) for item in node.elts)
    return tuple(word for word in words if word is not None) if all(word is not None for word in words) else None


def _string(node: ast.expr | None) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None
