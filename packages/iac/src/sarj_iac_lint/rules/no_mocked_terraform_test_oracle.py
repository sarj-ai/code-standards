from __future__ import annotations

from pathlib import PurePosixPath
import re
from typing import TYPE_CHECKING, ClassVar, NamedTuple, final, override

from sarj_iac_lint._hcl import blocks, tokens
from sarj_iac_lint.json_boundary import parse_json
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
    from pathlib import Path

    from sarj_iac_lint._hcl import Block

_TEST_SUFFIX = ".tftest.hcl"
_IDENTIFIER_RE = re.compile(r"[A-Za-z_][\w-]*")
_NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?")
_STRING_RE = re.compile(r'"(?:\\.|[^"\\])*"')
_TEMPLATE_RE = re.compile(r"(?<!\$)\$\{|(?<!%)%\{")
_PARENTHESIS_PAIR_LENGTH = 2


class _InjectedLiteral(NamedTuple):
    target: str
    expression: str
    literal: str


@final
class NoMockedTerraformTestOracle(Rule):
    id = "no-mocked-terraform-test-oracle"
    code = "SARJ206"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary=("Warn when a Terraform assertion directly reasserts the same literal injected by a module override."),
        rationale=(
            "An assertion that compares an overridden attribute directly with its authored override value is "
            "self-fulfilling; it does not exercise configuration logic or provider behavior."
        ),
        remediation=(
            "Assert on configuration behavior derived from the override, or add provider-backed/runtime coverage for "
            "provider-dependent claims. Empty mock providers remain valid for fast configuration tests."
        ),
        category=RuleCategory.TESTING,
        autofix=AutofixPolicy.NONE,
        aliases=("no-terraform-test-file",),
        limitations=(
            (
                "Only direct literal entries in outputs maps on file-level or run-level override_module "
                "blocks in .tftest.hcl are compared. Run overrides replace "
                "file-level overrides for the entire target."
            ),
            (
                "Resource/data overrides replace computed provider attributes, not configured or noncomputed "
                "default attributes. Without provider-schema proof, these overrides are excluded, even for "
                "genuine computed-value reassertions. Mock providers, generated defaults, transformed assertions, "
                "JSON test syntax, provider-scoped overrides, and dynamic expressions are also excluded."
            ),
        ),
        examples=(
            RuleExample(
                example_id="direct-override-reassertion",
                title="Assertion repeats its own module output override",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.iac(
                        "tests/routing.tftest.hcl",
                        "override_module {\n"
                        "  target = module.storage\n"
                        '  outputs = { arn = "fixture-arn" }\n'
                        "}\n\n"
                        'run "routing" {\n'
                        "  assert {\n"
                        '    condition     = module.storage.arn == "fixture-arn"\n'
                        '    error_message = "ARN mismatch"\n'
                        "  }\n"
                        "}\n",
                    ),
                ),
                focus_path=PurePosixPath("tests/routing.tftest.hcl"),
                expected_count=1,
                public=True,
                scenario="terraform-provider-evidence",
            ),
            RuleExample(
                example_id="mock-backed-configuration-test",
                title="Empty mock provider validates configured plan behavior",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.iac(
                        "tests/routing.tftest.hcl",
                        'mock_provider "aws" {}\n\n'
                        'run "routing" {\n  command = plan\n\n'
                        "  assert {\n    condition     = aws_s3_bucket.main.bucket == var.bucket_name\n"
                        '    error_message = "bucket configuration drifted"\n  }\n}\n',
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
        if not path.name.casefold().endswith(_TEST_SUFFIX):
            return []
        try:
            top_level = blocks(source)
        except ValueError:
            return []
        file_overrides = _injected_literals(top_level)
        findings: list[Diagnostic] = []
        for run in (block for block in top_level if block.type == "run"):
            shadowed = {
                "".join(tokens(target.value))
                for block in run.blocks
                if block.type == "override_module" and (target := block.attribute("target")) is not None
            }
            injected = (
                *(item for item in file_overrides if item.target not in shadowed),
                *_injected_literals(run.blocks),
            )
            findings.extend(_run_assertion_findings(run, injected, path, self.code))
        return findings


def _injected_literals(items: tuple[Block, ...]) -> tuple[_InjectedLiteral, ...]:
    injected: list[_InjectedLiteral] = []
    for block in items:
        if block.type != "override_module":
            continue
        target = block.attribute("target")
        values = block.attribute("outputs")
        if target is None or values is None:
            continue
        target_expression = "".join(tokens(target.value))
        injected.extend(
            _InjectedLiteral(target_expression, f"{target_expression}.{key}", literal)
            for key, literal in _direct_literal_entries(values.value)
        )
    return tuple(injected)


def _direct_literal_entries(value: str) -> tuple[tuple[str, str], ...]:
    value_tokens = tokens(value)
    if not value_tokens or value_tokens[0] != "{" or value_tokens[-1] != "}":
        return ()
    entries: list[tuple[str, str]] = []
    index = 1
    while index < len(value_tokens) - 1:
        key = _entry_key(value_tokens[index])
        if key is None or value_tokens[index + 1] not in {"=", ":"}:
            return ()
        index += 2
        start = index
        end = _entry_expression_end(value_tokens, start)
        if end is None:
            return ()
        index = end
        expression = value_tokens[start:index]
        if (literal := _literal_value(expression)) is not None:
            entries.append((key, literal))
        if value_tokens[index] == ",":
            index += 1
    return tuple(entries)


def _entry_expression_end(value_tokens: tuple[str, ...], start: int) -> int | None:
    index = start
    closers: list[str] = []
    while index < len(value_tokens) - 1:
        lexeme = value_tokens[index]
        if not closers and (
            lexeme == ","
            or (index > start and _entry_key(lexeme) is not None and value_tokens[index + 1] in {"=", ":"})
        ):
            break
        if lexeme in {"{", "[", "("}:
            closers.append({"{": "}", "[": "]", "(": ")"}[lexeme])
        elif lexeme in {"}", "]", ")"} and (not closers or closers.pop() != lexeme):
            return None
        index += 1
    return index if not closers and index > start else None


def _entry_key(token: str) -> str | None:
    if token.startswith('"'):
        try:
            decoded = parse_json(token)
        except ValueError:
            return None
        if not isinstance(decoded, str):
            return None
        token = decoded
    return token if _IDENTIFIER_RE.fullmatch(token) else None


def _literal_value(expression: tuple[str, ...]) -> str | None:
    literal = "".join(expression)
    if _NUMBER_RE.fullmatch(literal):
        return literal
    if len(expression) != 1:
        return None
    if literal in {"true", "false", "null"}:
        return literal
    if _STRING_RE.fullmatch(literal) and not _TEMPLATE_RE.search(literal):
        return literal
    return None


def _run_assertion_findings(
    run: Block, injected: tuple[_InjectedLiteral, ...], path: Path, code: str
) -> list[Diagnostic]:
    findings: list[Diagnostic] = []
    for assertion in (block for block in run.blocks if block.type == "assert"):
        condition = assertion.attribute("condition")
        if condition is None:
            continue
        matched = next((item for item in injected if _directly_reasserts(condition.value, item)), None)
        if matched is None:
            continue
        findings.append(
            Diagnostic(
                path=path,
                line=condition.line,
                col=condition.col,
                code=code,
                message=(
                    f"Assertion directly repeats the injected `{matched.expression}` literal; assert on "
                    "derived configuration behavior instead."
                ),
            )
        )
    return findings


def _directly_reasserts(condition: str, injected: _InjectedLiteral) -> bool:
    condition_tokens = tokens(condition)
    while (
        len(condition_tokens) >= _PARENTHESIS_PAIR_LENGTH and condition_tokens[0] == "(" and condition_tokens[-1] == ")"
    ):
        condition_tokens = condition_tokens[1:-1]
    expected = tokens(f"{injected.expression} == {injected.literal}")
    reversed_expected = tokens(f"{injected.literal} == {injected.expression}")
    return condition_tokens in {expected, reversed_expected}
