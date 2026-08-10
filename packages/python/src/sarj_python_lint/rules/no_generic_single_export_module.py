"""SARJ022 — Reject a junk-drawer module stem with a single public definition.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_no_generic_single_export_module.py
"""

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
    parse_or_none,
)
from sarj_python_lint.rules._paths import is_generated


if TYPE_CHECKING:
    from pathlib import Path


# Generic module stems that describe no responsibility.
_JUNK_DRAWER_STEMS = frozenset(
    {
        "common",
        "helper",
        "helpers",
        "misc",
        "shared",
        "stuff",
        "util",
        "utils",
    }
)


@final
class NoGenericSingleExportModule(Rule):
    id: str = "no-generic-single-export-module"
    code: str = "SARJ022"
    documentation = RuleDocumentation(
        summary="A generic module name should not conceal a single-definition responsibility.",
        rationale="Names such as `utils` and `helpers` hide a module's responsibility and encourage unrelated additions.",
        remediation="Choose a responsibility-bearing module name or colocate the definition with its domain.",
        category=RuleCategory.ARCHITECTURE,
        autofix=AutofixPolicy.NONE,
        aliases=("single-public-export",),
        limitations=(
            "Only known junk-drawer stems with exactly one top-level public class or function are reported.",
            "An absent `__all__`, or one static entry matching that definition, must prove the public surface.",
            "Generated and test paths are excluded; semantic role and framework filenames are outside the stem set.",
        ),
        examples=(
            RuleExample(
                example_id="generic-single-export-module",
                title="Generic module contains one public definition",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.python("utils.py", "def snake_case_text(value: str) -> str: ...\n"),),
                focus_path=PurePosixPath("utils.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="specific-single-export-module",
                title="Specific module contains one public definition",
                outcome=ExampleOutcome.NO_MATCH,
                files=(ExampleFile.python("text_case.py", "def snake_case_text(value: str) -> str: ...\n"),),
                focus_path=PurePosixPath("text_case.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if path.suffix != ".py":
            return []
        if is_generated(path, source):
            return []
        if _is_skipped_path(path):
            return []
        if path.stem not in _JUNK_DRAWER_STEMS:
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []

        public_defs = [
            node
            for node in tree.body
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_")
        ]
        if len(public_defs) != 1:
            return []

        primary = public_defs[0]
        if _has_additional_public_export(tree, primary.name):
            return []

        return [
            Diagnostic(
                path=path,
                line=primary.lineno,
                col=primary.col_offset + 1,
                code=self.code,
                message=(
                    f"module stem `{path.stem}` is a generic junk-drawer name while its only "
                    f"top-level public definition is `{primary.name}`; choose a responsibility-bearing "
                    "module name or colocate the definition with its domain."
                ),
            )
        ]


def _has_additional_public_export(tree: ast.Module, primary_name: str) -> bool:
    """Report whether a definition is not the module's only public export."""
    if not _dunder_all_matches_primary(tree, primary_name):
        return True
    targets: list[ast.expr] = []
    for stmt in tree.body:
        match stmt:
            case ast.TypeAlias(name=ast.Name(id=name)) if not name.startswith("_"):
                return True
            case ast.Assign(targets=assigned):
                targets.extend(assigned)
            case ast.AnnAssign(target=target):
                if (
                    isinstance(target, ast.Name)
                    and not target.id.startswith("_")
                    and _annotation_name(stmt.annotation) == "TypeAlias"
                ):
                    return True
                targets.append(target)
            case _:
                pass
    assigned_names = (node for target in targets for node in ast.walk(target) if isinstance(node, ast.Name))
    return any(
        not name.id.startswith("_") and name.id == name.id.upper() and any(c.isalpha() for c in name.id)
        for name in assigned_names
    )


def _dunder_all_matches_primary(tree: ast.Module, primary_name: str) -> bool:
    """Accept no declared surface, or one fully static surface naming only the definition."""
    owners = [statement for statement in tree.body if _mentions_dunder_all(statement)]
    if not owners:
        return True
    if len(owners) != 1:
        return False
    declaration = owners[0]
    value: ast.expr | None
    match declaration:
        case ast.Assign(targets=[ast.Name(id="__all__")]) | ast.AnnAssign(target=ast.Name(id="__all__"), simple=1):
            value = declaration.value
        case _:
            return False
    if not isinstance(value, (ast.List, ast.Tuple)) or len(value.elts) != 1:
        return False
    (entry,) = value.elts
    return isinstance(entry, ast.Constant) and entry.value == primary_name


def _mentions_dunder_all(node: ast.AST) -> bool:
    """Conservatively detect explicit, dynamic, or string-stored export surfaces."""
    for child in ast.walk(node):
        match child:
            case ast.Name(id="__all__"):
                return True
            case ast.alias() if (child.asname or child.name).split(".")[0] == "__all__":
                return True
            case ast.FunctionDef() | ast.AsyncFunctionDef() | ast.ClassDef() if child.name == "__all__":
                return True
            case ast.arg(arg="__all__") | ast.ExceptHandler(name="__all__"):
                return True
            case ast.MatchAs() | ast.MatchStar() if child.name == "__all__":
                return True
            case ast.MatchMapping(rest="__all__"):
                return True
            case ast.Global() | ast.Nonlocal() if "__all__" in child.names:
                return True
            case _:
                pass
    return False


def _annotation_name(node: ast.expr) -> str:
    """Return the final component of an annotation name."""
    match node:
        case ast.Name(id=name) | ast.Attribute(attr=name):
            return name
        case _:
            return ""


def _is_skipped_path(path: Path) -> bool:
    return "tests" in path.parts
