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
from sarj_python_lint.rules._type_guard_symbols import (
    builtin_guard_symbol,
    guard_symbols_ambiguous,
    unique_guard_function_names,
)


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rules._imports import ImportIndex


_PAIR_ARITY = 2
_MAX_INPUT_NODES = 256
_MAX_LITERAL_MEMBERS = 256
_TYPING_SYMBOLS = frozenset({"TypeGuard", "TypeIs", "Literal"})
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
            "Use an ordinary bool return for a value filter. Ensure every accepted value satisfies the declared target. Use TypeGuard for an intentional partial "
            "predicate only when its true branch is sound; TypeIs must recognize exactly the target values. "
            "Check false-branch callers when changing the narrowing contract."
        ),
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Checks undecorated, non-generic module functions with one parameter and one return, optionally after a docstring.",
            "Requires an import-proven TypeIs target and a concrete builtin member demonstrably rejected by a direct predicate or by a builtin isinstance check followed by one predicate.",
            "Targets are builtin int, str, bytes, bool and parameterized list, dict or set. Scalar comparisons use same-kind literals; length comparisons prove rejection of the valid empty member only.",
            "Direct bool conversion rejects the valid falsey member. Unary not is checked only for scalar targets with an inhabited truthy member. Direct ordering or length comparisons require an exact matching builtin input annotation; equality comparisons use a concrete same-kind witness. Raw parameter returns are checked only when proven bool.",
            "Also checks bounded, import-proven string Literal targets with exact builtin str or object input: a bool constant or equality/inequality comparison must reject an actual declared literal. Single-literal total equality predicates remain valid.",
            "Input union analysis is iterative and bounded to 256 nodes. Constrained inputs, target unions, aliases, subclasses, custom refinements, helper calls, decorated functions and complex predicates are not inferred. TypeGuard may intentionally be partial and is excluded.",
            "Visible shadowing, wildcard imports and namespace mutation abstain conservatively. There is no autofix because changing TypeIs affects both branches at callers.",
            "Repeated top-level function definition names are excluded because overloads can expose a more constrained public input than the implementation annotation.",
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
            RuleExample(
                example_id="declared-literal-rejected",
                scenario="string-literal-domain",
                title="Every declared literal belongs to the TypeIs target",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/guards.py",
                        "from typing import Literal, TypeIs\ndef is_selected(value: str) -> TypeIs[Literal['red', 'blue']]:\n    return value == 'red'\n",
                    ),
                ),
                focus_path=PurePosixPath("app/guards.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="total-literal-equality",
                scenario="string-literal-domain",
                title="Equality recognizes every member of a singleton target",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/guards.py",
                        "from typing import Literal, TypeIs\ndef is_selected(value: str) -> TypeIs[Literal['red']]:\n    return value == 'red'\n",
                    ),
                ),
                focus_path=PurePosixPath("app/guards.py"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="truthiness-is-not-text-membership",
                scenario="truthiness-value-filter",
                title="Truthiness can accept integers and reject the empty string",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/guards.py",
                        "from typing import TypeIs\ndef is_text(value: object) -> TypeIs[str]:\n    return bool(value)\n",
                    ),
                ),
                focus_path=PurePosixPath("app/guards.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="truthiness-bool-value-filter",
                scenario="truthiness-value-filter",
                title="A value filter can return an ordinary bool",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/guards.py", "def is_truthy(value: object) -> bool:\n    return bool(value)\n"
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
        if (
            context.tree is None
            or context.generated
            or "TypeIs" not in context.symbol_source
            or guard_symbols_ambiguous(context, _BUILTINS, typing_symbols=_TYPING_SYMBOLS)
        ):
            return []
        findings: list[Diagnostic] = []
        unique_names = unique_guard_function_names(context)
        for node in context.tree.body:
            if not isinstance(node, ast.FunctionDef) or node.name not in unique_names:
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
                    message="TypeIs rejects a valid target member, making false-branch narrowing unsound; use bool for a value filter, or validate accepted values and reserve TypeGuard for sound partial recognition.",
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
    parameter = positional[0]
    statement = _single_return(function)
    if statement is None:
        return None
    literals = _string_literal_domain(annotation.slice, context.module_imports)
    if literals is not None:
        rejected = _partial_literal_expression(statement.value, parameter, literals, context)
        return statement if rejected else None
    kind = _target_kind(annotation.slice, context.module_imports)
    if kind is None or not _input_admits(parameter.annotation, kind, context.module_imports):
        return None
    return statement if _partial_expression(statement.value, parameter, kind, context) else None


def _single_return(function: ast.FunctionDef) -> ast.Return | None:
    body = function.body
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body = body[1:]
    return body[0] if len(body) == 1 and isinstance(body[0], ast.Return) else None


def _string_literal_domain(node: ast.expr, imports: ImportIndex) -> frozenset[str] | None:
    if not isinstance(node, ast.Subscript) or not imports.resolves(
        node.value, sources=TYPING_SOURCES, symbol="Literal"
    ):
        return None
    members = node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]
    if len(members) > _MAX_LITERAL_MEMBERS or not all(
        isinstance(member, ast.Constant) and isinstance(member.value, str) for member in members
    ):
        return None
    return frozenset(
        member.value for member in members if isinstance(member, ast.Constant) and isinstance(member.value, str)
    )


