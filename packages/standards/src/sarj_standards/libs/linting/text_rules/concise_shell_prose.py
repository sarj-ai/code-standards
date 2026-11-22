from __future__ import annotations

from dataclasses import dataclass
from operator import itemgetter
from pathlib import Path, PurePosixPath
import re
from typing import TYPE_CHECKING, Literal, final, override

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from sarj_standards.libs.linting.shell_ast import parse_shell
from sarj_standards.libs.linting.text_rule_base import Finding, Rule, RuleMeta
from sarj_standards.libs.rules import DefaultLevel, ExampleFile, ExpectedOutcome, Language, RuleCategory, RuleExample


if TYPE_CHECKING:
    from collections.abc import Iterator


_COMMENT_LINES = 2
_HELP_LINES = 3
_WORDS = 40
_DIRECTIVE = re.compile(r"^(?:shellcheck\b|shfmt\b|sarj-noqa\b|noqa\b|SBATCH\b|PBS\b|BSUB\b)", re.IGNORECASE)
_LEGAL = re.compile(
    r"^\s*(?:copyright\b|spdx-license-identifier:|permission is hereby granted\b|licensed under\b|all rights reserved\b)",
    re.IGNORECASE,
)
_HELP = frozenset({"--help", "-h"})

_SUPPRESSION = re.compile(
    r"^sarj-noqa:\s*(?P<codes>SARJ[0-9]{3}(?:\s*,\s*SARJ[0-9]{3})*)\s+(?:--|—)\s+\S", re.IGNORECASE
)


class _Position(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, hide_input_in_errors=True)
    line: int = Field(alias="Line", gt=0)
    column: int = Field(alias="Col", gt=0)


class _Descriptor(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, hide_input_in_errors=True)
    value: str = Field(alias="Value")


class _Heredoc(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, hide_input_in_errors=True)
    operator: Literal["<<", "<<-"] = Field(alias="Op")
    descriptor: _Descriptor | None = Field(default=None, alias="N")
    body: JsonValue = Field(alias="Hdoc")


@dataclass(frozen=True, slots=True)
class _HelpText:
    text: str
    line: int


def _example(source: str) -> tuple[ExampleFile, ...]:
    return (ExampleFile(path=PurePosixPath("app.sh"), source=source),)


