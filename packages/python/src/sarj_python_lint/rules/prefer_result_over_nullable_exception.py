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
from sarj_python_lint.rules._annotation_semantics import bit_or_members
from sarj_python_lint.rules._inherited_contract import inherited_contract
from sarj_python_lint.rules._paths import is_test_path, is_test_support_path


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rules._imports import ImportIndex


def _builtin_exception_names() -> frozenset[str]:
    names: set[str] = set()
    pending: list[type[BaseException]] = [BaseException]
    while pending:
        exception = pending.pop()
        if exception.__module__ == "builtins":
            names.add(exception.__name__)
        pending.extend(exception.__subclasses__())
    return frozenset(names)


_BUILTIN_EXCEPTIONS = _builtin_exception_names()
_TYPING_SOURCES = frozenset({"typing", "typing_extensions"})
_BAD = (
    "class ParsingError(Exception):\n    pass\n\n"
    "def validate(row: dict[str, str]) -> ParsingError | None:\n"
    "    return None if row else ParsingError('empty row')\n"
)
_GOOD = (
    "from dataclasses import dataclass\n\n"
    "class ParsingError(Exception):\n    pass\n\n"
    "@dataclass(frozen=True, slots=True)\n"
    "class Success[T]:\n    value: T\n\n"
    "@dataclass(frozen=True, slots=True)\n"
    "class Failure[E: BaseException]:\n    error: E\n\n"
    "type Result[T, E: BaseException] = Success[T] | Failure[E]\n\n"
    "def validate(row: dict[str, str]) -> Result[dict[str, str], ParsingError]:\n"
    "    return Success(row) if row else Failure(ParsingError('empty row'))\n"
)


