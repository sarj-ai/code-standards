from __future__ import annotations

import base64
from dataclasses import replace
import json
from typing import TYPE_CHECKING

import pytest

from sarj_standards.libs.release import rollout

from .fakes import FakeRolloutRunner


if TYPE_CHECKING:
    from pathlib import Path

    from pydantic import JsonValue


VERSION = "8.135.5"


def consumer() -> rollout.Consumer:
    return rollout.Consumer("Consumer", "example/consumer", "main", ("make", "check"))


def closed_pull(version: str = VERSION) -> dict[str, JsonValue]:
    return {
        "state": "closed",
        "merged_at": None,
        "html_url": "https://github.com/example/consumer/pull/12",
        "head": {"ref": "standards-rollout/current", "repo": {"full_name": "example/consumer"}},
        "base": {"ref": "main", "repo": {"full_name": "example/consumer"}},
        "body": rollout.pr_marker(consumer(), version) + "\n" + rollout.desired_marker(version),
    }


def reopened_pull(version: str = VERSION) -> dict[str, JsonValue]:
    return {
        "state": "OPEN",
        "mergedAt": None,
        "url": "https://github.com/example/consumer/pull/12",
        "headRefName": "standards-rollout/current",
        "headRefOid": "a" * 40,
        "baseRefName": "main",
        "isCrossRepository": False,
        "headRepository": {"name": "consumer"},
        "headRepositoryOwner": {"login": "example"},
        "body": closed_pull(version)["body"],
    }


def runner_with_closed(pull: dict[str, JsonValue]) -> FakeRolloutRunner:
    return FakeRolloutRunner(
        [(0, "[]"), (1, "HTTP 404")],
        closed_pull_responses=[(0, json.dumps([pull]))],
    )


@pytest.mark.parametrize(
    ("repository", "pull"),
    [
        pytest.param(
            "None/None",
            {"isCrossRepository": False, "headRepository": {}, "headRepositoryOwner": {}},
            id="missing-origin-fields",
        ),
        pytest.param(
            "1/2",
            {"isCrossRepository": False, "headRepository": {"name": 2}, "headRepositoryOwner": {"login": 1}},
            id="non-text-origin-fields",
        ),
    ],
)
def test_open_pull_origin_never_coerces_missing_or_nontext_identity(
    repository: str, pull: dict[str, JsonValue]
) -> None:
    target = rollout.Consumer("Consumer", repository, "main", ("make", "check"))

    assert not rollout.same_repository_pull(target, pull)


def test_requested_decline_blocks_planning_despite_an_older_open_pr() -> None:
    runner = FakeRolloutRunner(
        [(0, json.dumps([reopened_pull("8.135.4")]))],
        closed_pull_responses=[(0, json.dumps([closed_pull()]))],
    )

    outcome = rollout.status_one(consumer(), VERSION, runner)

    assert outcome.state is rollout.OutcomeState.BLOCKED
    assert outcome.url == closed_pull()["html_url"]
    assert "reopen" in outcome.detail
    assert rollout.pending_matrix((outcome,)) == []


@pytest.mark.parametrize("dry_run", [False, True])
def test_older_open_pr_cannot_prepare_a_declined_requested_release(*, dry_run: bool) -> None:
    runner = FakeRolloutRunner(
        [(0, json.dumps([reopened_pull("8.135.4")]))],
        closed_pull_responses=[(0, json.dumps([closed_pull()]))],
    )

    with pytest.raises(rollout.RolloutError, match="closed without merging"):
        rollout.apply_one(consumer(), VERSION, runner, dry_run=dry_run)

    assert all(command[:2] != ("gh", "repo") and command[0] != "git" for command in runner.commands)
    assert all("install" not in command and command != consumer().verify for command in runner.commands)


