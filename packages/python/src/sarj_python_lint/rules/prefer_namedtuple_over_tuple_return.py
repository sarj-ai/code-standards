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
    parse_or_none,
)
from sarj_python_lint.rules._imports import ImportIndex
from sarj_python_lint.rules._paths import is_generated, is_test_path, is_test_support_path


if TYPE_CHECKING:
    from pathlib import Path


_MIN_FIELDS = 3
_DOCUMENTATION_DIR_NAMES = frozenset({"docs", "docs_src"})
_TUPLE_SOURCES = frozenset({"builtins"})
_TYPING_SOURCES = frozenset({"typing"})

_MSG = (
    "public function returns three or more distinct fields as a positional tuple — prefer typing.NamedTuple "
    "when tuple compatibility matters; a dataclass or validation model requires an intentional caller migration."
)


@final
class PreferNamedtupleOverTupleReturn(Rule):
    id: str = "prefer-namedtuple-over-tuple-return"
    code: str = "SARJ026"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary=(
            "Public top-level functions should use named records for heterogeneous tuple returns with three or more fields."
        ),
        rationale=(
            "A public tuple with several distinct field roles makes callers remember positions and lets adjacent values be "
            "silently swapped. Small pairs, homogeneous coordinates, private helpers, and callback protocols are often "
            "intentionally positional and remain outside this advisory."
        ),
        remediation=(
            "Use `typing.NamedTuple` when existing unpacking, indexing, tuple equality, or sequence-shaped JSON compatibility "
            "matters. Use a frozen dataclass or validation model only as a deliberate API migration with callers updated."
        ),
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Tests, test-support code, generated files, documentation examples, private or nested functions, methods, decorated functions, and functions used as key callbacks are excluded.",
            "Only explicit provenance-resolved builtin or typing tuple annotations with at least three fixed, heterogeneous slots are reported; inferred, variadic, homogeneous, aliased, wrapped, stringized, and collection-nested tuples are excluded.",
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
        if (
            is_generated(path, source)
            or is_test_path(path)
            or is_test_support_path(path)
            or _is_documentation_path(path)
        ):
            return []
        tree = parse_or_none(path, source)
        if tree is None or _has_wildcard_import(tree):
            return []
        imports = ImportIndex.from_tree(tree)
        key_callbacks = _key_callback_names(tree)
        reported_names: set[str] = set()
        diagnostics: list[Diagnostic] = []
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if node.name.startswith("_") or node.name in key_callbacks or node.name in reported_names:
                continue
            if node.decorator_list or node.returns is None:
                continue
            if not _is_public_record_tuple(node.returns, imports):
                continue
            reported_names.add(node.name)
            diagnostics.append(
                Diagnostic(
                    path=path,
                    line=node.lineno,
                    col=node.col_offset + 1,
                    code=self.code,
                    message=_MSG,
                    severity=Severity.WARNING,
                )
            )
        return diagnostics


def _is_documentation_path(path: Path) -> bool:
    return any(part.lower() in _DOCUMENTATION_DIR_NAMES for part in path.parts)


def _has_wildcard_import(tree: ast.Module) -> bool:
    return any(
        isinstance(node, ast.ImportFrom) and any(alias.name == "*" for alias in node.names)
        for node in ast.walk(tree)
    )


def _key_callback_names(tree: ast.Module) -> frozenset[str]:
    return frozenset(
        keyword.value.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        for keyword in node.keywords
        if keyword.arg == "key" and isinstance(keyword.value, ast.Name)
    )


def _is_public_record_tuple(annotation: ast.expr, imports: ImportIndex) -> bool:
    if not isinstance(annotation, ast.Subscript) or not isinstance(annotation.slice, ast.Tuple):
        return False
    target = annotation.value
    is_tuple = (
        isinstance(target, ast.Name)
        and target.id == "tuple"
        and imports.builtin_is_unshadowed("tuple")
    ) or imports.resolves(target, sources=_TUPLE_SOURCES, symbol="tuple") or imports.resolves(
        target, sources=_TYPING_SOURCES, symbol="Tuple"
    )
    if not is_tuple:
        return False
    fields = annotation.slice.elts
    if len(fields) < _MIN_FIELDS or any(_is_variadic_field(field) for field in fields):
        return False
    return len({_annotation_shape(field, imports) for field in fields}) > 1


def _is_variadic_field(node: ast.expr) -> bool:
    return (
        isinstance(node, ast.Starred)
        or (isinstance(node, ast.Subscript) and _leaf_name(node.value) == "Unpack")
        or (isinstance(node, ast.Constant) and node.value is Ellipsis)
    )


def _annotation_shape(node: ast.expr, imports: ImportIndex) -> str:
    builtin_name = _builtin_annotation_name(node, imports)
    if builtin_name is not None:
        return f"builtin:{builtin_name}"
    return ast.dump(node, include_attributes=False)


def _builtin_annotation_name(node: ast.expr, imports: ImportIndex) -> str | None:
    if isinstance(node, ast.Name) and imports.builtin_is_unshadowed(node.id):
        return node.id
    return imports.resolved_symbol(node, sources=_TUPLE_SOURCES)


def _leaf_name(node: ast.expr) -> str | None:
    match node:
        case ast.Name(id=name) | ast.Attribute(attr=name):
            return name
        case _:
            return None
