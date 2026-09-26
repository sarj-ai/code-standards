from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import TYPE_CHECKING, final

import pytest

from sarj_standards.libs.release import rollout

from .fakes import FakeRolloutRunner


if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    import subprocess


_VERSION = "8.1.1"
_CONSUMERS = (
    rollout.Consumer("first", "example/first", "main", ("make", "check")),
    rollout.Consumer("next", "example/next", "main", ("make", "check")),
)


def _manifest_response(source: str) -> str:
    return json.dumps({"content": base64.b64encode(source.encode()).decode()})


@final
class ManifestRunner:
    def __init__(self, manifest: str, *, clone_error: Exception | None = None) -> None:
        self.manifest = manifest
        self.clone_error = clone_error
        self.fake = FakeRolloutRunner(
            [
                (0, f"code-standards {_VERSION}"),
                (0, f"{'c' * 40}\trefs/tags/standards-v{_VERSION}\n{'a' * 40}\trefs/tags/standards-v{_VERSION}^{{}}\n"),
                (0, "[]"),
                (0, _manifest_response(manifest)),
                (0, ""),
                (0, "b" * 40),
                (0, ""),
                (0, ""),
                (0, "[]"),
                (0, _manifest_response(f'schema = 4\nbundle = "{_VERSION}"\n')),
            ]
        )

    def run(
        self,
        command: Sequence[str],
        *,
        cwd: Path | None = None,
        check: bool = True,
        env: Mapping[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        if tuple(command[:3]) == ("gh", "repo", "clone"):
            if self.clone_error is not None:
                raise self.clone_error
            repo = Path(command[4])
            repo.mkdir(parents=True)
            (repo / rollout.MANIFEST).write_text(self.manifest, encoding="utf-8")
        return self.fake.run(command, cwd=cwd, check=check, env=env)


@pytest.mark.parametrize(
    ("manifest", "detail"),
    [
        pytest.param("schema = [", "not valid TOML", id="invalid-toml"),
        pytest.param('schema = 999\nbundle = "8.0.0"\n', "`schema`", id="unsupported-schema"),
        pytest.param("schema = 4\nbundle = 8\n", "string `bundle`", id="non-string-bundle"),
        pytest.param('schema = 4\nbundle = "8.0.0"\nexclude = false\n', "must be a table", id="non-table-exclusion"),
        pytest.param(
            'schema = 4\nbundle = "8.0.0"\n[exclude]\nrules = ["python:unknown-rule"]\n',
            "unknown-rule",
            id="unknown-rule-exclusion",
        ),
    ],
)
def test_invalid_consumer_manifest_does_not_abort_later_consumers(manifest: str, detail: str) -> None:
    runner = ManifestRunner(manifest)

    outcomes = rollout.apply(_VERSION, _CONSUMERS, runner)

    assert [outcome.consumer for outcome in outcomes] == list(_CONSUMERS)
    assert [outcome.state for outcome in outcomes] == [rollout.OutcomeState.ERROR, rollout.OutcomeState.ALREADY_CURRENT]
    assert "invalid consumer .sarj-standards.toml" in outcomes[0].detail
    assert detail in outcomes[0].detail
    assert not outcomes[1].detail
    assert runner.fake.responses == []
    assert not any(command[:2] == ("git", "push") or "uvx" in command for command in runner.fake.commands[2:])


@pytest.mark.parametrize("error_type", [ValueError, TypeError, RuntimeError])
def test_unrelated_programming_errors_are_not_consumer_validation_failures(error_type: type[Exception]) -> None:
    failure = error_type("unexpected clone adapter defect")
    runner = ManifestRunner('schema = 4\nbundle = "8.0.0"\n', clone_error=failure)

    with pytest.raises(error_type, match="unexpected clone adapter defect") as raised:
        rollout.apply(_VERSION, _CONSUMERS, runner)

    assert raised.value is failure
