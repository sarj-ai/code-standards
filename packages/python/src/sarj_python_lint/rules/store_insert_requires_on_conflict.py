from __future__ import annotations

import ast
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
from sarj_python_lint.rules._ast_index import nodes, walk
from sarj_python_lint.rules._paths import is_generated
from sarj_python_lint.rules._sql import is_store_module, sql_string_value, strip_sql_noise


if TYPE_CHECKING:
    from pathlib import Path


# Strict keyword adjacency distinguishes SQL writes from prose.
_INSERT_WRITE = re.compile(
    r"\bINSERT\s+(?:OR\s+\w+\s+)?INTO\s+[\w.\"'`?$:@-]+\s*(?:\([^)]*\)\s*)?(?:VALUES|SELECT|DEFAULT\s+VALUES)\b",
    re.IGNORECASE,
)

# Replay-safe conflict handling supported across the repository's SQL dialects.
_CONFLICT_HANDLED = re.compile(
    r"\bON\s+CONFLICT\b[\s\S]*?\bDO\s+(?:NOTHING|UPDATE)\b"
    r"|\bON\s+DUPLICATE\s+KEY\s+UPDATE\b"
    r"|\bINSERT\s+OR\s+(?:IGNORE|REPLACE)\b",
    re.IGNORECASE,
)

_IDENTIFIER = r'(?:[A-Za-z_][\w$]*|"(?:""|[^"])+")'
_INSERT_SELECT_TARGET = re.compile(
    rf"\bINSERT\s+INTO\s+(?P<target>{_IDENTIFIER}(?:\s*\.\s*{_IDENTIFIER})?)[\s\S]*?\bSELECT\b",
    re.IGNORECASE,
)

_REPLAY_CONTRACT_NAME = re.compile(
    r"(?:^|_)(?:enqueue|ensure|record_once|"
    r"get_or_create|create_if_absent|insert_if_absent)(?:_|$)",
    re.IGNORECASE,
)

_SQL_CALL = frozenset({"execute", "executemany", "prepare"})
_SQL_KEYWORD = frozenset({"query", "sql", "statement", "stmt"})
_DYNAMIC_POLICY_NAME = re.compile(
    r"(?:on_conflict(?:_sql|_clause)?|duplicate_(?:policy|clause)|replay_policy|upsert_clause)",
    re.IGNORECASE,
)


