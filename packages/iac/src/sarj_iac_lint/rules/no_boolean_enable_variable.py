from __future__ import annotations

from pathlib import PurePosixPath
from typing import TYPE_CHECKING, final, override

from sarj_iac_lint._hcl import strip_outer_parentheses, tokens
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
    from pathlib import Path


@final
class NoBooleanEnableVariable(Rule):
    id = "no-boolean-enable-variable"
    code = "SARJ220"
    documentation = RuleDocumentation(
        default_level=DefaultLevel.WARNING,
        summary="Prefer direct configuration over Boolean enable/disable input variables.",
        rationale=(
            "Enable switches add configuration plumbing and keep alternate implementations alive. "
            "An infrastructure change should normally configure its intended behavior directly."
        ),
        remediation=(
            "Remove the switch and configure the intended behavior directly. If deployments need different values, "
            "pass the actual typed configuration instead. Review resource addresses, prerequisites and consumers "
            "before removing an existing input; a necessary optional capability needs an explicit policy exception."
        ),
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "This is an explicit interface policy, not proof that every matching switch is redundant or unsafe.",
            (
                "Matches top-level .tf variable declarations with explicit bool type and an enable_/disable_ prefix, "
                "_enabled/_disabled suffix, or an exact enable, enabled, disable or disabled name."
            ),
            "Provider attributes, object members, other Boolean inputs, inferred types and JSON syntax are excluded.",
            "No automatic deletion or branch selection is safe: changing count/for_each can destroy resources.",
        ),
        examples=(
            RuleExample(
                example_id="boolean-enable-input",
                title="An extra switch gates the intended implementation",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.iac("main.tf", 'variable "keyless_storage_enabled" {\n  type = bool\n}\n'),),
                focus_path=PurePosixPath("main.tf"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="direct-provider-configuration",
                title="Configure the provider directly",
                outcome=ExampleOutcome.NO_MATCH,
                files=(ExampleFile.iac("main.tf", 'resource "example_storage" "app" {\n  enabled = true\n}\n'),),
                focus_path=PurePosixPath("main.tf"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if path.suffix.lower() != ".tf":
            return []
        try:
            declarations = balanced_blocks(source)
        except ValueError:
            return []
        return [
            Diagnostic(
                path,
                block.line,
                block.col,
                self.code,
                f"Boolean enable/disable input '{block.labels[0]}': configure the intended behavior directly "
                "or pass its actual typed configuration; review existing consumers before removal.",
                severity=DefaultLevel.WARNING,
            )
            for block in declarations
            if block.type == "variable"
            and len(block.labels) == 1
            and (
                block.labels[0] in {"enable", "enabled", "disable", "disabled"}
                or block.labels[0].startswith(("enable_", "disable_"))
                or block.labels[0].endswith(("_enabled", "_disabled"))
            )
            and (declared_type := block.attribute("type")) is not None
            and strip_outer_parentheses(tokens(declared_type.value)) == ("bool",)
        ]
