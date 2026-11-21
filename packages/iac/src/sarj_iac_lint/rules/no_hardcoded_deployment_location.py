from __future__ import annotations

from pathlib import PurePosixPath
import re
from types import MappingProxyType
from typing import TYPE_CHECKING, final, override

from sarj_iac_lint._hcl import (
    call_arguments,
    comma_parts,
    conditional_branches,
    header_comment_lines,
    literal_string,
    template_expressions,
    tokens,
)
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
from sarj_iac_lint.rules._literal_policy import (
    DEPLOYMENT_SCOPE_ATTRIBUTES,
    local_collections,
    resolve_local_tokens,
    static_string,
)
from sarj_iac_lint.terraform import TerraformSession, is_terraform, terraform_blocks


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
_LOCATION_ATTRIBUTES = _ROOT_PLACEMENT | _GOOGLE_PLACEMENT | {"data_locations", "region_name", "secondary_zone"}
_FIXED_PROJECT_REFERENCE = re.compile(
    r'^"(?:https://(?:www|compute)\.googleapis\.com/(?:compute/)?(?:v1|beta)/)?projects/[a-z0-9][a-z0-9.:_-]*(?=/)'
)
_INTEGER_LITERAL = re.compile(r"[0-9]+")
_NETWORK_INPUTS: Mapping[str, frozenset[str]] = MappingProxyType(
    {
        "google_compute_network": frozenset({"name"}),
        "google_compute_subnetwork": frozenset({"name", "network", "ip_cidr_range"}),
        "google_compute_address": frozenset({"name", "address", "subnetwork"}),
        "google_compute_global_address": frozenset({"name", "address", "network"}),
        "google_compute_forwarding_rule": frozenset({"name", "network", "subnetwork", "ip_address", "target"}),
        "google_compute_service_attachment": frozenset({"name", "target_service", "nat_subnets"}),
        "google_dns_managed_zone": frozenset({"name", "dns_name"}),
        "google_dns_record_set": frozenset({"name", "rrdatas"}),
        "google_certificate_manager_dns_authorization": frozenset({"domain"}),
        "google_cloud_run_domain_mapping": frozenset({"name"}),
        "google_cloud_run_v2_service": frozenset({"custom_audiences"}),
        "aws_route53_zone": frozenset({"name"}),
        "aws_route53_record": frozenset({"name", "records"}),
        "aws_eip": frozenset({"address", "public_ipv4_pool"}),
        "aws_vpc": frozenset({"cidr_block", "ipv6_cidr_block"}),
        "aws_subnet": frozenset({"cidr_block", "ipv6_cidr_block"}),
    }
)
_DNS_NAME_RESOURCES = frozenset(
    {"google_dns_record_set", "google_cloud_run_domain_mapping", "aws_route53_record", "aws_route53_zone"}
)
_DNS_RECORD_RESOURCES = frozenset({"google_dns_record_set", "aws_route53_record"})
_ENDPOINT_RECORD_TYPES = frozenset({"A", "AAAA", "CNAME", "NS", "PTR", "MX", "SRV"})
_NESTED_NETWORK_INPUTS: Mapping[tuple[str, tuple[str, ...]], frozenset[str]] = MappingProxyType(
    {
        ("google_compute_subnetwork", ("secondary_ip_range",)): frozenset({"ip_cidr_range"}),
        ("google_compute_instance", ("network_interface", "access_config")): frozenset({"nat_ip"}),
        ("google_compute_url_map", ("default_url_redirect",)): frozenset({"host_redirect"}),
        ("google_certificate_manager_certificate", ("managed",)): frozenset({"domains"}),
        ("google_compute_managed_ssl_certificate", ("managed",)): frozenset({"domains"}),
        ("azurerm_virtual_network", ("subnet",)): frozenset({"address_prefix", "address_prefixes"}),
    }
)
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
_CIDR_FUNCTIONS = frozenset({"cidrhost", "cidrsubnet", "cidrsubnets"})
_FIXTURE_DIRS = frozenset({"fixture", "fixtures", "testdata", "generated"})
_GENERATED = re.compile(r"generated.{0,80}(?:do not edit|don't edit)", re.IGNORECASE)


