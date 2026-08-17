"""SARJ416 preserves project-declared nominal identifier roles.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_preserve_declared_nominal_id.py
"""

from __future__ import annotations

import ast
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, ClassVar, final, override

from sarj_python_lint.rule_base import (
    AutofixPolicy,
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    ProjectRule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
    Severity,
    parse_or_none,
)
from sarj_python_lint.rules._paths import is_generated, is_test_path
from sarj_python_lint.rules._project_index import ProjectIndexSet


if TYPE_CHECKING:
    from pathlib import Path


@final
class PreserveDeclaredNominalId(ProjectRule):
    id = "preserve-declared-nominal-id"
    code = "SARJ416"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="Keep project-declared nominal identifier types in test overrides.",
        rationale="A fake override that widens a declared ID role back to its primitive carrier defeats type-checker swap protection.",
        remediation="Import and propagate the matching project `NewType` instead of annotating the role with its carrier.",
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "The field name must map exactly and unambiguously to a first-party NewType declaration.",
            "Only explicit override methods in test files are inspected; production boundary discovery remains SARJ093's responsibility.",
        ),
        examples=(
            RuleExample(
                example_id="declared-id-erased",
                title="A declared nominal ID is widened to string",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "tests/fake.py",
                        "from typing import NewType, override\nSipTrunkId = NewType('SipTrunkId', str)\nclass Fake:\n    @override\n    def route(self, sip_trunk_id: str): ...\n",
                    ),
                ),
                focus_path=PurePosixPath("tests/fake.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="declared-id-preserved",
                title="A declared nominal ID remains nominal",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "tests/fake.py",
                        "from typing import NewType, override\nSipTrunkId = NewType('SipTrunkId', str)\nclass Fake:\n    @override\n    def route(self, sip_trunk_id: SipTrunkId): ...\n",
                    ),
                ),
                focus_path=PurePosixPath("tests/fake.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if is_generated(path, source) or "migrations" in {part.lower() for part in path.parts}:
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        indexes = self._project_indexes or ProjectIndexSet.single(path, source)
        if not is_test_path(path):
            return []
        diagnostics: list[Diagnostic] = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if not any(_tail(item) == "override" for item in node.decorator_list):
                    continue
                for argument in [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]:
                    diagnostics.extend(_diagnose(path, argument.arg, argument.annotation, indexes, self.code))
        return sorted(diagnostics, key=lambda item: (item.line, item.col))


def _diagnose(
    path: Path,
    name: str,
    annotation: ast.expr | None,
    indexes: ProjectIndexSet,
    code: str,
) -> list[Diagnostic]:
    nominal = indexes.nominal_for_field(name)
    if nominal is None or annotation is None or not _raw_primitive(annotation):
        return []
    return [
        Diagnostic(
            path=path,
            line=annotation.lineno,
            col=annotation.col_offset + 1,
            code=code,
            severity=Severity.WARNING,
            message=f"`{name}` erases declared nominal `{nominal.name}`; propagate the nominal ID type through this boundary",
        )
    ]


def _raw_primitive(node: ast.expr | None) -> bool:
    match node:
        case ast.Name(id=name):
            return name in {"UUID", "int", "str"}
        case ast.BinOp(left=left, op=ast.BitOr(), right=right):
            return _raw_primitive(left) or _raw_primitive(right)
        case ast.Subscript(slice=member):
            return _raw_primitive(member)
        case ast.Tuple(elts=members):
            return any(_raw_primitive(item) for item in members)
        case _:
            return False


def _tail(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""
