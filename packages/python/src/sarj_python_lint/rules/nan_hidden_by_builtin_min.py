from __future__ import annotations

import ast
from dataclasses import dataclass
import math
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, final, override

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
from sarj_python_lint.rules._numeric_proof import (
    imported_api,
    local_value,
    native_builtin,
    overridden_exit,
    value_origin,
)
from sarj_python_lint.rules._paths import is_test_path


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext


_FINITE = frozenset({"math.isfinite", "numpy.isfinite"})
_MAX_PROOF_DEPTH = 8
_MIN_REDUCTION_OPERANDS = 2
_NUMPY_FLOATS = frozenset({"numpy.float16", "numpy.float32", "numpy.float64", "numpy.longdouble"})
_BAD = """import math

def validate(single: float, batched: float) -> None:
    lowest = min(single, batched)
    if not math.isfinite(lowest) or lowest < 0.99:
        raise ValueError("Invalid export")
"""
_GOOD = """import math

def validate(single: float, batched: float) -> None:
    if not math.isfinite(single) or not math.isfinite(batched):
        raise ValueError("Invalid export")
    lowest = min(single, batched)
    if lowest < 0.99:
        raise ValueError("Invalid export")
"""


@dataclass(frozen=True, slots=True)
class _FloatValue:
    origin: str
    nan: bool = True
    finite: bool = True


