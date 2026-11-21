from __future__ import annotations

from pathlib import PurePosixPath
from typing import TYPE_CHECKING, final, override

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
from sarj_iac_lint.rules.no_restated_comment import has_generated_header
from sarj_iac_lint.terraform import is_terraform, is_terraform_override, terraform_blocks


if TYPE_CHECKING:
    from pathlib import Path


@final
class CanonicalTerraformDeclarations(Rule):
    id = "canonical-terraform-declarations"
    code = "SARJ224"
    documentation = RuleDocumentation(
        default_level=DefaultLevel.WARNING,
        summary="Keep variable and output declarations in their owning module canonical interface files.",
        rationale="A module's inputs and exports form its interface. Canonical files expose that interface without introducing folders Terraform does not load.",
        remediation="Consolidate declarations into variables.tf or outputs.tf in the same module directory; use variables.tf.json or outputs.tf.json for JSON. Keep implementation and deployment entrypoints in place. Review comments, override files and duplicate declarations before moving blocks.",
        category=RuleCategory.STYLE,
        autofix=AutofixPolicy.SAFE,
        limitations=(
            "Checks top-level variable/output blocks in .tf and .tf.json; filenames alone cannot establish this source-semantic finding.",
            "No empty files, new module, resource move or tfvars relocation is required. Terraform does not recursively load variables/ or outputs/ folders.",
            "Generated/vendor/example/fixture sources and Terraform override files are excluded. Overrides merge by filename ordering and require review.",
            "First ships as a warning; a separate reviewed promotion through maintain rules promote-error enables blocking. Source, registry and generated lifecycle metadata must agree before qualification.",
            "Core check/fix and staged checks can move native HCL declaration blocks into existing selected canonical files in the same module. The per-file IaC fixer cannot establish a complete module and refuses movement. JSON, missing/unselected destinations, guards, comments/directives, overrides, duplicate interfaces and source-reading functions require review. Core verifies the entire module structure and stale source/index/directory preconditions, then applies all files through its existing rollback transaction.",
        ),
        examples=(
            RuleExample(
                example_id="misplaced-input",
                title="Keep the interface visible in its owning module",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.iac(
                        "service.tf",
                        'variable "region" { type = string }\nresource "terraform_data" "this" { input = var.region }\n',
                    ),
                    ExampleFile.iac("variables.tf", 'variable "project" { type = string }\n'),
                ),
                fixed_files=(
                    ExampleFile.iac("service.tf", 'resource "terraform_data" "this" { input = var.region }\n'),
                    ExampleFile.iac(
                        "variables.tf", 'variable "project" { type = string }\n\nvariable "region" { type = string }\n'
                    ),
                ),
                focus_path=PurePosixPath("service.tf"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="canonical-input",
                title="A module owns its input file",
                outcome=ExampleOutcome.NO_MATCH,
                files=(ExampleFile.iac("variables.tf", 'variable "region" { type = string }\n'),),
                focus_path=PurePosixPath("variables.tf"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="misplaced-json-output",
                scenario="json",
                title="JSON declarations belong to the same owning module",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.iac("service.tf.json", '{"output":{"endpoint":{"value":"${var.endpoint}"}}}\n'),),
                focus_path=PurePosixPath("service.tf.json"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="canonical-json-output",
                scenario="json",
                title="A module owns its JSON output file",
                outcome=ExampleOutcome.NO_MATCH,
                files=(ExampleFile.iac("outputs.tf.json", '{"output":{"endpoint":{"value":"${var.endpoint}"}}}\n'),),
                focus_path=PurePosixPath("outputs.tf.json"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        documentation = self.documentation
        if documentation is None or documentation.default_level is DefaultLevel.OFF:
            return []
        if not is_terraform(path) or _excluded(path, source):
            return []
        extension = ".tf.json" if path.name.endswith(".tf.json") else ".tf"
        return [
            Diagnostic(
                path,
                block.line,
                block.col,
                self.code,
                f"Declare {block.type} {block.labels[0]!r} in {filename} in this same module directory; preserve its interface and tfvars loading.",
                severity=documentation.default_level,
            )
            for block in terraform_blocks(path, source)
            if block.type in {"variable", "output"} and len(block.labels) == 1
            if path.name != (filename := ("variables" if block.type == "variable" else "outputs") + extension)
        ]


def _excluded(path: Path, source: str) -> bool:
    return (
        any(
            part.casefold() in {"vendor", "generated", "fixture", "fixtures", "testdata", "examples"}
            for part in path.parts
        )
        or is_terraform_override(path)
        or has_generated_header(source)
    )
