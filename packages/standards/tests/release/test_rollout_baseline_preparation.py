from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import subprocess
from typing import TYPE_CHECKING

import pytest

from sarj_standards.libs.release import rollout


if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


_MANIFEST_SOURCE = (
    'schema = 4\nbundle = "8.129.1"\n'
    '[baseline]\ndiagnostics = "diagnostic-baseline.json"\n'
    '[ci]\nbootstrap = ["generate-analysis-inputs"]\n'
)


@dataclass
class BaselineRunner:
    repo: Path
    bootstrap_exit: int = 0
    mutation_path: Path | None = None
    replacement: bytes | None = None
    commands: list[tuple[str, ...]] = field(default_factory=list)

    def run(
        self,
        command: Sequence[str],
        *,
        cwd: Path | None = None,
        check: bool = True,
        env: Mapping[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        assert cwd == self.repo
        assert env == {"PATH": "/declared-tools"}
        rendered = tuple(command)
        self.commands.append(rendered)
        if rendered[-1] == "generate-analysis-inputs":
            assert not check
            (self.repo / "generated-types").write_text("ready\n")
            if self.mutation_path is not None:
                if self.replacement is None:
                    self.mutation_path.unlink()
                else:
                    self.mutation_path.write_bytes(self.replacement)
            return subprocess.CompletedProcess(rendered, self.bootstrap_exit, "bootstrap output", "")
        assert "baseline" in rendered
        assert check
        assert (self.repo / "generated-types").is_file(), "baseline must analyze the generated inputs"
        (self.repo / "diagnostic-baseline.json").write_bytes(b"refreshed baseline\n")
        return subprocess.CompletedProcess(rendered, 0, "", "")


def _prepare(repo: Path, runner: BaselineRunner) -> rollout._RolloutBaseline:  # pyright: ignore[reportPrivateUsage] -- transaction-boundary regression.
    (repo / rollout.MANIFEST).write_text(_MANIFEST_SOURCE)
    return rollout._prepare_rollout_baseline(  # pyright: ignore[reportPrivateUsage] -- transaction-boundary regression. # ruff: ignore[private-member-access]
        rollout.Consumer("Example", "example/consumer", "main", ("make", "check")),
        repo,
        runner,
        ("eslint:@typescript-eslint/naming-convention",),
        ("mise", "exec", "--"),
        tool=("code-standards",),
        environment={"PATH": "/declared-tools"},
    )


@pytest.mark.parametrize("existing", [False, True])
def test_declared_inputs_exist_before_scoped_baseline_analysis(tmp_path: Path, *, existing: bool) -> None:
    if existing:
        (tmp_path / "diagnostic-baseline.json").write_bytes(b"original baseline\n")
    runner = BaselineRunner(tmp_path)

    result = _prepare(tmp_path, runner)

    assert result.expected == b"refreshed baseline\n"
    assert result.bootstrap is None
    assert len(runner.commands) == 2
    assert runner.commands[0][-1] == "generate-analysis-inputs"
    assert "baseline" in runner.commands[1]


def test_failed_bootstrap_cannot_refresh_scoped_baseline(tmp_path: Path) -> None:
    baseline = tmp_path / "diagnostic-baseline.json"
    baseline.write_bytes(b"original baseline\n")
    runner = BaselineRunner(tmp_path, bootstrap_exit=7)

    result = _prepare(tmp_path, runner)

    assert result.bootstrap is not None
    assert result.bootstrap.returncode == 7
    assert result.expected == baseline.read_bytes() == b"original baseline\n"
    assert len(runner.commands) == 1


def test_bootstrap_cannot_redirect_the_diagnostic_baseline(tmp_path: Path) -> None:
    runner = BaselineRunner(
        tmp_path,
        mutation_path=tmp_path / rollout.MANIFEST,
        replacement=_MANIFEST_SOURCE.replace("diagnostic-baseline.json", "other-baseline.json").encode(),
    )

    with pytest.raises(rollout.RolloutError, match="changed the diagnostic baseline path"):
        _prepare(tmp_path, runner)

    assert len(runner.commands) == 1


def test_failed_bootstrap_without_a_baseline_preserves_the_failure(tmp_path: Path) -> None:
    runner = BaselineRunner(tmp_path, bootstrap_exit=7)

    with pytest.raises(rollout.RolloutError, match="bootstrap failed before") as failure:
        _prepare(tmp_path, runner)

    assert "bootstrap output" in str(failure.value)
    assert len(runner.commands) == 1
    assert not (tmp_path / "diagnostic-baseline.json").exists()


@pytest.mark.parametrize("relative", ["diagnostic-baseline.json", ".repo-standards/baseline.json"])
@pytest.mark.parametrize("mutation", ["create", "replace", "delete"])
def test_bootstrap_cannot_change_baseline_bytes_or_absence(tmp_path: Path, relative: str, mutation: str) -> None:
    path = tmp_path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    if mutation != "create":
        path.write_bytes(b"original baseline\n")
    runner = BaselineRunner(tmp_path, mutation_path=path, replacement=None if mutation == "delete" else b"expanded\n")

    with pytest.raises(rollout.RolloutError, match="controller-owned"):
        _prepare(tmp_path, runner)

    assert len(runner.commands) == 1