@pytest.mark.parametrize("closed_version", [None, "8.135.4", "8.135.6"])
def test_older_open_pr_still_allows_a_release_without_its_own_decline(closed_version: str | None) -> None:
    pages: list[list[dict[str, JsonValue]]] = [[closed_pull(closed_version)]] if closed_version is not None else [[]]
    responses = [(0, json.dumps([reopened_pull("8.135.4")]))]
    runner = FakeRolloutRunner(responses, closed_pull_responses=[(0, "\n".join(json.dumps(page) for page in pages))])

    outcome = rollout.status_one(consumer(), VERSION, runner)

    assert outcome.state is rollout.OutcomeState.MISSING
    assert rollout.pending_matrix((outcome,))
    applied = rollout.apply_one(
        consumer(),
        VERSION,
        FakeRolloutRunner(responses, closed_pull_responses=[(0, "\n".join(json.dumps(page) for page in pages))]),
        dry_run=True,
    )
    assert applied.state is rollout.OutcomeState.WOULD_CREATE


@pytest.mark.parametrize("failed_verification", [False, True])
def test_closed_decline_survives_controller_and_consumer_base_movement(
    monkeypatch: pytest.MonkeyPatch, *, failed_verification: bool
) -> None:
    monkeypatch.setenv("GITHUB_SHA", "a" * 40)
    pull = closed_pull()
    base = pull["base"]
    assert isinstance(base, dict)
    base["sha"] = "b" * 40
    pull["body"] = str(pull["body"]) + "\n" + f"{rollout.CONTROLLER_MARKER_PREFIX}={'c' * 40} -->"
    if failed_verification:
        pull["body"] = str(pull["body"]) + "\n" + rollout.VERIFICATION_FAILED_MARKER
    runner = runner_with_closed(pull)

    outcome = rollout.status_one(consumer(), VERSION, runner)

    assert outcome.state is rollout.OutcomeState.BLOCKED
    assert outcome.url == pull["html_url"]
    assert "reopen" in outcome.detail
    assert rollout.pending_matrix((outcome,)) == []
    assert outcome.detail != rollout.VERIFICATION_RETRY_DETAIL
    query = runner.commands[-1]
    assert query[:5] == ("gh", "api", "--method", "GET", "--paginate")
    assert len(query) == 6
    assert "head=example%3Astandards-rollout%2Fcurrent&base=main" in query[-1]


@pytest.mark.parametrize("dry_run", [False, True])
def test_explicit_apply_never_clones_or_installs_a_declined_version(*, dry_run: bool) -> None:
    runner = runner_with_closed(closed_pull())

    with pytest.raises(rollout.RolloutError, match="closed without merging"):
        rollout.apply_one(consumer(), VERSION, runner, dry_run=dry_run)

    assert all(command[:2] != ("gh", "repo") and command[0] != "git" for command in runner.commands)
    assert all("install" not in command and "create" not in command for command in runner.commands)


@pytest.mark.parametrize("repository", ["contributor/consumer", "example/fork"])
def test_known_foreign_fork_spoofs_cannot_decline(repository: str) -> None:
    pull = closed_pull()
    head = pull["head"]
    assert isinstance(head, dict)
    head["repo"] = {"full_name": repository}

    assert rollout.status_one(consumer(), VERSION, runner_with_closed(pull)).state is rollout.OutcomeState.MISSING


@pytest.mark.parametrize("field", ["head", "base"])
@pytest.mark.parametrize(
    "origin",
    [
        None,
        pytest.param({}, id="missing-repository-record"),
        pytest.param({"full_name": None}, id="null-repository-name"),
        pytest.param({"full_name": 0}, id="non-text-repository-name"),
    ],
)
def test_indeterminate_owned_origin_is_unavailable_not_permission_to_retry(field: str, origin: JsonValue) -> None:
    pull = closed_pull()
    reference = pull[field]
    assert isinstance(reference, dict)
    reference["repo"] = origin

    outcome = rollout.status_one(consumer(), VERSION, runner_with_closed(pull))

    assert outcome.state is rollout.OutcomeState.BLOCKED
    assert "unavailable or incomplete" in outcome.detail
    assert "reopen" not in outcome.detail
    assert rollout.pending_matrix((outcome,)) == []


