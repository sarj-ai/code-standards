from __future__ import annotations

from pathlib import Path, PurePosixPath
import re
import shlex
from typing import final, override

import yaml
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode

from sarj_standards.libs.linting.text_rule_base import Finding, Rule, RuleMeta
from sarj_standards.libs.linting.text_rules._slack_payload import payload_markup_uses, references_github_environment
from sarj_standards.libs.rules import DefaultLevel, ExampleFile, ExpectedOutcome, Language, RuleCategory, RuleExample
from sarj_standards.libs.yaml_boundary import mapping_items, parse_yaml_documents, sequence_items


_EVENT = re.compile(r"\$\{\{\s*github\.(?:event\.pull_request\.(?:title|head\.ref)|head_ref)\s*\}\}")
_OUTPUT = re.compile(r"\$\{\{\s*steps\.([a-zA-Z_][a-zA-Z_0-9-]*)\.outputs\.([a-zA-Z_][a-zA-Z_0-9-]*)\s*\}\}")
_SLACK_ACTION = re.compile(r"slackapi/slack-github-action@[a-zA-Z0-9_./-]+")
_MAX_SOURCE = 131_072
_BUILDER_COMMAND_WORDS = 2
_PR_EVENTS = frozenset({"pull_request", "pull_request_target"})
_PR_TRIGGERS = _PR_EVENTS | {"workflow_call"}
_TRIGGER_PROFILE = _PR_TRIGGERS | {"push", "workflow_dispatch"}
_EVENT_GUARD = re.compile(r"github\.event_name\s*(==|!=)\s*'([^']*)'", re.IGNORECASE | re.ASCII)


def _example(markup: str) -> tuple[ExampleFile, ...]:
    workflow = (
        "name: Notify\non: pull_request\njobs:\n  notify:\n    runs-on: ubuntu-latest\n    steps:\n"
        "      - id: payload\n        env:\n          TITLE: ${{ github.event.pull_request.title }}\n"
        "        run: bash scripts/slack_payload.sh\n"
        "      - uses: slackapi/slack-github-action@v4\n        with:\n"
        "          webhook-type: incoming-webhook\n"
        "          webhook: ${{ secrets.SLACK_WEBHOOK }}\n"
        "          payload: ${{ steps.payload.outputs.payload }}\n"
    )
    builder = (
        "#!/usr/bin/env bash\n"
        'payload=$(jq -nc --arg title "$TITLE" \'{blocks: [{type: "section", '
        f'text: {{type: "{markup}", text: $title}}' + "}]}')\n"
        'printf \'payload=%s\\n\' "$payload" >>"$GITHUB_OUTPUT"\n'
    )
    return (
        ExampleFile(path=PurePosixPath(".github/workflows/notify.yml"), source=workflow),
        ExampleFile(path=PurePosixPath("scripts/slack_payload.sh"), source=builder),
    )


def _fields(node: Node | None) -> dict[str, Node]:
    if not isinstance(node, MappingNode):
        return {}
    return {_text(key): value for key, value in mapping_items(node) if isinstance(key, ScalarNode)}


def _text(node: Node | None) -> str:
    if not isinstance(node, ScalarNode):
        return ""
    value: object = node.value  # pyright: ignore[reportAny] -- PyYAML scalar parser boundary.
    return value if isinstance(value, str) else ""


def _environment(*nodes: Node | None) -> frozenset[str]:
    values: dict[str, str] = {}
    for node in nodes:
        values.update({name: _text(value) for name, value in _fields(node).items()})
    return frozenset(name for name, value in values.items() if _EVENT.fullmatch(value))


def _program(path: Path, top: dict[str, Node], job: dict[str, Node], step: dict[str, Node]) -> str | None:
    source = _text(step.get("run"))
    if not source or len(source) > _MAX_SOURCE:
        return None
    # Inline programs have their own complete source. An external builder is
    # admitted only as a literal, argument-free invocation inside this checkout.
    defaults = {
        **_fields(_fields(top.get("defaults")).get("run")),
        **_fields(_fields(job.get("defaults")).get("run")),
    }
    if "jq" in source:
        shell = _text(step.get("shell") or defaults.get("shell"))
        runner = _text(job.get("runs-on"))
        if shell in {"bash", "sh"} or (not shell and runner in {"ubuntu-latest", "ubuntu-24.04", "ubuntu-22.04"}):
            return source
        return None
    argument = _builder_script_argument(source)
    if argument is None:
        return None
    if path.parent.name != "workflows" or path.parent.parent.name != ".github":
        return None
    root = path.parent.parent.parent.resolve()
    directory = _text(step.get("working-directory") or defaults.get("working-directory"))
    if (
        "$" in directory
        or any(character in argument for character in "$*?[]{}\\\n;|&<>")
        or PurePosixPath(argument).is_absolute()
    ):
        return None
    script = root / directory / argument
    try:
        if not script.resolve().is_relative_to(root) or script.stat().st_size > _MAX_SOURCE:
            return None
        return script.read_bytes().decode("utf-8")
    except OSError, UnicodeError:
        return None


