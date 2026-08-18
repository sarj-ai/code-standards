from __future__ import annotations

import ast
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, ClassVar, override

from sarj_python_lint.rule_base import (
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    Rule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
    parse_or_none,
)
from sarj_python_lint.rules._ast_index import nodes
from sarj_python_lint.rules._paths import is_test_path


if TYPE_CHECKING:
    from pathlib import Path


_MSG = (
    "collections.namedtuple is untyped and positionally constructed — prefer "
    "typing.NamedTuple, or a frozen pydantic BaseModel for boundary values."
)


class PreferStructOverNamedtuple(Rule):
    id: str = "prefer-struct-over-namedtuple"
    code: str = "SARJ015"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="`collections.namedtuple` creates an untyped, positionally constructed record.",
        rationale="Typed record declarations expose field types and make construction and review less error-prone.",
        remediation="Declare a `typing.NamedTuple` class or use a frozen pydantic model for boundary values.",
        category=RuleCategory.MAINTAINABILITY,
        limitations=(
            "Only imports from `collections` and qualified calls through `collections` bindings are reported.",
            "Tests, `typing.NamedTuple`, unrelated attributes, and unbound bare calls are excluded.",
        ),
        examples=(
            RuleExample(
                example_id="collections-namedtuple",
                title="Functional untyped namedtuple",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "models.py",
                        "import collections\n\nRow = collections.namedtuple('Row', ['id', 'name'])\n",
                    ),
                ),
                focus_path=PurePosixPath("models.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="typed-named-tuple",
                title="Typed NamedTuple declaration",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "models.py",
                        "from typing import NamedTuple\n\nclass Row(NamedTuple):\n    id: int\n    name: str\n",
                    ),
                ),
                focus_path=PurePosixPath("models.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description: str = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if is_test_path(path):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        collections_names: set[str] = set()
        candidates: list[tuple[ast.AST, str | None]] = []
        for node in nodes(tree, ast.ImportFrom, ast.Import, ast.Call):
            if isinstance(node, ast.ImportFrom):
                if node.module == "collections":
                    candidates.extend((node, None) for alias in node.names if alias.name == "namedtuple")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "collections" or (alias.name.startswith("collections.") and alias.asname is None):
                        collections_names.add(alias.asname or "collections")
            elif (
                isinstance(node.func, ast.Attribute)
                and node.func.attr == "namedtuple"
                and isinstance(node.func.value, ast.Name)
            ):
                candidates.append((node, node.func.value.id))
        shadowed = _shadowed_names(tree, collections_names)
        return [
            self._diag(path, node)
            for node, name in candidates
            if name is None or (name in collections_names and name not in shadowed)
        ]

    def _diag(self, path: Path, node: ast.AST) -> Diagnostic:
        return Diagnostic(
            path=path,
            line=getattr(node, "lineno", 1),
            col=getattr(node, "col_offset", 0) + 1,
            code=self.code,
            message=_MSG,
        )


def _shadowed_names(tree: ast.Module, imported: set[str]) -> set[str]:
    shadowed: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store) and node.id in imported:
            shadowed.add(node.id)
        elif isinstance(node, ast.arg) and node.arg in imported:
            shadowed.add(node.arg)
        elif (
            isinstance(
                node,
                (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.ExceptHandler, ast.MatchAs, ast.MatchStar),
            )
            and node.name in imported
        ):
            shadowed.add(node.name)
    return shadowed
