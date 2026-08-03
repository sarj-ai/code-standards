"""SARJ081 — Prefer assignment expression (`:=`) for regex match assignments immediately preceding an `if` check

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_prefer_walrus_regex_match.py
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, is_suppressed, parse_or_none
from sarj_python_lint.rules._ast_index import walk


if TYPE_CHECKING:
    from pathlib import Path


def _is_regex_call(node: ast.AST) -> bool:
    """Check if node is a call to re.search/match/fullmatch or pattern.search/match."""
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Attribute):
        if func.attr not in {"search", "match", "fullmatch", "finditer"}:
            return False
        if isinstance(func.value, ast.Name) and func.value.id in {"re", "regex", "pattern", "compiled_pattern"}:
            return True
        if isinstance(func.value, ast.Attribute) and func.value.attr in {"pattern", "regex", "_pattern"}:
            return True
    return False


def _is_simple_truthy_test(test_node: ast.AST, var_name: str) -> bool:
    """Check if test_node is `if var_name:` or `if var_name is not None:`."""
    if isinstance(test_node, ast.Name) and test_node.id == var_name:
        return True
    if (
        isinstance(test_node, ast.Compare)
        and isinstance(test_node.left, ast.Name)
        and test_node.left.id == var_name
        and len(test_node.ops) == 1
        and isinstance(test_node.ops[0], ast.IsNot)
    ):
        right = test_node.comparators[0]
        if isinstance(right, ast.Constant) and right.value is None:
            return True
    return False


def _is_name_used_after(stmts: list[ast.stmt], start_idx: int, name: str) -> bool:
    class UsageVisitor(ast.NodeVisitor):
        used: bool = False

        def visit_Name(self, node: ast.Name) -> None:
            if node.id == name:
                self.used = True
            self.generic_visit(node)

    visitor = UsageVisitor()
    for st in stmts[start_idx:]:
        visitor.visit(st)
        if visitor.used:
            return True
    return False


class PreferWalrusRegexMatch(Rule):
    id: str = "prefer-walrus-regex-match"
    code: str = "SARJ081"
    description: str = (
        "regex match assignment immediately followed by an `if` check — combine into `if (match := re.search(...)):`."
    )

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        tree = parse_or_none(path, source)
        if tree is None:
            return []

        source_lines = source.splitlines()
        diags: list[Diagnostic] = []

        for node in walk(tree):
            raw_body = getattr(node, "body", None)
            if not isinstance(raw_body, list):
                continue
            body: list[ast.stmt] = [st for st in raw_body if isinstance(st, ast.stmt)]  # pyright: ignore[reportUnknownVariableType]

            for i in range(len(body) - 1):
                s1 = body[i]
                s2 = body[i + 1]

                if not (isinstance(s1, ast.Assign) and len(s1.targets) == 1 and isinstance(s1.targets[0], ast.Name)):
                    continue
                var_name = s1.targets[0].id

                if not _is_regex_call(s1.value) or not isinstance(s2, ast.If):
                    continue

                if not _is_simple_truthy_test(s2.test, var_name) or _is_name_used_after(body, i + 2, var_name):
                    continue

                if not is_suppressed(source_lines, s1.lineno, self.code):
                    diags.append(
                        Diagnostic(
                            path=path,
                            line=s1.lineno,
                            col=s1.col_offset + 1,
                            code=self.code,
                            message=(
                                f"Regex match pre-assignment `{var_name} = ...` before `if` — "
                                f"combine into `if ({var_name} := ...):`."
                            ),
                        )
                    )

        return sorted(diags, key=lambda d: (d.line, d.col))
