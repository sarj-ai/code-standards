from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import final, override

from sarj_standards.libs.linting.cloudbuild import check_cloudbuild
from sarj_standards.libs.linting.text_rule_base import Finding, Rule, RuleMeta
from sarj_standards.libs.rules.contracts import (
    AutofixPolicy,
    DefaultLevel,
    ExampleFile,
    ExpectedOutcome,
    Language,
    RuleCategory,
    RuleExample,
)


@final
class CloudBuildContract(Rule):
    id = "cloudbuild-contract"
    documentation = RuleMeta(
        code="SARJ315",
        default_level=DefaultLevel.ERROR,
        summary="Cloud Build dependencies and execution fields must have valid, safe semantics.",
        rationale="Forward or duplicate dependencies invalidate a build; substitution into shell source changes executable syntax.",
        remediation="Order uniquely identified steps before their consumers and pass substituted values through env or direct argv.",
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.NONE,
        languages=frozenset({Language.CONFIG}),
        file_patterns=("**/*.yaml", "**/*.yml"),
        references=(
            "https://docs.cloud.google.com/build/docs/configuring-builds/configure-build-step-order",
            "https://docs.cloud.google.com/build/docs/build-config-file-schema",
        ),
        limitations=(
            "This checks step dependencies and execution semantics, not a complete Cloud Build API schema.",
            "Only YAML documents with a Build-shaped steps sequence are selected; other configuration shapes are not guessed.",
            "Unknown execution entrypoints, substitutions supplied by triggers, and effective service identities require prepared-output validation.",
            "YAML aliases retain executable use-site locations, including inherited mappings and aliased argument lists; shared anchor data is not treated as an execution site.",
            "Malformed or duplicate-key YAML raises a parser error instead of a suppressible rule finding.",
        ),
        examples=tuple(
            RuleExample(
                example_id=example_id,
                title=title,
                outcome=outcome,
                files=(ExampleFile(path=PurePosixPath("build.yaml"), source=source),),
                focus_path=PurePosixPath("build.yaml"),
                expected_count=count,
                public=True,
                scenario=scenario,
            )
            for example_id, title, outcome, source, count, scenario in (
                (
                    "forward-dependency",
                    "A build cannot depend on a later step",
                    ExpectedOutcome.MATCH,
                    "steps:\n- name: builder\n  waitFor: [later]\n- name: builder\n  id: later\n",
                    1,
                    "primary",
                ),
                (
                    "prior-dependency",
                    "Dependencies precede their consumers",
                    ExpectedOutcome.NO_MATCH,
                    "steps:\n- name: builder\n  id: first\n- name: builder\n  waitFor: [first]\n",
                    0,
                    "primary",
                ),
                (
                    "alias-shell-source-substitution",
                    "An aliased shell program reports substitution at its executable use",
                    ExpectedOutcome.MATCH,
                    'args: &args [-c, "printf %s $_VALUE"]\nsteps:\n- name: builder\n  entrypoint: bash\n  args: *args\n',
                    1,
                    "cloudbuild-alias-location",
                ),
                (
                    "alias-external-script-arguments",
                    "Aliased external-script arguments retain substitution as argv data",
                    ExpectedOutcome.NO_MATCH,
                    'args: &args [scripts/check.sh, "$_VALUE"]\nsteps:\n- name: builder\n  entrypoint: bash\n  args: *args\n',
                    0,
                    "cloudbuild-alias-location",
                ),
            )
        ),
    )

    @override
    def check(self, path: Path, source: str) -> list[Finding]:
        return check_cloudbuild(path, source, selected="cloudbuild" in path.stem.lower() or "cloudbuild" in path.parts)
