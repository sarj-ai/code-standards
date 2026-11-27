from __future__ import annotations

import ast
from dataclasses import dataclass
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
_OPAQUE_INPUTS = frozenset({"Any", "Never", "NoReturn"})
_LEGACY_TYPE_PARAMETERS = frozenset({"TypeVar", "TypeVarTuple", "ParamSpec"})
_MAX_INPUT_NODES = 4096
_BAD = (
    "from typing import TypeGuard\ndef is_text(value: object) -> TypeGuard[str]:\n    return isinstance(value, int)\n"
)
_GOOD = _BAD.replace("isinstance(value, int)", "isinstance(value, str)")
_CONSTANT_CLASS_GUARD = (
    "from typing import TypeIs\n\nclass User:\n    pass\n\ndef is_user(value: object) -> TypeIs[User]:\n"
    "    return True\n"
)


@dataclass(frozen=True, slots=True)
class _Contradiction:
    statement: ast.Return
    message: str


@final
class NoContradictoryTypeGuard(Rule):
    id = "no-contradictory-type-guard"
    code = "SARJ513"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        default_level=Severity.ERROR,
        summary="Type guards must agree with the predicate they return.",
        rationale=(
            "Callers trust a guard's declared target. An incompatible primitive test or an unconditional result "
            "can narrow a value incorrectly. TypeIs can also exclude the target incorrectly in the false branch."
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
            "Guard symbols must resolve to typing or typing_extensions TypeGuard or TypeIs. Runtime predicate checks cover builtin int, bool, str and bytes, with bool treated as an int subtype.",
            "Primitive checks require object or fully classified plain unions of those primitive types and None. Direct positive impossible isinstance tests and compiler-invalid TypeIs target/input relationships are excluded.",
            "Input unions are traversed iteratively with a bounded node budget; overly complex annotations are excluded.",
            "Literal and refined targets, aliases, custom classes, float numeric promotion, tuple isinstance tests, helper predicates, nested functions and complex bodies are outside the runtime predicate analysis.",
            "TypeGuard may intentionally recognize a subset of its target, so TypeGuard[int] with an isinstance bool test remains legal. Visible namespace mutation and ambiguous or shadowed symbols abstain conservatively.",
            "Constant results also cover class and parameterized targets. Constant false is valid for TypeGuard and for TypeIs with a directly imported bottom type. Constant true is valid when the input and target annotations agree directly. Bare object targets and untyped, Any or bottom-type inputs abstain. Proper primitive checks retain their finite witness domains.",
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
            RuleExample(
                example_id="constant-true-claims-class",
                scenario="class-predicate",
                title="An unconditional result does not identify a user",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.python("app/guards.py", _CONSTANT_CLASS_GUARD),),
                focus_path=PurePosixPath("app/guards.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="runtime-test-identifies-class",
                scenario="class-predicate",
                title="Check the value's class before narrowing",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/guards.py", _CONSTANT_CLASS_GUARD.replace("return True", "return isinstance(value, User)")
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
        if context.tree is None:
            return []
        findings: list[Diagnostic] = []
        unique_names = unique_guard_function_names(context)
        for function in context.tree.body:
            if not isinstance(function, ast.FunctionDef) or function.name not in unique_names:
                continue
            contradiction = _contradictory_return(function, context)
            if contradiction is None:
                continue
            statement = contradiction.statement
            if context.suppressions.is_suppressed(statement.lineno, self.code):
                continue
            findings.append(
                Diagnostic(
                    context.path,
                    statement.lineno,
                    statement.col_offset + 1,
                    self.code,
                    contradiction.message,
                    severity=Severity.ERROR,
                )
            )
        if findings and guard_symbols_ambiguous(context, _BUILTINS):
            return []
        return findings


def _contradictory_return(function: ast.FunctionDef, context: PythonFileContext) -> _Contradiction | None:
    parameter = _sole_parameter(function)
    annotation = function.returns
    if parameter is None or not isinstance(annotation, ast.Subscript):
        return None
    guard = context.module_imports.resolved_symbol(annotation.value, sources=TYPING_SOURCES)
    if guard not in {"TypeGuard", "TypeIs"}:
        return None
    statement = _single_return(function)
    if statement is None:
        return None
    target_kind = builtin_guard_symbol(annotation.slice, context.module_imports, _BUILTINS)
    target = _WITNESSES.get(target_kind) if target_kind is not None else None
    if target is None:
        if _contradictory_constant(guard, parameter.annotation, annotation.slice, statement.value, context):
            return _Contradiction(
                statement,
                "This guard returns a constant without testing its target; check the value before narrowing.",
            )
        return None
    inputs = _input_witnesses(parameter.annotation, context.module_imports)
    if inputs is None or (guard == "TypeIs" and not target <= inputs):
        return None
    accepted = _accepted_witnesses(statement.value, parameter.arg, inputs, context)
    if accepted is None:
        return None
    accepts_wrong = bool(accepted - target)
    rejects_target = guard == "TypeIs" and bool((inputs & target) - accepted)
    if accepts_wrong or rejects_target:
        return _Contradiction(
            statement,
            (
                "This guard's builtin predicate contradicts its primitive narrowing promise; align the target "
                "and test, preserving TypeIs false-branch behavior and intentional TypeGuard partial predicates."
            ),
        )
    return None


def _contradictory_constant(
    guard: str,
    input_annotation: ast.expr | None,
    target_annotation: ast.expr,
    result: ast.expr | None,
    context: PythonFileContext,
) -> bool:
    if not isinstance(result, ast.Constant) or type(result.value) is not bool:
        return False
    if not result.value and guard == "TypeGuard":
        return False
    input_type = context.annotation_semantics.parse(input_annotation)
    target = context.annotation_semantics.parse(target_annotation)
    if input_type is None or target is None:
        return False
    imports = context.module_imports
    if builtin_guard_symbol(target, imports, _BUILTINS) is not None:
        return False
    if imports.resolved_symbol(input_type, sources=TYPING_SOURCES) in _OPAQUE_INPUTS:
        return False
    target_symbol = imports.resolved_symbol(target, sources=TYPING_SOURCES)
    if target_symbol == "Any" or (not result.value and target_symbol in _OPAQUE_INPUTS):
        return False
    if _uses_legacy_type_parameter(input_type, target, context):
        return False
    return not result.value or not ast.compare(input_type, target)


def _uses_legacy_type_parameter(input_type: ast.expr, target: ast.expr, context: PythonFileContext) -> bool:
    tree = context.tree
    if tree is None or not any(symbol in context.symbol_source for symbol in _LEGACY_TYPE_PARAMETERS):
        return False
    annotation_names = {
        name.id for annotation in (input_type, target) for name in ast.walk(annotation) if isinstance(name, ast.Name)
    }
    for statement in tree.body:
        match statement:
            case (
                ast.Assign(targets=[ast.Name(id=name)], value=ast.Call(func=factory))
                | ast.AnnAssign(target=ast.Name(id=name), value=ast.Call(func=factory))
            ) if name in annotation_names and (
                context.module_imports.resolved_symbol(factory, sources=TYPING_SOURCES) in _LEGACY_TYPE_PARAMETERS
            ):
                return True
            case _:
                continue
    return False


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
        match member:
            case ast.Constant() if member.value is None:
                witnesses.add("none")
                continue
            case ast.BinOp() if isinstance(member.op, ast.BitOr):
                pending.extend((member.left, member.right))
                continue
            case _:
                pass
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
