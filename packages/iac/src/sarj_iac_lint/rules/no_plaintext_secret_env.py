from __future__ import annotations

from itertools import chain
from pathlib import PurePosixPath
import re
from typing import TYPE_CHECKING, final, override

from sarj_iac_lint._hcl import (
    call_arguments,
    conditional_branches,
    literal_string,
    strip_outer_parentheses,
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
from sarj_iac_lint.rules._literal_policy import balanced_blocks


if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from sarj_iac_lint._hcl import Block
    from sarj_iac_lint.terraform import TerraformSession


_NON_SECRET_LITERAL = re.compile(r"true|false", re.IGNORECASE)
_SECRET_NAME_REFERENCE = re.compile(r"google_secret_manager_secret\.\w+\.(?:secret_id|name|id)\b")
_SECRET_NAME = re.compile(r"^(?:[A-Z0-9]+_)*(?:SECRET|TOKEN|PASSWORD|API_KEY|PRIVATE_KEY)$")
_MAX_METADATA_DEPTH = 32


@final
class NoPlaintextSecretEnv(Rule):
    id = "no-plaintext-secret-env"
    code = "SARJ214"
    documentation = RuleDocumentation(
        default_level=DefaultLevel.ERROR,
        summary="A secret-named container environment variable should come from a secret reference, not a plain value.",
        rationale=(
            "A plain `value` copies the secret into Terraform state, the plan output and the service revision, where "
            "anyone who can read them sees it, and rotating it needs a redeploy."
        ),
        remediation=(
            "Store the secret in Secret Manager and reference it with `value_source { secret_key_ref { ... } }` or "
            "`value_from { secret_key_ref { ... } }`."
        ),
        category=RuleCategory.SECURITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only `env` blocks inside Terraform resources in .tf files are checked.",
            (
                "Other literal names are reported only when the value directly consumes a same-module variable declared "
                "`sensitive = true` (bare reference, template interpolation, `urlencode`/`format` argument or conditional "
                "branch); secrets reached through locals, module outputs or other functions are not recognized."
            ),
            "Empty literal values are not reported.",
            "Public Secret Manager names, homogeneous metadata branches, metadata-only templates and format calls are allowed; a metadata reference does not exempt other dynamic values in the same expression.",
        ),
        examples=tuple(
            RuleExample(
                example_id=example_id,
                title=title,
                outcome=outcome,
                files=(ExampleFile.iac("main.tf", source),),
                focus_path=PurePosixPath("main.tf"),
                expected_count=count,
                public=True,
                scenario=(
                    "metadata-composition"
                    if example_id in {"metadata-does-not-exempt-secret", "public-metadata-composition"}
                    else "primary"
                ),
            )
            for example_id, title, outcome, source, count in (
                (
                    "plain-api-key",
                    "An API key is injected as a plain value",
                    ExampleOutcome.MATCH,
                    (
                        'resource "google_cloud_run_v2_service" "api" {\n  template {\n    containers {\n'
                        '      env {\n        name  = "API_KEY"\n        value = var.api_key\n      }\n    }\n  }\n}\n'
                    ),
                    1,
                ),
                (
                    "secret-reference",
                    "An API key is read from Secret Manager",
                    ExampleOutcome.NO_MATCH,
                    (
                        'resource "google_cloud_run_v2_service" "api" {\n  template {\n    containers {\n'
                        '      env {\n        name = "API_KEY"\n        value_source {\n          secret_key_ref {\n'
                        "            secret  = google_secret_manager_secret.api_key.secret_id\n"
                        '            version = "latest"\n          }\n        }\n      }\n    }\n  }\n}\n'
                    ),
                    0,
                ),
                (
                    "metadata-does-not-exempt-secret",
                    "A public secret name does not hide a secret value",
                    ExampleOutcome.MATCH,
                    (
                        'resource "google_cloud_run_v2_service" "api" {\n  template {\n    containers {\n'
                        '      env {\n        name = "API_KEY"\n'
                        '        value = format("%s/%s", google_secret_manager_secret.api.name, var.api_key)\n'
                        "      }\n    }\n  }\n}\n"
                    ),
                    1,
                ),
                (
                    "public-metadata-composition",
                    "A composed secret name contains only public metadata",
                    ExampleOutcome.NO_MATCH,
                    (
                        'resource "google_cloud_run_v2_service" "api" {\n  template {\n    containers {\n'
                        '      env {\n        name = "API_KEY"\n'
                        '        value = format("projects/%s", google_secret_manager_secret.api.name)\n'
                        "      }\n    }\n  }\n}\n"
                    ),
                    0,
                ),
            )
        ),
    )
    description = documentation.summary

    def __init__(
        self,
        *,
        session: TerraformSession | None = None,  # sarj-noqa: SARJ468 -- Registry requires no-argument factories.
    ) -> None:
        self.session = session

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if path.suffix.lower() != ".tf" or "env" not in source:
            return []
        try:
            top = balanced_blocks(source)
        except ValueError:
            return []
        sensitive_names = frozenset(
            block.labels[0]
            for block in (self.session.blocks(path) if self.session is not None else top)
            if block.type == "variable"
            and len(block.labels) == 1
            and (sensitive := block.attribute("sensitive")) is not None
            and sensitive.value.strip() == "true"
        )
        findings: list[Diagnostic] = []
        for env in chain.from_iterable(_env_blocks(resource) for resource in top if resource.type == "resource"):
            name_attribute = env.attribute("name")
            value_attribute = env.attribute("value")
            if name_attribute is None or value_attribute is None:
                continue
            name = literal_string(name_attribute.value.strip())
            if name is None or not _is_plaintext_secret(name, value_attribute.value, sensitive_names):
                continue
            findings.append(
                Diagnostic(
                    path,
                    value_attribute.line,
                    value_attribute.col,
                    self.code,
                    f"Environment variable {name} receives a plain value; reference a Secret Manager secret "
                    "with value_source or value_from instead",
                    severity=DefaultLevel.ERROR,
                )
            )
        return findings


