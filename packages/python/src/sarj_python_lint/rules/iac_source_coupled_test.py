from __future__ import annotations

import ast
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, ClassVar, final, override

from sarj_python_lint.rule_base import (
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
from sarj_python_lint.rules._paths import is_generated, is_test_path
from sarj_python_lint.rules.source_coupled_test import FunctionAnalyzer, top_level_test_functions


if TYPE_CHECKING:
    from pathlib import Path


IAC_SOURCE_SUFFIXES = (".hcl", ".tf", ".tf.json", ".tfvars", ".tftest.hcl", ".tftest.json")


@final
class IacSourceCoupledTest(Rule):
    id = "iac-source-coupled-test"
    code = "SARJ412"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="Test uses raw Terraform/HCL text as an infrastructure-behavior oracle.",
        rationale=(
            "Substring and regex checks can pass on comments, formatting, or unreachable Terraform configuration "
            "without proving the plan or deployed behavior."
        ),
        remediation=(
            "Assert on parsed configuration, Terraform test or rendered plan/state JSON, provider state, or runtime behavior. "
            "When exact source representation is the contract, suppress the assertion with that rationale."
        ),
        category=RuleCategory.TESTING,
        limitations=(
            "The rule follows local aliases, path collections, context-managed reads, and common normalization; interprocedural flows remain unreported.",
            "Files produced beneath recognized temporary-directory fixtures are generated outputs and remain unreported.",
            "The Python detector currently owns Terraform and HCL suffixes; YAML remains with the general source-coupled rule.",
            "Golden, packaging, formatter, and compatibility representation contracts require an exact suppression.",
        ),
        examples=(
            RuleExample(
                example_id="rendered-plan-contract",
                title="Assert on structured Terraform plan behavior",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_policy.py",
                        "def test_policy(rendered_plan_json: str):\n"
                        "    plan = json.loads(rendered_plan_json)\n"
                        "    changes = plan['resource_changes']\n"
                        "    assert changes[0]['change']['actions'] == ['create']\n",
                    ),
                ),
                focus_path=PurePosixPath("tests/test_policy.py"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="terraform-substring-contract",
                title="Do not prove Terraform behavior with a substring",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_policy.py",
                        "def test_policy():\n    source = Path('main.tf').read_text()\n    assert 'prevent_destroy = true' in source\n",
                    ),
                ),
                focus_path=PurePosixPath("tests/test_policy.py"),
                expected_count=1,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if not is_test_path(path) or is_generated(path, source):
            return []
        tree = parse_or_none(path, source)
        if not isinstance(tree, ast.Module):
            return []
        assertions = [
            assertion
            for function, unittest_style in top_level_test_functions(tree)
            for assertion in FunctionAnalyzer(IAC_SOURCE_SUFFIXES, unittest_style=unittest_style).analyze(function)
        ]
        return [
            Diagnostic(
                path=path,
                line=assertion.lineno,
                col=assertion.col_offset + 1,
                code=self.code,
                severity=Severity.WARNING,
                message=(
                    "raw Terraform/HCL text is being used to infer infrastructure behavior; assert on parsed configuration, "
                    "rendered plan or state, provider state, or runtime behavior instead."
                ),
            )
            for assertion in assertions
        ]
