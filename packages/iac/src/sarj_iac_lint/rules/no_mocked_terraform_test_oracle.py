from __future__ import annotations

import json
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, ClassVar, TypeIs, final, override

from sarj_iac_lint._hcl import blocks
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


if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from sarj_iac_lint._hcl import Block

_BANNED_SUFFIXES = (".tftest.hcl", ".tftest.json")
_MOCK_OR_OVERRIDE_BLOCKS = frozenset(
    {
        "mock_data",
        "mock_provider",
        "mock_resource",
        "override_data",
        "override_module",
        "override_resource",
    }
)


@final
class NoMockedTerraformTestOracle(Rule):
    id = "no-mocked-terraform-test-oracle"
    code = "SARJ206"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="Terraform test must not replace provider behavior with repository-owned mock or override data.",
        rationale=(
            "Mocked providers and override blocks can make an IaC test pass against values authored in the same "
            "repository instead of behavior returned by the provider, a rendered plan, or deployed infrastructure."
        ),
        remediation=(
            "Run the Terraform test with a real provider against disposable infrastructure, or move the assertion to "
            "a rendered-plan, provider-API, or runtime contract test."
        ),
        category=RuleCategory.TESTING,
        autofix=AutofixPolicy.NONE,
        aliases=("no-terraform-test-file",),
        limitations=(
            (
                "Only mock_provider, mock_resource, mock_data, and override_* blocks in .tftest.hcl or .tftest.json "
                "files are reported; real-provider plan and apply tests are allowed."
            ),
            (
                "The rule cannot determine whether an override mirrors a stable external fixture, so reviewed "
                "exceptions may use a line-level SARJ206 suppression."
            ),
        ),
        examples=(
            RuleExample(
                example_id="mocked-provider-oracle",
                title="Repository-authored provider values are not infrastructure evidence",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.iac(
                        "tests/routing.tftest.hcl",
                        'mock_provider "aws" {}\n\nrun "routing" {\n  command = plan\n}\n',
                    ),
                ),
                focus_path=PurePosixPath("tests/routing.tftest.hcl"),
                expected_count=1,
                public=True,
                scenario="terraform-provider-evidence",
            ),
            RuleExample(
                example_id="real-provider-contract",
                title="A Terraform test may validate a real plan or apply",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.iac(
                        "tests/routing.tftest.hcl",
                        'provider "aws" {\n  region = "us-east-1"\n}\n\n'
                        'run "routing" {\n  command = plan\n\n'
                        "  assert {\n    condition     = aws_s3_bucket.main.bucket == var.bucket_name\n"
                        '    error_message = "bucket name drifted"\n  }\n}\n',
                    ),
                ),
                focus_path=PurePosixPath("tests/routing.tftest.hcl"),
                expected_count=0,
                public=True,
                scenario="terraform-provider-evidence",
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if not path.name.casefold().endswith(_BANNED_SUFFIXES):
            return []
        if path.name.casefold().endswith(".json"):
            try:
                parsed: object = json.loads(source)  # pyright: ignore[reportAny] -- validated below as JSON containers.
            except json.JSONDecodeError:
                return []
            block_type = next(
                _mock_or_override_json_blocks(  # sarj-noqa: SARJ411 -- syntax keys checked after container narrowing
                    parsed
                ),
                None,
            )
            if block_type is None:
                return []
            line, col = 1, 1
        else:
            offending = next(_mock_or_override_blocks(blocks(source)), None)
            if offending is None:
                return []
            block_type, line, col = offending.type, offending.line, offending.col
        return [
            Diagnostic(
                path=path,
                line=line,
                col=col,
                code=self.code,
                message=(
                    f"Terraform {block_type} is a repository-owned oracle; validate real provider, plan, or runtime behavior."
                ),
            )
        ]


def _mock_or_override_blocks(items: tuple[Block, ...]) -> Iterator[Block]:
    for block in items:
        if block.type in _MOCK_OR_OVERRIDE_BLOCKS:
            yield block
        yield from _mock_or_override_blocks(block.blocks)


def _mock_or_override_json_blocks(value: object) -> Iterator[str]:
    if not _is_json_object(value):
        return
    for key, item in value.items():
        if key in _MOCK_OR_OVERRIDE_BLOCKS:
            yield key
        if key == "run":
            for body in _json_labeled_block_bodies(item):
                yield from (name for name in body if name in _MOCK_OR_OVERRIDE_BLOCKS)


def _json_labeled_block_bodies(value: object) -> Iterator[dict[str, object]]:
    candidates = value.values() if _is_json_object(value) else (value,)
    for candidate in candidates:
        items = candidate if _is_json_array(candidate) else (candidate,)
        for item in items:
            if _is_json_object(item):
                yield item


def _is_json_object(value: object) -> TypeIs[dict[str, object]]:
    # JSON object keys are strings by grammar; json.loads is the only caller.
    return isinstance(value, dict)


def _is_json_array(value: object) -> TypeIs[list[object]]:
    return isinstance(value, list)
