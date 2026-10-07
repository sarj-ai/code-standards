from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from pathlib import Path

import pytest

from sarj_standards.libs.release import test_selection
from sarj_standards.libs.release.process import ProcessFailureError, ProcessResult, run_process
from sarj_standards.libs.release.test_selection import TestPlan as SelectionPlan, execute_plan, select_tests


def _write(root: Path, path: str, source: str = "def test_fixture():\n    pass\n") -> None:
    destination = root / path
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(source, encoding="utf-8")


def _git(root: Path, *args: str) -> str:
    return run_process(
        (
            "git",
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            *args,
        ),
        cwd=root,
        capture_output=True,
    ).stdout.strip()


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q")
    for name in (
        "test_smoke.py",
        "test_cli_startup.py",
        "test_architecture.py",
        "test_supply_chain.py",
        "test_ci_scope.py",
        "test_mobile_tools.py",
        "test_runner.py",
        "test_rule_inventory_artifact.py",
        "release/test_rollout.py",
    ):
        _write(tmp_path, "packages/standards/tests/" + name)
    _write(
        tmp_path,
        "packages/standards/pyproject.toml",
        '[project]\nname="code-standards"\nversion="1.0.0"\ndependencies=["sarj-python-lint==1.0.0", "pydantic==2.13.5"]\n',
    )
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "base")
    return tmp_path


def test_test_only_change_includes_smoke_and_untracked_tests(repository: Path) -> None:
    _write(repository, "packages/standards/tests/test_new_feature.py")
    plan = select_tests(repository, base="HEAD")
    assert not plan.full
    assert "tests/test_new_feature.py" in plan.tests
    assert "tests/test_smoke.py" in plan.tests
    assert "tests/test_mobile_tools.py" not in plan.tests


@pytest.mark.parametrize(
    "path",
    [
        "packages/standards/tests/conftest.py",
        "packages/standards/tests/release/fakes.py",
        ".github/workflows/ci.yml",
        "packages/standards/src/sarj_standards/api.py",
        "packages/standards/src/sarj_standards/libs/release/test_selection.py",
        "new-owner/file.py",
    ],
)
def test_shared_or_unknown_changes_fall_back_to_every_test(repository: Path, path: str) -> None:
    _write(repository, path)
    plan = select_tests(repository, base="HEAD")
    assert plan.full
    assert len(plan.tests) == plan.total_files


def test_release_change_tracks_transitive_relative_imports(repository: Path) -> None:
    source = "packages/standards/src/sarj_standards/"
    _write(repository, f"{source}libs/release/status.py", "VALUE = 1\n")
    _write(repository, f"{source}cli.py", "from .libs.release.status import VALUE\n")
    _write(repository, "packages/standards/tests/test_other_consumer.py", "from sarj_standards.cli import VALUE\n")
    _git(repository, "add", ".")
    _git(repository, "commit", "-qm", "imports")
    _write(repository, f"{source}libs/release/status.py", "VALUE = 2\n")
    plan = select_tests(repository, base="HEAD")
    assert not plan.full
    assert "tests/test_other_consumer.py" in plan.tests
    assert "tests/release/test_rollout.py" in plan.tests
    assert "tests/test_mobile_tools.py" not in plan.tests


def test_release_dispatch_lazy_import_does_not_expand_unrelated_commands(repository: Path) -> None:
    source = "packages/standards/src/sarj_standards/"
    _write(repository, f"{source}libs/release/status.py", "VALUE = 1\n")
    _write(
        repository,
        f"{source}cli/main.py",
        "def release_status():\n    from sarj_standards.libs.release.status import VALUE\n    return VALUE\n\ndef other_command():\n    return 1\n",
    )
    _write(
        repository,
        "packages/standards/tests/test_unrelated_command.py",
        "from sarj_standards.cli.main import other_command\n",
    )
    _git(repository, "add", ".")
    _git(repository, "commit", "-qm", "dispatcher")
    _write(repository, f"{source}libs/release/status.py", "VALUE = 2\n")
    plan = select_tests(repository, base="HEAD")
    assert not plan.full
    assert "tests/release/test_rollout.py" in plan.tests
    assert "tests/test_cli_startup.py" in plan.tests
    assert "tests/test_unrelated_command.py" not in plan.tests


