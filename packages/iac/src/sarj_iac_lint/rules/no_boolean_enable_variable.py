from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import PurePosixPath
import re
from typing import TYPE_CHECKING, final, override

from sarj_iac_lint._hcl import literal_string, literal_token, strip_outer_parentheses, tokens
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

    from sarj_iac_lint._hcl import Block


_LIFECYCLE = re.compile(r"^[ \t]*(Retire by|Permanent):[ \t]*(.*)$", re.IGNORECASE | re.MULTILINE)
_REMOVAL = re.compile(r"^[ \t]*Remove when:[ \t]*([^\r\n]*)$", re.IGNORECASE | re.MULTILINE)
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_HEREDOC = re.compile(r"<<-?([^\W\d][\w-]*)\r?\n([\s\S]*)\r?\n[ \t]*\1[ \t]*")


@final
class NoBooleanEnableVariable(Rule):
    id = "no-boolean-enable-variable"
    code = "SARJ220"
    documentation = RuleDocumentation(
        default_level=DefaultLevel.ERROR,
        summary="Require a retirement date and removal plan, or a permanent rationale, for Boolean inputs.",
        rationale=(
            "Enable switches add configuration plumbing and keep alternate implementations alive. "
            "An infrastructure change should normally configure its intended behavior directly. Necessary temporary "
            "gates need a deadline for deleting the switch and old path; lasting controls need an explicit rationale."
        ),
        remediation=(
            "Remove the switch and configure the intended behavior directly. If deployments need different values, "
            "pass the actual typed configuration instead. Otherwise add description lines 'Retire by: YYYY-MM-DD' "
            "and 'Remove when: <cutover condition and removal action>', or 'Permanent: <why both settings remain "
            "useful>'. Prefer cutover now; aim to retire temporary gates within 30 days and remove them earlier "
            "when ready. Review every environment, resource address, prerequisite and consumer before removal."
        ),
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "This is an explicit interface policy, not proof that a switch is redundant or that its rationale is truthful.",
            (
                "Matches every top-level .tf variable declaration with explicit bool type, regardless of its name. "
                "This requires classification, without inferring whether the input is temporary or permanent."
            ),
            "An explicit Retire by: or Permanent: description line also opts any other top-level variable into this policy, including migration modes.",
            "Lifecycle records must be unique description lines in a literal quoted string or heredoc. Comments and nested descriptions cannot satisfy them; dynamic descriptions cannot be verified.",
            "Retirement dates are inclusive UTC calendar dates; the finding returns the following day even if the gate is already enabled. There is no hard maximum duration or automatic extension tracking.",
            "Unannotated provider attributes, object members, non-Boolean inputs, inferred types and JSON syntax are excluded. Generators must put the lifecycle description in their generated declarations.",
            "CI must run after the date passes to detect expiry. The rule does not change Terraform planning or apply behavior.",
            "Result caches must include the current UTC date or leave this rule uncached; unchanged source can acquire an expiry finding.",
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
                example_id="temporary-switch-with-removal-plan",
                title="Record the deadline and deletion condition in the input description",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.iac(
                        "main.tf",
                        'variable "private_route_enabled" {\n  type = bool\n  description = "Retire by: 2099-12-31\\nRemove when: All deployments use the private route; delete this input and the legacy route."\n}\n',
                    ),
                ),
                focus_path=PurePosixPath("main.tf"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="permanent-control-without-rationale",
                scenario="permanent",
                title="A permanent exemption needs a rationale",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.iac(
                        "main.tf", 'variable "paging_enabled" {\n  type = bool\n  description = "Permanent:"\n}\n'
                    ),
                ),
                focus_path=PurePosixPath("main.tf"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="permanent-operational-control",
                scenario="permanent",
                title="Explain a lasting per-environment control",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.iac(
                        "main.tf",
                        'variable "paging_enabled" {\n  type = bool\n  description = "Permanent: Production pages on-call; disposable environments must keep paging off."\n}\n',
                    ),
                ),
                focus_path=PurePosixPath("main.tf"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="expired-nonboolean-migration-mode",
                scenario="migration-mode",
                title="Explicit lifecycle records also expire on migration modes",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.iac(
                        "main.tf",
                        'variable "migration_phase" {\n  type = string\n  description = "Retire by: 2000-01-01\\nRemove when: Every deployment uses the new store; delete the old phase and input."\n}\n',
                    ),
                ),
                focus_path=PurePosixPath("main.tf"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="scheduled-nonboolean-migration-mode",
                scenario="migration-mode",
                title="Keep an explicitly scheduled migration mode until cutover",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.iac(
                        "main.tf",
                        'variable "migration_phase" {\n  type = string\n  description = "Retire by: 2099-12-31\\nRemove when: Every deployment uses the new store; delete the old phase and input."\n}\n',
                    ),
                ),
                focus_path=PurePosixPath("main.tf"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    def __init__(self, *, today: date | None = None) -> None:
        self._today = today

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if path.suffix.lower() != ".tf":
            return []
        try:
            declarations = balanced_blocks(source)
        except ValueError:
            return []
        today = self._today if self._today is not None else datetime.now(UTC).date()
        findings: list[Diagnostic] = []
        for block in declarations:
            if block.type != "variable" or len(block.labels) != 1:
                continue
            description = _description(block)
            records = tuple(_LIFECYCLE.finditer(description))
            if not _boolean_input(block) and not records:
                continue
            issue = _lifecycle_issue(records, description, today)
            if issue is None:
                continue
            findings.append(
                Diagnostic(
                    path,
                    block.line,
                    block.col,
                    self.code,
                    f"Input '{block.labels[0]}': {issue}. Prefer direct configuration; otherwise use description lines "
                    "'Retire by: YYYY-MM-DD' and 'Remove when: <cutover condition and removal action>', or "
                    "'Permanent: <why both settings remain useful>'. Review consumers and resource addresses before removal.",
                    baselineable=False,
                    severity=DefaultLevel.ERROR,
                )
            )
        return findings


def _boolean_input(block: Block) -> bool:
    declared_type = block.attribute("type")
    return declared_type is not None and strip_outer_parentheses(tokens(declared_type.value)) == ("bool",)


def _description(block: Block) -> str:
    descriptions = [attribute for attribute in block.attributes if attribute.name == "description"]
    if len(descriptions) != 1:
        return ""
    value = descriptions[0].value.replace("\r\n", "\n")
    literal = literal_string(value)
    if literal is not None:
        return literal.replace("\r\n", "\n")
    token = literal_token(value)
    heredoc = _HEREDOC.fullmatch(token) if token is not None else None
    if heredoc is None:
        return ""
    body = heredoc[2]
    if re.search(r"(?<!\$)\$\{|(?<!%)%\{", body):
        return ""
    return body.replace("\r\n", "\n")


def _lifecycle_issue(records: tuple[re.Match[str], ...], description: str, today: date) -> str | None:
    if not records:
        return "Boolean input has no lifecycle declaration"
    if len(records) != 1:
        return "lifecycle declarations are duplicated or conflicting"
    record = records[0]
    removal = tuple(_REMOVAL.finditer(description))
    if record[1].casefold() == "permanent":
        if not record[2].strip():
            return "permanent input has no rationale"
        return "permanent input also declares a removal condition" if removal else None
    text = record[2].strip()
    if _DATE.fullmatch(text) is None:
        return "retirement date must be a literal YYYY-MM-DD calendar date"
    try:
        deadline = date.fromisoformat(text)
    except ValueError:
        return "retirement date is not a valid calendar date"
    if today > deadline:
        return f"temporary input expired after {deadline.isoformat()} UTC; complete cutover and remove the gate and old path"
    if len(removal) != 1 or not removal[0][1].strip():
        return "temporary input needs exactly one nonempty Remove when: condition and removal action"
    return None
