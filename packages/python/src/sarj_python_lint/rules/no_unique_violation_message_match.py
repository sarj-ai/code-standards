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
from sarj_python_lint.rules._paths import is_generated, is_test_path


if TYPE_CHECKING:
    from pathlib import Path


_DRIVERS = frozenset({"psycopg", "psycopg2"})


@final
class NoUniqueViolationMessageMatch(Rule):
    id = "no-unique-violation-message-match"
    code = "SARJ404"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="Do not identify a database unique constraint by substring-matching an exception message.",
        rationale=(
            "Database error text is not a stable interface and can change with driver or server versions; "
            "psycopg exposes the violated constraint as structured diagnostic data."
        ),
        remediation="Compare `exc.diag.constraint_name` with the expected constraint name.",
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "The rule recognizes psycopg and psycopg2 `UniqueViolation` handlers with direct `in` or `not in` checks against `str(exc)`.",
            "Aliases of the stringified exception and other message operations remain outside its scope.",
            "Tests and generated files are excluded.",
        ),
        examples=(
            RuleExample(
                example_id="message-matched-constraint",
                title="Unique constraint selected from error text",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/store.py",
                        "from psycopg import errors\n\ntry:\n    save()\nexcept errors.UniqueViolation as exc:\n    if 'user_email_key' in str(exc):\n        raise DuplicateEmail from exc\n    raise\n",
                    ),
                ),
                focus_path=PurePosixPath("app/store.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="structured-constraint-check",
                title="Unique constraint selected from structured diagnostics",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/store.py",
                        "from psycopg import errors\n\ntry:\n    save()\nexcept errors.UniqueViolation as exc:\n    if exc.diag.constraint_name == 'user_email_key':\n        raise DuplicateEmail from exc\n    raise\n",
                    ),
                ),
                focus_path=PurePosixPath("app/store.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if is_test_path(path) or is_generated(path, source) or "UniqueViolation" not in source:
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        imports = ImportIndex.from_tree(tree)
        if not imports.builtin_is_unshadowed("str"):
            return []
        findings: list[ast.Call] = []
        for handler in (node for node in ast.walk(tree) if isinstance(node, ast.ExceptHandler)):
            if handler.name is None or not _catches_unique_violation(handler.type, tree):
                continue
            for statement in handler.body:
                _collect_message_matches(statement, handler.name, findings)
        findings.sort(key=lambda node: (node.lineno, node.col_offset))
        return [
            Diagnostic(
                path=path,
                line=node.lineno,
                col=node.col_offset + 1,
                code=self.code,
                message=(
                    "UniqueViolation is classified by substring-matching its message; compare "
                    "`exc.diag.constraint_name` with the expected constraint instead."
                ),
                severity=Severity.WARNING,
            )
            for node in findings
        ]


def _catches_unique_violation(node: ast.expr | None, tree: ast.Module) -> bool:
    if node is None:
        return False
    candidates = node.elts if isinstance(node, ast.Tuple) else (node,)
    return any(
        _qualified_import(candidate, tree) in {"psycopg.errors.UniqueViolation", "psycopg2.errors.UniqueViolation"}
        for candidate in candidates
    )


def _qualified_import(node: ast.expr, tree: ast.Module) -> str | None:
    parts: list[str] = []
    current = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if not isinstance(current, ast.Name):
        return None
    parts.reverse()
    for statement in tree.body:
        if isinstance(statement, ast.Import):
            for alias in statement.names:
                local = alias.asname or alias.name.split(".")[0]
                if local == current.id:
                    base = alias.name if alias.asname else alias.name.split(".")[0]
                    return ".".join((base, *parts))
        elif isinstance(statement, ast.ImportFrom) and statement.level == 0 and statement.module:
            for alias in statement.names:
                if (alias.asname or alias.name) != current.id:
                    continue
                return ".".join((statement.module, alias.name, *parts))
    return None


def _collect_message_matches(node: ast.AST, exception_name: str, findings: list[ast.Call]) -> None:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
        return
    if isinstance(node, ast.Compare) and any(isinstance(operator, (ast.In, ast.NotIn)) for operator in node.ops):
        findings.extend(
            operand
            for operand in (node.left, *node.comparators)
            if isinstance(operand, ast.Call) and _is_str_exception_call(operand, exception_name)
        )
    for child in ast.iter_child_nodes(node):
        _collect_message_matches(child, exception_name, findings)


def _is_str_exception_call(node: ast.expr, exception_name: str) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "str"
        and len(node.args) == 1
        and not node.keywords
        and isinstance(node.args[0], ast.Name)
        and node.args[0].id == exception_name
    )
