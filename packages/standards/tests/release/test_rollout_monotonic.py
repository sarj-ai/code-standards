from __future__ import annotations

import json
from pathlib import Path

import pytest

from sarj_standards.libs.json_boundary import parse_json
from sarj_standards.libs.release import rollout

from .fakes import FakeRolloutRunner


def consumer() -> rollout.Consumer:
    return rollout.Consumer("Consumer", "example/consumer", "main", ("true",), auto_merge=True)


def pull_payload(markers: str, *, head_sha: str = "a" * 40) -> str:
    return json.dumps(
        [
            {
                "state": "OPEN",
                "mergedAt": None,
                "url": "https://example.invalid/pr/1",
                "headRefName": "standards-rollout/current",
                "headRefOid": head_sha,
                "baseRefName": "main",
                "body": rollout.pr_marker(consumer(), "8.2.1") + "\n" + markers,
            }
        ]
    )


def branch_runner(version: str) -> FakeRolloutRunner:
    head_sha, parent_sha, tree_sha = "a" * 40, "b" * 40, "c" * 40
    message = rollout.managed_commit_message("8.2.1", tree_sha).replace("8.2.1", version, 1)
    return FakeRolloutRunner(
        [
            (0, f"{head_sha}\trefs/heads/standards-rollout/current"),
            (0, ""),
            (0, message),
            (0, f"{head_sha} {parent_sha}"),
            (0, tree_sha),
            (0, ""),
            (0, ""),
        ]
    )


@pytest.mark.parametrize(
    ("requested", "desired"),
    [("8.2.1", "8.2.2"), ("8.9.0", "8.10.0"), ("8.2.1rc1", "8.2.1")],
)
def test_newer_managed_pr_blocks_stale_rollout(requested: str, desired: str) -> None:
    runner = FakeRolloutRunner([(0, pull_payload(rollout.desired_marker(desired)))])

    outcome = rollout.status_one(consumer(), requested, runner)

    assert outcome.state is rollout.OutcomeState.BLOCKED
    assert "downgrade" in outcome.detail
    assert desired in outcome.detail
    assert len(runner.commands) == 1


@pytest.mark.parametrize("dry_run", [False, True])
def test_newer_failed_pr_is_not_retried_or_cloned(*, dry_run: bool) -> None:
    markers = rollout.desired_marker("8.2.2") + "\n" + rollout.VERIFICATION_FAILED_MARKER
    runner = FakeRolloutRunner([(0, pull_payload(markers))])

    with pytest.raises(rollout.RolloutError, match="downgrade"):
        rollout.apply_one(consumer(), "8.2.1", runner, dry_run=dry_run)

    assert len(runner.commands) == 1


@pytest.mark.parametrize(
    "markers",
    [
        "",
        "<!-- sarj-standards-rollout:desired=invalid -->",
        "<!-- sarj-standards-rollout:desired=8.2.1garbage -->",
        "<!-- sarj-standards-rollout:desired=8.2.1",
        rollout.desired_marker("8.2.1") + "\n" + rollout.desired_marker("8.2.1"),
        rollout.desired_marker("8.2.1") + "\n" + rollout.desired_marker("8.2.2"),
        rollout.desired_marker("8.2.1") + "\n<!-- sarj-standards-rollout:desired=8.2.2",
    ],
    ids=["missing", "invalid", "invalid-pep440", "unterminated", "duplicate", "conflicting", "extra-unterminated"],
)
def test_ambiguous_or_invalid_desired_release_fails_closed(markers: str) -> None:
    runner = FakeRolloutRunner([(0, pull_payload(markers))])

    outcome = rollout.status_one(consumer(), "8.2.1", runner)

    assert outcome.state is rollout.OutcomeState.BLOCKED
    assert "desired" in outcome.detail
    assert len(runner.commands) == 1


def test_same_version_verification_failure_still_retries() -> None:
    markers = rollout.desired_marker("8.2.1") + "\n" + rollout.VERIFICATION_FAILED_MARKER
    runner = FakeRolloutRunner([(0, pull_payload(markers))])

    outcome = rollout.apply_one(consumer(), "8.2.1", runner, dry_run=True)

    assert outcome.state is rollout.OutcomeState.WOULD_CREATE


@pytest.mark.parametrize(
    ("requested", "desired"),
    [("8.2.2", "8.2.1"), ("8.10.0", "8.9.0"), ("8.2.1", "8.2.1rc1")],
)
def test_older_managed_pr_can_advance(requested: str, desired: str) -> None:
    runner = FakeRolloutRunner([(0, pull_payload(rollout.desired_marker(desired)))])

    assert rollout.status_one(consumer(), requested, runner).state is rollout.OutcomeState.MISSING


def test_newer_managed_pr_does_not_count_as_requested_release_adoption(capsys: pytest.CaptureFixture[str]) -> None:
    runner = FakeRolloutRunner([(0, pull_payload(rollout.desired_marker("8.2.2")))])
    outcome = rollout.status_one(consumer(), "8.2.1", runner)

    rollout.print_outcomes("8.2.1", (outcome,))

    payload = parse_json(capsys.readouterr().out)
    assert rollout.is_object(payload)
    assert payload["adoptedCount"] == "0/1"
    assert payload["distributedCount"] == "0/1"
    assert payload["complete"] is False