@final
class NoHardcodedDeploymentLocation(Rule):
    id = "no-hardcoded-deployment-location"
    code = "SARJ219"
    documentation = RuleDocumentation(
        default_level=DefaultLevel.ERROR,
        summary="Pass cloud deployment identities, locations and network values through explicit configuration inputs.",
        rationale=(
            "Literal deployment identities and coordinates inside infrastructure implementations bypass the caller's "
            "configuration. Changing inputs can leave resources bound to an old project, location, address or domain."
        ),
        remediation=(
            "Reuse an existing typed input or resource reference; otherwise add the smallest required input. "
            "Define deployment policy in caller inputs, variable defaults or tfvars instead of scattering literal "
            "identities, coordinates and matching preconditions through resource implementations."
        ),
        category=RuleCategory.ARCHITECTURE,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "An explicit configuration-ownership policy, not a claim that literals are invalid Terraform. Variable defaults, tfvars and caller module arguments are valid configuration boundaries.",
            "Checks recognized cloud scope/placement attributes and curated network, address and DNS resource fields, including enumerated nested schema paths and dynamic content. Arbitrary names, labels, tags, IAM role names, image selections, protocol constants and geographic access filters are not inferred as deployment inputs.",
            "Recognizes literal strings/lists, same-module local aliases, static joins, simple conversions, and conditional/coalesce/try output alternatives. Fixed project prefixes and contextual endpoint template fragments are checked. Unknown function results, object traversals and inherited provider configuration remain opaque.",
            "At the same attribute, this error takes precedence over repeated-deployment-literal guidance when both rules are selected.",
            "Covers authored .tf and .tf.json, contextual interpolated endpoint templates and same-module cross-file aliases through the shared analysis session. Bare per-file API calls have only same-file facts. Unknown functions and provider schema paths remain explicit blind spots.",
            "A module with an explicit backend/cloud block is a deployment composition root and may own concrete choices. Child module arguments and tfvars are also configuration boundaries. Reusable defaults consumed by placement fields need a nonempty literal description; descriptions are review evidence, not proof of a correct default.",
            "Generated headers, vendor/example/fixture paths and other HCL dialects are excluded. Provider global selectors remain constants. No variable default, state change, replacement binding or new input is inferred automatically.",
            "Module-owned resource names may be meaningful implementation constants; data lookup names and DNS names remain deployment identities. DNS record payloads are checked only for known endpoint-bearing record types; TXT/schema payloads and unknown record types are not inferred as endpoints.",
        ),
        examples=(
            RuleExample(
                example_id="literal-placement",
                title="The resource ignores caller placement configuration",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.iac(
                        "main.tf",
                        'resource "google_storage_bucket" "this" {\n  project = "example-project"\n  location = "us-central1"\n}\n',
                    ),
                ),
                focus_path=PurePosixPath("main.tf"),
                expected_count=2,
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

    def __init__(self, *, session: TerraformSession | None = None) -> None:
        self.session = session

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if not is_terraform(path) or any(part.lower() in _FIXTURE_DIRS | {"vendor", "examples"} for part in path.parts):
            return []
        if _GENERATED.search(" ".join(header_comment_lines(source, leading_only=True))):
            return []
        try:
            top = terraform_blocks(path, source)
            module = self.session.blocks(path) if self.session is not None else top
            values = local_collections(module)
            composition = any(
                block.type == "terraform" and any(child.type in {"backend", "cloud"} for child in block.blocks)
                for block in module
            )
            if composition:
                return []
            return [
                Diagnostic(
                    path,
                    attribute.line,
                    attribute.col,
                    self.code,
                    f"Hardcoded deployment `{attribute.name}`: pass a typed {'location ' if attribute.name in _LOCATION_ATTRIBUTES else ''}input or an input-derived value; keep defaults in caller configuration.",
                )
                for attribute in _module_placement_attributes(top)
                if _has_literal_placement(
                    tokens(attribute.value), values, global_selector=attribute.name in _LOCATION_ATTRIBUTES
                )
            ] + _undocumented_defaults(path, top, module, values, self.code, composition=composition)
        except ValueError:
            return []


def _placement_attributes(root: Block) -> Iterator[Attribute]:
    if root.type not in {"provider", "resource", "data", "ephemeral"} or not root.labels:
        return
    kind = root.labels[0]
    provider = kind if root.type == "provider" else kind.split("_", 1)[0]
    provider = "google" if provider == "google-beta" else provider
    if provider not in _CLOUD_PROVIDERS and provider not in DEPLOYMENT_SCOPE_ATTRIBUTES:
        return
    names = DEPLOYMENT_SCOPE_ATTRIBUTES.get(provider, frozenset[str]()) | _NETWORK_INPUTS.get(kind, frozenset[str]())
    if provider in _CLOUD_PROVIDERS or kind == "cloudflare_r2_bucket":
        names |= _ROOT_PLACEMENT
    if provider == "google":
        names |= _GOOGLE_PLACEMENT
    if provider == "hcloud":
        names = frozenset({"location"})
    for block, path in _nodes(root):
        selected = names
        if path:
            selected = _NESTED_PLACEMENT.get((kind, path), frozenset[str]()) | _NESTED_NETWORK_INPUTS.get(
                (kind, path), frozenset[str]()
            )
        for attribute in block.attributes:
            if attribute.name in selected and _deployment_field(root, attribute.name):
                yield attribute


def _deployment_field(root: Block, name: str) -> bool:
    kind = root.labels[0]
    if name == "name" and root.type in {"resource", "ephemeral"} and kind not in _DNS_NAME_RESOURCES:
        return False
    if kind in _DNS_RECORD_RESOURCES and name in {"rrdatas", "records"}:
        record_type = root.attribute("type")
        return record_type is not None and literal_string(record_type.value) in _ENDPOINT_RECORD_TYPES
    return True


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


def _has_literal_placement(parts: tuple[str, ...], values: Mapping[str, str], *, global_selector: bool = True) -> bool:
    pending = [parts]
    seen: set[tuple[str, ...]] = set()
    while pending:
        resolved = resolve_local_tokens(pending.pop(), values)
        if resolved is None or resolved in seen:
            continue
        seen.add(resolved)
        if _is_literal_input(resolved, values, global_selector=global_selector):
            return True
        if branches := conditional_branches(resolved):
            pending.extend(branches)
        elif resolved[:1] == ("[",) and resolved[-1:] == ("]",):
            pending.extend(comma_parts(resolved[1:-1]))
        elif resolved and resolved[0] in _CIDR_FUNCTIONS and (args := call_arguments(resolved)):
            pending.append(args[0])
        elif (args := call_arguments(resolved)) is not None and (
            resolved[0] in _ALTERNATIVES or (resolved[0] in _UNARY_CONVERSIONS and len(args) == 1)
        ):
            pending.extend(args)
    return False


def _is_literal_input(parts: tuple[str, ...], values: Mapping[str, str], *, global_selector: bool) -> bool:
    if (literal := static_string(parts, values)) is not None:
        if literal.rstrip(".").casefold() in _PROTOCOL_HOSTS:
            return False
        if literal in _PROTOCOL_URLS:
            return False
        return bool(literal.strip() and (not global_selector or literal.strip().casefold() != "global"))
    template = _deployment_template(parts)
    if template:
        return True
    if global_selector:
        return False
    if _INTEGER_LITERAL.fullmatch("".join(parts)):
        return True
    if parts[:1] == ("format",) and (args := call_arguments(parts)):
        parts = args[0]
    return len(parts) == 1 and _FIXED_PROJECT_REFERENCE.match(parts[0]) is not None


_FIXED_COORDINATE = re.compile(
    r"(?<![\w-])(?:[a-z][a-z0-9-]*\.)+[a-z]{2,}(?![\w-])"
    r"|(?<![\d.])(?:[0-9]{1,3}\.){3}[0-9]{1,3}(?![\d.])"
    r"|(?<![\w-])(?:us|eu|europe|asia|me|africa|australia|northamerica|southamerica)-(?:[a-z]+-)?[a-z]+-?[0-9](?![\w])"
)
_PROTOCOL_HOSTS = frozenset(
    {
        "localhost",
        "metadata.google.internal",
        "www.googleapis.com",
        "storage.googleapis.com",
        "oauth2.googleapis.com",
        "sts.googleapis.com",
        "accounts.google.com",
    }
)
_PROTOCOL_URLS = frozenset(
    {
        "https://accounts.google.com",
        "https://oauth2.googleapis.com/token",
        "https://sts.googleapis.com/v1/token",
        "https://www.googleapis.com/auth/cloud-platform",
    }
)


def _deployment_template(parts: tuple[str, ...]) -> bool:
    if parts[:1] == ("format",) and (args := call_arguments(parts)):
        parts = args[0]
    if len(parts) != 1:
        return False
    value = parts[0]
    expressions = template_expressions(value)
    if not expressions and literal_string(value) is None:
        return False
    for expression in sorted(expressions, key=len, reverse=True):
        value = value.replace("${" + expression + "}", " ").replace("%{" + expression + "}", " ")
    return any(match.group(0) not in _PROTOCOL_HOSTS for match in _FIXED_COORDINATE.finditer(value))


def _undocumented_defaults(
    path: Path,
    top: tuple[Block, ...],
    module: tuple[Block, ...],
    values: Mapping[str, str],
    code: str,
    *,
    composition: bool,
) -> list[Diagnostic]:
    if composition or not any(block.type == "variable" and block.attribute("default") is not None for block in top):
        return []
    used_inputs = _deployment_inputs(module, values)
    findings: list[Diagnostic] = []
    for variable in top:
        if variable.type != "variable" or len(variable.labels) != 1:
            continue
        if variable.labels[0] not in used_inputs:
            continue
        default = variable.attribute("default")
        if default is None or not _has_literal_placement(tokens(default.value), values):
            continue
        description = variable.attribute("description")
        if description is not None and literal_string(description.value):
            continue
        findings.append(
            Diagnostic(
                path,
                default.line,
                default.col,
                code,
                f"Deployment default for {variable.labels[0]!r} in a reusable module needs an intentional literal description; prefer an existing caller input or discovery reference.",
            )
        )
    return findings


def _module_placement_attributes(module: tuple[Block, ...]) -> Iterator[Attribute]:
    for owner in module:
        yield from _placement_attributes(owner)


def _deployment_inputs(module: tuple[Block, ...], values: Mapping[str, str]) -> set[str]:
    inputs: set[str] = set()
    for attribute in _module_placement_attributes(module):
        parts = resolve_local_tokens(tokens(attribute.value), values)
        if parts is None:
            continue
        expressions = (" ".join(parts), *template_expressions(attribute.value))
        for expression in expressions:
            inputs.update(
                part.removeprefix("var.")
                for part in tokens(expression)
                if part.startswith("var.") and part.count(".") == 1
            )
    return inputs
