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
from sarj_python_lint.rules._annotation_origins import AnnotationOrigins
from sarj_python_lint.rules._test_composition import call_arguments


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext

_RAW_PARSERS = frozenset({"argparse.ArgumentParser", "getopt.getopt", "getopt.gnu_getopt", "optparse.OptionParser"})
_CLICK_COMMANDS = frozenset({"click.command", "click.group", "click.Command", "click.Group"})
_MAX_DEPTH = 32
_BAD = "import sys\ndef main(arguments: list[str]) -> None:\n    deploy(arguments[0])\nmain(sys.argv[1:])\n"
_GOOD = "import typer\ndef main(service: str, attempts: int = 3) -> None:\n    deploy(service, attempts)\nif __name__ == '__main__':\n    typer.run(main)\n"


@final
class PreferTypedCli(Rule):
    id = "prefer-typed-cli"
    code = "SARJ533"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        default_level=Severity.ERROR,
        summary="Declare CLI arguments with typed Typer commands.",
        rationale="A list of argv strings does not declare positional meaning, conversions or option validation. Typer derives those contracts from the command signature and rejects invalid arguments before calling application code.",
        remediation="Use typer.run on a command with explicit parameter types, or register typed functions with Typer.command/callback. Preserve option names, defaults, validation and exit behavior during migration.",
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Checks import-proven sys.argv reads, argparse/optparse parser construction, getopt parsing and Click command construction. sys.argv[0], assignment targets and forwarding through args= to a proven local Typer application are retained.",
            "Checks parameters of source-visible functions passed directly to typer.run or registered with a stable local Typer application's command/callback decorator. Missing annotations and bare Any/object, including Annotated wrappers, are reported. Ordinary functions and unrelated command decorators are excluded.",
            "Stable local import and application aliases are followed. Shadowed or mutated imports, wildcard imports, dynamic namespaces and generated/vendor files abstain. Imported command functions, dynamic registrations and composite erased types require separate type checking.",
            "No automatic rewrite: positional/option compatibility and conversion behavior require review. This policy does not claim every argparse or Click program is incorrectly validated.",
        ),
        examples=(
            RuleExample(
                example_id="raw-argv",
                title="Positional strings hide the CLI contract",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.python("app/cli.py", _BAD),),
                focus_path=PurePosixPath("app/cli.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="typed-typer",
                title="The command declares each argument",
                outcome=ExampleOutcome.NO_MATCH,
                files=(ExampleFile.python("app/cli.py", _GOOD),),
                focus_path=PurePosixPath("app/cli.py"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="untyped-typer",
                scenario="command-annotations",
                title="Typer still needs parameter annotations",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/cli.py", "import typer\ndef main(service):\n    deploy(service)\ntyper.run(main)\n"
                    ),
                ),
                focus_path=PurePosixPath("app/cli.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="annotated-typer",
                scenario="command-annotations",
                title="Typer parses the declared parameter type",
                outcome=ExampleOutcome.NO_MATCH,
                files=(ExampleFile.python("app/cli.py", _GOOD),),
                focus_path=PurePosixPath("app/cli.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if (
            not any(
                name in context.symbol_source for name in ("sys", "argparse", "optparse", "getopt", "click", "typer")
            )
            or context.tree is None
            or context.generated
        ):
            return []
        facts = AnnotationOrigins(context)
        if facts.provenance.wildcard or facts.provenance.dynamic_namespace:
            return []
        nodes: set[ast.expr | ast.arg] = set(_raw_cli_inputs(facts))
        for function in _registered_commands(facts):
            for argument in ast.iter_child_nodes(function.args):
                if isinstance(argument, ast.arg) and _untyped_parameter(argument, facts):
                    nodes.add(argument)
        return [
            Diagnostic(
                context.path,
                node.lineno,
                node.col_offset + 1,
                self.code,
                "Declare CLI arguments with typed Typer command parameters; do not parse raw argv or use an untyped command signature.",
                severity=Severity.ERROR,
            )
            for node in sorted(nodes, key=lambda item: (item.lineno, item.col_offset))
            if not is_suppressed(context.source_lines, node.lineno, self.code)
        ]


def _raw_cli_inputs(facts: AnnotationOrigins) -> set[ast.expr]:
    nodes: set[ast.expr] = {
        node
        for node in facts.context.nodes(ast.Attribute, ast.Name)
        if isinstance(node.ctx, ast.Load)
        and facts.qualified(node, node) == "sys.argv"
        and not _retained_argv(node, facts)
    }
    for call in facts.context.nodes(ast.Call):
        if facts.qualified(call.func, call) in _RAW_PARSERS | _CLICK_COMMANDS:
            nodes.add(call)
    return nodes


def _registered_commands(facts: AnnotationOrigins) -> set[ast.FunctionDef | ast.AsyncFunctionDef]:
    commands: set[ast.FunctionDef | ast.AsyncFunctionDef] = set()
    for call in facts.context.nodes(ast.Call):
        if facts.qualified(call.func, call) != "typer.run":
            continue
        arguments = call_arguments(call, ("function",))
        if arguments is None:
            continue
        callback = arguments.get("function")
        if not isinstance(callback, ast.Name):
            continue
        function = facts.provenance.binding(callback.id, call)
        if isinstance(function, ast.FunctionDef | ast.AsyncFunctionDef):
            commands.add(function)
    for function in facts.context.nodes(ast.FunctionDef, ast.AsyncFunctionDef):
        if any(_command_decorator(decorator, facts) for decorator in function.decorator_list):
            commands.add(function)
    return commands


def _typer_app(node: ast.expr, facts: AnnotationOrigins, *, seen: frozenset[ast.AST] = frozenset()) -> bool:
    if len(seen) >= _MAX_DEPTH:
        return False
    if isinstance(node, ast.Call):
        return facts.qualified(node.func, node) == "typer.Typer"
    if not isinstance(node, ast.Name) or node.id in facts.provenance.mutated | facts.provenance.external_bindings:
        return False
    binding = facts.provenance.binding(node.id, node)
    if not isinstance(binding, ast.Name) or binding in seen:
        return False
    value = facts.provenance.assignment_value(binding, node)
    return value is not None and _typer_app(value, facts, seen=seen | {binding})


def _command_decorator(node: ast.expr, facts: AnnotationOrigins) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"command", "callback"}
        and _typer_app(node.func.value, facts)
    )


