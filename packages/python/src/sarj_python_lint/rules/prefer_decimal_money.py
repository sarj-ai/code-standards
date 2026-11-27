from __future__ import annotations

import ast
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, final, override

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
)
from sarj_python_lint.rules._annotation_origins import AnnotationOrigins
from sarj_python_lint.rules._declared_contracts import DeclaredClass, DeclaredContracts
from sarj_python_lint.rules._value_models import value_model


if TYPE_CHECKING:
    from collections.abc import Iterator

    from sarj_python_lint._file_context import PythonFileContext

_MONEY_ROLES = frozenset(
    {
        "amount",
        "balance",
        "price",
        "fee",
        "fees",
        "cost",
        "salary",
        "payment",
        "refund",
        "deposit",
        "withdrawal",
        "installment",
        "premium",
        "principal",
        "profit",
        "interest",
    }
)
_CURRENCY_SUFFIXES = frozenset({"usd", "sar", "aed", "eur", "gbp", "cents", "halalas"})
_NON_MONEY_ROLES = frozenset({"count", "rate", "pct", "percent", "ratio", "id", "type"})


@final
class PreferDecimalMoney(ProjectRule):
    id = "prefer-decimal-money"
    code = "SARJ611"
    documentation = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Carry monetary amounts as Decimal or a money type, not float.",
        rationale="Binary floating-point arithmetic can round monetary amounts and make totals disagree with their component transactions.",
        remediation="Use Decimal or a dedicated money type and preserve the agreed serialization format at the boundary. Integer minor units are also valid when the contract defines them.",
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Checks annotated function parameters and returns, plus fields on module-level classes proven to be Pydantic models, dataclasses or TypedDicts. Monetary role names and currency suffixes are a naming heuristic, so ambiguous names and generated files are excluded.",
            "Looks for builtin float through transparent annotation wrappers, including Optional and Annotated. It does not infer monetary roles from values or change arithmetic and serialization automatically.",
            "At the same field, this warning takes precedence over the generic SARJ530 numeric advice. An exact suppression of the money warning preserves the generic advice.",
        ),
        examples=(
            RuleExample(
                example_id="float-purchase-price",
                title="A purchase price uses binary floating point",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/deals.py",
                        "from pydantic import BaseModel\nclass Deal(BaseModel):\n    purchase_price: float\n",
                    ),
                ),
                focus_path=PurePosixPath("app/deals.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="decimal-purchase-price",
                title="A purchase price uses decimal arithmetic",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/deals.py",
                        "from decimal import Decimal\nfrom pydantic import BaseModel\n"
                        "class Deal(BaseModel):\n    purchase_price: Decimal\n",
                    ),
                ),
                focus_path=PurePosixPath("app/deals.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        tree = context.tree
        if tree is None or "float" not in context.source or context.generated or context.has_wildcard_import:
            return []
        annotations = list(_monetary_annotations(tree, context))
        if not annotations:
            return []
        facts = AnnotationOrigins(context)
        return [
            Diagnostic(
                context.path,
                location.lineno,
                location.col_offset + 1,
                self.code,
                "Use Decimal or a money type for this monetary value to avoid binary rounding.",
                severity=Severity.WARNING,
            )
            for location in annotations
            if not context.suppressions.is_suppressed(location.lineno, self.code)
            and _is_float(location, context, facts)
        ]


def _monetary_annotations(tree: ast.Module, context: PythonFileContext) -> Iterator[ast.AnnAssign | ast.expr]:
    for argument in context.nodes(ast.arg):
        if argument.annotation is not None and _monetary_role(argument.arg):
            yield argument.annotation
    for function in context.nodes(ast.FunctionDef, ast.AsyncFunctionDef):
        if function.returns is not None and _monetary_role(function.name):
            yield function.returns
    yield from _monetary_model_fields(tree, context)


def _monetary_model_fields(tree: ast.Module, context: PythonFileContext) -> Iterator[ast.AnnAssign]:
    candidates = [
        declaration
        for declaration in tree.body
        if isinstance(declaration, ast.ClassDef)
        and any(
            isinstance(field, ast.AnnAssign) and isinstance(field.target, ast.Name) and _monetary_role(field.target.id)
            for field in declaration.body
        )
    ]
    if not candidates:
        return
    contracts = DeclaredContracts(context)
    if contracts.unit is None:
        return
    for declaration in candidates:
        model = DeclaredClass(contracts.unit, declaration)
        if value_model(model, contracts, include_typed_dict=True):
            yield from (field for name, field in contracts.model_fields(model).items() if _monetary_role(name))


def _monetary_role(name: str) -> bool:
    tokens = name.lower().strip("_").split("_")
    suffix = tokens[-1]
    return _NON_MONEY_ROLES.isdisjoint(tokens) and (
        suffix in _MONEY_ROLES or (len(tokens) > 1 and suffix in _CURRENCY_SUFFIXES)
    )


def _is_float(location: ast.AnnAssign | ast.expr, context: PythonFileContext, facts: AnnotationOrigins) -> bool:
    match location:
        case ast.AnnAssign(annotation=annotation):
            pass
        case _:
            annotation = location
    members = [
        member
        for member in context.annotation_semantics.transparent_members(annotation)
        if not (isinstance(member, ast.Constant) and member.value is None)
    ]
    return bool(members) and all(
        facts.builtin(member, "float", annotation) or facts.qualified(member, annotation) == "builtins.float"
        for member in members
    )
