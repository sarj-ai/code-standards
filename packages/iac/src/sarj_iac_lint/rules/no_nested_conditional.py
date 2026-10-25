from __future__ import annotations

from pathlib import PurePosixPath
import re
from typing import TYPE_CHECKING, final, override

from sarj_iac_lint._hcl import header_comment_lines, strip_outer_parentheses, tokens
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
from sarj_iac_lint.rules.no_environment_conditional import NoEnvironmentConditional


if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from sarj_iac_lint._hcl import Attribute, Block


_FIXTURE_DIRS = frozenset({"fixture", "fixtures", "testdata", "generated"})
_ASSERTIONS = frozenset({"validation", "precondition", "postcondition", "assert", "check"})
_GENERATED = re.compile(r"generated.{0,80}(?:do not edit|don't edit)", re.IGNORECASE)
_MIN_CONDITIONALS = 2


@final
class NoNestedConditional(Rule):
    id = "no-nested-conditional"
    code = "SARJ215"
    documentation = RuleDocumentation(
        summary="Prefer a named value or explicit input over chained Terraform conditional selections.",
        rationale="Chained conditional branches obscure the value being selected and scatter deployment policy.",
        remediation=(
            "Extract a branch into a named local or pass a typed input from the caller. Preserve lazy evaluation, "
            "null guards and resource dependencies when extracting an expression."
        ),
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.SAFE,
        default_level=DefaultLevel.WARNING,
        limitations=(
            "Safe fixes select an existing literal leaf only from a closed Boolean-literal conditional tree with homogeneous Boolean, bounded decimal-number or plain quoted-string leaves on one standalone attribute line in top-level locals. All branches are validated; comments, escapes, templates, nulls, references, calls, mixed types and ambiguous source ranges remain manual.",
            "Only direct conditional branches are inspected; independent choices inside calls, collections and templates remain out of scope.",
            "Assertions, generated files, fixtures, testdata and non-.tf inputs are excluded.",
            "An existing deployment-identity diagnostic takes precedence at the same attribute.",
            "This is a review advisory; no automatic extraction or deletion is safe for every expression.",
        ),
        examples=(
            RuleExample(
                example_id="closed-literal-selection",
                title="A closed literal selection already determines the selected value",
                outcome=ExampleOutcome.MATCH,
                scenario="closed-literal-selection",
                files=(
                    ExampleFile.iac(
                        "main.tf",
                        'locals {\n  size = true ? "large" : false ? "medium" : "small"\n}\n',
                    ),
                ),
                fixed_files=(ExampleFile.iac("main.tf", 'locals {\n  size = "large"\n}\n'),),
                focus_path=PurePosixPath("main.tf"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="selected-literal-value",
                title="The selected literal is already explicit",
                outcome=ExampleOutcome.NO_MATCH,
                scenario="closed-literal-selection",
                files=(ExampleFile.iac("main.tf", 'locals {\n  size = "large"\n}\n'),),
                focus_path=PurePosixPath("main.tf"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="nested-selection",
                title="A nested selection hides the selected configuration",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.iac(
                        "main.tf", 'locals {\n  size = var.primary ? "large" : var.secondary ? "medium" : "small"\n}\n'
                    ),
                ),
                focus_path=PurePosixPath("main.tf"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="explicit-selected-value",
                title="The caller supplies the selected value",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.iac(
                        "main.tf",
                        'variable "size" { type = string }\nmodule "service" {\n  source = "./service"\n  size = var.size\n}\n',
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
            or source.count("?") < _MIN_CONDITIONALS
            or any(part.lower() in _FIXTURE_DIRS for part in path.parts)
        ):
            return []
        if _GENERATED.search(" ".join(header_comment_lines(source, leading_only=True))):
            return []
        try:
            blocks = balanced_blocks(source)
        except ValueError:
            return []
        attributes = [attribute for attribute in _attributes(blocks) if _nested_selection(attribute.value)]
        if not attributes:
            return []
        identity_locations = {(finding.line, finding.col) for finding in NoEnvironmentConditional().check(path, source)}
        return [
            Diagnostic(
                path,
                attribute.line,
                attribute.col,
                self.code,
                "Nested conditional selection: extract a branch into a named local or pass an explicit typed input.",
                severity=DefaultLevel.WARNING,
            )
            for attribute in attributes
            if (attribute.line, attribute.col) not in identity_locations
        ]


def _attributes(blocks: tuple[Block, ...]) -> Iterator[Attribute]:
    for block in blocks:
        if block.type not in _ASSERTIONS:
            yield from block.attributes
            yield from _attributes(block.blocks)


def _nested_selection(expression: str) -> bool:
    parts = tokens(expression)
    if parts.count("?") < _MIN_CONDITIONALS:
        return False
    return any(_conditional_branches(branch) for branch in _conditional_branches(parts))


def _conditional_branches(parts: tuple[str, ...]) -> tuple[tuple[str, ...], ...]:
    parts = strip_outer_parentheses(parts)
    depth = 0
    pending = 0
    question = 0
    for index, part in enumerate(parts):
        if part in {"(", "[", "{"}:
            depth += 1
        elif part in {")", "]", "}"}:
            depth -= 1
        elif part == "?" and depth == 0:
            if pending == 0:
                question = index
            pending += 1
        elif part == ":" and depth == 0 and pending:
            pending -= 1
            if pending == 0:
                return parts[question + 1 : index], parts[index + 1 :]
    return ()
