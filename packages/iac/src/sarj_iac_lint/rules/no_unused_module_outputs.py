from __future__ import annotations

from pathlib import PurePosixPath
from typing import TYPE_CHECKING, final, override

from sarj_iac_lint.module_outputs import unused_module_outputs
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


if TYPE_CHECKING:
    from collections.abc import Collection, Mapping
    from pathlib import Path

    from sarj_iac_lint.module_outputs import UnusedModuleOutput


@final
class NoUnusedModuleOutputs(Rule):
    id = "no-unused-module-outputs"
    code = "SARJ223"
    documentation = RuleDocumentation(
        default_level=DefaultLevel.ERROR,
        summary="Ban Terraform module outputs without a reachable consumer or exact external contract.",
        rationale=(
            "Unused exports duplicate an infrastructure interface and obscure which resources own values. "
            "A file-local search cannot establish non-use: unchanged parents, other roots and nested value flows matter."
        ),
        remediation=(
            "Trace parent and nested modules, root re-exports, remote state, scripts, CI and external users. "
            "Remove a proven-unused export while preserving its resource and safety dependencies. "
            "Preserve uncertain external users with an exact module/output/reason/evidence record in "
            "iac.no-unused-module-outputs.external_outputs. Do not fabricate consumers or visualization references."
        ),
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Code Standards enforces this rule on the complete selected Git HEAD or staged index, including unchanged files and every local root.",
            "The per-file API cannot prove non-use and retains standalone outputs; whole-project callers must supply complete sources to check_project.",
            "Only modules explicitly declared closed-world in iac.no-unused-module-outputs.internal_modules can have unused exports. This reviewed contract asserts that all consumers are in the selected repository; a local module call alone cannot establish that boundary.",
            "Root/public/unknown exports, dynamic projections, unread outputs with preconditions and exact documented external contracts are preserved. Retained unknown exports are not thereby proved live.",
            "Unresolved local modules, malformed HCL/JSON, missing source or stale external contracts fail analysis instead of proving non-use.",
            "This required error cannot be baselined or suppressed with sarj-noqa; no automatic deletion is provided.",
        ),
        examples=(
            RuleExample(
                example_id="unused-child-output",
                title="Remove an unconsumed child export",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.iac(
                        ".sarj-standards.toml",
                        '[iac.no-unused-module-outputs]\ninternal_modules = ["child"]\n',
                    ),
                    ExampleFile.iac("main.tf", 'module "child" { source = "./child" }\n'),
                    ExampleFile.iac("child/outputs.tf", 'output "unused" { value = true }\n'),
                ),
                focus_path=PurePosixPath("child/outputs.tf"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="root-reexport",
                title="Keep a child output consumed by a root contract",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.iac(
                        ".sarj-standards.toml",
                        '[iac.no-unused-module-outputs]\ninternal_modules = ["child"]\n',
                    ),
                    ExampleFile.iac(
                        "main.tf",
                        'module "child" { source = "./child" }\noutput "public" { value = module.child.used }\n',
                    ),
                    ExampleFile.iac("child/outputs.tf", 'output "used" { value = true }\n'),
                ),
                focus_path=PurePosixPath("child/outputs.tf"),
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
        return cls.diagnostics(
            root,
            unused_module_outputs(
                {path.as_posix(): source for path, source in sources.items()},
                external_outputs=external_outputs,
                internal_modules=internal_modules,
            ),
        )

    @classmethod
    def diagnostics(cls, root: Path, outputs: Collection[UnusedModuleOutput]) -> list[Diagnostic]:
        return [
            Diagnostic(
                path=root / output.path,
                line=output.line,
                col=1,
                code=cls.code,
                message=(
                    f"Module output {output.name!r} has no reachable consumer in the selected Git tree. "
                    "Remove the unused export after reviewing external users, or document its exact external contract "
                    "in iac.no-unused-module-outputs.external_outputs."
                ),
                suppressible=False,
                baselineable=False,
                severity=DefaultLevel.ERROR,
            )
            for output in outputs
        ]