@final
class StoreInsertRequiresOnConflict(Rule):
    id: str = "replay-contract-insert-requires-duplicate-policy"
    code: str = "SARJ018"
    documentation = RuleDocumentation(
        summary="A literal INSERT in a replay-named store callable must declare duplicate behavior.",
        rationale=(
            "A store callable named ensure, enqueue, record_once, get_or_create, create_if_absent, or "
            "insert_if_absent promises that a retry will not create duplicate state."
        ),
        remediation=(
            "Add an explicit conflict action or same-target NOT EXISTS guard. If duplicate failure or "
            "append-only insertion is deliberate, add an exact SARJ018 suppression explaining it; rename only "
            "when the callable does not promise replay safety."
        ),
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.NONE,
        aliases=("store-insert-requires-on-conflict", "replay-named-store-insert-requires-duplicate-policy"),
        limitations=(
            (
                "Only SQL literals passed directly, or through a stable local binding, to execute-like calls in "
                "explicitly replay-named callables in recognized store modules are analyzed."
            ),
            "Dynamic SQL policy composition and ordinary create, seed, migration, schedule, and upsert methods are excluded.",
        ),
        examples=(
            RuleExample(
                example_id="insert-without-duplicate-policy",
                title="Replay-named store callable omits duplicate behavior",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/task_store.py",
                        "def ensure_task(cursor, task_id):\n"
                        '    cursor.execute("INSERT INTO task (id) VALUES (%s)", (task_id,))\n',
                    ),
                ),
                focus_path=PurePosixPath("app/task_store.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="insert-with-duplicate-policy",
                title="Replay-named store callable declares duplicate behavior",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/task_store.py",
                        "def ensure_task(cursor, task_id):\n"
                        '    cursor.execute("INSERT INTO task (id) VALUES (%s) ON CONFLICT DO NOTHING", (task_id,))\n',
                    ),
                ),
                focus_path=PurePosixPath("app/task_store.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if not is_store_module(path) or is_generated(path, source):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []

        diags: list[Diagnostic] = []
        parents = {id(child): parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
        consumed: set[int] = set()
        for node in nodes(tree, ast.Constant, ast.BinOp, ast.JoinedStr):
            if id(node) in consumed:
                continue
            text = _sql_template_value(node)
            if text is None:
                continue
            consumed.update(id(sub) for sub in walk(node))

            sql = strip_sql_noise(text, mask_dollar_quotes=False, mask_double_quotes=False)
            owner = _enclosing_callable(tree, node)
            if (
                owner is None
                or _REPLAY_CONTRACT_NAME.search(owner.name) is None
                or not _is_executable_sql(node, owner, parents)
                or _has_dynamic_duplicate_policy(node, owner, parents)
            ):
                continue
            if any(_requires_duplicate_policy(statement) for statement in sql.split(";")):
                diags.append(
                    Diagnostic(
                        path=path,
                        line=node.lineno,
                        col=node.col_offset + 1,
                        code=self.code,
                        message=(
                            "Replay-named store INSERT has no explicit duplicate policy; add a conflict action "
                            "or same-target NOT EXISTS guard. If insert-only behavior is deliberate, add an "
                            "exact SARJ018 suppression explaining it."
                        ),
                        severity=Severity.WARNING,
                    )
                )
        diags.sort(key=lambda d: (d.line, d.col))
        return diags


def _enclosing_callable(
    tree: ast.AST,
    node: ast.expr,
) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    owners = [
        function
        for function in nodes(tree, ast.FunctionDef, ast.AsyncFunctionDef)
        if function.lineno <= node.lineno <= (function.end_lineno or function.lineno)
    ]
    return min(owners, key=_source_span) if owners else None


def _source_span(function: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    end_lineno = function.end_lineno
    return (end_lineno if end_lineno is not None else function.lineno) - function.lineno


def _is_executable_sql(
    node: ast.expr,
    owner: ast.FunctionDef | ast.AsyncFunctionDef,
    parents: dict[int, ast.AST],
) -> bool:
    current: ast.AST = node
    while current is not owner:
        parent = parents.get(id(current))
        if parent is None:
            return False
        if isinstance(parent, (ast.Assign, ast.AnnAssign, ast.NamedExpr)):
            targets = parent.targets if isinstance(parent, ast.Assign) else [parent.target]
            names = {target.id for target in targets if isinstance(target, ast.Name)}
            return bool(names) and _binding_reaches_execution(owner, parent, names)
        if isinstance(parent, ast.Call):
            name = _call_name(parent.func)
            is_query_argument = (bool(parent.args) and current is parent.args[0]) or (
                isinstance(current, ast.keyword) and current in parent.keywords and current.arg in _SQL_KEYWORD
            )
            if is_query_argument and name is not None and name.lower() in _SQL_CALL:
                return True
        current = parent
    return False


def _call_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _sql_template_value(node: ast.expr) -> str | None:
    value = sql_string_value(node, interpolation_placeholder="__dynamic__")
    if value is not None:
        return value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _sql_template_value(node.left) or "__dynamic__"
        right = _sql_template_value(node.right) or "__dynamic__"
        return left + right
    return None


def _binding_reaches_execution(
    owner: ast.FunctionDef | ast.AsyncFunctionDef,
    assignment: ast.Assign | ast.AnnAssign | ast.NamedExpr,
    names: set[str],
) -> bool:
    for call in nodes(owner, ast.Call):
        if (
            call.lineno <= assignment.lineno
            or (_call_name(call.func) or "").lower() not in _SQL_CALL
            or _enclosing_callable(owner, call) is not owner
        ):
            continue
        arguments = [*call.args, *(keyword.value for keyword in call.keywords if keyword.arg in _SQL_KEYWORD)]
        used = {argument.id for argument in arguments if isinstance(argument, ast.Name)} & names
        if not used:
            continue
        if not any(
            isinstance(candidate, ast.Name)
            and isinstance(candidate.ctx, ast.Store)
            and candidate.id in used
            and assignment.lineno < candidate.lineno < call.lineno
            for candidate in ast.walk(owner)
        ):
            return True
    return False


def _has_dynamic_duplicate_policy(
    node: ast.expr,
    owner: ast.FunctionDef | ast.AsyncFunctionDef,
    parents: dict[int, ast.AST],
) -> bool:
    if isinstance(node, ast.JoinedStr):
        prefix = ""
        for part in node.values:
            if isinstance(part, ast.Constant) and isinstance(part.value, str):
                prefix += part.value
                continue
            if (
                isinstance(part, ast.FormattedValue)
                and prefix.rstrip().endswith(")")
                and _DYNAMIC_POLICY_NAME.fullmatch(ast.unparse(part.value)) is not None
            ):
                return True
            prefix += "__dynamic__"
        return False
    current: ast.AST = node
    while current is not owner:
        parent = parents.get(id(current))
        if parent is None:
            break
        if isinstance(parent, ast.Call) and isinstance(parent.func, ast.Attribute) and parent.func.attr == "format":
            if isinstance(parent.func.value, ast.Constant) and isinstance(parent.func.value.value, str):
                template = parent.func.value.value
                return any(
                    keyword.arg is not None
                    and _DYNAMIC_POLICY_NAME.fullmatch(keyword.arg) is not None
                    and (marker := "{" + keyword.arg + "}") in template
                    and template.split(marker, 1)[0].rstrip().endswith(")")
                    for keyword in parent.keywords
                )
            return False
        current = parent
    return False


def _requires_duplicate_policy(statement: str) -> bool:
    return (
        _INSERT_WRITE.search(statement) is not None
        and _CONFLICT_HANDLED.search(statement) is None
        and not _select_filters_existing_target(statement)
    )


def _select_filters_existing_target(statement: str) -> bool:
    match = _INSERT_SELECT_TARGET.search(statement)
    if match is None:
        return False
    target = re.sub(r"\s+", "", match.group("target")).split(".")[-1].strip('"').replace('""', '"')
    guard = re.compile(
        rf"\bWHERE\s+NOT\s+EXISTS\s*\([\s\S]*?\bFROM\s+"
        rf"(?:{_IDENTIFIER}\s*\.\s*)?(?:{re.escape(target)}\b|\"{re.escape(target)}\"(?=\s|\)|$))",
        re.IGNORECASE,
    )
    return guard.search(statement, match.end()) is not None
