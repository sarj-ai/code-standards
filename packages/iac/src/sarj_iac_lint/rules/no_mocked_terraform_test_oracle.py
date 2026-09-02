from __future__ import annotations

from pathlib import PurePosixPath
import re
from types import MappingProxyType
from typing import TYPE_CHECKING, ClassVar, NamedTuple, final, override

from sarj_iac_lint._hcl import blocks, tokens
from sarj_iac_lint.rule_base import (
    AutofixPolicy,
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    Rule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
)


if TYPE_CHECKING:
    from pathlib import Path

    from sarj_iac_lint._hcl import Block

_TEST_SUFFIX = ".tftest.hcl"
_OVERRIDE_VALUE_ATTRIBUTES = MappingProxyType(
    {
        "override_data": "values",
        "override_module": "outputs",
        "override_resource": "values",
    }
)
_LITERAL_ENTRY_RE = re.compile(
    r"(?<![\w.])(?P<key>[A-Za-z_]\w*)\s*=\s*"
    r'(?P<value>"(?:\\.|[^"\\])*"|true\b|false\b|null\b|-?\d+(?:\.\d+)?)'
)
_PARENTHESIS_PAIR_LENGTH = 2


class _InjectedLiteral(NamedTuple):
    expression: str
    literal: str


@final
class NoMockedTerraformTestOracle(Rule):
    id = "no-mocked-terraform-test-oracle"
    code = "SARJ206"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary=(
            "Warn when a Terraform assertion directly reasserts the same literal injected by a resource, data, or "
            "module override."
        ),
        rationale=(
            "An assertion that compares an overridden attribute directly with its authored override value is "
            "self-fulfilling; it does not exercise configuration logic or provider behavior."
        ),
        remediation=(
            "Assert on configuration behavior derived from the override, or add provider-backed/runtime coverage for "
            "provider-dependent claims. Empty mock providers remain valid for fast configuration tests."
        ),
        category=RuleCategory.TESTING,
        autofix=AutofixPolicy.NONE,
        aliases=("no-terraform-test-file",),
        limitations=(
            (
                "Only direct literal entries in values/outputs maps on file-level or run-level override_resource, "
                "override_data, and override_module blocks in .tftest.hcl are compared."
            ),
            (
                "Mock providers, generated mock defaults, transformed assertions, JSON test syntax, provider-scoped "
                "overrides, and dynamic expressions are deliberately excluded because their data flow is ambiguous."
            ),
        ),
        examples=(
            RuleExample(
                example_id="direct-override-reassertion",
                title="Assertion repeats its own resource override",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.iac(
                        "tests/routing.tftest.hcl",
                        "override_resource {\n"
                        "  target = aws_s3_bucket.main\n"
                        '  values = { arn = "fixture-arn" }\n'
                        "}\n\n"
                        'run "routing" {\n'
                        "  assert {\n"
                        '    condition     = aws_s3_bucket.main.arn == "fixture-arn"\n'
                        '    error_message = "ARN mismatch"\n'
                        "  }\n"
                        "}\n",
                    ),
                ),
                focus_path=PurePosixPath("tests/routing.tftest.hcl"),
                expected_count=1,
                public=True,
                scenario="terraform-provider-evidence",
            ),
            RuleExample(
                example_id="mock-backed-configuration-test",
                title="Empty mock provider validates configured plan behavior",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.iac(
                        "tests/routing.tftest.hcl",
                        'mock_provider "aws" {}\n\n'
                        'run "routing" {\n  command = plan\n\n'
                        "  assert {\n    condition     = aws_s3_bucket.main.bucket == var.bucket_name\n"
                        '    error_message = "bucket configuration drifted"\n  }\n}\n',
                    ),
                ),
                focus_path=PurePosixPath("tests/routing.tftest.hcl"),
                expected_count=0,
                public=True,
                scenario="terraform-provider-evidence",
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if not path.name.casefold().endswith(_TEST_SUFFIX):
            return []
        try:
            top_level = blocks(source)
        except ValueError:
            return []
        file_overrides = _injected_literals(top_level)
        findings: list[Diagnostic] = []
        for run in (block for block in top_level if block.type == "run"):
            injected = (*file_overrides, *_injected_literals(run.blocks))
            for assertion in (block for block in run.blocks if block.type == "assert"):
                condition = assertion.attribute("condition")
                if condition is None:
                    continue
                matched = next((item for item in injected if _directly_reasserts(condition.value, item)), None)
                if matched is None:
                    continue
                findings.append(
                    Diagnostic(
                        path=path,
                        line=condition.line,
                        col=condition.col,
                        code=self.code,
                        message=(
                            f"Assertion directly repeats the injected `{matched.expression}` literal; assert on "
                            "derived configuration behavior instead."
                        ),
                    )
                )
        return findings


def _injected_literals(items: tuple[Block, ...]) -> tuple[_InjectedLiteral, ...]:
    injected: list[_InjectedLiteral] = []
    for block in items:
        value_attribute = _OVERRIDE_VALUE_ATTRIBUTES.get(block.type)
        if value_attribute is None:
            continue
        target = block.attribute("target")
        values = block.attribute(value_attribute)
        if target is None or values is None:
            continue
        injected.extend(
            _InjectedLiteral(f"{target.value}.{match['key']}", match["value"])
            for match in _LITERAL_ENTRY_RE.finditer(values.value)
        )
    return tuple(injected)


def _directly_reasserts(condition: str, injected: _InjectedLiteral) -> bool:
    condition_tokens = tokens(condition)
    while (
        len(condition_tokens) >= _PARENTHESIS_PAIR_LENGTH and condition_tokens[0] == "(" and condition_tokens[-1] == ")"
    ):
        condition_tokens = condition_tokens[1:-1]
    expected = (injected.expression, "==", injected.literal)
    return condition_tokens == expected or condition_tokens == tuple(reversed(expected))
