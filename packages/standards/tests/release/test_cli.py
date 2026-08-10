from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

import sarj_standards.cli.main as cli
from sarj_standards.libs import release


if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def test_changes_cli_passes_keyword_revisions(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[tuple[Path, str, str]] = []

    def changed(root: Path, *, before: str, after: str) -> dict[str, bool]:
        calls.append((root, before, after))
        return {target: target == "python" for target in release.RELEASE_TARGETS}

    monkeypatch.setattr(release, "pending_release_targets", changed)
    output = tmp_path / "github-output"

    status = cli.main(
        [
            "--root",
            str(tmp_path),
            "maintain",
            "release",
            "changes",
            "--before",
            "old",
            "--after",
            "new",
            "--github-output",
            str(output),
        ]
    )

    assert status == 0
    assert calls == [(tmp_path.resolve(), "old", "new")]
    assert "python=true\n" in output.read_text(encoding="utf-8")


def test_release_cli_preserves_release_age_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    policies: list[release.ReleaseAgePolicy] = []

    def check(
        lockfile: Path,
        policy: release.ReleaseAgePolicy,
    ) -> release.ReleaseAgeReport:
        assert lockfile == (tmp_path / "package-lock.json").resolve()
        policies.append(policy)
        return release.ReleaseAgeReport((), ())

    monkeypatch.setattr(release, "check_lockfile_release_age", check)
    monkeypatch.setenv("MIN_RELEASE_AGE_DAYS", "21")
    monkeypatch.setenv("MIN_RELEASE_AGE_EXCLUDE", "from-env,from-both")
    (tmp_path / "release-age.txt").write_text("from-file@1.0.0\n", encoding="utf-8")

    status = cli.main(
        [
            "--root",
            str(tmp_path),
            "maintain",
            "release",
            "lock-age",
            "package-lock.json",
            "--exclude",
            "from-cli",
            "--exclude",
            "from-both",
            "--exclude-file",
            "release-age.txt",
        ]
    )

    assert status == 0
    assert policies == [
        release.ReleaseAgePolicy(
            timedelta(days=21),
            frozenset({"from-env", "from-cli", "from-both", "from-file@1.0.0"}),
        )
    ]


def test_release_process_failure_is_a_clean_cli_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail(_root: Path, _target: release.PublishTarget) -> None:
        raise release.ProcessFailureError(("uv", "publish"), 1)

    monkeypatch.setattr(release, "publish_target", fail)

    status = cli.main(["--root", str(tmp_path), "maintain", "release", "publish", "python"])

    assert status == 2
    assert capsys.readouterr().err == "error: uv publish failed with exit code 1\n"


def test_verify_tags_without_commit_preserves_missing_tag_mode(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[Path] = []

    def missing(root: Path) -> tuple[str, ...]:
        calls.append(root)
        return ()

    monkeypatch.setattr(release, "missing_remote_release_tags", missing)

    status = cli.main(["--root", str(tmp_path), "maintain", "release", "verify-tags"])

    assert status == 0
    assert calls == [tmp_path.resolve()]


def test_verify_tags_process_failure_is_not_reported_as_recovery(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail(_root: Path, *, commit: str) -> tuple[str, ...]:
        assert commit == "publish-sha"
        raise release.ProcessFailureError(("git", "ls-remote"), 128)

    monkeypatch.setattr(release, "verify_remote_release_tags", fail)

    status = cli.main(
        ["--root", str(tmp_path), "maintain", "release", "verify-tags", "--commit", "publish-sha"]
    )

    assert status == 2
    assert capsys.readouterr().err == "error: git ls-remote failed with exit code 128\n"
