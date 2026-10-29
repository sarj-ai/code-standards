from __future__ import annotations

import ast
from dataclasses import dataclass
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
    is_suppressed,
)


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext


_MIN_ATTRIBUTES = 2


@dataclass(frozen=True)
class _AttributeAlias:
    target: str
    receiver: str


@final
class NoRedundantAttributeUnpacking(Rule):
    id = "no-redundant-attribute-unpacking"
    code = "SARJ554"
    documentation = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Use an aggregate's named attributes instead of repeating their names in tuple aliases.",
        rationale="A tuple assignment that repeats every attribute name adds parallel bindings without describing a transformation or a new concept.",
        remediation="Read the aggregate's named attributes directly. Retain intentional value snapshots with an explained local suppression.",
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Reports unconditional tuple/list assignments directly in function bodies only when every element aliases an identically named attribute of the same simple receiver and no target rebinds that receiver.",
            "Conditional/loop/context-manager aliases can normalize branch results or preserve resource scopes and are excluded. Renamed attributes, mixed receivers, nested unpacking, calls, module/class bindings, generated source and malformed source are excluded.",
            "This is an explicitly requested warning-level style preference. A retained snapshot can be meaningful when the aggregate changes; no autofix or claim of behavioral equivalence is made.",
        ),
        examples=(
            RuleExample(
                example_id="repeated-attribute-names",
                title="Keep the named result aggregate",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_save.py",
                        "def test_save(seeded):\n    scenario, current = seeded.scenario, seeded.current\n    assert scenario.id == current.id\n",
                    ),
                ),
                focus_path=PurePosixPath("tests/test_save.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="direct-attribute-use",
                title="Read names on their owner",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_save.py",
                        "def test_save(seeded):\n    assert seeded.scenario.id == seeded.current.id\n",
                    ),
                ),
                focus_path=PurePosixPath("tests/test_save.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if context.tree is None or context.generated:
            return []
        findings: list[Diagnostic] = []
        for function in context.nodes(ast.FunctionDef, ast.AsyncFunctionDef):
            for node in function.body:
                if (
                    not isinstance(node, ast.Assign)
                    or not _redundant_unpacking(node)
                    or is_suppressed(context.source_lines, node.lineno, self.code)
                ):
                    continue
                findings.append(
                    Diagnostic(
                        context.path,
                        node.lineno,
                        node.col_offset + 1,
                        self.code,
                        "Use these named attributes on their aggregate directly; retain intentional snapshots with an explained exception.",
                        severity=Severity.WARNING,
                    )
                )
        return list({(finding.line, finding.col): finding for finding in findings}.values())


def _redundant_unpacking(node: ast.Assign) -> bool:
    if len(node.targets) != 1:
        return False
    target = node.targets[0]
    if not isinstance(target, ast.Tuple | ast.List) or not isinstance(node.value, ast.Tuple | ast.List):
        return False
    if len(target.elts) < _MIN_ATTRIBUTES or len(target.elts) != len(node.value.elts):
        return False
    receivers: set[str] = set()
    targets: set[str] = set()
    for left, right in zip(target.elts, node.value.elts, strict=True):
        pair = _attribute_alias(left, right)
        if pair is None:
            return False
        targets.add(pair.target)
        receivers.add(pair.receiver)
    return len(receivers) == 1 and receivers.isdisjoint(targets)


def _attribute_alias(left: ast.expr, right: ast.expr) -> _AttributeAlias | None:
    if not isinstance(left, ast.Name) or not isinstance(right, ast.Attribute) or not isinstance(right.value, ast.Name):
        return None
    return _AttributeAlias(left.id, right.value.id) if left.id == right.attr else None
