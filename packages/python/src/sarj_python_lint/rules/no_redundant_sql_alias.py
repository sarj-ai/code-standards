from __future__ import annotations

import ast
from pathlib import PurePosixPath
import re
from string import ascii_lowercase, ascii_uppercase
from typing import TYPE_CHECKING, final, override

from sarj_python_lint._closed_sql_literal import literal_query, owned_literal
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
    is_suppressed,
)
from sarj_python_lint.rules._sql import sql_string_value
from sarj_python_lint.rules._store_sql import store_queries


if TYPE_CHECKING:
    from sqlglot import exp

    from sarj_python_lint._file_context import PythonFileContext


_COMPOSABLE_HOLE = re.compile(r"(?<!\{)\{(?:[A-Za-z_]\w*|\d*)\}(?!\})")
_SQL_HOLE = "__sarj_sql_hole__"
_STORE_SQL_HOLE = "__sarj_store_sql_hole__"
_ASCII_FOLD = str.maketrans(ascii_uppercase, ascii_lowercase)


_BAD = 'from psycopg.sql import SQL\nQUERY = SQL("SELECT call.id AS id FROM call AS call WHERE id = %s")\n'
_GOOD = 'from psycopg.sql import SQL\nQUERY = SQL("SELECT call.id FROM call WHERE id = %s")\n'
_SAFE = (
    "from psycopg import Connection\n"
    "def literal_rows():\n"
    "    with Connection.connect() as connection:\n"
    '        return connection.execute(\'SELECT "r"."id" AS "id" FROM (VALUES (1)) AS "r"("id")\').fetchall()\n'
)
_FIXED = _SAFE.replace('"r"."id" AS "id"', '"r"."id"')