def _env_blocks(block: Block) -> Iterator[Block]:
    for child in block.blocks:
        if child.type == "env":
            yield child
        yield from _env_blocks(child)


def _is_plaintext_secret(name: str, value: str, sensitive_names: frozenset[str]) -> bool:
    if _SECRET_NAME.fullmatch(name):
        return not _is_inert_value(value)
    return _consumes_sensitive_variable(value, sensitive_names)


def _consumes_sensitive_variable(raw: str, names: frozenset[str], depth: int = 0) -> bool:
    if depth >= _MAX_METADATA_DEPTH:
        return False
    parts = strip_outer_parentheses(tokens(raw))
    if len(parts) == 1 and parts[0].startswith("var."):
        name = parts[0].removeprefix("var.")
        if "." not in name and name in names:
            return True
    if branches := conditional_branches(parts):
        return any(_consumes_sensitive_variable(" ".join(branch), names, depth + 1) for branch in branches)
    if parts[:1] in {("urlencode",), ("format",)} and (arguments := call_arguments(parts)) is not None:
        return any(_consumes_sensitive_variable(" ".join(argument), names, depth + 1) for argument in arguments)
    if len(parts) == 1 and parts[0].startswith('"'):
        return any(_consumes_sensitive_variable(item, names, depth + 1) for item in template_expressions(parts[0]))
    return False


def _is_inert_value(raw: str, depth: int = 0) -> bool:
    if depth >= _MAX_METADATA_DEPTH:
        return False
    parts = strip_outer_parentheses(tokens(raw))
    expression = " ".join(parts)
    value = literal_string(expression)
    if value is not None and (not value or _NON_SECRET_LITERAL.fullmatch(value)):
        return True
    if len(parts) == 1 and _SECRET_NAME_REFERENCE.fullmatch(parts[0]):
        return True
    if branches := conditional_branches(parts):
        return all(_is_inert_value(" ".join(branch), depth + 1) for branch in branches)
    if parts[:1] == ("format",) and (arguments := call_arguments(parts)) is not None:
        return (
            len(arguments) > 1
            and literal_string(" ".join(arguments[0])) is not None
            and all(_is_inert_value(" ".join(argument), depth + 1) for argument in arguments[1:])
        )
    if len(parts) == 1 and parts[0].startswith('"') and "%{" not in parts[0]:
        expressions = template_expressions(parts[0])
        return bool(expressions) and all(_is_inert_value(item, depth + 1) for item in expressions)
    return False
