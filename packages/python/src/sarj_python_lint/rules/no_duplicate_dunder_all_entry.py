from __future__ import annotations

import ast
from pathlib import PurePosixPath
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
from sarj_python_lint.rules._paths import is_generated


if TYPE_CHECKING:
    from pathlib import Path


class _LiteralElement(NamedTuple):
    value: str
    line: int
    column: int


_INSERT_ARGUMENT_COUNT = 2


@final
class NoDuplicateDunderAllEntry(Rule):
    id = "no-duplicate-dunder-all-entry"
    code = "SARJ098"
    documentation = RuleDocumentation(
        summary="static module `__all__` declarations should list each exported name once",
        rationale=(
            "Duplicate exports add noise to a module's public contract and commonly reveal copy-paste mistakes in "
            "generated or maintained facade lists."
        ),
        remediation="Remove each later duplicate while preserving the first declaration of the exported name.",
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "One fully static module-level list or tuple plus literal append, extend, and insert growth is analyzed.",
            "Generated, dynamically reassigned, and non-Python declarations are excluded.",
        ),
        examples=(
            RuleExample(
                example_id="duplicate-package-export",
                title="Duplicate name in a package export list",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "diagnostics/__init__.py",
                        '__all__ = ["Diagnostic", "AnalysisReport", "Diagnostic"]\n',
                    ),
                ),
                focus_path=PurePosixPath("diagnostics/__init__.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="unique-package-exports",
                title="Unique names in a package export list",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "diagnostics/__init__.py",
                        '__all__ = ["Diagnostic", "AnalysisReport"]\n',
                    ),
                ),
                focus_path=PurePosixPath("diagnostics/__init__.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if path.suffix != ".py" or is_generated(path, source):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []

        declarations = [statement for statement in tree.body if _assigns_dunder_all(statement)]
        if len(declarations) != 1:
            return []
        declaration = declarations[0]
        if _has_other_dunder_all_rebindings(tree, declaration):
            return []
        elements = _literal_elements(declaration)
        if elements is None:
            return []
        growth = _literal_growth_elements(tree, declaration)
        if growth is None:
            return []
        elements.extend(growth)

        first_lines: dict[str, int] = {}
        findings: list[Diagnostic] = []
        for name, line, col in elements:
            first_line = first_lines.get(name)
            if first_line is None:
                first_lines[name] = line
                continue
            findings.append(
                Diagnostic(
                    path=path,
                    line=line,
                    col=col,
                    code=self.code,
                    message=(
                        f"`{name}` duplicates an earlier `__all__` entry on line {first_line}; remove the later entry."
                    ),
                )
            )
        return findings


def _assigns_dunder_all(statement: ast.AST) -> bool:
    match statement:
        case ast.Assign(targets=targets):
            return any(isinstance(target, ast.Name) and target.id == "__all__" for target in targets)
        case ast.AnnAssign(target=ast.Name(id="__all__")) | ast.AugAssign(target=ast.Name(id="__all__")):
            return True
        case _:
            return False


def _has_other_dunder_all_rebindings(tree: ast.Module, declaration: ast.stmt) -> bool:
    for statement in tree.body:
        if statement is declaration:
            continue
        if _is_supported_dunder_all_growth(statement):
            continue
        if _mentions_dunder_all(statement):
            return True
    return False


def _is_supported_dunder_all_growth(statement: ast.stmt) -> bool:
    match statement:
        case ast.Expr(
            value=ast.Call(func=ast.Attribute(value=ast.Name(id="__all__"), attr="append" | "extend" | "insert"))
        ):
            return True
        case _:
            return False


def _mentions_dunder_all(node: ast.AST) -> bool:
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


def _literal_elements(statement: ast.stmt) -> list[_LiteralElement] | None:
    value: ast.expr | None
    match statement:
        case ast.Assign(targets=[ast.Name(id="__all__")]) | ast.AnnAssign(target=ast.Name(id="__all__"), simple=1):
            value = statement.value
        case _:
            return None
    if not isinstance(value, (ast.List, ast.Tuple)):
        return None
    elements: list[_LiteralElement] = []
    for element in value.elts:
        if not isinstance(element, ast.Constant) or not isinstance(element.value, str):
            return None
        elements.append(_LiteralElement(element.value, element.lineno, element.col_offset + 1))
    return elements


def _literal_growth_elements(tree: ast.Module, declaration: ast.stmt) -> list[_LiteralElement] | None:
    elements: list[_LiteralElement] = []
    for statement in tree.body:
        if statement is declaration or not _is_supported_dunder_all_growth(statement):
            continue
        if not isinstance(statement, ast.Expr):
            return None
        call = statement.value
        if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Attribute):
            return None
        if (element := _single_literal_growth(call)) is not None:
            elements.append(element)
            continue
        match call.func.attr, call.args, call.keywords:
            case "extend", [ast.List() | ast.Tuple() as values], []:
                extended = _sequence_literal_elements(values)
                if extended is None:
                    return None
                elements.extend(extended)
            case _:
                return None
    return elements


def _single_literal_growth(call: ast.Call) -> _LiteralElement | None:
    if call.keywords or not isinstance(call.func, ast.Attribute):
        return None
    if call.func.attr == "append" and len(call.args) == 1:
        candidate = call.args[0]
    elif call.func.attr == "insert" and len(call.args) == _INSERT_ARGUMENT_COUNT:
        candidate = call.args[1]
    else:
        return None
    if not isinstance(candidate, ast.Constant) or not isinstance(candidate.value, str):
        return None
    return _LiteralElement(candidate.value, candidate.lineno, candidate.col_offset + 1)


def _sequence_literal_elements(node: ast.List | ast.Tuple) -> list[_LiteralElement] | None:
    if not all(isinstance(element, ast.Constant) and isinstance(element.value, str) for element in node.elts):
        return None
    return [
        _LiteralElement(element.value, element.lineno, element.col_offset + 1)
        for element in node.elts
        if isinstance(element, ast.Constant) and isinstance(element.value, str)
    ]
