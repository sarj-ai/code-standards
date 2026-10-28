from typing import TYPE_CHECKING

import pytest
from sarj_rule_contracts.examples import verify_examples

from sarj_standards.libs.linting.text_rules.slack_event_text_in_mrkdwn import SlackEventTextInMrkdwn
from sarj_standards.libs.repository.rule_examples import selected
from sarj_standards.libs.rules import RuleSelector


if TYPE_CHECKING:
    from pathlib import Path


def test_documented_examples() -> None:
    rule = selected(RuleSelector.parse("text:slack-event-text-in-mrkdwn"))
    verify_examples(rule.spec.examples, rule.analyze)


_WORKFLOW = (
    "name: Notify\non: pull_request\njobs:\n  notify:\n    runs-on: ubuntu-latest\n    steps:\n"
    "      - id: build\n        env:\n          TITLE: ${{ github.event.pull_request.title }}\n"
    "        run: bash scripts/payload.sh\n"
    "      - uses: slackapi/slack-github-action@v4\n        with:\n"
    "          webhook-type: incoming-webhook\n"
    "          payload: ${{ steps.build.outputs.payload }}\n"
)
_SCRIPT = (
    "#!/usr/bin/env bash\nset -euo pipefail\n"
    'payload=$(jq -nc --arg title "${TITLE:?}" '
    '\'{blocks: [{type: "section", text: {type: "mrkdwn", text: "PR: \\($title)"}}]}\')\n'
    'printf \'payload=%s\\n\' "$payload" >>"${GITHUB_OUTPUT:?}"\n'
)


def _analyze(tmp_path: Path, workflow: str = _WORKFLOW, script: str = _SCRIPT) -> int:
    path = tmp_path / ".github/workflows/notify.yml"
    path.parent.mkdir(parents=True)
    path.write_text(workflow)
    builder = tmp_path / "scripts/payload.sh"
    builder.parent.mkdir()
    builder.write_text(script)
    return len(SlackEventTextInMrkdwn().check(path, workflow))


def test_external_builder_has_proven_slack_transport(tmp_path: Path) -> None:
    assert _analyze(tmp_path) == 1


@pytest.mark.parametrize(
    ("program", "expected"),
    [("bash\nscripts/payload.sh\n", 0), ("bash scripts/payload.sh\n", 1)],
    ids=("separate-commands", "terminal-newline"),
)
def test_external_builder_requires_one_command_line(tmp_path: Path, program: str, expected: int) -> None:
    workflow = _WORKFLOW.replace(
        "        run: bash scripts/payload.sh\n",
        "        run: |\n" + "".join(f"          {line}\n" for line in program.splitlines()),
    )
    assert _analyze(tmp_path, workflow=workflow) == expected


@pytest.mark.parametrize("separator", ["\u00a0", "\r"], ids=("nonbreaking-space", "carriage-return"))
def test_jq_constructor_rejects_non_native_whitespace(tmp_path: Path, separator: str) -> None:
    script = _SCRIPT.replace("'{blocks:", "'{blocks:" + separator)
    assert _analyze(tmp_path, script=script) == 0


def test_jq_quoted_string_preserves_nonbreaking_space(tmp_path: Path) -> None:
    script = _SCRIPT.replace('"PR: ', '"PR:\u00a0')
    assert _analyze(tmp_path, script=script) == 1