def _builder_script_argument(source: str) -> str | None:
    source = source.strip(" \t\n")
    if "\n" in source or "\r" in source:
        return None
    try:
        words = shlex.split(source)
    except ValueError:
        return None
    if len(words) != _BUILDER_COMMAND_WORDS or words[0] not in {"bash", "sh"}:
        return None
    return words[1]


def _slack_outputs(steps: list[dict[str, Node]], events: frozenset[str]) -> dict[str, set[str]]:
    outputs: dict[str, set[str]] = {}
    producers = {_text(step.get("id")): index for index, step in enumerate(steps) if "id" in step}
    for index, step in enumerate(steps):
        if not _SLACK_ACTION.fullmatch(_text(step.get("uses"))):
            continue
        inputs = _fields(step.get("with"))
        if _text(inputs.get("webhook-type")) != "incoming-webhook" and _text(inputs.get("method")) not in {
            "chat.postMessage",
            "chat.postEphemeral",
        }:
            continue
        match = _OUTPUT.fullmatch(_text(inputs.get("payload")))
        if match is None:
            continue
        producer = producers.get(match[1], index)
        if producer >= index:
            continue
        consumer_events = _guarded_events(step.get("if"), events)
        flow_events = _guarded_events(steps[producer].get("if"), consumer_events)
        if flow_events & _PR_EVENTS:
            outputs.setdefault(match[1], set()).add(match[2])
    return outputs


@final
class SlackEventTextInMrkdwn(Rule):
    id = "slack-event-text-in-mrkdwn"
    documentation = RuleMeta(
        code="SARJ316",
        default_level=DefaultLevel.WARNING,
        summary="Keep proven event-controlled text out of Slack markup controls.",
        rationale="JSON quoting does not neutralize Slack markup controls in pull-request titles or branch names.",
        remediation="Use plain_text for event-controlled text, or deliberately encode reserved Slack controls before combining it with trusted markup.",
        category=RuleCategory.SECURITY,
        languages=frozenset({Language.CONFIG}),
        file_patterns=("**/*.yml", "**/*.yaml"),
        limitations=(
            "Requires a file immediately inside .github/workflows, an official Slack action consuming a same-job step output, and a direct pull-request title/head-ref environment binding.",
            "Recognizes scalar, list or mapping trigger selectors using pull_request, pull_request_target, workflow_call, push and workflow_dispatch; at least one PR-capable trigger is required. Unknown, missing and review-event selectors abstain. A reusable workflow may inherit a PR caller; caller graphs are not modeled.",
            "Literal false and whole github.event_name equality/inequality guards filter job, producer and consumer events. Other conditions are admitted only with PR-only remaining event possibilities; unresolved mixed-event guards abstain. General condition satisfiability is not modeled.",
            "Prior inline shell references to GITHUB_ENV invalidate inherited workflow/job environment bindings; explicit producer-step bindings remain eligible. Dynamic aliases, external builders in prior steps, and action-managed environment mutations are not modeled.",
            "Recognizes one jq constructor assignment and one unchanged printf to GITHUB_OUTPUT, optionally preceded by set -euo pipefail. Unknown shell commands, jq transformations, aliases, payload-file transport and custom Slack clients abstain.",
            "Checks Block Kit section text and section fields. Header text only accepts plain_text and is not a mrkdwn sink. JSON serialization alone is not a Slack escape. This concerns reserved entity/link/mention controls; it does not claim to sanitize every formatting delimiter.",
            "An external builder must be a literal argument-free bash/sh invocation, bounded to the same checkout. Only selected workflows are analyzed; selecting a builder alone does not discover its callers.",
        ),
        examples=(
            RuleExample(
                example_id="raw-event-markup",
                title="A PR title reaches Slack markup unchanged",
                outcome=ExpectedOutcome.MATCH,
                files=_example("mrkdwn"),
                focus_path=PurePosixPath(".github/workflows/notify.yml"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="plain-event-text",
                title="A PR title remains plain text",
                outcome=ExpectedOutcome.NO_MATCH,
                files=_example("plain_text"),
                focus_path=PurePosixPath(".github/workflows/notify.yml"),
                expected_count=0,
                public=True,
            ),
        ),
    )

    @override
    def check(self, path: Path, source: str) -> list[Finding]:
        if (
            path.suffix not in {".yml", ".yaml"}
            or path.parent.name != "workflows"
            or path.parent.parent.name != ".github"
            or "slackapi/slack-github-action@" not in source
        ):
            return []
        try:
            documents = parse_yaml_documents(source)
        except ValueError, TypeError, yaml.YAMLError:
            return []
        if len(documents) != 1:
            return []
        node: object = yaml.compose(source)  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType] -- PyYAML compose parser boundary.
        top = _fields(node) if isinstance(node, MappingNode) else {}
        events = _possible_events(top.get("on"))
        if not events & _PR_EVENTS:
            return []
        findings: list[Finding] = []
        for job_node in _fields(top.get("jobs")).values():
            findings.extend(self._job_findings(path, top, _fields(job_node), events))
        return findings

    def _job_findings(
        self, path: Path, top: dict[str, Node], job: dict[str, Node], events: frozenset[str]
    ) -> list[Finding]:
        job_events = _guarded_events(job.get("if"), events)
        if not job_events & _PR_EVENTS:
            return []
        step_nodes = job.get("steps")
        if not isinstance(step_nodes, SequenceNode):
            return []
        steps = [_fields(node) for node in sequence_items(step_nodes)]
        identifiers = [_text(step.get("id")) for step in steps if "id" in step]
        if len(identifiers) != len(set(identifiers)):
            return []
        outputs = _slack_outputs(steps, job_events)
        environments = _step_environments(steps, top.get("env"), job.get("env"))
        findings: list[Finding] = []
        for step in steps:
            identifier = _text(step.get("id"))
            if identifier not in outputs:
                continue
            tainted = environments[identifier]
            program = _program(path, top, job, step) if tainted else None
            if program is None:
                continue
            count = sum(
                payload_markup_uses(program, output=output, tainted_environment=tainted)
                for output in outputs[identifier]
            )
            run = step.get("run")
            if count and isinstance(run, ScalarNode):
                findings.append(
                    Finding(
                        path,
                        run.start_mark.line + 1,
                        self.documentation.code,
                        "Event-controlled text reaches Slack mrkdwn without a proven escape; use plain_text or encode reserved controls at the boundary.",
                    )
                )
        return findings


