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
    Severity,
    parse_or_none,
)
from sarj_python_lint.rules._ast_index import children, walk
from sarj_python_lint.rules._paths import is_generated, is_test_path


if TYPE_CHECKING:
    from pathlib import Path


_MIN_LENGTH = 40
_MIN_DISTINCT_SCOPES = 2
_PREVIEW_LENGTH = 40

_SCAFFOLDING_KWARGS = frozenset({"examples", "description", "title", "summary"})

_SQL_SHAPE_RE = re.compile(
    r"(?:\bSELECT\b[\s\S]*?\bFROM\b|\bINSERT\s+INTO\b|\bUPDATE\b[\s\S]*?\bSET\b|"
    r"\bDELETE\s+FROM\b|\bMERGE\s+INTO\b|^\s*(?:GROUP\s+BY|ORDER\s+BY|ON\s+CONFLICT|RETURNING)\b)",
    re.IGNORECASE,
)
_IDENTIFIER_RE = re.compile(r"^[a-z_][a-z0-9_.]*$")
_URL_PATH_RE = re.compile(r"^/(?=[^\s]*[A-Za-z0-9])[A-Za-z0-9._~!$&'()*+,;=:@%/?#{}\[\]-]+$")
_CONSTANT_RE = re.compile(r"^_?[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)*$")
_MIN_CONSTANT_NAME_LENGTH = 3

_MODULE_SCOPE = -1


@final
class NoRepeatedStringLiteral(Rule):
    id: str = "no-repeated-structured-string-literal"
    code: str = "SARJ024"
    documentation = RuleDocumentation(
        summary="Exact SQL or route literals repeated across callable scopes should share one named binding.",
        rationale=(
            "When exact copies represent one SQL, route, or protocol contract, editing one copy can silently diverge "
            "the others. Identical text can also represent independent concepts, so this rule is advisory."
        ),
        remediation=(
            "If the occurrences are one maintained concept, reuse an existing constant or extract a descriptive "
            "module-level constant within that ownership boundary. If equality is intentional but ownership is "
            "independent, suppress with a rationale."
        ),
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        aliases=("no-repeated-string-literal",),
        limitations=(
            "Only exact same-file literals of at least 40 characters repeated across distinct callable scopes are compared; near-duplicates are not detected.",
            "Cross-scope findings require credible SQL or an absolute route; identifier-like strings require an existing unique module constant.",
            "Prose, documentation scaffolding, annotations, tests, migrations, examples, generated files, match patterns, and f-string fragments are excluded.",
        ),
        examples=(
            RuleExample(
                example_id="repeated-sql-across-functions",
                title="SQL literal is copied across functions",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "queries.py",
                        'def load(cursor):\n    cursor.execute("SELECT id, name, created_at FROM organization")\n\ndef refresh(cursor):\n    cursor.execute("SELECT id, name, created_at FROM organization")\n',
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
                        '_SELECT_ORGANIZATIONS = "SELECT id, name, created_at FROM organization"\n\ndef load(cursor):\n    cursor.execute(_SELECT_ORGANIZATIONS)\n\ndef refresh(cursor):\n    cursor.execute(_SELECT_ORGANIZATIONS)\n',
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
        scope_line_of: dict[int, int] = {}
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
                    scope_line_of[scope] = node.lineno
            elif isinstance(node, ast.Lambda):
                scope = id(node)
                scope_line_of[scope] = node.lineno
            elif isinstance(node, ast.JoinedStr):
                excluded.update(id(value) for value in node.values)
            elif isinstance(node, ast.MatchValue):
                excluded.update(id(child) for child in walk(node) if isinstance(child, ast.Constant))
            elif isinstance(node, ast.Call):
                for kw in node.keywords:
                    if kw.arg in _SCAFFOLDING_KWARGS:
                        excluded.update(id(child) for child in walk(kw.value) if isinstance(child, ast.Constant))
            elif (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and len(node.value) >= _MIN_LENGTH
                and id(node) not in excluded
                and _is_candidate(node.value)
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
            eligible_canonical = tuple(
                name
                for name, line in canonical
                if all(line < scope_line_of.get(scope, 0) for scope in function_scopes)
            )
            if len(eligible_canonical) == 1 and function_scopes:
                (constant_name,) = eligible_canonical
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
                        severity=Severity.WARNING,
                    )
                    for node in function_nodes
                )
                continue
            if len(function_scopes) < _MIN_DISTINCT_SCOPES:
                continue
            if not _is_cross_scope_structured(value):
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
                        f"callable scopes (first use at line {first.lineno}) — reuse a named binding "
                        "when they share ownership, or suppress with an independent-ownership rationale."
                    ),
                    severity=Severity.WARNING,
                )
                for node in repeats
            )
        diags.sort(key=lambda d: (d.line, d.col))
        return diags


def _canonical_constants(tree: ast.Module) -> dict[str, tuple[tuple[str, int], ...]]:
    names: dict[str, list[tuple[str, int]]] = defaultdict(list)
    binding_counts: dict[str, int] = defaultdict(int)
    for statement in tree.body:
        match statement:
            case ast.Assign(targets=[ast.Name(id=name)], value=value):
                pass
            case ast.AnnAssign(target=ast.Name(id=name), value=value):
                pass
            case ast.FunctionDef() | ast.AsyncFunctionDef() | ast.ClassDef():
                binding_counts[statement.name] += 1
                continue
            case _:
                continue
        binding_counts[name] += 1
        canonical_value = _canonical_value(name, value)
        if canonical_value is not None:
            names[canonical_value].append((name, statement.lineno))
    return {
        value: tuple((name, line) for name, line in bound_names if binding_counts[name] == 1)
        for value, bound_names in names.items()
    }


def _canonical_value(name: str, value: ast.expr | None) -> str | None:
    if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
        return None
    is_canonical = (
        _CONSTANT_RE.fullmatch(name) is not None
        and len(name.lstrip("_")) >= _MIN_CONSTANT_NAME_LENGTH
        and len(value.value) >= _MIN_LENGTH
        and _is_candidate(value.value)
    )
    return value.value if is_canonical else None


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


def _is_candidate(value: str) -> bool:
    return _is_cross_scope_structured(value) or _IDENTIFIER_RE.fullmatch(value) is not None


def _is_cross_scope_structured(value: str) -> bool:
    return _SQL_SHAPE_RE.search(value) is not None or _URL_PATH_RE.fullmatch(value) is not None


def _preview(value: str) -> str:
    if len(value) <= _PREVIEW_LENGTH:
        return repr(value)
    return repr(f"{value[:_PREVIEW_LENGTH]}…")


def _is_skipped_path(path: Path) -> bool:
    excluded_parts = frozenset(
        {"benchmark", "benchmarks", "example", "examples", "fixture", "fixtures", "migration", "migrations", "snapshots"}
    )
    return is_test_path(path) or bool(excluded_parts.intersection(part.lower() for part in path.parts))
