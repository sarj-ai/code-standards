from __future__ import annotations

import ast
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, ClassVar, TypeGuard, final, override

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
    parse_or_none,
)
from sarj_python_lint.rules._paths import is_generated, is_test_path


if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


_ERROR_SUFFIXES = ("Error", "Exception")


@final
class TypedErrorReasons(Rule):
    id = "typed-error-reasons"
    code = "SARJ435"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="Exception aggregates presentation strings instead of typed error reasons.",
        rationale=(
            "A collection of rendered sentences has no stable identity for API clients, UI formatting, telemetry, "
            "or exhaustive handling; consumers must display or parse text that should be presentation-only."
        ),
        remediation=(
            "Replace `list[str]` with a nominal reason type: usually a record containing a `StrEnum` code and typed "
            "context. Format that structure only at the presentation boundary."
        ),
        category=RuleCategory.ARCHITECTURE,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only an Error/Exception subclass whose direct Error/Exception base is visible in the class declaration is checked.",
            "The constructor must have exactly one non-self parameter, annotated exactly `list[str]`, and join that same parameter inside `super().__init__(...)`.",
            "Formatting delegated to another function, legacy `typing.List`, mixed constructor context, tests, and generated files are intentionally not inferred.",
        ),
        examples=(
            RuleExample(
                example_id="rendered-reason-list",
                title="An exception renders raw reason strings",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/errors.py",
                        "class DomainError(Exception): ...\n\n"
                        "class IncompleteError(DomainError):\n"
                        "    def __init__(self, reasons: list[str]) -> None:\n"
                        "        self.reasons = reasons\n"
                        "        super().__init__(f\"Incomplete: {'; '.join(reasons)}\")\n",
                    ),
                ),
                focus_path=PurePosixPath("app/errors.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="typed-reason-list",
                title="An exception carries nominal reason records",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/errors.py",
                        "from dataclasses import dataclass\n"
                        "from enum import StrEnum\n\n"
                        "class ReasonCode(StrEnum):\n"
                        "    MISSING_URL = 'missing_url'\n\n"
                        "@dataclass(frozen=True)\n"
                        "class Reason:\n"
                        "    code: ReasonCode\n"
                        "    field: str | None = None\n\n"
                        "class DomainError(Exception): ...\n\n"
                        "class IncompleteError(DomainError):\n"
                        "    def __init__(self, reasons: list[Reason]) -> None:\n"
                        "        self.reasons = reasons\n"
                        "        super().__init__('Integration is incomplete')\n",
                    ),
                ),
                focus_path=PurePosixPath("app/errors.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if path.suffix != ".py" or is_test_path(path) or is_generated(path, source):
            return []
        if "list[str]" not in source or ".join(" not in source or "super(" not in source:
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []

        diagnostics: list[Diagnostic] = []
        for error_class in (node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)):
            if not _is_conventional_exception(error_class):
                continue
            constructor = next(
                (
                    member
                    for member in error_class.body
                    if isinstance(member, ast.FunctionDef) and member.name == "__init__"
                ),
                None,
            )
            if constructor is None:
                continue
            parameter = _sole_string_list_parameter(constructor)
            if parameter is None:
                continue
            joined = _joined_in_super_message(constructor, parameter.arg)
            if joined is None:
                continue
            diagnostics.append(
                Diagnostic(
                    path=path,
                    line=joined.lineno,
                    col=joined.col_offset + 1,
                    code=self.code,
                    severity=Severity.WARNING,
                    message=(
                        f"`{error_class.name}` joins `{parameter.arg}: list[str]` into its message; carry nominal "
                        "reason codes with typed context and format them at the presentation boundary"
                    ),
                )
            )
        return sorted(diagnostics, key=lambda diagnostic: (diagnostic.line, diagnostic.col))


def _is_conventional_exception(node: ast.ClassDef) -> bool:
    return node.name.endswith(_ERROR_SUFFIXES) and any(_tail(base).endswith(_ERROR_SUFFIXES) for base in node.bases)


def _tail(node: ast.expr) -> str:
    match node:
        case ast.Name(id=name) | ast.Attribute(attr=name):
            return name
        case _:
            return ""


def _sole_string_list_parameter(function: ast.FunctionDef) -> ast.arg | None:
    parameters = [
        argument
        for argument in (
            *function.args.posonlyargs,
            *function.args.args,
            *function.args.kwonlyargs,
        )
        if argument.arg not in {"self", "cls"}
    ]
    if len(parameters) != 1:
        return None
    parameter = parameters[0]
    return parameter if _is_string_list(parameter.annotation) else None


def _is_string_list(annotation: ast.expr | None) -> bool:
    return (
        isinstance(annotation, ast.Subscript)
        and isinstance(annotation.value, ast.Name)
        and annotation.value.id == "list"
        and isinstance(annotation.slice, ast.Name)
        and annotation.slice.id == "str"
    )


def _joined_in_super_message(function: ast.FunctionDef, parameter: str) -> ast.Call | None:
    for node in _own_scope_nodes(function):
        if not _is_super_init_call(node):
            continue
        for argument in node.args:
            joined = next(
                (candidate for candidate in ast.walk(argument) if _joins_parameter(candidate, parameter)),
                None,
            )
            if joined is not None:
                return joined
    return None


def _own_scope_nodes(function: ast.FunctionDef) -> Iterator[ast.AST]:
    stack: list[ast.AST] = list(function.body)
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        yield node
        stack.extend(ast.iter_child_nodes(node))


def _is_super_init_call(node: ast.AST) -> TypeGuard[ast.Call]:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "__init__"
        and isinstance(node.func.value, ast.Call)
        and isinstance(node.func.value.func, ast.Name)
        and node.func.value.func.id == "super"
    )


def _joins_parameter(node: ast.AST, parameter: str) -> TypeGuard[ast.Call]:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "join"
        and len(node.args) == 1
        and not node.keywords
        and isinstance(node.args[0], ast.Name)
        and node.args[0].id == parameter
    )
