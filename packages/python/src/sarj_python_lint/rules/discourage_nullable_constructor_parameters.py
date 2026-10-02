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
)
from sarj_python_lint.rules._paths import is_test_path


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext


_REJECTED = (
    "class Service:\n"
    "    def __init__(self, store: Store | None = None) -> None:\n"
    "        if store is None:\n"
    "            raise ValueError('store is required')\n"
    "        self.store = store\n"
)


@final
class DiscourageNullableConstructorParameters(Rule):
    id = "discourage-nullable-constructor-parameters"
    code = "SARJ468"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Make constructor inputs required when their None default is immediately rejected.",
        rationale=(
            "A constructor that immediately rejects its None default advertises omission even though it cannot "
            "construct an instance from that default. Static typing permits the omitted call."
        ),
        remediation=(
            "Make the rejected input required and non-nullable. Keep deliberate optional state nullable; "
            "no wrapper, interface, or alternate constructor is needed."
        ),
        category=RuleCategory.ARCHITECTURE,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Requires a PEP604 nullable parameter with a literal None default and immediate explicit rejection in an undecorated synchronous __init__ body.",
            "Only a first executable `if parameter is None: raise ...` or `assert parameter is not None` is checked; docstrings and simple assignments preparing a raised error are allowed. Compound guards, later validation, fallbacks, and required nullable inputs are excluded.",
            "An assertion expresses rejection in normal assertions-enabled execution; Python -O can remove it. No autofix changes a public constructor signature or error type.",
            "Tests, generated code, decorated classes, and constructors with decorators are excluded. Nullable state that is stored or handled is valid.",
        ),
        examples=(
            RuleExample(
                example_id="rejected-constructor-default",
                title="The constructor immediately rejects its advertised default",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.python("app/service.py", _REJECTED),),
                focus_path=PurePosixPath("app/service.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="required-constructor-input",
                title="The signature requires the input that construction needs",
                outcome=ExampleOutcome.NO_MATCH,
                files=(ExampleFile.python("app/service.py", _REJECTED.replace("Store | None = None", "Store")),),
                focus_path=PurePosixPath("app/service.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if context.generated or context.tree is None or is_test_path(context.path):
            return []
        findings: list[Diagnostic] = []
        for owner in context.nodes(ast.ClassDef):
            if owner.decorator_list:
                continue
            for method in owner.body:
                if not isinstance(method, ast.FunctionDef) or method.name != "__init__" or method.decorator_list:
                    continue
                parameter = _rejected_default(method)
                if parameter is None:
                    continue
                findings.append(
                    Diagnostic(
                        path=context.path,
                        line=parameter.lineno,
                        col=parameter.col_offset + 1,
                        code=self.code,
                        severity=Severity.WARNING,
                        message=f"Constructor input `{parameter.arg}` defaults to None but immediately rejects it; make this input required and non-nullable instead of adding an abstraction.",
                    )
                )
        return findings


def _rejected_default(method: ast.FunctionDef) -> ast.arg | None:
    rejected = _immediately_rejected_parameter(method)
    if rejected is None:
        return None
    positional = (*method.args.posonlyargs, *method.args.args)
    defaulted = positional[-len(method.args.defaults) :] if method.args.defaults else ()
    defaults = (
        *zip(defaulted, method.args.defaults, strict=True),
        *zip(method.args.kwonlyargs, method.args.kw_defaults, strict=True),
    )
    for parameter, default in defaults:
        if parameter.arg != rejected or (positional and parameter is positional[0]):
            continue
        if (
            not isinstance(default, ast.Constant)
            or default.value is not None
            or parameter.annotation is None
            or not _is_nullable_union(parameter.annotation)
        ):
            continue
        return parameter
    return None


def _immediately_rejected_parameter(method: ast.FunctionDef) -> str | None:
    body = method.body
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body = body[1:]
    if not body:
        return None
    first = body[0]
    if (
        isinstance(first, ast.If)
        and isinstance(first.body[-1], ast.Raise)
        and all(isinstance(statement, (ast.Assign, ast.AnnAssign)) for statement in first.body[:-1])
    ):
        condition, operator = first.test, ast.Is
    elif isinstance(first, ast.Assert):
        condition, operator = first.test, ast.IsNot
    else:
        return None
    if not isinstance(condition, ast.Compare) or len(condition.ops) != 1 or not isinstance(condition.ops[0], operator):
        return None
    left, right = condition.left, condition.comparators[0]
    for name, absent in ((left, right), (right, left)):
        if isinstance(name, ast.Name) and isinstance(absent, ast.Constant) and absent.value is None:
            return name.id
    return None


def _is_nullable_union(annotation: ast.expr) -> bool:
    if not isinstance(annotation, ast.BinOp) or not isinstance(annotation.op, ast.BitOr):
        return False
    return _is_none_union_member(annotation.left) or _is_none_union_member(annotation.right)


def _is_none_union_member(annotation: ast.expr) -> bool:
    if isinstance(annotation, ast.BinOp) and isinstance(annotation.op, ast.BitOr):
        return _is_none_union_member(annotation.left) or _is_none_union_member(annotation.right)
    return isinstance(annotation, ast.Constant) and annotation.value is None
