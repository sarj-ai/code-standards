from __future__ import annotations

from pathlib import PurePosixPath
from typing import TYPE_CHECKING, final, override

from sarj_iac_lint._hcl import document
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
from sarj_iac_lint.rules.no_environment_conditional import uses_environment_conditional


if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from sarj_iac_lint._hcl import Attribute, Block


_PRINCIPAL_LITERALS = ("@", '"group:', '"principal', '"roles/', '"serviceAccount:', '"user:')
_HCL_SUFFIXES = (".tf", ".hcl")
_TEST_SUFFIXES = (".tftest.hcl", ".tftest.json")


@final
class NoEnvironmentDerivedAccessGrant(Rule):
    id = "no-environment-derived-access-grant"
    code = "SARJ208"
    documentation = RuleDocumentation(
        summary="Terraform access grants must be selected by explicit tfvars, not environment-name conditionals.",
        rationale=(
            "Deriving principals or IAM resources from an environment name hides the authorization decision in "
            "shared Terraform code. New stacks then inherit access according to a naming convention instead of "
            "an explicit, reviewable value in that stack's tfvars."
        ),
        remediation=(
            "Declare a typed capability input such as `product_qa_access_enabled`, set it explicitly in every "
            "environment's tfvars, and gate the fixed principal set with that input."
        ),
        category=RuleCategory.SECURITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "The rule inspects .tf and .hcl attributes that construct a Terraform set containing a literal IAM principal or role.",
            (
                "Principal sets assembled entirely from variable or local references are outside this narrow "
                "detector and remain covered by SARJ204."
            ),
            "Environment-name conditionals outside access-related attributes remain owned by SARJ204.",
        ),
        examples=(
            RuleExample(
                example_id="environment-derived-groups",
                title="Access groups selected from the environment name",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.iac(
                        "iam.tf",
                        "locals {\n"
                        '  product_qa_groups = contains(["dev", "preview"], var.environment) ? '
                        'toset(["team-product@example.com"]) : toset([])\n'
                        "}\n",
                    ),
                ),
                focus_path=PurePosixPath("iam.tf"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="explicit-capability-input",
                title="Access groups gated by an explicit tfvars input",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.iac(
                        "iam.tf",
                        "locals {\n"
                        "  product_qa_groups = var.product_qa_access_enabled ? "
                        'toset(["team-product@example.com"]) : toset([])\n'
                        "}\n",
                    ),
                ),
                focus_path=PurePosixPath("iam.tf"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        name = str(path)
        if name.endswith(_TEST_SUFFIXES) or not name.endswith(_HCL_SUFFIXES):
            return []
        return [
            Diagnostic(
                path=path,
                line=attribute.line,
                col=attribute.col,
                code=self.code,
                message=(
                    "Access grants must not branch on the environment identity; pass an explicit capability "
                    "value from each environment's tfvars."
                ),
            )
            for attribute in _attributes((document(source),))
            if _contains_principal(attribute.value) and uses_environment_conditional(attribute.value)
        ]


def _attributes(blocks: tuple[Block, ...]) -> Iterator[Attribute]:
    for block in blocks:
        yield from block.attributes
        yield from _attributes(block.blocks)


def _contains_principal(value: str) -> bool:
    return "toset(" in value and any(marker in value for marker in _PRINCIPAL_LITERALS)
