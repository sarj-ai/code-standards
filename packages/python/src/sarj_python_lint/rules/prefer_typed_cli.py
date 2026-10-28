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
            "Checks import-proven sys.argv reads, argparse/optparse parser construction, getopt parsing and Click command construction. sys.argv[0], assignment targets and forwarding through args= to a proven local Typer application are retained. A source-proven isolated, fixed-arity path transport with a raising guard and checked Path conversion is also retained.",
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
    if isinstance(parent, ast.keyword) and parent.arg == "args":
        call = facts.context.parents.get(parent)
        if isinstance(call, ast.Call) and _typer_app(call.func, facts):
            return True
    return _isolated_path_transport(node, facts)


def _isolated_path_transport(node: ast.expr, facts: AnnotationOrigins) -> bool:
    selection = facts.context.parents.get(node)
    alternative = facts.context.parents.get(selection) if selection is not None else None
    assignment = facts.context.parents.get(alternative) if alternative is not None else None
    function = facts.context.parents.get(assignment) if assignment is not None else None
    if not (
        isinstance(selection, ast.Subscript)
        and selection.value is node
        and isinstance(selection.slice, ast.Slice)
        and _integer_constant(selection.slice.lower, 1)
        and selection.slice.upper is None
        and selection.slice.step is None
        and isinstance(alternative, ast.IfExp)
        and alternative.body is selection
        and isinstance(assignment, ast.Assign)
        and assignment.value is alternative
        and len(assignment.targets) == 1
        and isinstance(target := assignment.targets[0], ast.Name)
        and isinstance(function, ast.FunctionDef)
        and isinstance(facts.context.parents.get(function), ast.Module)
        and not function.decorator_list
        and not function.type_params
    ):
        return False
    match function.body:
        case [entry, ast.Expr(value=ast.Call() as guard_call), _, *_] if entry is assignment:
            pass
        case _:
            return False
    argument = _optional_argv_argument(function, facts)
    if not (
        argument is not None
        and isinstance(alternative.test, ast.Compare)
        and _same_binding(alternative.test.left, argument, facts)
        and len(alternative.test.ops) == len(alternative.test.comparators) == 1
        and isinstance(alternative.test.ops[0], ast.Is)
        and isinstance(alternative.test.comparators[0], ast.Constant)
        and alternative.test.comparators[0].value is None
        and _same_binding(alternative.orelse, argument, facts)
        and set(facts.provenance.binding_reads(argument.arg, argument)) == {alternative.test.left, alternative.orelse}
    ):
        return False
    arity = _isolated_arity_read(_guard_condition(guard_call, facts), target, facts)
    if arity is None:
        return False
    permitted = {arity}
    offset = 2
    if isinstance(probe := function.body[offset], ast.If):
        if not (
            isinstance(probe.test, ast.Compare)
            and (read := _fixed_element(probe.test.left, target, facts)) is not None
            and len(probe.test.ops) == len(probe.test.comparators) == 1
            and isinstance(probe.test.ops[0], ast.Eq)
            and isinstance(probe.test.comparators[0], ast.Constant)
            and isinstance(probe.test.comparators[0].value, str)
            and not probe.orelse
            and probe.body
            and isinstance(probe.body[-1], ast.Return)
        ):
            return False
        permitted.add(read)
        offset += 1
    if offset >= len(function.body):
        return False
    transfer = function.body[offset]
    if not (
        isinstance(transfer, ast.Assign)
        and len(transfer.targets) == 1
        and isinstance(transfer.targets[0], ast.Name)
        and isinstance(transfer.value, ast.Call)
        and len(transfer.value.args) == 1
        and not transfer.value.keywords
        and (read := _fixed_element(transfer.value.args[0], target, facts)) is not None
        and _checked_path(transfer.value, facts)
    ):
        return False
    permitted.add(read)
    return set(facts.provenance.binding_reads(target.id, target)) == permitted and not any(
        isinstance(child, ast.Yield | ast.YieldFrom) for child in ast.walk(function)
    )