@final
class NoRedundantSqlAlias(Rule):
    id = "no-redundant-sql-alias"
    code = "SARJ543"
    documentation = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Remove SQL aliases that repeat the original relation or column name.",
        rationale="A self-alias adds syntax without naming a distinct role or result field. It obscures useful aliases among repeated names.",
        remediation="Remove an alias whose PostgreSQL identifier equals the original table or bare column name. Keep role aliases for self joins, renamed outputs, quoted case distinctions and alias column lists.",
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.SAFE,
        limitations=(
            "Checks parsed PostgreSQL queries in proven psycopg SQL constructors and execution contexts. Generated sources, comments, malformed statements, opaque dynamic SQL and unrelated strings are excluded.",
            "Only table self-aliases without alias column lists and bare-column output self-aliases are checked. Identifier folding follows PostgreSQL UTF-8 ASCII case rules. Casts, computed expressions, CTE aliases, different role names and quoted identifier case retain their contract.",
            "Autofix only removes qualified bare-column self-aliases over one to eight equally wide VALUES rows of unsigned integer literals with explicit known unique labels, directly returned through a fresh default Psycopg Connection in a closed source-owned function. Already unaliased qualified columns remain unchanged. Table aliases, external relations, comments, configured connections, query composition and other consumers remain manual. Original token spelling, output names, values, row order and SQL clauses are preserved.",
            "The finding is emitted once per SQL expression even when it contains several redundant aliases. It does not infer that different relation names belong to the same model.",
        ),
        examples=(
            RuleExample(
                example_id="safe-autofix",
                title="Remove a self-alias from a closed literal result column",
                outcome=ExampleOutcome.MATCH,
                scenario="owned-literal-self-alias",
                files=(ExampleFile.python("app/literal_rows.py", _SAFE),),
                fixed_files=(ExampleFile.python("app/literal_rows.py", _FIXED),),
                focus_path=PurePosixPath("app/literal_rows.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="fixed-owned-literal",
                title="A closed literal column keeps its implicit output name",
                outcome=ExampleOutcome.NO_MATCH,
                scenario="owned-literal-self-alias",
                files=(ExampleFile.python("app/literal_rows.py", _FIXED),),
                focus_path=PurePosixPath("app/literal_rows.py"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="self-aliases",
                title="Aliases repeat the existing names",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.python("app/call_store.py", _BAD),),
                focus_path=PurePosixPath("app/call_store.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="direct-names",
                title="Use the existing relation and column names",
                outcome=ExampleOutcome.NO_MATCH,
                files=(ExampleFile.python("app/call_store.py", _GOOD),),
                focus_path=PurePosixPath("app/call_store.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if context.generated or context.tree is None:
            return []
        # Both query recovery paths require an import-proven Psycopg symbol.
        if not context.nodes(ast.Import, ast.ImportFrom):
            return []
        candidates: dict[ast.expr, bool] = {}
        for query in store_queries(context):
            candidates[query.node] = candidates.get(query.node, False) or _statement_alias(query.statement)
        _record_closed_literal(candidates, context.tree, context.source)
        for call in context.nodes(ast.Call):
            if context.static_resource_provenance.runtime_import_name(call.func) not in {
                "psycopg.sql.SQL",
                "psycopg2.sql.SQL",
            }:
                continue
            if len(call.args) != 1 or call.keywords:
                continue
            node = call.args[0]
            text = sql_string_value(node, interpolation_placeholder=_SQL_HOLE)
            if text is not None:
                candidates[node] = _redundant_alias(text)
        return [
            Diagnostic(
                context.path,
                node.lineno,
                node.col_offset + 1,
                self.code,
                "Remove SQL aliases that repeat the original table or bare-column name; preserve distinct roles, quoted case, and alias column lists.",
                severity=Severity.WARNING,
            )
            for node, redundant in candidates.items()
            if redundant and not is_suppressed(context.source_lines, node.lineno, self.code)
        ]


def _record_closed_literal(candidates: dict[ast.expr, bool], tree: ast.Module, source: str) -> None:
    closed_literal = owned_literal(tree)
    if closed_literal is None:
        return
    closed_query = literal_query(source, closed_literal)
    if closed_query is None:
        return
    candidates[closed_literal] = candidates.get(closed_literal, False) or _redundant_alias(closed_query)


def _redundant_alias(source: str) -> bool:
    from sqlglot.errors import SqlglotError  # ruff: ignore[import-outside-top-level] -- malformed SQL abstains.

    from sarj_python_lint.rules._postgres import parse_postgres  # ruff: ignore[import-outside-top-level] -- preserve private SQL logging policy.

    try:
        statements = parse_postgres(_COMPOSABLE_HOLE.sub(_SQL_HOLE, source))
    except SqlglotError, RecursionError:
        return False
    return any(_statement_alias(statement) for statement in statements if statement is not None)


def _statement_alias(statement: exp.Expr) -> bool:
    from sqlglot import exp  # ruff: ignore[import-outside-top-level] -- only parsed queries need expression types.

    for node in statement.walk():
        if isinstance(node, exp.Table) and _table_self_alias(node):
            return True
        if isinstance(node, exp.Alias) and _column_self_alias(node):
            return True
    return False


def _table_self_alias(node: exp.Expr) -> bool:
    from sqlglot import exp  # ruff: ignore[import-outside-top-level] -- preserve relation alias contracts.

    alias = _child(node, "alias")
    if not isinstance(alias, exp.TableAlias) or any(child.arg_key == "columns" for child in alias.iter_expressions()):
        return False
    original = identifier_key(_child(node, "this"))
    return original is not None and original == identifier_key(_child(alias, "this"))


def _column_self_alias(node: exp.Expr) -> bool:
    from sqlglot import exp  # ruff: ignore[import-outside-top-level] -- only bare column names are redundant.

    column = _child(node, "this")
    if not isinstance(column, exp.Column):
        return False
    original = identifier_key(_child(column, "this"))
    return original is not None and original == identifier_key(_child(node, "alias"))


def _child(node: exp.Expr, key: str) -> exp.Expr | None:
    return next((child for child in node.iter_expressions() if child.arg_key == key), None)


def identifier_key(node: exp.Expr | None) -> str | None:
    from sqlglot import exp  # ruff: ignore[import-outside-top-level] -- parse SQL only after ownership proof.

    if not isinstance(node, exp.Identifier):
        return None
    name = node.name
    if _SQL_HOLE in name or _STORE_SQL_HOLE in name:
        return None
    return name if node.args.get("quoted") else name.translate(_ASCII_FOLD)
