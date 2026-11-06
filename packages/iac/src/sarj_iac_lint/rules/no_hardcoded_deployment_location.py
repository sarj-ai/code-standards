from __future__ import annotations

from pathlib import PurePosixPath
import re
from types import MappingProxyType
from typing import TYPE_CHECKING, final, override

from sarj_iac_lint._hcl import call_arguments, comma_parts, conditional_branches, header_comment_lines, tokens
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
from sarj_iac_lint.rules._literal_policy import balanced_blocks, local_collections, resolve_local_tokens, static_string


if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping
    from pathlib import Path

    from sarj_iac_lint._hcl import Attribute, Block


_CLOUD_PROVIDERS = frozenset(
    {
        "aws",
        "google",
        "google-beta",
        "azurerm",
        "azapi",
        "oci",
        "alicloud",
        "scaleway",
        "digitalocean",
        "hcloud",
        "openstack",
    }
)
_ROOT_PLACEMENT = frozenset(
    {"region", "regions", "zone", "zones", "location", "locations", "availability_zone", "availability_zones"}
)
_GOOGLE_PLACEMENT = frozenset({"location_id", "node_locations", "distribution_policy_zones", "replica_zones"})
_NESTED_PLACEMENT: Mapping[tuple[str, tuple[str, ...]], frozenset[str]] = MappingProxyType(
    {
        ("google_secret_manager_secret", ("replication", "user_managed", "replicas")): frozenset({"location"}),
        ("google_bigtable_instance", ("cluster",)): frozenset({"zone"}),
        ("google_sql_database_instance", ("settings", "location_preference")): frozenset({"zone", "secondary_zone"}),
        ("google_dataproc_cluster", ("cluster_config", "gce_cluster_config")): frozenset({"zone"}),
        ("google_storage_bucket", ("custom_placement_config",)): frozenset({"data_locations"}),
        ("aws_secretsmanager_secret", ("replica",)): frozenset({"region"}),
        ("aws_dynamodb_table", ("replica",)): frozenset({"region_name"}),
        ("azurerm_cosmosdb_account", ("geo_location",)): frozenset({"location"}),
        ("azurerm_container_registry", ("georeplications",)): frozenset({"location"}),
    }
)
_UNARY_CONVERSIONS = frozenset({"upper", "lower", "trimspace", "toset", "tolist", "tomap"})
_ALTERNATIVES = frozenset({"coalesce", "try"})
_FIXTURE_DIRS = frozenset({"fixture", "fixtures", "testdata", "generated"})
_GENERATED = re.compile(r"generated.{0,80}(?:do not edit|don't edit)", re.IGNORECASE)