def _partial_literal_expression(
    node: ast.expr | None, parameter: ast.arg, literals: frozenset[str], context: PythonFileContext
) -> bool:
    if builtin_guard_symbol(parameter.annotation, context.module_imports, _BUILTINS) not in {"str", "object"}:
        return False
    if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.And) and len(node.values) == _PAIR_ARITY:
        check, predicate = node.values
        if not _checks_target(check, parameter.arg, "str", context.imports):
            return False
        node = predicate
    if isinstance(node, ast.Constant) and isinstance(node.value, bool):
        return not node.value and bool(literals)
    if not isinstance(node, ast.Compare) or len(node.ops) != 1 or not isinstance(node.ops[0], (ast.Eq, ast.NotEq)):
        return False
    if not isinstance(node.left, ast.Name) or node.left.id != parameter.arg:
        return False
    bound = _literal(node.comparators[0])
    return isinstance(bound, str) and any(_comparison(value, node.ops[0], bound) is False for value in literals)


def _partial_expression(node: ast.expr | None, parameter: ast.arg, kind: str, context: PythonFileContext) -> bool:
    if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.And) and len(node.values) == _PAIR_ARITY:
        check, predicate = node.values
        return _checks_target(check, parameter.arg, kind, context.imports) and _rejects_member(
            predicate, parameter.arg, kind, context.imports
        )
    if _rejects_truthiness(node, parameter.arg, kind, context.imports):
        return not isinstance(node, ast.Name) or _target_kind(parameter.annotation, context.module_imports) == "bool"
    if not isinstance(node, ast.Compare):
        return False
    same_input = _target_kind(parameter.annotation, context.module_imports) == kind
    equality = len(node.ops) == 1 and isinstance(node.ops[0], (ast.Eq, ast.NotEq)) and isinstance(node.left, ast.Name)
    return (same_input or equality) and _rejects_member(node, parameter.arg, kind, context.imports)


def _target_kind(node: ast.expr | None, imports: ImportIndex) -> str | None:
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
    if _rejects_truthiness(node, parameter, kind, imports):
        return True
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


def _rejects_truthiness(node: ast.expr | None, parameter: str, kind: str, imports: ImportIndex) -> bool:
    match node:
        case ast.Call(func=func, args=[ast.Name(id=name)], keywords=[]):
            return name == parameter and builtin_guard_symbol(func, imports, _BUILTINS) == "bool"
        case ast.Name(id=name):
            return name == parameter and kind == "bool"
        case ast.UnaryOp(op=ast.Not(), operand=ast.Name(id=name)):
            return name == parameter and kind in _SCALARS
        case _:
            return False


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
