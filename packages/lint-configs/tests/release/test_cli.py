from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from sarj_lint_configs import __main__ as cli
from sarj_lint_configs.libs import release


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

    monkeypatch.setattr(release, "changed_release_targets", changed)
    output = tmp_path / "github-output"

    status = cli.main(
        [
            "repo",
            "release",
            "changes",
            "--before",
            "old",
            "--after",
            "new",
            "--github-output",
            str(output),
            "--dest",
            str(tmp_path),
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

    status = cli.main(
        [
            "repo",
            "release",
            "lock-age",
            "package-lock.json",
            "--exclude",
            "from-cli",
            "--exclude",
            "from-both",
            "--dest",
            str(tmp_path),
        ]
    )

    assert status == 0
    assert policies == [
        release.ReleaseAgePolicy(
            timedelta(days=21),
            frozenset({"from-env", "from-cli", "from-both"}),
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

    status = cli.main(["repo", "release", "publish", "python", "--dest", str(tmp_path)])

    assert status == 2
    assert capsys.readouterr().err == "error: uv publish failed with exit code 1\n"
