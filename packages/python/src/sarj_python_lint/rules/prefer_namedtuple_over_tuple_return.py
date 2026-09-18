from __future__ import annotations

import ast
from pathlib import Path, PurePosixPath
from typing import ClassVar, final, override

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
from sarj_python_lint.rules._imports import ImportIndex
from sarj_python_lint.rules._paths import is_generated


_MIN_FIELDS = 2
_DOCUMENTATION_DIR_NAMES = frozenset({"docs", "docs_src"})
_TUPLE_SOURCES = frozenset({"builtins"})
_TYPING_SOURCES = frozenset({"typing"})

_MSG = (
    "function returns a fixed positional tuple record — return a dataclass or validation model; "
    "use typing.NamedTuple only when tuple protocol compatibility is required."
)


@final
class PreferNamedtupleOverTupleReturn(Rule):
    id: str = "no-positional-tuple-record"
    code: str = "SARJ026"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="Fixed tuple return records should use named fields instead of positional slots.",
        rationale=(
            "A fixed tuple return makes callers remember positions and lets adjacent values be silently swapped. "
            "Named records preserve field meaning across public, private, decorated, method, and test boundaries."
        ),
        remediation=(
            "Return a frozen dataclass or validation model. Use `typing.NamedTuple` only when an exact tuple protocol is required."
        ),
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        aliases=("prefer-namedtuple-over-tuple-return",),
        limitations=(
            "Generated files and documentation examples are excluded.",
            "Explicit provenance-resolved builtin or typing fixed tuple return annotations with at least two slots are reported; variadic tuples remain valid collections.",
        ),
        examples=(
            RuleExample(
                example_id="positional-public-return",
                title="Public function returns a positional record",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/profile.py",
                        "def load_profile() -> tuple[str, int, bool]:\n    return 'Ada', 42, True\n",
                    ),
                ),
                focus_path=PurePosixPath("app/profile.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="named-public-return",
                title="Public function returns a tuple-compatible named record",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/profile.py",
                        "from typing import NamedTuple\n\n"
                        "class Profile(NamedTuple):\n"
                        "    name: str\n"
                        "    age: int\n"
                        "    active: bool\n\n"
                        "def load_profile() -> Profile:\n"
                        "    return Profile(name='Ada', age=42, active=True)\n",
                    ),
                ),
                focus_path=PurePosixPath("app/profile.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description: str = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if is_generated(path, source) or _is_documentation_path(path):
            return []
        tree = parse_or_none(path, source)
        if tree is None or _has_wildcard_import(tree):
            return []
        imports = ImportIndex.from_tree(tree)
        diagnostics: list[Diagnostic] = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or node.returns is None:
                continue
            if not _is_public_record_tuple(node.returns, imports):
                continue
            diagnostics.append(
                Diagnostic(
                    path=path,
                    line=node.lineno,
                    col=node.col_offset + 1,
                    code=self.code,
                    message=_MSG,
                    severity=Severity.ERROR,
                )
            )
        return diagnostics


def _is_documentation_path(path: Path) -> bool:
    return any(part.lower() in _DOCUMENTATION_DIR_NAMES for part in path.parts)


def _has_wildcard_import(tree: ast.Module) -> bool:
    return any(
        isinstance(node, ast.ImportFrom) and any(alias.name == "*" for alias in node.names) for node in ast.walk(tree)
    )


def _is_public_record_tuple(annotation: ast.expr, imports: ImportIndex) -> bool:
    annotation = _unwrap_return_annotation(annotation, imports)
    if not isinstance(annotation, ast.Subscript) or not isinstance(annotation.slice, ast.Tuple):
        return False
    target = annotation.value
    is_tuple = (
        (isinstance(target, ast.Name) and target.id == "tuple" and imports.builtin_is_unshadowed("tuple"))
        or imports.resolves(target, sources=_TUPLE_SOURCES, symbol="tuple")
        or imports.resolves(target, sources=_TYPING_SOURCES, symbol="Tuple")
    )
    if not is_tuple:
        return False
    fields = annotation.slice.elts
    return len(fields) >= _MIN_FIELDS and not any(_is_variadic_field(field) for field in fields)


def _unwrap_return_annotation(annotation: ast.expr, imports: ImportIndex) -> ast.expr:
    if isinstance(annotation, ast.Constant) and isinstance(annotation.value, str):
        parsed = parse_or_none(Path("annotation.py"), f"value: {annotation.value}")
        if parsed is not None and isinstance(parsed.body[0], ast.AnnAssign):
            return parsed.body[0].annotation
    if (
        isinstance(annotation, ast.Subscript)
        and imports.resolves(annotation.value, sources=_TYPING_SOURCES, symbol="Annotated")
        and isinstance(annotation.slice, ast.Tuple)
        and annotation.slice.elts
    ):
        return _unwrap_return_annotation(annotation.slice.elts[0], imports)
    return annotation


def _is_variadic_field(node: ast.expr) -> bool:
    return (
        isinstance(node, ast.Starred)
        or (isinstance(node, ast.Subscript) and _leaf_name(node.value) == "Unpack")
        or (isinstance(node, ast.Constant) and node.value is Ellipsis)
    )


def _leaf_name(node: ast.expr) -> str | None:
    match node:
        case ast.Name(id=name) | ast.Attribute(attr=name):
            return name
        case _:
            return None