@final
class NanHiddenByBuiltinMin(Rule):
    id = "nan-hidden-by-builtin-min"
    code = "SARJ539"
    documentation = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Validate floating candidates before a built-in min/max can hide a NaN.",
        rationale="Python's min/max compares operands in order. A later NaN can be ignored, leaving a finite result that passes a finiteness check even though an original candidate was invalid.",
        remediation="Check every floating candidate before reducing it, or use a deliberately NaN-propagating reduction and validate its result.",
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Requires an unshadowed multiargument built-in min/max, stable local aliases/float conversion, and a subsequent direct not math.isfinite/numpy.isfinite rejection guard. Only a single raising guard or its OR with direct comparisons is supported.",
            "Floating candidates are direct float-typed parameters, float literals/casts, known NumPy floating constructors, or scalar min results from closed local NumPy array/asarray constructors with explicit floating dtype and optional sum. The initial array payload must be a direct unannotated or float-typed parameter; literal, locally assembled and integer-typed payloads abstain. NumPy scalar constructors require an already proved NaN-capable scalar argument. Unknown methods named min and external model arrays are not inferred.",
            "Requires a finite-capable first operand and a distinct later NaN-capable origin. Integer-only inputs, repeated aliases of the same floating origin, a known NaN first operand, custom key/comparators, mutation/escape and unknown numeric types abstain.",
            "Any preceding finiteness check in the same function causes abstention rather than attempting arbitrary validator/control-flow equivalence. Dynamic namespaces, import mutations/escapes, test and generated files are excluded. The warning concerns an ineffective finiteness subcheck; it does not prove every other acceptance condition is satisfiable. Control-transferring enclosing finalizers abstain. There is no automatic rewrite or rule against deliberate NaN-ignoring APIs.",
        ),
        examples=(
            RuleExample(
                example_id="nan-hidden-before-finite-check",
                title="Do not validate only the reduced value",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.python("app/export_validation.py", _BAD),),
                focus_path=PurePosixPath("app/export_validation.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="candidates-checked-first",
                title="Validate each floating candidate",
                outcome=ExampleOutcome.NO_MATCH,
                files=(ExampleFile.python("app/export_validation.py", _GOOD),),
                focus_path=PurePosixPath("app/export_validation.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if (
            "isfinite" not in context.symbol_source
            or context.generated
            or is_test_path(context.path)
            or context.tree is None
        ):
            return []
        if context.dynamic_namespace or context.has_wildcard_import:
            return []
        findings: dict[tuple[int, int], Diagnostic] = {}
        for branch in context.nodes(ast.If):
            if overridden_exit(context, branch):
                continue
            if len(branch.body) != 1 or not isinstance(branch.body[0], ast.Raise):
                continue
            for checked in _rejected_values(context, branch.test):
                reduced = _unchecked_nan_reduction(context, branch, checked)
                if reduced is None:
                    continue
                if is_suppressed(context.source_lines, reduced.lineno, self.code):
                    continue
                key = reduced.lineno, reduced.col_offset
                findings[key] = Diagnostic(
                    path=context.path,
                    line=reduced.lineno,
                    col=reduced.col_offset + 1,
                    code=self.code,
                    severity=Severity.WARNING,
                    message="a later floating NaN can be hidden by this built-in min/max before its result is checked for finiteness; validate every candidate first",
                )
        return [findings[key] for key in sorted(findings)]


def _unchecked_nan_reduction(context: PythonFileContext, branch: ast.If, checked: ast.expr) -> ast.Call | None:
    reduced = _reduction(context, checked)
    if reduced is None or not _masked_nan(context, reduced):
        return None
    owner = context.static_resource_provenance.scope(reduced)
    if not isinstance(owner, ast.FunctionDef | ast.AsyncFunctionDef):
        return None
    if context.static_resource_provenance.scope(branch) is not owner:
        return None
    if _earlier_finiteness_check(context, reduced, owner):
        return None
    return reduced


def _earlier_finiteness_check(
    context: PythonFileContext, reduced: ast.Call, owner: ast.FunctionDef | ast.AsyncFunctionDef
) -> bool:
    return any(
        call.lineno < reduced.lineno
        and context.static_resource_provenance.scope(call) is owner
        and context.imports.resolved_qualified_name(call.func) in _FINITE
        for call in context.nodes(ast.Call)
    )


def _rejected_values(context: PythonFileContext, expression: ast.expr) -> list[ast.expr]:
    if isinstance(expression, ast.BoolOp) and isinstance(expression.op, ast.Or):
        return _or_rejected_values(context, expression)
    if not isinstance(expression, ast.UnaryOp) or not isinstance(expression.op, ast.Not):
        return []
    call = expression.operand
    if not isinstance(call, ast.Call) or len(call.args) != 1 or call.keywords:
        return []
    return [call.args[0]] if any(imported_api(context, call.func, name) for name in _FINITE) else []


def _or_rejected_values(context: PythonFileContext, expression: ast.BoolOp) -> list[ast.expr]:
    if any(not isinstance(value, ast.Compare | ast.UnaryOp) for value in expression.values):
        return []
    checked: list[ast.expr] = []
    for value in expression.values:
        if isinstance(value, ast.UnaryOp):
            checked.extend(_rejected_values(context, value))
    if not checked:
        return []
    origins = {value_origin(context, value) for value in checked}
    for value in expression.values:
        if isinstance(value, ast.Compare):
            if not _comparison_uses_origin(context, value, origins):
                return []
        elif not _rejected_values(context, value):
            return []
    return checked


def _comparison_uses_origin(context: PythonFileContext, comparison: ast.Compare, origins: set[str]) -> bool:
    return any(value_origin(context, operand) in origins for operand in [comparison.left, *comparison.comparators])


def _reduction(context: PythonFileContext, expression: ast.expr, *, depth: int = 0) -> ast.Call | None:
    if depth > _MAX_PROOF_DEPTH:
        return None
    if isinstance(expression, ast.Name):
        value = local_value(context, expression)
        return _reduction(context, value, depth=depth + 1) if value is not None else None
    if not isinstance(expression, ast.Call):
        return None
    if native_builtin(context, expression.func, "float") and len(expression.args) == 1 and not expression.keywords:
        return _reduction(context, expression.args[0], depth=depth + 1)
    if len(expression.args) < _MIN_REDUCTION_OPERANDS or expression.keywords:
        return None
    return expression if any(native_builtin(context, expression.func, name) for name in ("min", "max")) else None


def _masked_nan(context: PythonFileContext, call: ast.Call) -> bool:
    candidates = [_floating(context, value) for value in call.args]
    if any(value is None for value in candidates):
        return False
    first = candidates[0]
    return (
        first is not None
        and first.finite
        and any(value is not None and value.nan and value.origin != first.origin for value in candidates[1:])
    )


def _floating(context: PythonFileContext, expression: ast.expr, *, depth: int = 0) -> _FloatValue | None:
    if depth > _MAX_PROOF_DEPTH:
        return None
    if isinstance(expression, ast.Constant) and type(expression.value) is float:
        return _literal_float(expression.value, ast.dump(expression))
    if isinstance(expression, ast.Name):
        return _floating_name(context, expression, depth=depth)
    if not isinstance(expression, ast.Call):
        return None
    builtin_float = native_builtin(context, expression.func, "float")
    if builtin_float or any(imported_api(context, expression.func, name) for name in _NUMPY_FLOATS):
        return _float_conversion(context, expression, builtin_float=builtin_float, depth=depth)
    if (
        isinstance(expression.func, ast.Attribute)
        and expression.func.attr == "min"
        and not expression.args
        and not expression.keywords
    ):
        origin = _floating_array(context, expression.func.value, depth=depth + 1)
        return _FloatValue(origin) if origin is not None else None
    return None


def _floating_name(context: PythonFileContext, expression: ast.Name, *, depth: int) -> _FloatValue | None:
    binding = context.static_resource_provenance.binding(expression.id, expression)
    if (
        isinstance(binding, ast.arg)
        and isinstance(binding.annotation, ast.Name)
        and native_builtin(context, binding.annotation, "float")
    ):
        return _FloatValue(value_origin(context, expression))
    value = local_value(context, expression)
    return _floating(context, value, depth=depth + 1) if value is not None else None


def _float_conversion(
    context: PythonFileContext, expression: ast.Call, *, builtin_float: bool, depth: int
) -> _FloatValue | None:
    if len(expression.args) != 1 or expression.keywords:
        return None
    argument = expression.args[0]
    previous = _floating(context, argument, depth=depth + 1)
    if not builtin_float:
        return previous if previous is not None and previous.nan else None
    resolved = _conversion_argument(context, argument, depth=depth)
    if resolved is None:
        return None
    if isinstance(resolved, ast.Constant) and isinstance(resolved.value, str | int | float):
        try:
            value = float(resolved.value)
        except ValueError, OverflowError:
            return None
        return _literal_float(value, ast.dump(resolved))
    return previous or _FloatValue(value_origin(context, argument))


def _conversion_argument(context: PythonFileContext, argument: ast.expr, *, depth: int) -> ast.expr | None:
    resolved = argument
    while isinstance(resolved, ast.Name):
        if depth >= _MAX_PROOF_DEPTH:
            return None
        binding = context.static_resource_provenance.binding(resolved.id, resolved)
        if (
            isinstance(binding, ast.arg)
            and binding.annotation is not None
            and any(native_builtin(context, binding.annotation, name) for name in ("int", "bool"))
        ):
            return None
        aliased = local_value(context, resolved)
        if aliased is None:
            break
        resolved = aliased
        depth += 1
    return resolved


def _literal_float(value: float, origin: str) -> _FloatValue | None:
    return (
        _FloatValue(origin, nan=math.isnan(value), finite=math.isfinite(value))
        if math.isnan(value) or math.isfinite(value)
        else None
    )


def _floating_array(context: PythonFileContext, expression: ast.expr, *, depth: int) -> str | None:
    if depth > _MAX_PROOF_DEPTH:
        return None
    if isinstance(expression, ast.Name):
        return _local_array_origin(context, expression, depth=depth)
    if not isinstance(expression, ast.Call):
        return None
    if isinstance(expression.func, ast.Attribute) and expression.func.attr == "sum":
        return _summed_array_origin(context, expression, expression.func, depth=depth)
    return _constructed_array_origin(context, expression)


def _local_array_origin(context: PythonFileContext, expression: ast.Name, *, depth: int) -> str | None:
    provenance = context.static_resource_provenance
    binding = provenance.binding(expression.id, expression)
    if not isinstance(binding, ast.Name) or expression.id in provenance.mutated:
        return None
    for read in provenance.binding_reads(expression.id, binding):
        member = context.parents.get(read)
        call = context.parents.get(member) if member is not None else None
        if (
            not isinstance(member, ast.Attribute)
            or member.attr not in {"sum", "min"}
            or not isinstance(call, ast.Call)
            or call.func is not member
        ):
            return None
    value = local_value(context, expression)
    return _floating_array(context, value, depth=depth + 1) if value is not None else None


def _summed_array_origin(
    context: PythonFileContext, expression: ast.Call, method: ast.Attribute, *, depth: int
) -> str | None:
    if expression.args or any(
        item.arg != "axis" or not isinstance(item.value, ast.Constant) for item in expression.keywords
    ):
        return None
    origin = _floating_array(context, method.value, depth=depth + 1)
    axis = next((item.value.value for item in expression.keywords if isinstance(item.value, ast.Constant)), None)
    return f"sum:{origin}:{axis!r}" if origin is not None else None


def _constructed_array_origin(context: PythonFileContext, expression: ast.Call) -> str | None:
    if not any(imported_api(context, expression.func, name) for name in ("numpy.array", "numpy.asarray")):
        return None
    if len(expression.args) != 1 or any(item.arg != "dtype" for item in expression.keywords):
        return None
    payload = expression.args[0]
    if not isinstance(payload, ast.Name):
        return None
    source = context.static_resource_provenance.binding(payload.id, payload)
    if not isinstance(source, ast.arg):
        return None
    if source.annotation is not None and not native_builtin(context, source.annotation, "float"):
        return None
    dtype = next((item.value for item in expression.keywords if item.arg == "dtype"), None)
    if dtype is None or not (
        native_builtin(context, dtype, "float") or context.imports.resolved_qualified_name(dtype) in _NUMPY_FLOATS
    ):
        return None
    return value_origin(context, payload)