def _retained_argv(node: ast.expr, facts: AnnotationOrigins) -> bool:
    parent = facts.context.parents.get(node)
    if isinstance(parent, ast.Subscript) and parent.value is node:
        if isinstance(parent.ctx, ast.Store | ast.Del):
            return True
        if isinstance(parent.slice, ast.Constant) and type(parent.slice.value) is int and parent.slice.value == 0:
            return True
        parent = facts.context.parents.get(parent)
    if not isinstance(parent, ast.keyword) or parent.arg != "args":
        return False
    call = facts.context.parents.get(parent)
    return isinstance(call, ast.Call) and _typer_app(call.func, facts)


def _untyped_parameter(argument: ast.arg, facts: AnnotationOrigins) -> bool:
    if argument.annotation is None:
        return True
    resolved = facts.resolve_annotation(argument.annotation)
    for _ in range(_MAX_DEPTH):
        if resolved is None:
            return False
        node = resolved.expression
        if (
            isinstance(node, ast.Subscript)
            and facts.qualified(node.value, resolved.at) in {"typing.Annotated", "typing_extensions.Annotated"}
            and isinstance(node.slice, ast.Tuple)
        ):
            resolved = facts.resolve_annotation(node.slice.elts[0], at=resolved.at)
            continue
        return facts.builtin(node, "object", resolved.at) or facts.qualified(node, resolved.at) in {
            "typing.Any",
            "typing_extensions.Any",
        }
    return False