@pytest.mark.parametrize("field", ["head", "base"])
def test_missing_owned_origin_fields_are_unavailable(field: str) -> None:
    pull = closed_pull()
    reference = pull[field]
    assert isinstance(reference, dict)
    pull = {**pull, field: {key: value for key, value in reference.items() if key != "repo"}}

    outcome = rollout.status_one(consumer(), VERSION, runner_with_closed(pull))

    assert outcome.state is rollout.OutcomeState.BLOCKED
    assert "unavailable or incomplete" in outcome.detail


@pytest.mark.parametrize("field", ["head", "base"])
def test_incomplete_owned_reference_is_unavailable(field: str) -> None:
    pull = closed_pull()
    pull[field] = None

    assert rollout.status_one(consumer(), VERSION, runner_with_closed(pull)).state is rollout.OutcomeState.BLOCKED


@pytest.mark.parametrize("field", ["head", "base"])
def test_missing_owned_ref_name_is_unavailable(field: str) -> None:
    pull = closed_pull()
    reference = pull[field]
    assert isinstance(reference, dict)
    pull = {**pull, field: {key: value for key, value in reference.items() if key != "ref"}}

    assert rollout.status_one(consumer(), VERSION, runner_with_closed(pull)).state is rollout.OutcomeState.BLOCKED


@pytest.mark.parametrize("replacement", ["human proposal", "channel-mismatch"])
def test_unowned_or_foreign_channel_is_not_a_decline(replacement: str) -> None:
    pull = closed_pull()
    pull["body"] = (
        str(pull["body"]).replace("channel=stable", "channel=canary")
        if replacement == "channel-mismatch"
        else replacement
    )

    assert rollout.status_one(consumer(), VERSION, runner_with_closed(pull)).state is rollout.OutcomeState.MISSING


@pytest.mark.parametrize("desired", ["8.135.4", "8.135.6"])
def test_declining_a_different_release_does_not_create_a_new_version_restriction(desired: str) -> None:
    assert (
        rollout.status_one(consumer(), VERSION, runner_with_closed(closed_pull(desired))).state
        is rollout.OutcomeState.MISSING
    )


def test_merged_record_is_not_a_decline() -> None:
    pull = closed_pull()
    pull["merged_at"] = "2026-10-27T16:00:00Z"

    assert rollout.status_one(consumer(), VERSION, runner_with_closed(pull)).state is rollout.OutcomeState.MISSING


def test_complete_history_over_one_hundred_older_or_merged_records_allows_a_new_release() -> None:
    merged = closed_pull()
    merged["merged_at"] = "2026-10-27T16:00:00Z"
    pages = [[closed_pull("8.135.4")] * 100, [merged] * 100, [closed_pull("8.135.4")]]
    runner = FakeRolloutRunner(
        [(0, "[]"), (1, "HTTP 404")], closed_pull_responses=[(0, "\n".join(json.dumps(page) for page in pages))]
    )

    assert rollout.status_one(consumer(), VERSION, runner).state is rollout.OutcomeState.MISSING


def test_matching_decline_on_a_later_page_is_not_a_negative_prefix() -> None:
    pages = [[closed_pull("8.135.4")] * 100, [closed_pull()]]
    runner = FakeRolloutRunner(
        [(0, "[]"), (1, "HTTP 404")], closed_pull_responses=[(0, "\n".join(json.dumps(page) for page in pages))]
    )

    outcome = rollout.status_one(consumer(), VERSION, runner)

    assert outcome.state is rollout.OutcomeState.BLOCKED
    assert outcome.url == closed_pull()["html_url"]
    assert "reopen" in outcome.detail


@pytest.mark.parametrize("coalesced", [False, True])
@pytest.mark.parametrize("indent", [None, 2])
def test_later_decline_in_complete_native_pagination_output(*, coalesced: bool, indent: int | None) -> None:
    pages = [[closed_pull("8.135.4")], [closed_pull()]]
    payload = (
        json.dumps([pull for page in pages for pull in page], indent=indent)
        if coalesced
        else "\r\n \t".join(json.dumps(page, indent=indent) for page in pages)
    )
    runner = FakeRolloutRunner([(0, "[]"), (1, "HTTP 404")], closed_pull_responses=[(0, payload)])

    outcome = rollout.status_one(consumer(), VERSION, runner)

    assert outcome.state is rollout.OutcomeState.BLOCKED
    assert outcome.url == closed_pull()["html_url"]
    assert "reopen" in outcome.detail