@pytest.mark.parametrize(
    ("workflow", "script"),
    [
        (_WORKFLOW, _SCRIPT.replace('"mrkdwn"', '"plain_text"')),
        (_WORKFLOW.replace("github.event.pull_request.title", "github.repository"), _SCRIPT),
        (_WORKFLOW.replace("slackapi/slack-github-action", "example/json-consumer"), _SCRIPT),
        (_WORKFLOW.replace("incoming-webhook", "unrecognized-transport"), _SCRIPT),
        (_WORKFLOW.replace("steps.build.outputs.payload", "steps.other.outputs.payload"), _SCRIPT),
        (_WORKFLOW, _SCRIPT.replace('$payload" >>', '$other" >>')),
        (_WORKFLOW, _SCRIPT.replace("GITHUB_OUTPUT", "OTHER_FILE")),
        (_WORKFLOW, _SCRIPT.replace("--arg title", "--arg other")),
        (_WORKFLOW, _SCRIPT.replace('"${TITLE:?}"', "${TITLE:?}")),
        (_WORKFLOW, _SCRIPT.replace('"PR: \\($title)"', '"PR: \\($title | @html)"')),
        (_WORKFLOW, _SCRIPT.replace("set -euo pipefail", "TITLE=trusted")),
        (_WORKFLOW, _SCRIPT.replace("printf", "payload=trusted\nprintf")),
        (_WORKFLOW, _SCRIPT.replace("'{blocks:", "'{metadata:")),
        (_WORKFLOW.replace("bash scripts/payload.sh", "bash $BUILDER"), _SCRIPT),
        (_WORKFLOW.replace("run: bash", "working-directory: unknown\n        run: bash"), _SCRIPT),
    ],
    ids=(
        "plain-text",
        "trusted-input",
        "other-action",
        "unknown-transport",
        "other-output",
        "changed-value",
        "other-destination",
        "other-binding",
        "shell-word-splitting",
        "transformed-jq",
        "overwritten-env",
        "overwritten-payload",
        "metadata-is-not-block-kit",
        "dynamic-builder",
        "different-directory",
    ),
)
def test_near_misses_abstain(tmp_path: Path, workflow: str, script: str) -> None:
    assert _analyze(tmp_path, workflow, script) == 0


def test_step_environment_overrides_tainted_job_environment(tmp_path: Path) -> None:
    workflow = _WORKFLOW.replace(
        "    steps:\n", "    env:\n      TITLE: ${{ github.event.pull_request.title }}\n    steps:\n"
    ).replace("          TITLE: ${{ github.event.pull_request.title }}", "          TITLE: trusted")
    assert _analyze(tmp_path, workflow) == 0


def test_workflow_default_directory_selects_the_actual_builder(tmp_path: Path) -> None:
    workflow = _WORKFLOW.replace("jobs:\n", "defaults:\n  run:\n    working-directory: other\njobs:\n")
    assert _analyze(tmp_path, workflow) == 0


def test_external_builder_cannot_escape_checkout(tmp_path: Path) -> None:
    workflow = _WORKFLOW.replace("scripts/payload.sh", "../payload.sh")
    assert _analyze(tmp_path, workflow) == 0


def test_slack_consumer_must_follow_the_builder(tmp_path: Path) -> None:
    prefix, producer = _WORKFLOW.split("      - id: build", 1)
    producer, consumer = producer.split("      - uses:", 1)
    workflow = prefix + "      - uses:" + consumer + "      - id: build" + producer
    assert _analyze(tmp_path, workflow) == 0


def test_multiple_unsafe_text_objects_produce_one_diagnostic(tmp_path: Path) -> None:
    script = _SCRIPT.replace(
        'text: "PR: \\($title)"}}]',
        'text: "PR: \\($title)"}, fields: [{type: "mrkdwn", text: $title}]}]',
    )
    assert _analyze(tmp_path, script=script) == 1


@pytest.mark.parametrize(
    "metadata",
    ["$missing", '[{value: "\\($missing)"}]'],
    ids=("unbound-variable", "unbound-interpolation"),
)
def test_unbound_jq_variables_cannot_produce_a_payload(tmp_path: Path, metadata: str) -> None:
    script = _SCRIPT.replace("'{blocks:", "'{metadata: " + metadata + ", blocks:")
    assert _analyze(tmp_path, script=script) == 0


def test_header_text_has_no_mrkdwn_contract(tmp_path: Path) -> None:
    script = _SCRIPT.replace('type: "section"', 'type: "header"')
    assert _analyze(tmp_path, script=script) == 0


def test_malformed_shell_abstains(tmp_path: Path) -> None:
    script = _SCRIPT.replace("')\n", "'\n")
    assert _analyze(tmp_path, script=script) == 0


def test_malformed_yaml_abstains(tmp_path: Path) -> None:
    assert _analyze(tmp_path, workflow=_WORKFLOW + "invalid: [\n") == 0


