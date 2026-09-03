from __future__ import annotations

import ast
from pathlib import PurePosixPath
import re
from typing import TYPE_CHECKING, NamedTuple, final, override

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
from sarj_python_lint.rules._ast_index import nodes, walk
from sarj_python_lint.rules._paths import is_generated, is_test_path
from sarj_python_lint.rules._sql import sql_string_value, strip_sql_noise


if TYPE_CHECKING:
    from pathlib import Path


_SQL_TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_$]*|\d+(?:\.\d+)?|[(),.*;]")
_SELECT_PREFIX_WORDS = frozenset(
    {
        "ALL",
        "DISTINCT",
        "HIGH_PRIORITY",
        "PERCENT",
        "SQL_BIG_RESULT",
        "SQL_BUFFER_RESULT",
        "SQL_CACHE",
        "SQL_CALC_FOUND_ROWS",
        "SQL_NO_CACHE",
        "SQL_SMALL_RESULT",
        "STRAIGHT_JOIN",
        "TIES",
        "TOP",
        "WITH",
    }
)
_QUERY_BINDING_TOKENS = frozenset({"query", "sql", "statement"})
_QUERY_SINKS = frozenset({"execute", "executemany", "executescript", "sql", "text"})
_NON_PRODUCTION_SQL_PARTS = frozenset({"examples", "fixtures", "migration", "migrations"})
_EXISTS_PREFIX_LENGTH = 2


class _SqlToken(NamedTuple):
    value: str
    depth: int


def _has_real_select_star(sql: str) -> bool:
    tokens = _tokens_with_depth(sql)
    selects: dict[int, tuple[int, bool, bool]] = {}
    for index, token in enumerate(tokens):
        lexeme = token.value
        depth = token.depth
        if lexeme == "SELECT":
            selects[depth] = (index, _is_exists_owned(tokens, index), False)
            continue
        context = selects.get(depth)
        if context is None:
            continue
        select_index, exists_owned, found_star = context
        if lexeme == "*" and not exists_owned and _is_projection_star(tokens, index, select_index):
            selects[depth] = (select_index, exists_owned, True)
        elif lexeme == "FROM":
            if found_star:
                return True
            selects.pop(depth, None)
        elif lexeme == ";":
            selects.pop(depth, None)
    return False


def _tokens_with_depth(sql: str) -> list[_SqlToken]:
    tokens: list[_SqlToken] = []
    depth = 0
    for match in _SQL_TOKEN.finditer(sql):
        lexeme = match.group().upper()
        if lexeme == ")":
            depth = max(0, depth - 1)
        tokens.append(_SqlToken(lexeme, depth))
        if lexeme == "(":
            depth += 1
    return tokens


def _is_exists_owned(tokens: list[_SqlToken], select_index: int) -> bool:
    return (
        select_index >= _EXISTS_PREFIX_LENGTH
        and tokens[select_index - 1].value == "("
        and tokens[select_index - _EXISTS_PREFIX_LENGTH].value == "EXISTS"
    )


def _is_projection_star(tokens: list[_SqlToken], star_index: int, select_index: int) -> bool:
    previous = tokens[star_index - 1].value if star_index else ""
    if previous == ".":
        return True
    if previous in {"SELECT", ","} or previous in _SELECT_PREFIX_WORDS:
        return True
    prefix = [
        token.value for token in tokens[select_index + 1 : star_index] if token.depth == tokens[select_index].depth
    ]
    return bool(prefix[:2] == ["DISTINCT", "ON"] and previous == ")")