def test_complete_empty_native_history_allows_a_new_release() -> None:
    runner = FakeRolloutRunner([(0, "[]"), (1, "HTTP 404")], closed_pull_responses=[(0, " \r\n [] \t")])

    assert rollout.status_one(consumer(), VERSION, runner).state is rollout.OutcomeState.MISSING


@pytest.mark.parametrize("suffix", ["not-json", "[", '{"incomplete":'])
@pytest.mark.parametrize("first_declined", [False, True])
def test_incomplete_trailing_page_cannot_qualify_a_valid_prefix(*, suffix: str, first_declined: bool) -> None:
    pull = closed_pull(VERSION if first_declined else "8.135.4")
    payload = json.dumps([pull]) + suffix
    runner = FakeRolloutRunner([(0, "[]"), (1, "HTTP 404")], closed_pull_responses=[(0, payload)])

    outcome = rollout.status_one(consumer(), VERSION, runner)

    assert outcome.state is rollout.OutcomeState.BLOCKED
    assert "unavailable or incomplete" in outcome.detail
    assert rollout.pending_matrix((outcome,)) == []


@pytest.mark.parametrize("payload", ["[]{}", "[]null", "[]1", "[][null]"])
def test_complete_nonarray_or_invalid_later_page_is_unavailable(payload: str) -> None:
    runner = FakeRolloutRunner([(0, "[]"), (1, "HTTP 404")], closed_pull_responses=[(0, payload)])

    outcome = rollout.status_one(consumer(), VERSION, runner)

    assert outcome.state is rollout.OutcomeState.BLOCKED
    assert "unavailable or incomplete" in outcome.detail


def test_failed_native_pagination_cannot_qualify_complete_partial_stdout() -> None:
    runner = FakeRolloutRunner([(0, "[]"), (1, "HTTP 404")], closed_pull_responses=[(1, "[]")])

    outcome = rollout.status_one(consumer(), VERSION, runner)

    assert outcome.state is rollout.OutcomeState.BLOCKED
    assert "unavailable or incomplete" in outcome.detail


def test_base_already_current_takes_priority_without_closed_history() -> None:
    manifest = base64.b64encode(f'bundle = "{VERSION}"\n'.encode()).decode()
    runner = FakeRolloutRunner([(0, "[]"), (0, json.dumps({"content": manifest}))])

    assert rollout.status_one(consumer(), VERSION, runner).state is rollout.OutcomeState.ALREADY_CURRENT
    assert all("--paginate" not in command for command in runner.commands)


def test_reopened_pr_takes_priority_and_keeps_normal_provenance_checks() -> None:
    commit = {
        "parents": [{"sha": "b" * 40}],
        "commit": {"tree": {"sha": "c" * 40}, "message": rollout.managed_commit_message(VERSION, "c" * 40)},
    }
    live = {"ref": "refs/heads/main", "object": {"type": "commit", "sha": "b" * 40}}
    runner = FakeRolloutRunner(
        [(0, json.dumps([reopened_pull()])), (0, json.dumps(commit)), (0, json.dumps(live))],
        closed_pull_responses=[(1, "must not query closed history")],
    )

    assert rollout.status_one(consumer(), VERSION, runner).state is rollout.OutcomeState.PR_OPEN
    assert len(runner.commands) == 3
    assert len(runner.closed_pull_responses) == 1


@pytest.mark.parametrize(
    ("code", "payload"),
    [
        (1, "unavailable"),
        (124, "timeout"),
        (0, "not-json"),
        (0, "{}"),
        (0, ""),
        (0, " \r\n\t"),
        (0, "[null]"),
        (0, "[[null]]"),
    ],
)
def test_failed_or_malformed_pagination_is_unavailable(code: int, payload: str) -> None:
    runner = FakeRolloutRunner([(0, "[]"), (1, "HTTP 404")], closed_pull_responses=[(code, payload)])

    outcome = rollout.status_one(consumer(), VERSION, runner)

    assert outcome.state is rollout.OutcomeState.BLOCKED
    assert "unavailable or incomplete" in outcome.detail
    assert rollout.pending_matrix((outcome,)) == []


