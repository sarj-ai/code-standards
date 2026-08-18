from __future__ import annotations

import ast
from collections import defaultdict
from pathlib import PurePosixPath
import re
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
    parse_or_none,
)
from sarj_python_lint.rules._ast_index import children, walk
from sarj_python_lint.rules._paths import is_generated


if TYPE_CHECKING:
    from pathlib import Path


_MIN_LENGTH = 40
_MIN_DISTINCT_SCOPES = 2
_PREVIEW_LENGTH = 40

_SCAFFOLDING_KWARGS = frozenset({"examples", "description", "title", "summary"})

_SQL_KEYWORD_RE = re.compile(
    r"\b(SELECT|INSERT|UPDATE|DELETE|FROM|WHERE|JOIN|VALUES|ON CONFLICT|RETURNING|GROUP BY|ORDER BY)\b"
)
_IDENTIFIER_RE = re.compile(r"^[a-z_][a-z0-9_.]*$")
_URL_PATH_RE = re.compile(r"^/(?=[^\s]*[A-Za-z0-9])[A-Za-z0-9._~!$&'()*+,;=:@%/?#{}\[\]-]+$")
_PUBLIC_CONSTANT_RE = re.compile(r"^[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)*$")
_MIN_CONSTANT_NAME_LENGTH = 3

_MODULE_SCOPE = -1


@final
class NoRepeatedStringLiteral(Rule):
    id: str = "no-repeated-string-literal"
    code: str = "SARJ024"
    documentation = RuleDocumentation(
        summary="Structured string literals repeated across functions should use a module constant.",
        rationale="Independent copies of SQL, route templates, and identifier-like strings can drift while appearing equivalent.",
        remediation="Extract the shared value to one named module-level constant and reference it from each function.",
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only structured literals of at least 40 characters repeated across distinct functions are reported.",
            "Prose, documentation scaffolding, annotations, generated files, and repeated f-string fragments are excluded.",
        ),
        examples=(
            RuleExample(
                example_id="repeated-sql-across-functions",
                title="SQL literal is copied across functions",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "queries.py",
                        'def load():\n    return "SELECT id, name, created_at FROM organization"\n\ndef refresh():\n    return "SELECT id, name, created_at FROM organization"\n',
                    ),
                ),
                focus_path=PurePosixPath("queries.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="shared-sql-module-constant",
                title="Functions reuse one SQL constant",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "queries.py",
                        'QUERY = "SELECT id, name, created_at FROM organization"\n\ndef load():\n    return QUERY\n\ndef refresh():\n    return QUERY\n',
                    ),
                ),
                focus_path=PurePosixPath("queries.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if is_generated(path, source):
            return []
        if _is_skipped_path(path):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []

        canonical_constants = _canonical_constants(tree)

        occurrences: dict[str, list[ast.Constant]] = defaultdict(list)
        scope_of: dict[int, int] = {}
        excluded: set[int] = set()

        def visit(node: ast.AST, scope: int) -> None:
            for annotation in _annotation_exprs(node):
                excluded.update(id(child) for child in walk(annotation) if isinstance(child, ast.Constant))
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                body = node.body
                if (
                    body
                    and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)
                ):
                    excluded.add(id(body[0].value))
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    scope = id(node)
            elif isinstance(node, ast.JoinedStr):
                excluded.update(id(value) for value in node.values)
            elif isinstance(node, ast.Call):
                for kw in node.keywords:
                    if kw.arg in _SCAFFOLDING_KWARGS:
                        excluded.update(id(child) for child in walk(kw.value) if isinstance(child, ast.Constant))
            elif (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and len(node.value) >= _MIN_LENGTH
                and id(node) not in excluded
                and _is_structured(node.value)
            ):
                occurrences[node.value].append(node)
                scope_of[id(node)] = scope
            for child in children(node):
                visit(child, scope)

        visit(tree, _MODULE_SCOPE)

        diags: list[Diagnostic] = []
        for value, nodes in occurrences.items():
            function_scopes = {scope for n in nodes if (scope := scope_of.get(id(n), _MODULE_SCOPE)) != _MODULE_SCOPE}
            canonical = canonical_constants.get(value, ())
            if len(canonical) == 1 and function_scopes:
                (constant_name,) = canonical
                function_nodes = [node for node in nodes if scope_of.get(id(node), _MODULE_SCOPE) != _MODULE_SCOPE]
                diags.extend(
                    Diagnostic(
                        path=path,
                        line=node.lineno,
                        col=node.col_offset + 1,
                        code=self.code,
                        message=(
                            f"structured string literal {_preview(value)} duplicates module constant "
                            f"`{constant_name}` — reuse the canonical constant so the copies cannot drift."
                        ),
                    )
                    for node in function_nodes
                )
                continue
            if len(function_scopes) < _MIN_DISTINCT_SCOPES:
                continue
            nodes.sort(key=lambda n: (n.lineno, n.col_offset))
            first, *repeats = nodes
            diags.extend(
                Diagnostic(
                    path=path,
                    line=node.lineno,
                    col=node.col_offset + 1,
                    code=self.code,
                    message=(
                        f"structured string literal {_preview(value)} is repeated across "
                        f"functions (first use at line {first.lineno}) — extract a "
                        f"module-level constant so the copies cannot drift."
                    ),
                )
                for node in repeats
            )
        diags.sort(key=lambda d: (d.line, d.col))
        return diags


def _canonical_constants(tree: ast.Module) -> dict[str, tuple[str, ...]]:
    names: dict[str, list[str]] = defaultdict(list)
    for statement in tree.body:
        match statement:
            case ast.Assign(targets=[ast.Name(id=name)], value=ast.Constant(value=str() as value)):
                pass
            case ast.AnnAssign(target=ast.Name(id=name), value=ast.Constant(value=str() as value)):
                pass
            case _:
                continue
        if (
            _PUBLIC_CONSTANT_RE.fullmatch(name) is not None
            and len(name) >= _MIN_CONSTANT_NAME_LENGTH
            and len(value) >= _MIN_LENGTH
            and _is_structured(value)
        ):
            names[value].append(name)
    return {value: tuple(bound_names) for value, bound_names in names.items()}


def _annotation_exprs(node: ast.AST) -> list[ast.expr]:
    match node:
        case ast.arg(annotation=annotation) if annotation is not None:
            return [annotation]
        case ast.FunctionDef(returns=returns) | ast.AsyncFunctionDef(returns=returns) if returns is not None:
            return [returns]
        case ast.AnnAssign(annotation=annotation):
            return [annotation]
        case ast.Subscript(value=value, slice=annotation) if _is_annotated(value):
            return [annotation]
        case _:
            return []


def _is_annotated(expr: ast.expr) -> bool:
    if isinstance(expr, ast.Name):
        return expr.id == "Annotated"
    return isinstance(expr, ast.Attribute) and expr.attr == "Annotated"


def _is_structured(value: str) -> bool:
    return (
        "\n" in value
        or _SQL_KEYWORD_RE.search(value) is not None
        or _IDENTIFIER_RE.fullmatch(value) is not None
        or _URL_PATH_RE.fullmatch(value) is not None
    )


def _preview(value: str) -> str:
    if len(value) <= _PREVIEW_LENGTH:
        return repr(value)
    return repr(f"{value[:_PREVIEW_LENGTH]}…")


def _is_skipped_path(path: Path) -> bool:
    if path.name == "conftest.py":
        return True
    if path.name.startswith("test_"):
        return True
    return "tests" in path.parts
