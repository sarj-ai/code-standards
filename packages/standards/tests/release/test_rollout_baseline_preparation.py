from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import subprocess
from typing import TYPE_CHECKING

import pytest

from sarj_standards.libs.release import rollout


if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from sarj_standards.libs.adoption.transaction import FileSnapshot


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


def _prepare(
    repo: Path,
    runner: BaselineRunner,
    *,
    preserve_baselines: bool = False,
    rules: tuple[str, ...] = ("oxlint:@sarj/no-test-comments",),
    regenerate: bool = False,
) -> rollout._RolloutBaseline:  # pyright: ignore[reportPrivateUsage] -- transaction-boundary regression.
    (repo / rollout.MANIFEST).write_text(_MANIFEST_SOURCE)
    return rollout._prepare_rollout_baseline(  # pyright: ignore[reportPrivateUsage] -- transaction-boundary regression. # ruff: ignore[private-member-access]
        rollout.Consumer("Example", "example/consumer", "main", ("make", "check")),
        repo,
        runner,
        rules,
        ("mise", "exec", "--"),
        tool=("code-standards",),
        environment={"PATH": "/declared-tools"},
        preserve_baselines=preserve_baselines,
        regenerate=regenerate,
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


@pytest.mark.parametrize("rules", [(), ("oxlint:@sarj/no-test-comments",)], ids=["unscoped", "promoted"])
def test_switch_to_oxlint_regenerates_the_whole_baseline(tmp_path: Path, rules: tuple[str, ...]) -> None:
    (tmp_path / "diagnostic-baseline.json").write_bytes(b"eslint-era fingerprints\n")
    runner = BaselineRunner(tmp_path)

    result = _prepare(tmp_path, runner, rules=rules, regenerate=True)

    assert result.expected == b"refreshed baseline\n"
    assert "--rule" not in runner.commands[1]
    assert runner.commands[1][4:6] == ("baseline", "update")


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


def test_preservation_skips_scoped_baseline_generation_after_bootstrap(tmp_path: Path) -> None:
    path = tmp_path / "diagnostic-baseline.json"
    path.write_bytes(b"original baseline\n")
    path.chmod(0o640)
    runner = BaselineRunner(tmp_path)

    result = _prepare(tmp_path, runner, preserve_baselines=True)

    assert result.allowed_paths == frozenset()
    assert result.expected == path.read_bytes() == b"original baseline\n"
    assert path.stat().st_mode & 0o777 == 0o640
    assert len(runner.commands) == 1
    assert runner.commands[0][-1] == "generate-analysis-inputs"


@pytest.mark.parametrize("mutation", ["create", "replace", "delete", "chmod"])
def test_preservation_guards_declared_and_absent_consumer_baselines(tmp_path: Path, mutation: str) -> None:
    (tmp_path / rollout.MANIFEST).write_text(_MANIFEST_SOURCE)
    path = tmp_path / "custom-baseline.json"
    if mutation != "create":
        path.write_bytes(b"retained\n")
    consumer = rollout.Consumer("Example", "example/consumer", "main", ("make", "check"), baseline_paths=(path.name,))
    preserved = rollout.snapshot_consumer_baselines(tmp_path, consumer)
    rollout.assert_preserved_baselines(tmp_path, preserved)
    match mutation:
        case "delete":
            path.unlink()
        case "chmod":
            path.chmod(0o750)
        case _:
            path.write_bytes(b"expanded\n")

    with pytest.raises(rollout.RolloutError, match="controller-owned"):
        rollout.assert_preserved_baselines(tmp_path, preserved)


def test_disabled_preservation_does_not_inspect_baseline_targets(tmp_path: Path) -> None:
    consumer = rollout.Consumer("Example", "example/consumer", "main", ("make", "check"))

    assert rollout.snapshot_consumer_baselines(tmp_path / "not-cloned", consumer, preserve_baselines=False) == {}


_ENTRY: dict[str, int | str] = {
    "count": 2,
    "fingerprint": "a" * 64,
    "path": "service.py",
    "ruleId": "no-print",
    "source": "ruff",
}


def _baseline_bytes(bundle: str, entries: Sequence[Mapping[str, int | str]] = (_ENTRY,)) -> bytes:
    provenance = {"bundleVersion": bundle, "consumerBaseSha": "0" * 40, "catalogDigest": "1" * 64}
    document = {"schemaVersion": 2, "provenance": provenance, "diagnostics": list(entries)}
    return (json.dumps(document) + "\n").encode()


def _preserved_diagnostic_baseline(root: Path) -> Mapping[Path, FileSnapshot]:
    (root / rollout.MANIFEST).write_text(_MANIFEST_SOURCE)
    path = root / "diagnostic-baseline.json"
    path.write_bytes(_baseline_bytes("8.129.1"))
    path.chmod(0o640)
    consumer = rollout.Consumer("Example", "example/consumer", "main", ("make", "check"))
    return rollout.snapshot_consumer_baselines(root, consumer)


def test_preservation_accepts_a_provenance_only_diagnostic_baseline_refresh(tmp_path: Path) -> None:
    preserved = _preserved_diagnostic_baseline(tmp_path)
    path = tmp_path / "diagnostic-baseline.json"
    path.write_bytes(_baseline_bytes("9.2.3"))

    refreshed = rollout.refresh_preserved_provenance(tmp_path, preserved)

    assert refreshed.refreshed == frozenset({"diagnostic-baseline.json"})
    rollout.assert_preserved_baselines(tmp_path, refreshed.snapshots)
    path.write_bytes(_baseline_bytes("9.2.3", ({**_ENTRY, "count": 3},)))
    with pytest.raises(rollout.RolloutError, match="controller-owned"):
        rollout.assert_preserved_baselines(tmp_path, refreshed.snapshots)


@pytest.mark.parametrize("mutation", ["added-entry", "removed-entry", "changed-count", "chmod", "other-baseline"])
def test_preservation_refuses_diagnostic_baseline_entry_or_metadata_changes(tmp_path: Path, mutation: str) -> None:
    preserved = _preserved_diagnostic_baseline(tmp_path)
    path = tmp_path / "diagnostic-baseline.json"
    match mutation:
        case "added-entry":
            path.write_bytes(_baseline_bytes("9.2.3", (_ENTRY, {**_ENTRY, "fingerprint": "b" * 64})))
        case "removed-entry":
            path.write_bytes(_baseline_bytes("9.2.3", ()))
        case "changed-count":
            path.write_bytes(_baseline_bytes("9.2.3", ({**_ENTRY, "count": 3},)))
        case "chmod":
            path.write_bytes(_baseline_bytes("9.2.3"))
            path.chmod(0o600)
        case _:
            path.write_bytes(_baseline_bytes("9.2.3"))
            (tmp_path / rollout.MANIFEST).write_text(
                _MANIFEST_SOURCE.replace("diagnostic-baseline.json", "other-baseline.json")
            )

    with pytest.raises(rollout.RolloutError, match="controller-owned"):
        rollout.refresh_preserved_provenance(tmp_path, preserved)