@pytest.mark.parametrize("desired", ["", "invalid", VERSION + " -->\n" + rollout.desired_marker(VERSION)])
def test_ambiguous_owned_version_is_not_permission_to_retry(desired: str) -> None:
    pull = closed_pull()
    pull["body"] = rollout.pr_marker(consumer(), VERSION) + f"\n{rollout.DESIRED_MARKER_PREFIX}={desired} -->"

    assert rollout.status_one(consumer(), VERSION, runner_with_closed(pull)).state is rollout.OutcomeState.BLOCKED


def test_declined_earlier_wave_does_not_unlock_later_consumers() -> None:
    early = replace(consumer(), channel=rollout.RolloutChannel.CANARY)
    declined = rollout.Outcome(early, rollout.OutcomeState.BLOCKED, detail="declined")
    later = rollout.Outcome(consumer(), rollout.OutcomeState.MISSING)

    assert rollout.pending_matrix((declined, later)) == []
    assert not rollout.prior_wave_is_adopted(consumer(), (declined, later))


def test_close_during_verification_blocks_git_transport(tmp_path: Path) -> None:
    runner = FakeRolloutRunner([(0, "[]")], closed_pull_responses=[(0, json.dumps([closed_pull()]))])

    with pytest.raises(rollout.RolloutError, match="closed without merging"):
        rollout.push_rollout_head(
            tmp_path,
            consumer(),
            rollout.BranchPreparation("standards-rollout/current", None),
            "b" * 40,
            runner,
            version=VERSION,
            environment={},
        )

    assert all(command[0] != "git" for command in runner.commands)


def test_close_after_push_does_not_create_or_edit_a_replacement() -> None:
    runner = FakeRolloutRunner([(0, "[]")], closed_pull_responses=[(0, json.dumps([closed_pull()]))])

    outcome = rollout._publish_rollout_pull(  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage] -- isolate actual publication boundary.
        consumer(),
        VERSION,
        runner,
        "standards-rollout/current",
        pushed_head_sha="a" * 40,
        branch_paths=(".sarj-standards.toml",),
        verification_failure="",
    )

    assert outcome.state is rollout.OutcomeState.BLOCKED
    assert outcome.url == closed_pull()["html_url"]
    assert all(
        "create" not in command and "edit" not in command and "merge" not in command for command in runner.commands
    )


@pytest.mark.parametrize("cross_repository", [True, None])
def test_fork_or_unknown_open_record_cannot_override_a_known_decline(
    tmp_path: Path, *, cross_repository: bool | None
) -> None:
    pull = reopened_pull()
    pull["isCrossRepository"] = cross_repository
    runner = FakeRolloutRunner([(0, json.dumps([pull]))], closed_pull_responses=[(0, json.dumps([closed_pull()]))])

    with pytest.raises(rollout.RolloutError, match="closed without merging"):
        rollout.push_rollout_head(
            tmp_path,
            consumer(),
            rollout.BranchPreparation("standards-rollout/current", None),
            "b" * 40,
            runner,
            version=VERSION,
            environment={},
        )

    assert all(command[0] != "git" for command in runner.commands)


def test_owned_reopen_after_verification_keeps_normal_guarded_push(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GH_TOKEN", "private-fixture-token")
    runner = FakeRolloutRunner(
        [(0, json.dumps([reopened_pull()])), (0, ""), (0, "b" * 40), (0, "a" * 40), (0, "c" * 40), (0, "")],
        closed_pull_responses=[(0, json.dumps([closed_pull()]))],
    )

    pushed = rollout.push_rollout_head(
        tmp_path,
        consumer(),
        rollout.BranchPreparation("standards-rollout/current", None),
        "b" * 40,
        runner,
        version=VERSION,
        environment={},
    )

    assert pushed == "a" * 40
    assert runner.commands[-1][:4] == ("git", "-c", "core.hooksPath=/dev/null", "push")
