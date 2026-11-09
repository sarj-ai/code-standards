from __future__ import annotations

from pathlib import PurePosixPath
from types import MappingProxyType
from typing import TYPE_CHECKING, final, override

from sarj_iac_lint._hcl import literal_string, tokens
from sarj_iac_lint.rule_base import (
    AutofixPolicy,
    DefaultLevel,
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    Rule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
)
from sarj_iac_lint.rules._literal_policy import balanced_blocks
from sarj_iac_lint.rules.no_restated_comment import has_generated_header


if TYPE_CHECKING:
    from pathlib import Path

    from sarj_iac_lint._hcl import Attribute


_SCOPE_ATTRIBUTES = MappingProxyType(
    {
        "google": frozenset({"project", "project_id", "region", "zone", "location", "org_id", "folder_id"}),
        "aws": frozenset({"region", "availability_zone"}),
        "azurerm": frozenset({"subscription_id", "tenant_id", "location", "resource_group_name"}),
        "azuread": frozenset({"tenant_id"}),
        "azapi": frozenset({"subscription_id", "tenant_id", "location"}),
        "cloudflare": frozenset({"account_id", "zone_id"}),
    }
)
_DATA_DIRECTORIES = frozenset({"fixture", "fixtures", "testdata", "generated"})
_LABEL_COUNT = 2
_REPEATED_USE_COUNT = 2


@final
class NoDuplicateDeploymentLiteral(Rule):
    id = "no-duplicate-deployment-literal"
    code = "SARJ218"
    documentation = RuleDocumentation(
        default_level=DefaultLevel.WARNING,
        summary="Share repeated cloud deployment values through variables, locals or resource references.",
        rationale="Repeating deployment identities and locations scatters configuration across resource declarations and makes coordinated changes harder to review.",
        remediation="Use an existing resource/data reference, a shared local for a fixed deployment value, or a module input for a caller-configured value. Keep independently configurable scopes independent.",
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Checks repeated identical direct string assignments to curated cloud scope/location attributes on resource and data blocks in one .tf file. Each provider/attribute/value group produces one warning at its second use.",
            "Cloudflare coverage includes direct account_id and zone_id scope arguments; record contents, nested policy objects and security expectations are not inferred from matching identifier text.",
            "Explicit provider bindings are grouped separately. Provider configuration, module inputs, variable defaults, locals, snapshot maps, hashes, roles, embedded configuration, generated sources and fixture/data files are excluded.",
            "Expressions, templates, indirect aliases, cross-file repetitions, JSON HCL and unknown providers are not inferred. The Google global location sentinel is not a deployment input.",
            "No autofix: shared values and deliberately independent configuration need an author decision. This warning does not prove that literal infrastructure is invalid or authorize changing a security baseline.",
        ),
        examples=(
            RuleExample(
                example_id="repeated-project",
                title="Resources repeat one deployment project",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.iac(
                        "main.tf",
                        'resource "google_storage_bucket" "a" { project = "example-project" }\nresource "google_cloud_run_v2_job" "b" { project = "example-project" }\n',
                    ),
                ),
                focus_path=PurePosixPath("main.tf"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="shared-project-input",
                title="Resources use their shared deployment input",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.iac(
                        "main.tf",
                        'variable "project_id" { type = string }\nresource "google_storage_bucket" "a" { project = var.project_id }\nresource "google_cloud_run_v2_job" "b" { project = var.project_id }\n',
                    ),
                ),
                focus_path=PurePosixPath("main.tf"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="repeated-cloudflare-account",
                scenario="cloudflare-account",
                title="Cloudflare resources repeat their deployment account",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.iac(
                        "main.tf",
                        'resource "cloudflare_r2_bucket" "a" { account_id = "example-account" }\nresource "cloudflare_r2_bucket" "b" { account_id = "example-account" }\n',
                    ),
                ),
                focus_path=PurePosixPath("main.tf"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="shared-cloudflare-account-input",
                scenario="cloudflare-account",
                title="Cloudflare resources share their typed account input",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.iac(
                        "main.tf",
                        'variable "account_id" { type = string }\nresource "cloudflare_r2_bucket" "a" { account_id = var.account_id }\nresource "cloudflare_r2_bucket" "b" { account_id = var.account_id }\n',
                    ),
                ),
                focus_path=PurePosixPath("main.tf"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if (
            path.suffix.lower() != ".tf"
            or any(part.lower() in _DATA_DIRECTORIES for part in path.parts)
            or has_generated_header(source)
        ):
            return []
        try:
            top = balanced_blocks(source)
        except ValueError:
            return []
        uses: dict[tuple[str, tuple[str, ...], str, str], list[Attribute]] = {}
        for block in top:
            if block.type not in {"resource", "data"} or len(block.labels) != _LABEL_COUNT:
                continue
            provider = block.labels[0].partition("_")[0]
            binding = tokens(attribute.value) if (attribute := block.attribute("provider")) else ()
            for attribute in block.attributes:
                if not (value := _deployment_value(provider, attribute)):
                    continue
                uses.setdefault((provider, binding, attribute.name, value), []).append(attribute)
        findings: list[Diagnostic] = []
        for (_, _, name, _), attributes in uses.items():
            if len(attributes) >= _REPEATED_USE_COUNT:
                repeated = attributes[1]
                findings.append(
                    Diagnostic(
                        path,
                        repeated.line,
                        repeated.col,
                        self.code,
                        f"{name} repeats one literal {len(attributes)} times; share a variable/local or resource/data reference when these uses represent the same deployment value.",
                        severity=DefaultLevel.WARNING,
                    )
                )
        return sorted(findings, key=lambda finding: (finding.line, finding.col))


def _deployment_value(provider: str, attribute: Attribute) -> str | None:
    if attribute.name not in _SCOPE_ATTRIBUTES.get(provider, frozenset()):
        return None
    value = literal_string(attribute.value)
    if provider == "google" and attribute.name == "location" and value == "global":
        return None
    return value