@final
class NoHardcodedDeploymentLocation(Rule):
    id = "no-hardcoded-deployment-location"
    code = "SARJ219"
    documentation = RuleDocumentation(
        default_level=DefaultLevel.ERROR,
        summary="Pass cloud deployment regions, zones and locations through explicit configuration inputs.",
        rationale=(
            "Literal placement coordinates inside infrastructure implementations bypass the caller's deployment "
            "configuration. Resources in one module can silently remain in different locations when inputs change."
        ),
        remediation=(
            "Reuse an existing typed region, zone or location input; otherwise add the smallest required input. "
            "Define deployment policy in caller inputs, variable defaults or tfvars instead of scattering literal "
            "coordinates and matching preconditions through resource implementations."
        ),
        category=RuleCategory.ARCHITECTURE,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "An explicit configuration-ownership policy, not a claim that literal regions are invalid Terraform. Variable defaults, tfvars and caller module arguments are valid configuration boundaries.",
            "Checks recognized cloud provider/resource placement attributes and enumerated nested placement schema paths, including dynamic content. Cloudflare is limited to R2 bucket placement; Hetzner to geographic location fields. Labels, tags, geographic access filters, DNS zones and provider-required global selectors are not deployment coordinates.",
            "Recognizes literal strings/lists, direct same-file local aliases, static joins, simple conversions, and conditional/coalesce/try output alternatives. Unknown function results, object traversals, cross-file aliases and inherited provider configuration remain opaque.",
            "At the same attribute, this error takes precedence over repeated-deployment-literal guidance when both rules are selected.",
            "Only authored .tf inputs are checked; generated headers, fixtures and other HCL/JSON dialects are excluded. No variable name, value migration or Terraform state change is automatically inferred.",
        ),
        examples=(
            RuleExample(
                example_id="literal-placement",
                title="The resource ignores caller placement configuration",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.iac(
                        "main.tf", 'resource "google_storage_bucket" "this" {\n  location = "us-central1"\n}\n'
                    ),
                ),
                focus_path=PurePosixPath("main.tf"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="placement-input",
                title="The caller owns placement through a typed input",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.iac(
                        "main.tf",
                        'variable "region" { type = string }\nresource "google_storage_bucket" "this" {\n  location = var.region\n}\n',
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
        if path.suffix.lower() != ".tf" or any(part.lower() in _FIXTURE_DIRS for part in path.parts):
            return []
        if _GENERATED.search(" ".join(header_comment_lines(source, leading_only=True))):
            return []
        try:
            top = balanced_blocks(source)
            values = local_collections(top)
            return [
                Diagnostic(
                    path,
                    attribute.line,
                    attribute.col,
                    self.code,
                    f"Hardcoded deployment `{attribute.name}`: pass a typed location input or an input-derived value; keep defaults in caller configuration.",
                )
                for block in top
                for attribute in _placement_attributes(block)
                if _has_literal_placement(tokens(attribute.value), values)
            ]
        except ValueError:
            return []


def _placement_attributes(root: Block) -> Iterator[Attribute]:
    if root.type not in {"provider", "resource", "data", "ephemeral"} or not root.labels:
        return
    kind = root.labels[0]
    provider = kind if root.type == "provider" else kind.split("_", 1)[0]
    if provider not in _CLOUD_PROVIDERS and kind != "cloudflare_r2_bucket":
        return
    for block, path in _nodes(root):
        names = _NESTED_PLACEMENT.get((kind, path), frozenset()) if path else _ROOT_PLACEMENT
        if not path and provider == "google":
            names |= _GOOGLE_PLACEMENT
        if not path and provider == "hcloud":
            names = frozenset({"location"})
        for attribute in block.attributes:
            if attribute.name in names:
                yield attribute


def _nodes(root: Block) -> Iterator[tuple[Block, tuple[str, ...]]]:
    pending: list[tuple[Block, tuple[str, ...]]] = [(root, ())]
    while pending:
        block, path = pending.pop()
        yield block, path
        for child in reversed(block.blocks):
            if child.type == "dynamic" and len(child.labels) == 1:
                pending.extend(
                    (content, (*path, child.labels[0])) for content in child.blocks if content.type == "content"
                )
            else:
                pending.append((child, (*path, child.type)))


def _has_literal_placement(parts: tuple[str, ...], values: Mapping[str, str]) -> bool:
    pending = [parts]
    seen: set[tuple[str, ...]] = set()
    while pending:
        resolved = resolve_local_tokens(pending.pop(), values)
        if resolved is None or resolved in seen:
            continue
        seen.add(resolved)
        if (literal := static_string(resolved, values)) is not None:
            if literal.strip() and literal.strip().casefold() != "global":
                return True
            continue
        if branches := conditional_branches(resolved):
            pending.extend(branches)
        elif resolved[:1] == ("[",) and resolved[-1:] == ("]",):
            pending.extend(comma_parts(resolved[1:-1]))
        elif (args := call_arguments(resolved)) is not None and (
            resolved[0] in _ALTERNATIVES or (resolved[0] in _UNARY_CONVERSIONS and len(args) == 1)
        ):
            pending.extend(args)
    return False