def test_rule_change_and_local_pin_bump_select_integration(repository: Path) -> None:
    manifest = repository / "packages/standards/pyproject.toml"
    manifest.write_text(manifest.read_text(encoding="utf-8").replace("1.0.0", "1.0.1"), encoding="utf-8")
    _write(repository, "packages/python/src/sarj_python_lint/rules/new_rule.py", "VALUE = 1\n")
    plan = select_tests(repository, base="HEAD")
    assert not plan.full
    assert "tests/test_runner.py" in plan.tests
    assert "tests/test_rule_inventory_artifact.py" in plan.tests
    assert "tests/test_mobile_tools.py" not in plan.tests


def test_dependency_change_keeps_full_suite(repository: Path) -> None:
    manifest = repository / "packages/standards/pyproject.toml"
    manifest.write_text(manifest.read_text(encoding="utf-8").replace("2.13.5", "2.14.0"), encoding="utf-8")
    assert select_tests(repository, base="HEAD").full


def test_cli_reference_update_does_not_expand_all_rule_artifacts(repository: Path) -> None:
    _write(repository, "packages/standards/tests/test_cli_reference_artifact.py")
    _git(repository, "add", ".")
    _git(repository, "commit", "-qm", "cli test")
    _write(repository, "packages/standards/src/sarj_standards/configs/cli-reference.v1.json", "{}\n")
    plan = select_tests(repository, base="HEAD")
    assert not plan.full
    assert "tests/test_cli_reference_artifact.py" in plan.tests
    assert "tests/test_rule_inventory_artifact.py" not in plan.tests


@pytest.mark.parametrize("event", ["schedule", "workflow_dispatch", "unknown"])
def test_audit_events_run_all_tests_even_without_changes(repository: Path, event: str) -> None:
    assert select_tests(repository, base="HEAD", event=event).full


def test_missing_comparison_falls_back_to_full_suite(repository: Path) -> None:
    assert select_tests(repository, base="missing-revision").full


def test_removed_tests_are_not_sent_to_pytest(repository: Path) -> None:
    (repository / "packages/standards/tests/test_mobile_tools.py").unlink()
    plan = select_tests(repository, base="HEAD")
    assert not plan.full
    assert "tests/test_mobile_tools.py" not in plan.tests
    assert plan.tests


@pytest.mark.parametrize("jobs", [0, 17])
def test_invalid_workers_fail_before_execution(tmp_path: Path, jobs: int) -> None:
    plan = SelectionPlan(full=False, reason="test", changed_files=(), tests=("tests/test_small.py",), total_files=1)
    with pytest.raises(ValueError, match="between 1 and 16"):
        execute_plan(tmp_path, plan, jobs=jobs)


def test_small_suite_avoids_worker_startup_and_keeps_argv_paths(tmp_path: Path) -> None:
    plan = SelectionPlan(full=False, reason="test", changed_files=(), tests=("tests/test_a space.py",), total_files=1)
    calls: list[tuple[str, ...]] = []

    def runner(argv: tuple[str, ...], *, cwd: Path, capture_output: bool = False) -> ProcessResult:
        assert cwd == tmp_path / "packages/standards"
        assert not capture_output
        calls.append(argv)
        return ProcessResult(0)

    execute_plan(tmp_path, plan, jobs=4, runner=runner)
    assert "-n" not in calls[0]
    assert calls[0][-1] == "tests/test_a space.py"


def test_test_cli_preserves_pytest_failure_exit_code(repository: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def failure(root: Path, plan: SelectionPlan, *, jobs: int = 4) -> None:
        assert root == repository
        assert plan.tests
        assert jobs == 4
        raise ProcessFailureError(("pytest",), 1)

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- CLI global process lookup must be intercepted to verify exit propagation.
        test_selection, "execute_plan", failure
    )
    assert test_selection.main(["--root", str(repository), "--base", "HEAD", "--run"]) == 1
