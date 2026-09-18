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
    is_suppressed,
    parse_or_none,
)
from sarj_python_lint.rules._imports import ImportIndex
from sarj_python_lint.rules._paths import is_generated


if TYPE_CHECKING:
    from pathlib import Path


_TYPING_SOURCES = frozenset({"typing", "typing_extensions"})
_MAPPING_SOURCES = frozenset({"collections.abc", "typing"})
_MAPPING_NAMES = frozenset({"dict", "Dict", "Mapping", "MutableMapping"})
_MAPPING_ARGUMENT_COUNT = 2


@final
class NoVagueAnnotations(Rule):
    id = "no-vague-annotations"
    code = "SARJ447"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="Annotations must not erase domain shape with `object` or `dict[str, Any]`.",
        rationale=(
            "Vague annotations move schema mistakes from type checking to runtime and conceal the fields a caller may use."
        ),
        remediation=(
            "Use a named Pydantic model, dataclass, TypedDict, Protocol, TypeVar, domain type, or an explicit recursive "
            "JSON value type at a serialization boundary."
        ),
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.NONE,
        limitations=("Generated and vendored sources are excluded; exact local suppressions remain auditable.",),
        examples=(
            RuleExample(
                example_id="vague-mapping-annotation",
                title="An open mapping erases the record schema",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/offers.py", "from typing import Any\ndef details() -> dict[str, Any]: ...\n"
                    ),
                ),
                focus_path=PurePosixPath("app/offers.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="named-model-annotation",
                title="A named model preserves the record schema",
                outcome=ExampleOutcome.NO_MATCH,
                files=(ExampleFile.python("app/offers.py", "def details() -> OfferDetails: ...\n"),),
                focus_path=PurePosixPath("app/offers.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if is_generated(path, source) or _is_vendor_path(path):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        imports = ImportIndex.from_tree(tree)
        lines = source.splitlines()
        findings: list[Diagnostic] = []
        for annotation in _annotations(tree):
            problem = _vague_problem(annotation, imports)
            if problem is None or is_suppressed(lines, annotation.lineno, self.code):
                continue
            findings.append(
                Diagnostic(
                    path=path,
                    line=annotation.lineno,
                    col=annotation.col_offset + 1,
                    code=self.code,
                    message=f"vague annotation `{problem}` erases its domain schema; use a named precise type",
                )
            )
        return sorted(findings, key=lambda finding: (finding.line, finding.col))


def _annotations(tree: ast.Module) -> list[ast.expr]:
    return [annotation for node in ast.walk(tree) if (annotation := _node_annotation(node)) is not None]


def _node_annotation(node: ast.AST) -> ast.expr | None:
    match node:
        case (
            ast.arg(annotation=annotation)
            | ast.AnnAssign(annotation=annotation)
            | ast.FunctionDef(returns=annotation)
            | ast.AsyncFunctionDef(returns=annotation)
        ):
            return annotation
        case ast.TypeAlias(value=value):
            return value
        case _:
            return None


def _vague_problem(annotation: ast.expr, imports: ImportIndex) -> str | None:
    annotation = _parse_string_annotation(annotation)
    for node in ast.walk(annotation):
        if _is_object(node, imports):
            return "object"
        if _is_open_mapping(node, imports):
            return ast.unparse(node)
    return None


def _parse_string_annotation(annotation: ast.expr) -> ast.expr:
    if not isinstance(annotation, ast.Constant) or not isinstance(annotation.value, str):
        return annotation
    try:
        return ast.parse(annotation.value, mode="eval").body
    except SyntaxError:
        return annotation


def _is_object(node: ast.AST, imports: ImportIndex) -> bool:
    return isinstance(node, ast.expr) and (
        (isinstance(node, ast.Name) and node.id == "object" and imports.builtin_is_unshadowed("object"))
        or imports.resolves(node, sources=frozenset({"builtins"}), symbol="object")
    )


def _is_open_mapping(node: ast.AST, imports: ImportIndex) -> bool:
    if (
        not isinstance(node, ast.Subscript)
        or not isinstance(node.slice, ast.Tuple)
        or len(node.slice.elts) != _MAPPING_ARGUMENT_COUNT
    ):
        return False
    target = node.value
    mapping = (isinstance(target, ast.Name) and target.id == "dict" and imports.builtin_is_unshadowed("dict")) or any(
        imports.resolves(target, sources=_MAPPING_SOURCES, symbol=name) for name in _MAPPING_NAMES
    )
    if not mapping:
        return False
    key, value = node.slice.elts
    return _is_builtin_str(key, imports) and _is_any_or_object(value, imports)


def _is_builtin_str(node: ast.expr, imports: ImportIndex) -> bool:
    return isinstance(node, ast.Name) and node.id == "str" and imports.builtin_is_unshadowed("str")


def _is_any_or_object(node: ast.expr, imports: ImportIndex) -> bool:
    return _is_object(node, imports) or imports.resolves(node, sources=_TYPING_SOURCES, symbol="Any")


def _is_vendor_path(path: Path) -> bool:
    return any(part.casefold() in {"vendor", "vendored", "third_party"} for part in path.parts)