def _optional_argv_argument(function: ast.FunctionDef, facts: AnnotationOrigins) -> ast.arg | None:
    parameters = (*function.args.posonlyargs, *function.args.args)
    if len(parameters) != 1 or function.args.vararg is not None or function.args.kwarg is not None:
        return None
    if function.args.kwonlyargs or len(function.args.defaults) != 1:
        return None
    if (
        not isinstance(function.args.defaults[0], ast.Constant)
        or function.args.defaults[0].value is not None
        or parameters[0].annotation is None
    ):
        return None
    annotation = facts.resolve_annotation(parameters[0].annotation)
    if (
        annotation is None
        or not isinstance(annotation.expression, ast.BinOp)
        or not isinstance(annotation.expression.op, ast.BitOr)
    ):
        return None
    left, right = annotation.expression.left, annotation.expression.right
    if isinstance(left, ast.Constant) and left.value is None:
        left, right = right, left
    return (
        parameters[0]
        if isinstance(right, ast.Constant)
        and right.value is None
        and isinstance(left, ast.Subscript)
        and facts.builtin(left.value, "list", annotation.at)
        and facts.builtin(left.slice, "str", annotation.at)
        else None
    )


def _isolated_arity_read(condition: ast.expr | None, target: ast.Name, facts: AnnotationOrigins) -> ast.Name | None:
    match condition:
        case ast.BoolOp(
            op=ast.And(),
            values=[
                ast.Compare(left=isolation, ops=[ast.Eq()], comparators=[isolated_value]),
                ast.Compare(left=ast.Call() as arity, ops=[ast.Eq()], comparators=[arity_value]),
            ],
        ):
            pass
        case _:
            return None
    return (
        arity.args[0]
        if _integer_constant(isolated_value, 1)
        and _integer_constant(arity_value, 1)
        and facts.qualified(isolation, isolation) == "sys.flags.isolated"
        and facts.builtin(arity.func, "len", arity)
        and len(arity.args) == 1
        and not arity.keywords
        and isinstance(arity.args[0], ast.Name)
        and _same_binding(arity.args[0], target, facts)
        else None
    )


def _guard_condition(call: ast.Call, facts: AnnotationOrigins) -> ast.expr | None:
    function = _local_function(call, facts)
    if (
        function is None
        or function.args.vararg is not None
        or function.args.kwarg is not None
        or function.args.defaults
        or any(default is not None for default in function.args.kw_defaults)
    ):
        return None
    match function.body:
        case [ast.If(test=ast.UnaryOp(op=ast.Not(), operand=ast.Name() as tested), body=failure, orelse=[])]:
            pass
        case _:
            return None
    if not _raises(failure, facts):
        return None
    positional = (*function.args.posonlyargs, *function.args.args)
    parameters = (*positional, *function.args.kwonlyargs)
    values = call_arguments(call, tuple(parameter.arg for parameter in positional))
    return (
        values.get(tested.id)
        if values is not None
        and set(values) == {parameter.arg for parameter in parameters}
        and any(_same_binding(tested, parameter, facts) for parameter in parameters)
        and all(isinstance(value, ast.Constant) for name, value in values.items() if name != tested.id)
        else None
    )


def _raises(body: list[ast.stmt], facts: AnnotationOrigins, *, seen: frozenset[ast.FunctionDef] = frozenset()) -> bool:
    if len(body) != 1 or any(isinstance(node, ast.Yield | ast.YieldFrom) for node in ast.walk(body[0])):
        return False
    if isinstance(body[0], ast.Raise):
        return True
    return (
        isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Call)
        and (function := _local_function(body[0].value, facts)) is not None
        and function not in seen
        and len(seen) < _MAX_DEPTH
        and _raises(function.body, facts, seen=seen | {function})
    )


def _local_function(call: ast.Call, facts: AnnotationOrigins) -> ast.FunctionDef | None:
    if (
        not isinstance(call.func, ast.Name)
        or call.func.id in facts.provenance.mutated | facts.provenance.external_bindings
    ):
        return None
    function = facts.provenance.binding(call.func.id, call)
    return (
        function
        if isinstance(function, ast.FunctionDef)
        and isinstance(facts.context.parents.get(function), ast.Module)
        and not function.decorator_list
        and not function.type_params
        else None
    )


