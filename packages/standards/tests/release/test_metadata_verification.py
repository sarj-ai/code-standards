from __future__ import annotations

from dataclasses import dataclass, replace
import json
from pathlib import Path
import subprocess
from typing import TYPE_CHECKING, TypeGuard, override

import pytest

from sarj_standards.libs.json_boundary import parse_json
from sarj_standards.libs.release import metadata_verification, rollout


if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


@dataclass(frozen=True)
class Candidate:
    repo: Path
    base: str
    baseline: Path


def _object(value: object) -> TypeGuard[dict[str, object]]:
    return _mapping(value) and all(isinstance(key, str) for key in value)


def _mapping(value: object) -> TypeGuard[dict[object, object]]:
    return isinstance(value, dict)


def _data(path: Path) -> dict[str, object]:
    value = parse_json(path.read_text(encoding="utf-8"))
    assert _object(value)
    return value


def _git(repo: Path, *arguments: str) -> str:
    return (
        rollout.SubprocessRunner()
        .run(
            (
                "git",
                "-c",
                "core.hooksPath=/dev/null",
                "-c",
                "user.name=Test",
                "-c",
                "user.email=test@example.com",
                *arguments,
            ),
            cwd=repo,
        )
        .stdout.strip()
    )


def _commit(repo: Path) -> str:
    _git(repo, "add", "--all")
    _git(repo, "commit", "--quiet", "-m", "candidate")
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture
def candidate(tmp_path: Path) -> Candidate:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "--quiet")
    _git(repo, "config", "core.filemode", "true")
    manifest = repo / ".sarj-standards.toml"
    manifest.write_text('bundle = "8.38.16"\nrule_profile = "all"\nschema = 4\n')
    baseline = repo / "diagnostic-baseline.json"
    baseline.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "provenance": {"bundleVersion": "8.38.16", "consumerBaseSha": "a" * 40, "catalogDigest": "b" * 64},
                "diagnostics": [{"rule": "example", "path": "src/example.py"}],
            }
        )
    )
    (repo / "app.py").write_text("value = 1\n")
    base = _commit(repo)
    manifest.write_text(manifest.read_text().replace("8.38.16", "8.38.17"))
    data = _data(baseline)
    data["provenance"] = {"bundleVersion": "8.38.17", "consumerBaseSha": base, "catalogDigest": "c" * 64}
    baseline.write_text(json.dumps(data))
    _commit(repo)
    return Candidate(repo, base, baseline)


def _proved(candidate: Candidate) -> bool:
    repo, base, baseline = candidate.repo, candidate.base, candidate.baseline
    return metadata_verification.metadata_only_rollout(
        repo, rollout.SubprocessRunner(), base_sha=base, version="8.38.17", baseline_path=baseline
    )


def test_real_git_bundle_and_provenance_update_is_proved(candidate: Candidate) -> None:
    assert _proved(candidate)


@pytest.mark.parametrize(
    "change",
    [
        "source",
        "lock",
        "workflow",
        "rule-settings",
        "diagnostics",
        "baseline-schema",
        "manifest-type",
        "baseline-type",
        "provenance-extra",
        "provenance-base",
        "provenance-version",
        "provenance-digest",
        "addition",
        "deletion",
        "executable",
        "symlink",
        "malformed-manifest",
        "malformed-baseline",
    ],
)
def test_other_real_git_changes_require_full_verification(candidate: Candidate, change: str) -> None:
    repo, baseline = candidate.repo, candidate.baseline
    manifest = repo / ".sarj-standards.toml"
    match change:
        case "source":
            (repo / "app.py").write_text("value = 2\n")
        case "lock":
            (repo / "uv.lock").write_text("version = 1\n")
        case "workflow":
            workflow = repo / ".github/workflows/standards.yml"
            workflow.parent.mkdir(parents=True)
            workflow.write_text("name: changed\n")
        case "rule-settings":
            manifest.write_text(manifest.read_text().replace('rule_profile = "all"', 'rule_profile = "recommended"'))
        case "manifest-type":
            manifest.write_text(manifest.read_text().replace("schema = 4", "schema = 4.0"))
        case "baseline-type":
            data = _data(baseline)
            data["schemaVersion"] = True
            baseline.write_text(json.dumps(data))
        case (
            "diagnostics"
            | "baseline-schema"
            | "provenance-extra"
            | "provenance-base"
            | "provenance-version"
            | "provenance-digest"
        ):
            data = _data(baseline)
            provenance = data["provenance"]
            assert _object(provenance)
            match change:
                case "diagnostics":
                    data["diagnostics"] = []
                case "baseline-schema":
                    data["schemaVersion"] = 2
                case "provenance-extra":
                    provenance["other"] = True
                case "provenance-base":
                    provenance["consumerBaseSha"] = "d" * 40
                case "provenance-version":
                    provenance["bundleVersion"] = "8.38.18"
                case "provenance-digest":
                    provenance["catalogDigest"] = "invalid"
            baseline.write_text(json.dumps(data))
        case "addition":
            (repo / "extra.json").write_text("{}\n")
        case "deletion":
            baseline.unlink()
        case "executable":
            manifest.chmod(0o755)
        case "symlink":
            baseline.unlink()
            baseline.symlink_to("app.py")
        case "malformed-manifest":
            manifest.write_text("bundle = [\n")
        case "malformed-baseline":
            baseline.write_text("{\n")
        case _:
            raise AssertionError(change)
    _commit(repo)
    assert not _proved(candidate)


