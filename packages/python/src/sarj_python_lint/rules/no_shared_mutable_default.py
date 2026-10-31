from __future__ import annotations

import ast
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
)
from sarj_python_lint.rules._runtime_names import RuntimeNames


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext


_MUTABLE_CONSTRUCTORS = frozenset(
    {
        "builtins.list",
        "builtins.dict",
        "builtins.set",
        "builtins.bytearray",
        "collections.deque",
        "collections.defaultdict",
        "collections.Counter",
        "collections.OrderedDict",
        "collections.ChainMap",
        "collections.UserList",
        "collections.UserDict",
    }
)
_READONLY_BUILTINS = frozenset(
    {
        "builtins.bool",
        "builtins.bytes",
        "builtins.complex",
        "builtins.float",
        "builtins.frozenset",
        "builtins.int",
        "builtins.object",
        "builtins.range",
        "builtins.str",
        "builtins.tuple",
    }
)
_READONLY_INTERFACES = frozenset(
    {"Sequence", "Mapping", "AbstractSet", "Collection", "Container", "Iterable", "Reversible", "Callable", "Sized"}
)


@final
class NoSharedMutableDefault(Rule):
    id = "no-shared-mutable-default"
    code = "SARJ559"
    documentation = RuleDocumentation(
        default_level=Severity.ERROR,
        summary="Do not share mutable function defaults through aliases or read-only annotations.",
        rationale="A read-only annotation does not make a list or dictionary immutable, and a named mutable default still shares one object between calls.",
        remediation="Use an immutable default or accept None and create the mutable value inside the function. Keep an intentional shared cache in an explicit owner.",
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Complements Ruff B006 for mutable aliases, bytearray defaults, lambda defaults, read-only annotations and known container expressions. Native-owned shapes retain B006.",
            "Recognizes container literals/comprehensions, generic mutable constructors, simple aliases, both-mutable conditional branches, concatenation and literal-count repetition. Unknown factory return mutability and complex rebinding are not inferred.",
        ),
        examples=(
            RuleExample(
                example_id="read-only-annotation",
                title="A Sequence annotation still shares a mutable list",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "service/batch.py",
                        "from collections.abc import Sequence\n\ndef batch(values: Sequence[int] = []):\n    return values\n",
                    ),
                ),
                focus_path=PurePosixPath("service/batch.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="immutable-default",
                title="An immutable tuple can be shared safely",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "service/batch.py",
                        "from collections.abc import Sequence\n\ndef batch(values: Sequence[int] = ()):\n    return values\n",
                    ),
                ),
                focus_path=PurePosixPath("service/batch.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if context.tree is None or context.generated:
            return []
        names = RuntimeNames(context)
        findings: list[Diagnostic] = []
        for function in context.nodes(ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda):
            arguments = function.args
            positional = [*arguments.posonlyargs, *arguments.args]
            defaults = [
                *zip(positional[len(positional) - len(arguments.defaults) :], arguments.defaults, strict=True),
                *(
                    (parameter, value)
                    for parameter, value in zip(arguments.kwonlyargs, arguments.kw_defaults, strict=True)
                    if value is not None
                ),
            ]
            for parameter, value in defaults:
                if not _mutable(value, names, frozenset()):
                    continue
                if not (
                    isinstance(function, ast.Lambda)
                    or _readonly(parameter.annotation, names)
                    or not _native_mutable_default(value, names)
                ):
                    continue
                findings.append(
                    Diagnostic(
                        context.path,
                        value.lineno,
                        value.col_offset + 1,
                        self.code,
                        "This default shares a mutable object between calls. Use an immutable default or create the value inside the function.",
                    )
                )
        return findings


def _mutable(value: ast.expr, names: RuntimeNames, seen: frozenset[ast.AST]) -> bool:
    if value in seen:
        return False
    match value:
        case ast.List() | ast.Dict() | ast.Set() | ast.ListComp() | ast.DictComp() | ast.SetComp():
            return True
        case ast.Call():
            return names.qualified(_constructor(value.func)) in _MUTABLE_CONSTRUCTORS
        case ast.NamedExpr():
            return _mutable(value.value, names, seen | {value})
        case ast.IfExp():
            return _mutable(value.body, names, seen | {value}) and _mutable(value.orelse, names, seen | {value})
        case ast.BinOp(op=ast.Add()):
            return _mutable(value.left, names, seen | {value}) and _mutable(value.right, names, seen | {value})
        case ast.BinOp(op=ast.Mult()):
            return (_mutable(value.left, names, seen | {value}) and _integer(value.right)) or (
                _integer(value.left) and _mutable(value.right, names, seen | {value})
            )
        case ast.Name() if (origin := names.assigned_value(value)) is not None:
            return _mutable(origin, names, seen | {value})
        case _:
            return False


def _constructor(expression: ast.expr) -> ast.expr:
    return expression.value if isinstance(expression, ast.Subscript) else expression


def _integer(expression: ast.expr) -> bool:
    return isinstance(expression, ast.Constant) and isinstance(expression.value, int)


def _native_mutable_default(value: ast.expr, names: RuntimeNames) -> bool:
    match value:
        case ast.List() | ast.Dict() | ast.Set() | ast.ListComp() | ast.DictComp() | ast.SetComp():
            return True
        case ast.NamedExpr():
            return _native_mutable_default(value.value, names)
        case ast.Call():
            qualified = names.imported_qualified(_constructor(value.func))
            return qualified in _MUTABLE_CONSTRUCTORS and qualified != "builtins.bytearray"
        case _:
            return False


def _readonly(annotation: ast.expr | None, names: RuntimeNames) -> bool:
    if annotation is None:
        return False
    if isinstance(annotation, ast.Constant):
        return annotation.value is None
    if isinstance(annotation, ast.BinOp) and isinstance(annotation.op, ast.BitOr):
        return _readonly(annotation.left, names) and _readonly(annotation.right, names)
    base = annotation.value if isinstance(annotation, ast.Subscript) else annotation
    qualified = names.imported_qualified(base)
    if qualified is None:
        return False
    if qualified in _READONLY_BUILTINS:
        return True
    module, _, member = qualified.rpartition(".")
    if module in {"typing", "typing_extensions", "collections.abc"} and (
        member in _READONLY_INTERFACES or (module == "collections.abc" and member == "Set")
    ):
        return True
    if module not in {"typing", "typing_extensions"} or not isinstance(annotation, ast.Subscript):
        return False
    parts = annotation.slice.elts if isinstance(annotation.slice, ast.Tuple) else [annotation.slice]
    if member == "Literal":
        return True
    if member == "Annotated":
        return bool(parts) and _readonly(parts[0], names)
    return member in {"Union", "Optional"} and bool(parts) and all(_readonly(part, names) for part in parts)
