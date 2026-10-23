from __future__ import annotations

import ast
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, ClassVar, Final, final, override

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
from sarj_python_lint.rules._closed_helpers import executable_body
from sarj_python_lint.rules._imports import TYPING_SOURCES
from sarj_python_lint.rules._type_guard_symbols import (
    builtin_guard_symbol,
    guard_symbols_ambiguous,
    unique_guard_function_names,
)


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rules._imports import ImportIndex


_SCALARS = frozenset({"int", "bool", "str", "bytes"})
_BUILTINS = _SCALARS | {"object", "isinstance"}
_WITNESSES: Final = {
    "int": frozenset({"int", "bool"}),
    "bool": frozenset({"bool"}),
    "str": frozenset({"str"}),
    "bytes": frozenset({"bytes"}),
}
_ALL_WITNESSES = frozenset({"int", "bool", "str", "bytes", "none"})
_MAX_INPUT_NODES = 4096
_BAD = (
    "from typing import TypeGuard\ndef is_text(value: object) -> TypeGuard[str]:\n    return isinstance(value, int)\n"
)
_GOOD = _BAD.replace("isinstance(value, int)", "isinstance(value, str)")


@final
class NoContradictoryTypeGuard(Rule):
    id = "no-contradictory-type-guard"
    code = "SARJ513"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Primitive type guards must agree with the builtin predicate they return.",
        rationale=(
            "A guard annotation does not validate its implementation. Returning an incompatible primitive predicate "
            "check makes callers trust the wrong primitive; TypeIs also incorrectly excludes rejected target "
            "values in the false branch."
        ),
        remediation=(
            "Align the declared target and runtime test. For an intentional partial predicate, TypeGuard may "
            "narrow only the true branch; TypeIs must recognize every target value admitted by its input. "
            "Review callers before changing the narrowing contract."
        ),
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Checks undecorated, non-generic module functions with one parameter and a single returned direct builtin isinstance call, its unary not, or a bool constant, optionally after a docstring.",
            "Guard symbols must resolve to typing or typing_extensions TypeGuard or TypeIs. Targets and checked classes are builtin int, bool, str or bytes; bool is treated as an int subtype.",
            "Inputs must be object or fully classified plain unions of those primitive types and None. Direct positive impossible isinstance tests and compiler-invalid TypeIs target/input relationships are excluded.",
            "Input unions are traversed iteratively with a bounded node budget; overly complex annotations are excluded.",
            "Literal and refined targets, aliases, custom classes, float numeric promotion, tuple isinstance tests, helper predicates, nested functions and complex bodies are not inferred.",
            "TypeGuard may intentionally recognize a subset of its target, so TypeGuard[int] with an isinstance bool test remains legal. Visible namespace mutation and ambiguous or shadowed symbols abstain conservatively.",
            "Constant false remains legal for TypeGuard. Constant true is reported only with a proven incompatible primitive or None input; false TypeIs needs a proven inhabited target. Negated isinstance uses the same finite witness domains.",
            "Repeated top-level function definition names abstain because overloads can constrain the public input more narrowly than the implementation input.",
            "Generated files are excluded; maintained tests remain checked. No autofix guesses a domain or changes false-branch behavior.",
        ),
        examples=(
            RuleExample(
                example_id="wrong-primitive-promise",
                title="An integer test does not prove a string",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.python("app/guards.py", _BAD),),
                focus_path=PurePosixPath("app/guards.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="consistent-primitive-promise",
                title="Recognize the primitive promised to callers",
                outcome=ExampleOutcome.NO_MATCH,
                files=(ExampleFile.python("app/guards.py", _GOOD),),
                focus_path=PurePosixPath("app/guards.py"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="constant-true-claims-text",
                scenario="constant-predicate",
                title="A constant result does not prove a primitive type",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/guards.py",
                        "from typing import TypeGuard\ndef is_text(value: object) -> TypeGuard[str]:\n    return True\n",
                    ),
                ),
                focus_path=PurePosixPath("app/guards.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="constant-false-is-legal-partial-guard",
                scenario="constant-predicate",
                title="TypeGuard can intentionally recognize no inputs",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/guards.py",
                        "from typing import TypeGuard\ndef is_text(value: object) -> TypeGuard[str]:\n    return False\n",
                    ),
                ),
                focus_path=PurePosixPath("app/guards.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if context.generated or not any(symbol in context.symbol_source for symbol in ("TypeGuard", "TypeIs")):
            return []
        if context.tree is None or guard_symbols_ambiguous(context, _BUILTINS):
            return []
        findings: list[Diagnostic] = []
        unique_names = unique_guard_function_names(context)
        for function in context.tree.body:
            if not isinstance(function, ast.FunctionDef) or function.name not in unique_names:
                continue
            statement = _contradictory_return(function, context)
            if statement is None or is_suppressed(context.source_lines, statement.lineno, self.code):
                continue
            findings.append(
                Diagnostic(
                    context.path,
                    statement.lineno,
                    statement.col_offset + 1,
                    self.code,
                    "This guard's builtin predicate contradicts its primitive narrowing promise; align the target "
                    "and test, preserving TypeIs false-branch behavior and intentional TypeGuard partial predicates.",
                    severity=Severity.WARNING,
                )
            )
        return findings


def _contradictory_return(function: ast.FunctionDef, context: PythonFileContext) -> ast.Return | None:
    parameter = _sole_parameter(function)
    annotation = function.returns
    if parameter is None or not isinstance(annotation, ast.Subscript):
        return None
    guard = context.module_imports.resolved_symbol(annotation.value, sources=TYPING_SOURCES)
    if guard not in {"TypeGuard", "TypeIs"}:
        return None
    target_kind = builtin_guard_symbol(annotation.slice, context.module_imports, _BUILTINS)
    target = _WITNESSES.get(target_kind) if target_kind is not None else None
    inputs = _input_witnesses(parameter.annotation, context.module_imports)
    if target is None or inputs is None or (guard == "TypeIs" and not target <= inputs):
        return None
    statement = _single_return(function)
    accepted = _accepted_witnesses(statement.value, parameter.arg, inputs, context) if statement is not None else None
    if accepted is None:
        return None
    accepts_wrong = bool(accepted - target)
    rejects_target = guard == "TypeIs" and bool((inputs & target) - accepted)
    return statement if accepts_wrong or rejects_target else None


def _sole_parameter(function: ast.FunctionDef) -> ast.arg | None:
    args = function.args
    positional = [*args.posonlyargs, *args.args]
    if function.decorator_list or function.type_params or len(positional) != 1:
        return None
    if args.kwonlyargs or args.vararg is not None or args.kwarg is not None:
        return None
    return positional[0]


def _single_return(function: ast.FunctionDef) -> ast.Return | None:
    body = executable_body(function)
    return body[0] if len(body) == 1 and isinstance(body[0], ast.Return) else None


def _input_witnesses(annotation: ast.expr | None, imports: ImportIndex) -> frozenset[str] | None:
    pending = [annotation]
    visited = 0
    witnesses: set[str] = set()
    while pending:
        member = pending.pop()
        visited += 1
        if visited > _MAX_INPUT_NODES:
            return None
        if isinstance(member, ast.Constant) and member.value is None:
            witnesses.add("none")
            continue
        if isinstance(member, ast.BinOp) and isinstance(member.op, ast.BitOr):
            pending.extend((member.left, member.right))
            continue
        kind = builtin_guard_symbol(member, imports, _BUILTINS)
        if kind == "object":
            witnesses.update(_ALL_WITNESSES)
        elif kind in _WITNESSES:
            witnesses.update(_WITNESSES[kind])
        else:
            return None
    return frozenset(witnesses)


def _accepted_witnesses(
    node: ast.expr | None, parameter: str, inputs: frozenset[str], context: PythonFileContext
) -> frozenset[str] | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, bool):
        return inputs if node.value else frozenset()
    negate = isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not)
    expression = node.operand if negate and isinstance(node, ast.UnaryOp) else node
    checked_kind = _checked_kind(expression, parameter, context)
    checked = _WITNESSES.get(checked_kind) if checked_kind is not None else None
    if checked is None or (not negate and not inputs & checked):
        return None
    return inputs - checked if negate else inputs & checked


def _checked_kind(node: ast.expr | None, parameter: str, context: PythonFileContext) -> str | None:
    match node:
        case ast.Call(func=func, args=[ast.Name(id=name), target], keywords=[]) if name == parameter:
            if builtin_guard_symbol(func, context.imports, _BUILTINS) == "isinstance":
                return builtin_guard_symbol(target, context.imports, _BUILTINS)
        case _:
            pass
    return None