@pytest.mark.parametrize(
    ("requested", "fetched"),
    [("8.2.1", "8.2.2"), ("8.9.0", "8.10.0"), ("8.2.1rc1", "8.2.1")],
)
def test_newer_fetched_managed_commit_cannot_be_reset(requested: str, fetched: str) -> None:
    runner = branch_runner(fetched)

    with pytest.raises(rollout.RolloutError, match="downgrade"):
        rollout.prepare_branch(Path("/synthetic/unused"), requested, "d" * 40, runner)

    assert not any(command[:2] == ("git", "switch") for command in runner.commands)


@pytest.mark.parametrize("fetched", ["", "8.2.1garbage", "8.2.1 extra text"])
def test_invalid_fetched_managed_version_cannot_be_reset(fetched: str) -> None:
    runner = branch_runner(fetched)

    with pytest.raises(rollout.RolloutError, match="version"):
        rollout.prepare_branch(Path("/synthetic/unused"), "8.2.1", "d" * 40, runner)

    assert not any(command[:2] == ("git", "switch") for command in runner.commands)


@pytest.mark.parametrize("fetched", ["8.2.0", "8.2.1rc1", "8.2.1"])
def test_same_or_older_managed_commit_can_be_refreshed(fetched: str) -> None:
    runner = branch_runner(fetched)
    base_sha = "d" * 40

    prepared = rollout.prepare_branch(Path("/synthetic/unused"), "8.2.1", base_sha, runner)

    assert prepared.previous_sha == "a" * 40
    assert runner.commands[-1] == ("git", "switch", "-C", "standards-rollout/current", base_sha)


def test_stale_publisher_cannot_overwrite_newer_pr_metadata() -> None:
    payload = pull_payload(rollout.desired_marker("8.2.2"), head_sha="b" * 40)
    runner = FakeRolloutRunner([(0, payload), (0, ""), (0, payload)])

    outcome = rollout._publish_rollout_pull(  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage] -- isolate the transport boundary
        consumer(),
        "8.2.1",
        runner,
        "standards-rollout/current",
        pushed_head_sha="a" * 40,
        verification_failure="",
    )

    assert outcome.state not in {rollout.OutcomeState.PR_OPEN, rollout.OutcomeState.MERGED}
    assert not any(command[:3] in {("gh", "pr", "edit"), ("gh", "pr", "merge")} for command in runner.commands)


@pytest.mark.parametrize(
    "markers",
    [
        rollout.desired_marker("8.2.2"),
        rollout.desired_marker("8.2.1") + "\n" + rollout.desired_marker("8.2.2"),
        "<!-- sarj-standards-rollout:desired=invalid -->",
    ],
    ids=["newer", "conflicting", "invalid"],
)
def test_same_head_publisher_preserves_newer_or_ambiguous_target(markers: str) -> None:
    payload = pull_payload(markers)
    runner = FakeRolloutRunner([(0, payload), (0, ""), (0, payload)])

    outcome = rollout._publish_rollout_pull(  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage] -- isolate the transport boundary
        consumer(),
        "8.2.1",
        runner,
        "standards-rollout/current",
        pushed_head_sha="a" * 40,
        verification_failure="",
    )

    assert outcome.state is rollout.OutcomeState.BLOCKED
    assert len(runner.commands) == 1


def test_same_head_publisher_preserves_unowned_pr_metadata() -> None:
    payload = pull_payload(rollout.desired_marker("8.2.1")).replace(rollout.pr_marker(consumer(), "8.2.1"), "")
    runner = FakeRolloutRunner([(0, payload), (0, ""), (0, payload)])

    outcome = rollout._publish_rollout_pull(  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage] -- isolate the transport boundary
        consumer(),
        "8.2.1",
        runner,
        "standards-rollout/current",
        pushed_head_sha="a" * 40,
        verification_failure="",
    )

    assert outcome.state is rollout.OutcomeState.BLOCKED
    assert len(runner.commands) == 1


@pytest.mark.parametrize("previous", ["8.2.0", "8.2.1"])
def test_publisher_can_advance_or_refresh_owned_pr_metadata(previous: str) -> None:
    base_sha, tree_sha = "b" * 40, "c" * 40
    commit = json.dumps(
        {
            "parents": [{"sha": base_sha}],
            "commit": {
                "message": rollout.managed_commit_message("8.2.1", tree_sha),
                "tree": {"sha": tree_sha},
            },
        }
    )
    runner = FakeRolloutRunner(
        [
            (0, pull_payload(rollout.desired_marker(previous))),
            (0, ""),
            (0, pull_payload(rollout.desired_marker("8.2.1"))),
            (0, commit),
            (0, json.dumps({"object": {"type": "commit", "sha": base_sha}})),
        ]
    )

    outcome = rollout._publish_rollout_pull(  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage] -- isolate the transport boundary
        consumer(),
        "8.2.1",
        runner,
        "standards-rollout/current",
        pushed_head_sha="a" * 40,
        verification_failure="",
    )

    assert outcome.state is rollout.OutcomeState.PR_OPEN
    edit = next(command for command in runner.commands if command[:3] == ("gh", "pr", "edit"))
    assert rollout.desired_marker("8.2.1") in edit[edit.index("--body") + 1]
