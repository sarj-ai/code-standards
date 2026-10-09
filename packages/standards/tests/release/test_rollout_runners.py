from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from sarj_standards.libs.release import rollout


if TYPE_CHECKING:
    from pathlib import Path


REGISTRY = (
    'schema = 1\n[[consumer]]\nname = "Example"\nrepository = "example/consumer"\n'
    'branch = "main"\nverify = ["make", "check"]\nrequires_approval = true\n'
)


@pytest.mark.parametrize(
    "runner", ["ubuntu-latest", "ubuntu-24.04", "blacksmith-2vcpu-ubuntu-2404", "blacksmith-4vcpu-ubuntu-2404"]
)
def test_registry_routes_only_the_selected_consumer_to_an_allowed_host(tmp_path: Path, runner: str) -> None:
    path = tmp_path / "registry.toml"
    path.write_text(REGISTRY + f'workflow_runner = "{runner}"\n')

    consumer = rollout.load_registry(path)[0]
    matrix = rollout.pending_matrix((rollout.Outcome(consumer, rollout.OutcomeState.MISSING),))

    assert consumer.workflow_runner == runner
    assert consumer.requires_approval
    assert consumer.verify == ("make", "check")
    assert len(matrix) == 1
    assert matrix[0].get("workflow_runner", rollout.DEFAULT_WORKFLOW_RUNNER) == runner
    assert matrix[0]["identity"] == "example/consumer@main"


@pytest.mark.parametrize(
    "value",
    [
        pytest.param('""', id="empty"),
        pytest.param("false", id="boolean"),
        pytest.param("[]", id="array"),
        pytest.param('"self-hosted"', id="unapproved-host"),
        pytest.param('"blacksmith-8vcpu-ubuntu-2404"', id="unbounded-host"),
        pytest.param('"ubuntu-latest\\nself-hosted"', id="multiline"),
        pytest.param('"${{ secrets.TOKEN }}"', id="workflow-expression"),
    ],
)
def test_invalid_runner_is_rejected_before_planning(tmp_path: Path, value: str) -> None:
    path = tmp_path / "registry.toml"
    path.write_text(REGISTRY + f"workflow_runner = {value}\n")

    with pytest.raises(rollout.RolloutError, match="workflow_runner must be one of"):
        rollout.load_registry(path)


def test_runner_opt_in_keeps_approval_and_wave_barriers(tmp_path: Path) -> None:
    path = tmp_path / "registry.toml"
    path.write_text(REGISTRY + 'workflow_runner = "blacksmith-4vcpu-ubuntu-2404"\n')
    consumer = rollout.load_registry(path)[0]

    assert rollout.pending_matrix((rollout.Outcome(consumer, rollout.OutcomeState.PR_OPEN),)) == []
    assert rollout.pending_matrix((rollout.Outcome(consumer, rollout.OutcomeState.ALREADY_CURRENT),)) == []
    assert (
        rollout.pending_matrix((rollout.Outcome(consumer, rollout.OutcomeState.BLOCKED, detail="owner approval"),))
        == []
    )