@final
class NoSelectStar(Rule):
    id: str = "no-select-star"
    code: str = "SARJ021"
    documentation = RuleDocumentation(
        summary="SQL SELECT projections should list explicit result columns instead of wildcards.",
        rationale="Wildcard projections can over-fetch data and silently change result contracts when a source schema evolves.",
        remediation=(
            "List the output columns required by the query consumer. Suppress with a rationale when a bounded "
            "intermediate relation intentionally preserves its complete shape."
        ),
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only statically recoverable SQL strings in credible query assignments or execution/composition calls in production source files are analyzed.",
            "Dynamic SQL and SQLAlchemy expression trees are not analyzed; bounded CTE wildcards may require a documented suppression.",
        ),
        examples=(
            RuleExample(
                example_id="wildcard-store-projection",
                title="Store query selects every column",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/call_store.py",
                        "row = cursor.execute(\n    'SELECT c.* FROM call AS c WHERE c.id = %s',\n    (call_id,),\n).fetchone()\ncall = Call.model_validate(row)\n",
                    ),
                ),
                focus_path=PurePosixPath("app/call_store.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="explicit-store-projection",
                title="Store query selects named columns",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/call_store.py",
                        "row = cursor.execute(\n    'SELECT c.id, c.status FROM call AS c WHERE c.id = %s',\n    (call_id,),\n).fetchone()\ncall = Call.model_validate(row)\n",
                    ),
                ),
                focus_path=PurePosixPath("app/call_store.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if (
            is_test_path(path)
            or is_generated(path, source)
            or any(part.lower() in _NON_PRODUCTION_SQL_PARTS for part in path.parts)
        ):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []

        diags: list[Diagnostic] = []
        parents = {id(child): parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
        docstrings = _docstring_value_ids(tree)
        consumed: set[int] = set()
        for node in nodes(tree, ast.Constant, ast.BinOp, ast.JoinedStr):
            if id(node) in consumed or id(node) in docstrings or not _is_query_context(node, parents):
                continue
            text = sql_string_value(node, interpolation_placeholder=" __SARJ_DYNAMIC__ ")
            if text is None:
                continue
            consumed.update(id(sub) for sub in walk(node))

            sql = strip_sql_noise(text)
            if not _has_real_select_star(sql):
                continue

            diags.append(
                Diagnostic(
                    path=path,
                    line=node.lineno,
                    col=node.col_offset + 1,
                    code=self.code,
                    message=(
                        "SELECT projection uses a wildcard, which can over-fetch and make the result shape depend "
                        "on its source — list the consumed columns explicitly. Suppress "
                        "with `# sarj-noqa: SARJ021`."
                    ),
                )
            )
        diags.sort(key=lambda d: (d.line, d.col))
        return diags


def _docstring_value_ids(tree: ast.AST) -> set[int]:
    owners = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
    return {
        id(owner.body[0].value)
        for owner in ast.walk(tree)
        if isinstance(owner, owners)
        and owner.body
        and isinstance(owner.body[0], ast.Expr)
        and isinstance(owner.body[0].value, ast.Constant)
        and isinstance(owner.body[0].value.value, str)
    }


def _is_query_context(node: ast.expr, parents: dict[int, ast.AST]) -> bool:
    current: ast.AST = node
    while (parent := parents.get(id(current))) is not None:
        match parent:
            case ast.Assign() | ast.AnnAssign() | ast.NamedExpr():
                return any(_is_query_binding(target) for target in _assignment_targets(parent))
            case ast.Call():
                return _call_name(parent.func).lower() in _QUERY_SINKS
            case ast.Expr() | ast.Return() | ast.Raise():
                return False
            case _:
                pass
        current = parent
    return False


def _assignment_targets(node: ast.Assign | ast.AnnAssign | ast.NamedExpr) -> tuple[ast.expr, ...]:
    if isinstance(node, ast.Assign):
        return tuple(node.targets)
    return (node.target,)


def _is_query_binding(target: ast.expr) -> bool:
    if not isinstance(target, (ast.Name, ast.Attribute)):
        return False
    name = target.id if isinstance(target, ast.Name) else target.attr
    tokens = frozenset(part for part in name.lower().split("_") if part)
    return name == "q" or name.isupper() or bool(tokens & _QUERY_BINDING_TOKENS)


def _call_name(function: ast.expr) -> str:
    match function:
        case ast.Name(id=name) | ast.Attribute(attr=name):
            return name
        case _:
            return ""