def _possible_events(node: Node | None) -> frozenset[str]:
    if isinstance(node, ScalarNode):
        events = {_text(node)}
    elif isinstance(node, SequenceNode):
        events = {_text(item) for item in sequence_items(node)}
    elif isinstance(node, MappingNode):
        fields = _fields(node)
        if any(
            not isinstance(options, MappingNode)
            and not (isinstance(options, ScalarNode) and options.tag == "tag:yaml.org,2002:null")
            for options in fields.values()
        ):
            return frozenset()
        events = set(fields)
    else:
        return frozenset()
    if not events <= _TRIGGER_PROFILE:
        return frozenset()
    if "workflow_call" in events:
        events.update(_TRIGGER_PROFILE)
        events.remove("workflow_call")
    return frozenset(events)


def _guarded_events(node: Node | None, events: frozenset[str]) -> frozenset[str]:
    if node is None:
        return events
    if not isinstance(node, ScalarNode):
        return frozenset()
    expression = _text(node).strip(" \t\r\n")
    if expression.startswith("${{") and expression.endswith("}}"):
        expression = expression[3:-2].strip(" \t\r\n")
    if expression.lower() == "false":
        return frozenset()
    match = _EVENT_GUARD.fullmatch(expression)
    if match is None:
        return events if events <= _PR_EVENTS else frozenset()
    operator, expected = match.groups()
    if not expected.isascii():
        return frozenset()
    matching = frozenset(event for event in events if event.lower() == expected.lower())
    return matching if operator == "==" else events - matching


def _step_environments(
    steps: list[dict[str, Node]], workflow: Node | None, job: Node | None
) -> dict[str, frozenset[str]]:
    environments: dict[str, frozenset[str]] = {}
    inherited = True
    for step in steps:
        nodes = (workflow, job, step.get("env")) if inherited else (step.get("env"),)
        environments[_text(step.get("id"))] = _environment(*nodes)
        if references_github_environment(_text(step.get("run"))):
            inherited = False
    return environments