@pytest.mark.parametrize("change", ["modified", "untracked", "missing-base", "outside-baseline", "wrong-version"])
def test_unproved_checkout_or_identity_uses_full_gate(candidate: Candidate, change: str) -> None:
    repo, base, baseline = candidate.repo, candidate.base, candidate.baseline
    version = "8.38.17"
    match change:
        case "modified":
            (repo / "app.py").write_text("value = 2\n")
        case "untracked":
            (repo / "unexpected.txt").write_text("extra\n")
        case "missing-base":
            base = "d" * 40
        case "outside-baseline":
            baseline = repo.parent / "diagnostic-baseline.json"
        case "wrong-version":
            version = "8.38.18"
        case _:
            raise AssertionError(change)
    assert not metadata_verification.metadata_only_rollout(
        repo, rollout.SubprocessRunner(), base_sha=base, version=version, baseline_path=baseline
    )


@pytest.mark.parametrize("failed", ["", "standards", "metadata"])
def test_proved_path_requires_full_standards_and_repository_checks(candidate: Candidate, failed: str) -> None:
    repo, base, baseline = candidate.repo, candidate.base, candidate.baseline
    calls: list[tuple[str, ...]] = []

    class Runner(rollout.SubprocessRunner):
        @override
        def run(
            self,
            command: Sequence[str],
            *,
            cwd: Path | None = None,
            check: bool = True,
            env: Mapping[str, str] | None = None,
        ) -> subprocess.CompletedProcess[str]:
            if command[0] == "git":
                return super().run(command, cwd=cwd, check=check, env=env)
            calls.append(tuple(command))
            assert cwd == repo
            assert env == {"SARJ_STANDARDS_BASE": base}
            assert not check
            label = "standards" if command[1] == "exact-published-tool" else "metadata"
            return subprocess.CompletedProcess(command, int(label == failed), label, "")

    consumer = replace(
        rollout.Consumer("Example", "example/consumer", "main", ("full",)), verify_metadata=("metadata",)
    )
    result = rollout.run_consumer_verification(
        consumer,
        repo,
        Runner(),
        ("prefix",),
        environment={"SARJ_STANDARDS_BASE": base},
        standards_tool=("exact-published-tool",),
        base_sha=base,
        version="8.38.17",
        baseline_path=baseline,
    )
    expected: list[tuple[str, ...]] = [("prefix", "exact-published-tool", "check", "--trust-repository-code", ".")]
    if failed != "standards":
        expected.append(("prefix", "metadata"))
    assert calls == expected
    assert bool(result.returncode) == bool(failed)


@pytest.mark.parametrize("condition", ["default", "no-tool", "source-change"])
def test_unproved_or_disabled_path_runs_the_normal_gate(candidate: Candidate, condition: str) -> None:
    repo, base, baseline = candidate.repo, candidate.base, candidate.baseline
    if condition == "source-change":
        (repo / "app.py").write_text("value = 2\n")
        _commit(repo)
    calls: list[tuple[str, ...]] = []

    class Runner(rollout.SubprocessRunner):
        @override
        def run(
            self,
            command: Sequence[str],
            *,
            cwd: Path | None = None,
            check: bool = True,
            env: Mapping[str, str] | None = None,
        ) -> subprocess.CompletedProcess[str]:
            if command[0] == "git":
                return super().run(command, cwd=cwd, check=check, env=env)
            calls.append(tuple(command))
            return subprocess.CompletedProcess(command, 0, "", "")

    consumer = replace(
        rollout.Consumer("Example", "example/consumer", "main", ("full",)),
        verify_metadata=() if condition == "default" else ("metadata",),
        verify_checks=(("application-tests",),),
        verify_jobs=1,
    )
    result = rollout.run_consumer_verification(
        consumer,
        repo,
        Runner(),
        (),
        environment={},
        standards_tool=() if condition == "no-tool" else ("exact-published-tool",),
        base_sha=base,
        version="8.38.17",
        baseline_path=baseline,
    )
    assert result.returncode == 0
    assert calls == [("full",), ("application-tests",)]
