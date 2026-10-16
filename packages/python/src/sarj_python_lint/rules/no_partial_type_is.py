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
from sarj_python_lint.rules._imports import TYPING_SOURCES
from sarj_python_lint.rules._type_guard_symbols import builtin_guard_symbol, guard_symbols_ambiguous


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rules._imports import ImportIndex


_PAIR_ARITY = 2
_MAX_INPUT_NODES = 256
_SCALARS = frozenset({"int", "str", "bytes", "bool"})
_CONTAINERS = frozenset({"list", "dict", "set"})
_BUILTINS = _SCALARS | _CONTAINERS | {"object", "isinstance", "len"}
_BAD = (
    "from typing import TypeIs\n"
    "def is_positive(value: object) -> TypeIs[int]:\n"
    "    return isinstance(value, int) and value > 0\n"
)
_GOOD = _BAD.replace("TypeIs", "TypeGuard")


@final
class NoPartialTypeIs(Rule):
    id = "no-partial-type-is"
    code = "SARJ512"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="TypeIs must not reject a value belonging to its declared target type.",
        rationale=(
            "TypeIs narrows both branches. A positive-int or non-empty-container filter can return false for a valid "
            "member of its target type, making callers incorrectly exclude that type in the false branch."
        ),
        remediation=(
            "Use TypeGuard for an intentional partial predicate, or make TypeIs recognize every value of its target "
            "type. Check false-branch callers when changing the narrowing contract."
        ),
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Checks undecorated, non-generic module functions with one parameter and one return, optionally after a docstring.",
            "Requires an import-proven TypeIs target and a builtin isinstance check followed by one literal comparison. A concrete builtin member must demonstrably fail that comparison.",
            "Targets are builtin int, str, bytes, bool and parameterized list, dict or set. Scalar comparisons use same-kind literals; length comparisons prove rejection of the valid empty member only.",
            "Input union analysis is iterative and bounded to 256 nodes. Constrained inputs, target unions, aliases, subclasses, custom refinements, helper calls, decorated functions and complex predicates are not inferred. TypeGuard may intentionally be partial and is excluded.",
            "Visible shadowing, wildcard imports and namespace mutation abstain conservatively. There is no autofix because changing TypeIs affects both branches at callers.",
        ),
        examples=(
            RuleExample(
                example_id="positive-is-not-all-integers",
                title="Zero is still an integer in the false branch",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.python("app/guards.py", _BAD),),
                focus_path=PurePosixPath("app/guards.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="partial-type-guard",
                title="TypeGuard permits an intentional partial predicate",
                outcome=ExampleOutcome.NO_MATCH,
                files=(ExampleFile.python("app/guards.py", _GOOD),),
                focus_path=PurePosixPath("app/guards.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if (
            context.tree is None
            or context.generated
            or "TypeIs" not in context.symbol_source
            or guard_symbols_ambiguous(context, _BUILTINS)
        ):
            return []
        findings: list[Diagnostic] = []
        for node in context.tree.body:
            if not isinstance(node, ast.FunctionDef):
                continue
            statement = _partial_return(node, context)
            if statement is None or is_suppressed(context.source_lines, statement.lineno, self.code):
                continue
            findings.append(
                Diagnostic(
                    path=context.path,
                    line=statement.lineno,
                    col=statement.col_offset + 1,
                    code=self.code,
                    message="TypeIs rejects a valid member of its target type, so false-branch narrowing is unsound; use TypeGuard for a partial predicate or recognize every target value.",
                    severity=Severity.WARNING,
                )
            )
        return findings


def _partial_return(function: ast.FunctionDef, context: PythonFileContext) -> ast.Return | None:
    args = function.args
    positional = (*args.posonlyargs, *args.args)
    if function.decorator_list or function.type_params or len(positional) != 1:
        return None
    if args.kwonlyargs or args.vararg is not None or args.kwarg is not None:
        return None
    annotation = function.returns
    if not isinstance(annotation, ast.Subscript) or not context.module_imports.resolves(
        annotation.value, sources=TYPING_SOURCES, symbol="TypeIs"
    ):
        return None
    kind = _target_kind(annotation.slice, context.module_imports)
    parameter = positional[0]
    if kind is None or not _input_admits(parameter.annotation, kind, context.module_imports):
        return None
    body = function.body
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body = body[1:]
    if len(body) != 1 or not isinstance(body[0], ast.Return):
        return None
    statement = body[0]
    expression = statement.value
    if (
        not isinstance(expression, ast.BoolOp)
        or not isinstance(expression.op, ast.And)
        or len(expression.values) != _PAIR_ARITY
    ):
        return None
    check, comparison = expression.values
    if not _checks_target(check, parameter.arg, kind, context.imports):
        return None
    return statement if _rejects_member(comparison, parameter.arg, kind, context.imports) else None


def _target_kind(node: ast.expr, imports: ImportIndex) -> str | None:
    if isinstance(node, ast.Subscript):
        kind = builtin_guard_symbol(node.value, imports, _BUILTINS)
        return kind if kind in _CONTAINERS else None
    kind = builtin_guard_symbol(node, imports, _BUILTINS)
    return kind if kind in _SCALARS else None


def _input_admits(node: ast.expr | None, kind: str, imports: ImportIndex) -> bool:
    pending = [node] if node is not None else []
    inspected = 0
    while pending:
        if inspected >= _MAX_INPUT_NODES:
            return False
        current = pending.pop()
        inspected += 1
        if isinstance(current, ast.BinOp) and isinstance(current.op, ast.BitOr):
            pending.extend((current.right, current.left))
        elif builtin_guard_symbol(current, imports, _BUILTINS) == "object" or _target_kind(current, imports) == kind:
            return True
    return False


def _checks_target(node: ast.expr, parameter: str, kind: str, imports: ImportIndex) -> bool:
    match node:
        case ast.Call(func=func, args=[ast.Name(id=name), target], keywords=[]):
            return (
                name == parameter
                and builtin_guard_symbol(func, imports, _BUILTINS) == "isinstance"
                and builtin_guard_symbol(target, imports, _BUILTINS) == kind
            )
        case _:
            return False


def _rejects_member(node: ast.expr, parameter: str, kind: str, imports: ImportIndex) -> bool:
    if not isinstance(node, ast.Compare) or len(node.ops) != 1:
        return False
    left, right = node.left, node.comparators[0]
    bound = _literal(right)
    if bound is None:
        return False
    match left:
        case ast.Call(func=func, args=[ast.Name(id=name)], keywords=[]) if (
            name == parameter
            and builtin_guard_symbol(func, imports, _BUILTINS) == "len"
            and kind in _CONTAINERS | {"str", "bytes"}
            and type(bound) is int
        ):
            return _comparison(0, node.ops[0], bound) is False
        case _:
            pass
    if not isinstance(left, ast.Name) or left.id != parameter or type(bound).__name__ != kind:
        return False
    candidates = [bound]
    match bound:
        case bool():
            candidates.extend((True, False))
        case int():
            candidates.extend((bound - 1, bound + 1))
        case str():
            candidates.extend(("", bound + "x"))
        case bytes():
            candidates.extend((b"", bound + b"x"))
    return any(_comparison(value, node.ops[0], bound) is False for value in candidates)


def _literal(node: ast.expr) -> int | str | bytes | bool | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, str, bytes, bool)):
        return node.value
    if (
        isinstance(node, ast.UnaryOp)
        and isinstance(node.op, (ast.USub, ast.UAdd))
        and isinstance(node.operand, ast.Constant)
        and type(node.operand.value) is int
    ):
        return -node.operand.value if isinstance(node.op, ast.USub) else node.operand.value
    return None


def _comparison(left: int | str | bytes, op: ast.cmpop, right: int | str | bytes) -> bool | None:
    match op:
        case ast.Eq():
            return left == right
        case ast.NotEq():
            return left != right
        case ast.Is() | ast.IsNot() | ast.In() | ast.NotIn():
            return None
        case _:
            pass
    # Callers prove the operands have the same builtin kind, excluding user code.
    match left, right:
        case int(), int():
            return _ordered_comparison(left, op, right)
        case str(), str():
            return _ordered_comparison(left, op, right)
        case bytes(), bytes():
            return _ordered_comparison(left, op, right)
        case _:
            return None


def _ordered_comparison[T: (int, str, bytes)](left: T, op: ast.cmpop, right: T) -> bool | None:
    match op:
        case ast.Gt():
            return left > right
        case ast.GtE():
            return left >= right
        case ast.Lt():
            return left < right
        case ast.LtE():
            return left <= right
        case _:
            return None
