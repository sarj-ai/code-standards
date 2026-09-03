from __future__ import annotations

import ast
from pathlib import PurePosixPath
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
from sarj_python_lint.rules._prose_budget import groups


if TYPE_CHECKING:
    from pathlib import Path


@final
class NoTypedDocSections(Rule):
    id = "no-docstring-type-restatement"
    code = "SARJ092"
    documentation = RuleDocumentation(
        summary="A docstring type label repeats an annotation from the fully typed signature.",
        rationale=(
            "A repeated type spelling can drift from the annotation and obscures the behavioral contract that only prose "
            "can express."
        ),
        remediation=(
            "Remove only the redundant type label. Keep behavioral meaning, units, defaults, constraints, and raised-error "
            "conditions in the docstring."
        ),
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        aliases=("no-typed-doc-sections",),
        limitations=(
            "Only fully typed functions and Google-like colon-headed argument, return, and yield sections are checked.",
            "A documented label must parse as a Python type expression and match the corresponding annotation.",
            "Generated files, runtime-consumed prompt, CLI, and route docstrings, properties, abstract methods, overloads, protocol methods, and partially typed signatures are excluded.",
            "NumPy underlined sections and Sphinx type fields intentionally remain with their selected documentation convention.",
        ),
        examples=(
            RuleExample(
                example_id="parameter-type-restatement",
                title="Remove only the repeated type label",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app.py",
                        'def decode(payload: str) -> dict[str, object]:\n    """Decode the payload.\n\n    Args:\n        payload (str): UTF-8 JSON; duplicate keys are rejected.\n    """\n    return {}\n',
                    ),
                ),
                focus_path=PurePosixPath("app.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="behavioral-parameter-contract",
                title="Argument section records behavior",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app.py",
                        'def decode(payload: str) -> dict[str, object]:\n    """Decode the payload.\n\n    Args:\n        payload: UTF-8 JSON; duplicate keys are rejected.\n    """\n    return {}\n',
                    ),
                ),
                focus_path=PurePosixPath("app.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        excluded_lines = _public_contract_docstring_lines(path, source)
        return [
            Diagnostic(
                path,
                group.typed_restatements[0],
                group.col,
                self.code,
                (
                    f"This docstring repeats {len(group.typed_restatements)} type label(s) already present in the "
                    "signature; remove only the type labels and keep the behavioral descriptions."
                ),
                severity=Severity.WARNING,
                column_encoding=group.column_encoding,
            )
            for group in groups(path, source)
            if group.typed_restatements and group.line not in excluded_lines
        ]


_PUBLIC_CONTRACT_DECORATORS = frozenset({"abstractmethod", "cached_property", "overload", "property"})
_PUBLIC_CONTRACT_BASES = frozenset({"Protocol"})


def _public_contract_docstring_lines(path: Path, source: str) -> frozenset[int]:
    tree = parse_or_none(path, source)
    if tree is None:
        return frozenset()
    parents = {id(child): parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
    excluded: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or not node.body:
            continue
        first = node.body[0]
        if not (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)):
            continue
        decorators = {_terminal_name(item.func if isinstance(item, ast.Call) else item) for item in node.decorator_list}
        owner = parents.get(id(node))
        protocol_method = isinstance(owner, ast.ClassDef) and any(
            _terminal_name(base) in _PUBLIC_CONTRACT_BASES for base in owner.bases
        )
        if decorators & _PUBLIC_CONTRACT_DECORATORS or protocol_method:
            excluded.add(first.lineno)
    return frozenset(excluded)


def _terminal_name(node: ast.expr) -> str | None:
    match node:
        case ast.Name(id=name) | ast.Attribute(attr=name):
            return name
        case _:
            return None
