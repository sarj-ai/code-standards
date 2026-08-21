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
from sarj_python_lint.rules._project_index import ProjectIndexSet


if TYPE_CHECKING:
    from pathlib import Path


@final
class PreserveEnumTypes(ProjectRule):
    id = "preserve-enum-types"
    code = "SARJ417"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="Preserve a narrowed enum instead of converting it to an unconstrained string.",
        rationale="String conversion weakens downstream validation and generated schemas while hiding the loss from the type checker.",
        remediation="Carry the enum annotation and value through the receiving model or exception boundary.",
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "The initial rule requires an unambiguous class pattern, annotated enum field, and direct `str(subject.field)` call.",
            "Dynamic imports, star imports, and unresolved external classes fail open.",
        ),
        examples=(
            RuleExample(
                example_id="matched-enum-erased",
                title="A matched result enum is converted to string",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/__init__.py",
                        "from enum import StrEnum\nclass Status(StrEnum):\n    READY = 'ready'\nclass Result:\n    status: Status | None\ndef render(result):\n    match result:\n        case Result():\n            return str(result.status)\n",
                    ),
                ),
                focus_path=PurePosixPath("app/__init__.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="matched-enum-preserved",
                title="A matched result enum remains typed",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/__init__.py",
                        "from enum import StrEnum\nclass Status(StrEnum):\n    READY = 'ready'\nclass Result:\n    status: Status | None\ndef render(result):\n    match result:\n        case Result():\n            return result.status\n",
                    ),
                ),
                focus_path=PurePosixPath("app/__init__.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if "match " not in source or "str(" not in source:
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        indexes = self._project_indexes or ProjectIndexSet.single(path, source)
        unit = indexes.unit(path)
        if unit is None:
            return []
        diagnostics: list[Diagnostic] = []
        for match in (node for node in ast.walk(tree) if isinstance(node, ast.Match)):
            if not isinstance(match.subject, ast.Name):
                continue
            subject = match.subject.id
            for case in match.cases:
                if not isinstance(case.pattern, ast.MatchClass):
                    continue
                summary = indexes.class_for(unit, case.pattern.cls)
                if summary is None:
                    continue
                owner_unit = indexes.source_unit(summary.symbol.module)
                if owner_unit is None:
                    continue
                enum_fields = {
                    name
                    for name, annotation in summary.fields.items()
                    if indexes.annotation_contains_enum(owner_unit, annotation)
                }
                if not enum_fields:
                    continue
                for statement in case.body:
                    for call in (node for node in ast.walk(statement) if isinstance(node, ast.Call)):
                        if not _erases_field(call, subject, enum_fields):
                            continue
                        diagnostics.append(
                            Diagnostic(
                                path=path,
                                line=call.lineno,
                                col=call.col_offset + 1,
                                code=self.code,
                                severity=Severity.ERROR,
                                message="matched enum is converted to unconstrained `str`; preserve its enum type through the receiving boundary",
                            )
                        )
        return sorted(diagnostics, key=lambda item: (item.line, item.col))


def _erases_field(call: ast.Call, subject: str, fields: set[str]) -> bool:
    return (
        isinstance(call.func, ast.Name)
        and call.func.id == "str"
        and len(call.args) == 1
        and isinstance(call.args[0], ast.Attribute)
        and isinstance(call.args[0].value, ast.Name)
        and call.args[0].value.id == subject
        and call.args[0].attr in fields
    )