@pytest.mark.parametrize(
    "selector",
    [
        "on: pull_request_target\n",
        "on: workflow_call\n",
        "on: [pull_request]\n",
        "on: [push, pull_request]\n",
        "on:\n  pull_request:\n    types: [closed]\n",
        "on:\n  workflow_call:\n  workflow_dispatch:\n",
    ],
    ids=("target-scalar", "reusable-scalar", "event-list", "mixed-list", "closed-options", "mixed-mapping"),
)
def test_trigger_can_supply_pr_context(tmp_path: Path, selector: str) -> None:
    assert _analyze(tmp_path, workflow=_WORKFLOW.replace("on: pull_request\n", selector)) == 1


@pytest.mark.parametrize(
    "selector",
    [
        "on: push\n",
        "on: workflow_dispatch\n",
        "on: [push, workflow_dispatch]\n",
        "on:\n  push:\n  workflow_dispatch:\n",
        "",
        "on: unknown_event\n",
        "on: [pull_request, unknown_event]\n",
        "on: [pull_request, [push]]\n",
        "on: {pull_request: false}\n",
        "on: {pull_request: []}\n",
        "on: pull_request_review\n",
        "on: pull_request_review_comment\n",
    ],
    ids=(
        "push-only",
        "manual-only",
        "non-pr-list",
        "non-pr-mapping",
        "missing-trigger",
        "unknown-trigger",
        "unknown-mixed-trigger",
        "nested-list",
        "boolean-options",
        "sequence-options",
        "unsupported-review",
        "unsupported-review-comment",
    ),
)
def test_absent_or_unsupported_pr_provenance_abstains(tmp_path: Path, selector: str) -> None:
    assert _analyze(tmp_path, workflow=_WORKFLOW.replace("on: pull_request\n", selector)) == 0


@pytest.mark.parametrize("trigger", ["push", "workflow_dispatch", "pull_request_review"])
def test_head_ref_is_not_tainted_for_other_events(tmp_path: Path, trigger: str) -> None:
    workflow = _WORKFLOW.replace("on: pull_request", f"on: {trigger}").replace(
        "github.event.pull_request.title", "github.head_ref"
    )
    assert _analyze(tmp_path, workflow=workflow) == 0


@pytest.mark.parametrize(
    "logical_path", ["config/notify.yml", ".github/actions/notify.yml", ".github/workflows/nested/notify.yml"]
)
def test_inline_program_requires_workflow_placement(tmp_path: Path, logical_path: str) -> None:
    program = "".join(f"          {line}\n" for line in _SCRIPT.splitlines())
    workflow = _WORKFLOW.replace("        run: bash scripts/payload.sh\n", "        run: |\n" + program)
    path = tmp_path / logical_path
    path.parent.mkdir(parents=True)
    path.write_text(workflow)
    assert SlackEventTextInMrkdwn().check(path, workflow) == []


@pytest.mark.parametrize("condition", ["false", "False", "FALSE", "${{ false }}", "${{ FALSE }}"])
@pytest.mark.parametrize("location", ["job", "producer", "consumer"])
def test_literal_false_blocks_the_flow(tmp_path: Path, location: str, condition: str) -> None:
    targets = {
        "job": ("    runs-on:", f"    if: {condition}\n    runs-on:"),
        "producer": ("      - id: build\n", f"      - id: build\n        if: {condition}\n"),
        "consumer": ("        with:\n", f"        if: {condition}\n        with:\n"),
    }
    before, after = targets[location]
    assert _analyze(tmp_path, workflow=_WORKFLOW.replace(before, after)) == 0


@pytest.mark.parametrize(
    "condition",
    ["github.event_name == 'push'", "${{ github.event_name == 'PUSH' }}", "GITHUB.EVENT_NAME == 'push'"],
)
@pytest.mark.parametrize("location", ["job", "producer", "consumer"])
def test_non_pr_event_guard_blocks_a_mixed_workflow(tmp_path: Path, location: str, condition: str) -> None:
    targets = {
        "job": ("    runs-on:", f"    if: {condition}\n    runs-on:"),
        "producer": ("      - id: build\n", f"      - id: build\n        if: {condition}\n"),
        "consumer": ("        with:\n", f"        if: {condition}\n        with:\n"),
    }
    before, after = targets[location]
    workflow = _WORKFLOW.replace("on: pull_request", "on: [pull_request, push]").replace(before, after)
    assert _analyze(tmp_path, workflow=workflow) == 0


