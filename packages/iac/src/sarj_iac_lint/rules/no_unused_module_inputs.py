from __future__ import annotations

from pathlib import PurePosixPath
from typing import TYPE_CHECKING, final, override

from sarj_iac_lint._hcl import suppression_comment_lines
from sarj_iac_lint.module_outputs import module_consumers
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
    is_suppressed,
)


if TYPE_CHECKING:
    from collections.abc import Collection, Mapping
    from pathlib import Path

    from sarj_iac_lint.module_outputs import UnusedModuleInput


@final
class NoUnusedModuleInputs(Rule):
    id = "no-unused-module-inputs"
    code = "SARJ225"
    documentation = RuleDocumentation(
        default_level=DefaultLevel.WARNING,
        summary="Find forwarded Terraform inputs without a reachable consumer.",
        rationale=(
            "A variable referenced only by unused locals or discarded module arguments still passes a textual "
            "unused-declaration check. Its interface requires callers to maintain configuration that reaches no "
            "resource, validation, public export or external module."
        ),
        remediation=(
            "Review the declaration, every caller and their tfvars together. Remove the dead plumbing only after "
            "preserving required inputs, type conversion, validation, source-reading functions and external contracts. "
            "Do not replace operational controls with constants."
        ),
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Uses the existing complete selected Git HEAD/index module-output graph, including unchanged callers and multiple roots; the file-local API cannot prove non-use.",
            "Only modules reviewed as closed-world in iac.no-unused-module-outputs.internal_modules are eligible; unknown/public modules retain their interfaces.",
            "Variables without a syntactic reference remain owned by native TFLint terraform_unused_declarations, avoiding duplicate findings.",
            "Whole-object and dynamic consumption retain the input; merge arguments and their evaluation/error dependencies are conservative. This rule does not diagnose individual type attributes or prove that a referenced exposed input is architecturally necessary.",
            "Variable validations, output preconditions, public exports, external modules, templates and dynamic blocks remain consumers. Unresolved modules or malformed source fail project analysis.",
            "Override files make input analysis incomplete. No deletion fix is offered: even an unread field can impose requiredness, type conversion or validation contracts.",
            "Generated declarations require changes at their generator; this rule does not rewrite generated sources or their callers.",
            "This rule starts as a warning. Warnings remain visible and do not block checks; a separately reviewed promotion is required for error enforcement.",
        ),
        examples=(
            RuleExample(
                example_id="forwarded-to-unused-local",
                title="A local reference does not establish effective consumption",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.iac(
                        ".sarj-standards.toml", '[iac.no-unused-module-outputs]\ninternal_modules = ["child"]\n'
                    ),
                    ExampleFile.iac("main.tf", 'module "child" {\n source = "./child"\n region = "west"\n}\n'),
                    ExampleFile.iac("child/variables.tf", 'variable "region" { type = string }\n'),
                    ExampleFile.iac("child/main.tf", "locals { unused = var.region }\n"),
                ),
                focus_path=PurePosixPath("child/variables.tf"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="resource-consumes-input",
                title="A resource argument consumes the forwarded value",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.iac(
                        ".sarj-standards.toml", '[iac.no-unused-module-outputs]\ninternal_modules = ["child"]\n'
                    ),
                    ExampleFile.iac("main.tf", 'module "child" {\n source = "./child"\n region = "west"\n}\n'),
                    ExampleFile.iac("child/variables.tf", 'variable "region" { type = string }\n'),
                    ExampleFile.iac("child/main.tf", 'resource "example" "service" { region = var.region }\n'),
                ),
                focus_path=PurePosixPath("child/variables.tf"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        return []

    @classmethod
    def check_project(
        cls,
        root: Path,
        sources: Mapping[PurePosixPath, str],
        *,
        external_outputs: Collection[tuple[str, str]] = (),
        internal_modules: Collection[str] = (),
    ) -> list[Diagnostic]:
        analysis = module_consumers(
            {path.as_posix(): source for path, source in sources.items()},
            external_outputs=external_outputs,
            internal_modules=internal_modules,
        )
        return cls.diagnostics(root, analysis.inputs, sources)

    @classmethod
    def diagnostics(
        cls, root: Path, inputs: Collection[UnusedModuleInput] | None, sources: Mapping[PurePosixPath, str]
    ) -> list[Diagnostic]:
        documentation = cls.documentation
        level = DefaultLevel.WARNING if documentation is None else documentation.default_level
        if level is DefaultLevel.OFF:
            return []
        if inputs is None:
            message = "Terraform overrides or undeclared variable/argument references prevent complete effective-input analysis"
            raise ValueError(message)
        return [
            Diagnostic(
                path=root / item.path,
                line=item.line,
                col=1,
                code=cls.code,
                message=(
                    f"Input {item.name!r} is referenced but reaches no resource, validation or retained export "
                    "through any caller in the selected module graph. Review its declaration and all callers "
                    "together; requiredness and type/validation contracts prevent automatic deletion."
                ),
                severity=level,
            )
            for item in inputs
            if not is_suppressed(
                sources[PurePosixPath(item.path)].splitlines(),
                item.line,
                cls.code,
                comments=suppression_comment_lines(sources[PurePosixPath(item.path)]),
            )
        ]
