from __future__ import annotations

from pathlib import PurePosixPath
from typing import TYPE_CHECKING, final, override

from sarj_iac_lint._hcl import document, template_expressions, tokens
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
    from collections.abc import Iterator
    from pathlib import Path

    from sarj_iac_lint._hcl import Attribute, Block


_STATEMENT_BUDGET = 12
_VALIDATION_BUDGET = 6
_OPERATORS = frozenset({"==", "!=", "<", ">", "<=", ">=", "&&", "||", "!", "+", "-", "*", "/", "%"})


@final
class ExpressionComplexity(Rule):
    id = "expression-complexity"
    code = "SARJ217"
    documentation = RuleDocumentation(
        default_level=DefaultLevel.ERROR,
        summary="Limit Terraform statement and variable-validation expression complexity.",
        rationale="Large predicates hide independent deployment requirements and make an infrastructure change difficult to review.",
        remediation="Delete redundant checks or name independently meaningful expressions. Preserve lazy evaluation, null guards and dependencies; keep genuine domain validation.",
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Budget: 12 points per attribute, 6 per variable validation condition. Calls, operators and comprehension filters cost one; conditionals and comprehensions cost two.",
            "Scores depend on syntax, not formatting or line count. Actual template expressions count; literal data, type constraints and embedded languages such as CEL do not.",
            "Does not limit variable counts or prove that a necessary security check can be deleted. Malformed HCL is left to native validation.",
        ),
        examples=(
            RuleExample(
                example_id="large-predicate",
                title="A statement combines too many independent checks",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.iac(
                        "main.tf",
                        "locals {\n  ready = var.a > 0 && var.b > 0 && var.c > 0 && var.d > 0 && var.e > 0 && var.f > 0 && var.g > 0\n}\n",
                    ),
                ),
                focus_path=PurePosixPath("main.tf"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="small-domain-check",
                title="A small range validation remains readable",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.iac(
                        "variables.tf",
                        'variable "port" {\n  type = number\n  validation {\n    condition = var.port > 0 && var.port < 65536\n    error_message = "Supply a valid port."\n  }\n}\n',
                    ),
                ),
                focus_path=PurePosixPath("variables.tf"),
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
        findings: list[Diagnostic] = []
        for attribute, validation in _attributes(document(source)):
            budget = _VALIDATION_BUDGET if validation else _STATEMENT_BUDGET
            score = _score(attribute.value)
            if score > budget:
                context = "Variable validation" if validation else "Terraform statement"
                findings.append(
                    Diagnostic(
                        path,
                        attribute.line,
                        attribute.col,
                        self.code,
                        f"{context} complexity {score} exceeds {budget}; delete redundant checks or name independent expressions.",
                        severity=DefaultLevel.ERROR,
                    )
                )
        return findings


def _attributes(block: Block, parent: str = "") -> Iterator[tuple[Attribute, bool]]:
    for attribute in block.attributes:
        if not (block.type == "variable" and attribute.name == "type"):
            yield attribute, block.type == "validation" and parent == "variable" and attribute.name == "condition"
    for child in block.blocks:
        yield from _attributes(child, block.type)


def _score(expression: str) -> int:
    return sum(_token_score(tokens(fragment)) for fragment in (expression, *template_expressions(expression)))


def _token_score(parts: tuple[str, ...]) -> int:
    score = 0
    for index, part in enumerate(parts):
        if part in _OPERATORS and not (part == ">" and parts[index - 1 : index] == ("=",)):
            score += 1
        elif part == "?":
            score += 2
        elif part in {"for", "if"} and parts[index + 1 : index + 2] not in {("=",), (":",)}:
            score += 2 if part == "for" else 1
        elif part == "(" and index > 0 and parts[index - 1].isidentifier() and parts[index - 1] not in {"if", "for"}:
            score += 1
    return score