@final
class ConciseShellProse(Rule):
    id = "concise-shell-prose"
    documentation = RuleMeta(
        code="SARJ317",
        default_level=DefaultLevel.ERROR,
        summary="Keep shell comments and help output concise; preserve machine directives and data.",
        rationale="Source should contain executable behavior and rare concise constraints. Comment walls and operational runbooks in help heredocs duplicate documentation.",
        remediation="Keep necessary comments within two nonempty lines and 40 words, and literal help output within three nonempty lines and 40 words. Move longer instructions to existing documentation; use an exact-code justified exception for a required longer contract.",
        category=RuleCategory.MAINTAINABILITY,
        languages=frozenset({Language.CONFIG}),
        file_patterns=("**/*.sh", "**/*.bash"),
        limitations=(
            "Uses the pinned native shell AST: quoted hashes and heredoc data are not comments. Machine directives and legal notices remain protected. Parser failures propagate rather than silently returning clean results.",
            "Help heredocs require a literal --help/-h equality test and an argument-free cat writing to stdout in its then branch. Other redirects/consumers, dynamic words and shadowed cat abstain. Delimiter names do not establish documentation intent.",
            "No automatic deletion: help is observable output. Exact-code justified suppressions must be actual shell comments on the diagnostic line or preceding line; help findings anchor the cat command so the output need not change. The explicit prose budget is a style policy, not proof that every long constraint is incorrect.",
        ),
        examples=(
            RuleExample(
                example_id="long-comments",
                scenario="comments",
                title="An ordinary comment wall is rejected",
                outcome=ExpectedOutcome.MATCH,
                files=_example("# First explanation.\n# More explanation.\n# Yet more explanation.\nrun\n"),
                focus_path=PurePosixPath("app.sh"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="short-constraint",
                scenario="comments",
                title="A concise hidden constraint remains local",
                outcome=ExpectedOutcome.NO_MATCH,
                files=_example("# The remote token expires before this lock can be retried.\nrun\n"),
                focus_path=PurePosixPath("app.sh"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="help-runbook",
                scenario="help",
                title="A help branch is not a runbook",
                outcome=ExpectedOutcome.MATCH,
                files=_example(
                    "if [[ ${1:-} == --help ]]; then\ncat <<'DOC'\nUsage: app\nConfigure the account.\nPrepare the workspace.\nRead the deployment runbook.\nDOC\nfi\n"
                ),
                focus_path=PurePosixPath("app.sh"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="configuration-data",
                scenario="help",
                title="Configuration heredocs are data",
                outcome=ExpectedOutcome.NO_MATCH,
                files=_example(
                    "cat >settings.ini <<'DATA'\n[service]\nname = 'worker'\nmode = 'safe'\nregion = 'west'\nDATA\n"
                ),
                focus_path=PurePosixPath("app.sh"),
                expected_count=0,
                public=True,
            ),
        ),
    )

    @override
    def check(self, path: Path, source: str) -> list[Finding]:
        if path.suffix.casefold() not in {".sh", ".bash"}:
            return []
        nodes = list(_walk(dict(parse_shell(source))))
        findings = [*_comment_budgets(path, source, nodes), *_help_findings(path, nodes)]
        exempt = _suppressed_lines(nodes)
        findings = [finding for finding in findings if finding.line not in exempt and finding.line - 1 not in exempt]
        return sorted(
            {(finding.line, finding.message): finding for finding in findings}.values(),
            key=lambda finding: finding.line,
        )


def _comment_budgets(path: Path, source: str, nodes: list[dict[str, JsonValue]]) -> list[Finding]:
    source_lines = source.splitlines()
    comments = sorted(
        (
            (node["Text"], _line(node), _standalone(node, source_lines))
            for node in nodes
            if "Hash" in node and isinstance(node.get("Text"), str)
        ),
        key=itemgetter(1),
    )
    findings: list[Finding] = []
    paragraph: list[tuple[str, int]] = []
    for text, line, standalone in comments:
        if not isinstance(text, str):
            continue
        if paragraph and (not standalone or any(part.strip() for part in source_lines[paragraph[-1][1] : line - 1])):
            findings.extend(_comment_findings(path, paragraph))
            paragraph = []
        if _DIRECTIVE.match(text.strip()) or (line == 1 and text.strip().startswith(("!/", "! /"))):
            findings.extend(_comment_findings(path, paragraph))
            paragraph = []
        elif not standalone:
            findings.extend(_comment_findings(path, [(text, line)]))
        else:
            paragraph.append((text, line))
    findings.extend(_comment_findings(path, paragraph))
    return findings


def _help_findings(path: Path, nodes: list[dict[str, JsonValue]]) -> list[Finding]:
    findings: list[Finding] = []
    shadowed_cat = any(
        node.get("Type") == "FuncDecl" and isinstance(name := node.get("Name"), dict) and name.get("Value") == "cat"
        for node in nodes
    )
    if not shadowed_cat:
        for node in nodes:
            if node.get("Type") != "IfClause" or not _help_condition(node.get("Cond")):
                continue
            for statement in _walk(node.get("Then"), include_functions=False):
                body = _help_heredoc(statement)
                if body is not None and _over_budget(body.text, _HELP_LINES):
                    findings.append(
                        Finding(
                            path,
                            body.line,
                            "SARJ317",
                            "Keep help within three nonempty lines and 40 words; move operational instructions to documentation.",
                        )
                    )
    return findings


def _walk(value: JsonValue, *, include_functions: bool = True) -> Iterator[dict[str, JsonValue]]:
    match value:
        case dict():
            if not include_functions and value.get("Type") == "FuncDecl":
                return
            yield value
            for child in value.values():
                yield from _walk(child, include_functions=include_functions)
        case list():
            for child in value:
                yield from _walk(child, include_functions=include_functions)
        case _:
            return


def _line(node: dict[str, JsonValue]) -> int:
    return _Position.model_validate(node["Pos"]).line


def _standalone(node: dict[str, JsonValue], lines: list[str]) -> bool:
    position = _Position.model_validate(node["Pos"])
    return position.line <= len(lines) and not lines[position.line - 1].encode("utf-8")[: position.column - 1].strip()


def _literal(word: JsonValue) -> str | None:
    if not isinstance(word, dict):
        return None
    parts = word.get("Parts")
    if not isinstance(parts, list):
        return None
    values: list[str] = []
    for part in parts:
        if not isinstance(part, dict):
            return None
        value = (
            _literal(part)
            if part.get("Type") == "DblQuoted"
            else part.get("Value")
            if part.get("Type") in {"Lit", "SglQuoted"}
            else None
        )
        if not isinstance(value, str):
            return None
        values.append(value)
    return "".join(values)


def _help_condition(condition: JsonValue) -> bool:
    if not isinstance(condition, list) or len(condition) != 1 or not isinstance(condition[0], dict):
        return False
    statement = condition[0]
    if statement.get("Negated"):
        return False
    command = statement.get("Cmd")
    if not isinstance(command, dict) or command.get("Type") != "TestClause":
        return False
    test = command.get("X")
    return (
        isinstance(test, dict)
        and test.get("Type") == "BinaryTest"
        and test.get("Op") in {"=", "=="}
        and (_literal(test.get("X")) in _HELP or _literal(test.get("Y")) in _HELP)
    )


def _help_heredoc(statement: dict[str, JsonValue]) -> _HelpText | None:
    command = statement.get("Cmd")
    if not isinstance(command, dict) or command.get("Type") != "CallExpr":
        return None
    arguments = command.get("Args")
    if not isinstance(arguments, list) or [_literal(argument) for argument in arguments] != ["cat"]:
        return None
    redirects = statement.get("Redirs")
    if not isinstance(redirects, list) or len(redirects) != 1 or not isinstance(redirects[0], dict):
        return None
    if redirects[0].get("Op") not in {"<<", "<<-"}:
        return None
    redirect = _Heredoc.model_validate(redirects[0])
    if redirect.descriptor is not None and redirect.descriptor.value != "0":
        return None
    text = _literal(redirect.body)
    return _HelpText(text, _line(statement)) if text is not None else None


def _over_budget(text: str, lines: int) -> bool:
    return len([line for line in text.splitlines() if line.strip()]) > lines or len(text.split()) > _WORDS


def _comment_findings(path: Path, paragraph: list[tuple[str, int]]) -> list[Finding]:
    text = "\n".join(part for part, _ in paragraph)
    if not paragraph or _LEGAL.search(text) or not _over_budget(text, _COMMENT_LINES):
        return []
    return [
        Finding(
            path,
            paragraph[0][1],
            "SARJ317",
            "Keep a necessary constraint within two comment lines and 40 words; move longer prose to documentation.",
        )
    ]


def _suppressed_lines(nodes: list[dict[str, JsonValue]]) -> set[int]:
    lines: set[int] = set()
    for node in nodes:
        if "Hash" not in node:
            continue
        text = node.get("Text")
        match = _SUPPRESSION.match(text.strip()) if isinstance(text, str) else None
        if match is not None and "SARJ317" in {code.strip().upper() for code in match.group("codes").split(",")}:
            lines.add(_line(node))
    return lines