@pytest.mark.parametrize(
    "condition",
    ["github.event_name == 'PULL_REQUEST'", "${{ GITHUB.EVENT_NAME != 'PUSH' }}"],
)
def test_proven_pr_guard_keeps_a_mixed_flow(tmp_path: Path, condition: str) -> None:
    workflow = _WORKFLOW.replace("on: pull_request", "on: [pull_request, push]").replace(
        "    runs-on:", f"    if: {condition}\n    runs-on:"
    )
    assert _analyze(tmp_path, workflow=workflow) == 1


def test_producer_and_consumer_need_the_same_pr_event(tmp_path: Path) -> None:
    workflow = _WORKFLOW.replace("on: pull_request", "on: [pull_request, pull_request_target]")
    workflow = workflow.replace(
        "      - id: build\n", "      - id: build\n        if: github.event_name == 'pull_request'\n"
    )
    workflow = workflow.replace(
        "        with:\n", "        if: github.event_name == 'pull_request_target'\n        with:\n"
    )
    assert _analyze(tmp_path, workflow=workflow) == 0


def test_unknown_guard_abstains_on_a_mixed_trigger_profile(tmp_path: Path) -> None:
    workflow = _WORKFLOW.replace("on: pull_request", "on: [pull_request, push]").replace(
        "    runs-on:", "    if: env.ANNOUNCE_MERGE == 'true'\n    runs-on:"
    )
    assert _analyze(tmp_path, workflow=workflow) == 0


def test_unknown_guard_can_still_run_with_only_pr_context(tmp_path: Path) -> None:
    workflow = _WORKFLOW.replace("    runs-on:", "    if: env.ANNOUNCE_MERGE == 'true'\n    runs-on:")
    assert _analyze(tmp_path, workflow=workflow) == 1


@pytest.mark.parametrize("scope", ["workflow", "job"])
@pytest.mark.parametrize("overwrite", [False, True])
def test_visible_github_env_write_invalidates_inherited_binding(tmp_path: Path, scope: str, overwrite: bool) -> None:
    workflow = _WORKFLOW.replace("        env:\n          TITLE: ${{ github.event.pull_request.title }}\n", "")
    if scope == "workflow":
        workflow = workflow.replace("jobs:\n", "env:\n  TITLE: ${{ github.event.pull_request.title }}\njobs:\n")
    else:
        workflow = workflow.replace(
            "    steps:\n", "    env:\n      TITLE: ${{ github.event.pull_request.title }}\n    steps:\n"
        )
    if overwrite:
        workflow = workflow.replace(
            "    steps:\n", "    steps:\n      - run: printf 'TITLE=trusted\\n' >>\"$GITHUB_ENV\"\n"
        )
    assert _analyze(tmp_path, workflow=workflow) == (0 if overwrite else 1)


def test_explicit_producer_binding_overrides_a_prior_environment_write(tmp_path: Path) -> None:
    workflow = _WORKFLOW.replace(
        "    steps:\n", "    steps:\n      - run: printf 'TITLE=trusted\\n' >>\"$GITHUB_ENV\"\n"
    )
    assert _analyze(tmp_path, workflow=workflow) == 1


def test_comment_does_not_reference_the_environment_file(tmp_path: Path) -> None:
    workflow = _WORKFLOW.replace("        env:\n          TITLE: ${{ github.event.pull_request.title }}\n", "")
    workflow = workflow.replace("jobs:\n", "env:\n  TITLE: ${{ github.event.pull_request.title }}\njobs:\n")
    workflow = workflow.replace(
        "    steps:\n", "    steps:\n      - run: |\n          # $GITHUB_ENV is a runner file\n          echo ready\n"
    )
    assert _analyze(tmp_path, workflow=workflow) == 1