def _checked_path(call: ast.Call, facts: AnnotationOrigins) -> bool:
    function = _local_function(call, facts)
    if function is None:
        return False
    match function.body:
        case [first, _, *_, last]:
            pass
        case _:
            return False
    parameters = (*function.args.posonlyargs, *function.args.args)
    if not (
        len(parameters) == 1
        and function.args.vararg is None
        and function.args.kwarg is None
        and not function.args.defaults
        and all(
            isinstance(default, ast.Constant) and type(default.value) is bool for default in function.args.kw_defaults
        )
        and isinstance(first, ast.Assign)
        and len(first.targets) == 1
        and isinstance(text := first.targets[0], ast.Name)
        and isinstance(first.value, ast.Call)
        and len(first.value.args) == 1
        and not first.value.keywords
        and _same_binding(first.value.args[0], parameters[0], facts)
        and _checked_text(first.value, facts)
        and isinstance(last, ast.Return)
        and isinstance(last.value, ast.Name)
    ):
        return False
    constructors = [
        statement
        for statement in function.body
        if isinstance(statement, ast.Assign)
        and isinstance(statement.value, ast.Call)
        and facts.qualified(statement.value.func, statement.value) == "pathlib.Path"
    ]
    if len(constructors) != 1:
        return False
    constructor = constructors[0]
    if not (
        len(constructor.targets) == 1
        and isinstance(path := constructor.targets[0], ast.Name)
        and isinstance(constructor.value, ast.Call)
        and len(constructor.value.args) == 1
        and not constructor.value.keywords
        and _same_binding(constructor.value.args[0], text, facts)
        and _same_binding(last.value, path, facts)
        and set(facts.provenance.binding_reads(parameters[0].arg, parameters[0])) == {first.value.args[0]}
        and text.id not in facts.provenance.mutated
        and path.id not in facts.provenance.mutated
    ):
        return False
    return all(
        read is constructor.value.args[0] or _path_validation_read(read, path, facts)
        for read in facts.provenance.binding_reads(text.id, text)
    ) and not any(
        (isinstance(child, ast.Return) and child is not last)
        or isinstance(child, ast.Try | ast.TryStar | ast.With | ast.AsyncWith | ast.Yield | ast.YieldFrom)
        for child in ast.walk(function)
    )


def _path_validation_read(read: ast.Name, path: ast.Name, facts: AnnotationOrigins) -> bool:
    statement: ast.AST | None = read
    while statement is not None and not isinstance(statement, ast.stmt):
        statement = facts.context.parents.get(statement)
    if not isinstance(statement, ast.Expr) or not isinstance(statement.value, ast.Call):
        return False
    condition = _guard_condition(statement.value, facts)
    if condition is None or read not in ast.walk(condition):
        return False
    parent = facts.context.parents.get(read)
    if isinstance(parent, ast.Call):
        return facts.builtin(parent.func, "bool", parent) and parent.args == [read] and not parent.keywords
    if not (isinstance(parent, ast.Compare) and len(parent.ops) == 1 and parent.comparators == [read]):
        return False
    return (
        isinstance(parent.ops[0], ast.NotIn)
        and isinstance(parent.left, ast.Constant)
        and isinstance(parent.left.value, str)
    ) or (
        isinstance(parent.ops[0], ast.Eq)
        and isinstance(parent.left, ast.Call)
        and facts.builtin(parent.left.func, "str", parent.left)
        and len(parent.left.args) == 1
        and not parent.left.keywords
        and _same_binding(parent.left.args[0], path, facts)
    )


def _checked_text(call: ast.Call, facts: AnnotationOrigins) -> bool:
    function = _local_function(call, facts)
    if function is None:
        return False
    parameters = (*function.args.posonlyargs, *function.args.args)
    if (
        len(parameters) != 1
        or function.args.vararg is not None
        or function.args.kwarg is not None
        or function.args.kwonlyargs
        or function.args.defaults
    ):
        return False
    match function.body:
        case [
            ast.If(
                test=ast.UnaryOp(
                    op=ast.Not(), operand=ast.Call(args=[value, expected_type], keywords=[]) as validation
                ),
                body=failure,
                orelse=[],
            ),
            ast.Return(value=ast.expr() as returned),
        ]:
            pass
        case _:
            return False
    return (
        facts.builtin(validation.func, "isinstance", validation)
        and _same_binding(value, parameters[0], facts)
        and facts.builtin(expected_type, "str", validation)
        and _raises(failure, facts)
        and _same_binding(returned, parameters[0], facts)
    )


def _same_binding(node: ast.expr, binding: ast.Name | ast.arg, facts: AnnotationOrigins) -> bool:
    name = binding.id if isinstance(binding, ast.Name) else binding.arg
    return isinstance(node, ast.Name) and node.id == name and facts.provenance.binding(name, node) is binding


def _fixed_element(node: ast.expr, target: ast.Name, facts: AnnotationOrigins) -> ast.Name | None:
    return (
        node.value
        if isinstance(node, ast.Subscript)
        and isinstance(node.ctx, ast.Load)
        and isinstance(node.value, ast.Name)
        and _same_binding(node.value, target, facts)
        and _integer_constant(node.slice, 0)
        else None
    )


def _integer_constant(node: ast.AST | None, value: int) -> bool:
    return isinstance(node, ast.Constant) and type(node.value) is int and node.value == value


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