@final
class PreferResultOverNullableException(ProjectRule):
    id = "prefer-result-over-nullable-exception"
    code = "SARJ591"
    documentation = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Return a tagged Success | Failure outcome instead of a nullable exception value.",
        rationale=(
            "An `Error | None` return slot encodes success as the absence of a value. Callers must remember an "
            "untyped None check, success payloads travel in separate positions, and nothing makes the success "
            "and failure cases mutually exclusive."
        ),
        remediation=(
            "Raise the exception, or return a discriminated `Success[T] | Failure[E]` union (a shared `Result` "
            "alias over two frozen variants) and dispatch on it with `match`. Keep the failure's typed partial "
            "progress inside the `Failure` variant when callers need it."
        ),
        category=RuleCategory.ARCHITECTURE,
        autofix=AutofixPolicy.NONE,
        limitations=(
            (
                "Only return annotations are checked. A nullable exception is reported at the top level or inside "
                "a tuple, container or union slot; parameters, locals and record fields are out of scope (SARJ571 "
                "owns nullable error fields on records)."
            ),
            (
                "Exception classes are proven through unshadowed builtins, classes declared in the same module, or "
                "first-party project classes whose base chain reaches a builtin exception. Third-party exception "
                "types and dynamic bases are not guessed."
            ),
            (
                "Tests, test support, generated files, dunder methods and public methods on classes with explicit "
                "bases (inherited contracts) are excluded. Exact-code suppressions are respected."
            ),
        ),
        examples=(
            RuleExample(
                example_id="nullable-exception-return",
                title="Success is encoded as a missing exception",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.python("app/rows.py", _BAD),),
                focus_path=PurePosixPath("app/rows.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="tagged-result-return",
                title="Success and failure are explicit variants",
                outcome=ExampleOutcome.NO_MATCH,
                files=(ExampleFile.python("app/rows.py", _GOOD),),
                focus_path=PurePosixPath("app/rows.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        path = context.path
        tree = context.tree
        if tree is None or is_test_path(path) or is_test_support_path(path) or context.generated:
            return []
        if context.has_wildcard_import or ("None" not in context.source and "Optional" not in context.source):
            return []
        proof = _ExceptionProof(context, tree)
        diagnostics: list[Diagnostic] = []
        for node in context.nodes(ast.FunctionDef, ast.AsyncFunctionDef):
            if node.returns is None or (node.name.startswith("__") and node.name.endswith("__")):
                continue
            if inherited_contract(context.parents.get(node)) and not node.name.startswith("_"):
                continue
            slot = _nullable_exception(node.returns, context, proof)
            if slot is None or context.suppressions.is_suppressed(node.lineno, self.code):
                continue
            diagnostics.append(
                Diagnostic(
                    path=path,
                    line=node.lineno,
                    col=node.col_offset + 1,
                    code=self.code,
                    severity=Severity.WARNING,
                    message=(
                        f"`{node.name}` returns nullable exception `{ast.unparse(slot)}`; raise it or return a "
                        "discriminated `Success[T] | Failure[E]` outcome and dispatch with `match` instead of "
                        "a None check."
                    ),
                )
            )
        return diagnostics


def _nullable_exception(annotation: ast.expr, context: PythonFileContext, proof: _ExceptionProof) -> ast.expr | None:
    semantics = context.annotation_semantics
    pending: list[tuple[ast.expr, frozenset[str]]] = [(annotation, frozenset())]
    while pending:
        node, seen = pending.pop()
        parsed = semantics.parse(node)
        if isinstance(parsed, ast.Name) and parsed.id in semantics.aliases:
            if parsed.id not in seen:
                pending.append((semantics.aliases[parsed.id], seen | {parsed.id}))
            continue
        if parsed is None:
            continue
        members = _union_members(parsed, context.imports)
        if members is not None and _nullable_union(members, proof):
            return parsed
        pending.extend((child, seen) for child in (members if members is not None else _type_arguments(parsed)))
    return None


def _nullable_union(members: list[ast.expr], proof: _ExceptionProof) -> bool:
    return any(_is_none(member) for member in members) and any(proof.exception(member) for member in members)


def _type_arguments(node: ast.expr) -> list[ast.expr]:
    match node:
        case ast.Subscript(slice=ast.Tuple(elts=elements) | ast.List(elts=elements)):
            return elements
        case ast.Subscript(slice=element):
            return [element]
        case ast.List(elts=elements) | ast.Tuple(elts=elements):
            return elements
        case _:
            return []


def _union_members(node: ast.expr, imports: ImportIndex) -> list[ast.expr] | None:
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return bit_or_members(node)
    if not isinstance(node, ast.Subscript):
        return None
    wrapper = imports.resolved_symbol(node.value, sources=_TYPING_SOURCES)
    if wrapper == "Optional":
        return [node.slice, ast.Constant(value=None)]
    if wrapper == "Union":
        return list(node.slice.elts) if isinstance(node.slice, ast.Tuple) else [node.slice]
    return None


def _is_none(node: ast.expr) -> bool:
    return isinstance(node, ast.Constant) and node.value is None


class _ExceptionProof:
    def __init__(self, context: PythonFileContext, tree: ast.Module) -> None:
        self._context = context
        self._local_classes = {
            statement.name: statement for statement in tree.body if isinstance(statement, ast.ClassDef)
        }
        project = context.session.project
        self._project = project
        self._unit = project.unit(context.path) if project is not None else None

    def exception(self, node: ast.expr) -> bool:
        return isinstance(node, ast.Name) and self._name(node, frozenset())

    def _name(self, node: ast.Name, seen: frozenset[str]) -> bool:
        name = node.id
        if name in seen:
            return False
        local = self._local_classes.get(name)
        if local is not None:
            return any(isinstance(base, ast.Name) and self._name(base, seen | {name}) for base in local.bases)
        if name in _BUILTIN_EXCEPTIONS and self._context.imports.builtin_is_unshadowed(name):
            return True
        if self._project is None or self._unit is None:
            return False
        symbol = self._project.resolve(self._unit, node)
        return symbol is not None and self._project.symbol_inherits_builtin(symbol, _BUILTIN_EXCEPTIONS)
