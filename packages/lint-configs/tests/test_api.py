"""The typed facade remains importable independently of argparse."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sarj_lint_configs import api


if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    import pytest


def test_every_declared_public_api_resolves() -> None:
    assert api.__all__
    assert all(hasattr(api, name) for name in api.__all__)
    assert len(api.__all__) == len(set(api.__all__))


def test_public_api_keeps_pre_facade_compatibility_exports() -> None:
    preferred = {"Change", "Finding", "Inspection", "Result", "Standards", "Status", "__version__"}
    compatibility = {"RUFF_STRICT", "plan_upgrade", "check_text", "ReleaseTarget", "initialize", "sync_configs"}

    assert preferred | compatibility <= set(api.__all__)


def test_standards_facade_returns_typed_doctor_result(tmp_path: Path) -> None:
    result = api.Standards(tmp_path).doctor()

    assert not result.ok
    assert result.status is api.Status.DRIFT
    assert result.findings[0].id == "doctor.manifest.absent"


def test_standards_facade_rejects_selected_paths_outside_root(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside.py"
    outside.write_text("value = 1\n", encoding="utf-8")

    result = api.Standards(tmp_path).check([str(outside)])

    assert result.status is api.Status.INVALID
    assert result.exit_code == 2
    assert result.findings[0].id == "check.input.invalid"


def test_standards_facade_rejects_selected_symlink(tmp_path: Path) -> None:
    source = tmp_path / "source.py"
    source.write_text("value = 1\n", encoding="utf-8")
    link = tmp_path / "linked.py"
    link.symlink_to(source)

    result = api.Standards(tmp_path).check(["linked.py"])

    assert result.status is api.Status.INVALID
    assert "symlink" in result.findings[0].message


def test_standards_facade_enforces_selected_application_dependency_policy(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    adopted = api.Manifest(
        version=api.__version__,
        configs=("markdownlint",),
        python_dest=".",
        typescript_dest=".",
        profile="application",
    )
    (tmp_path / ".sarj-standards.toml").write_text(adopted.render(), encoding="utf-8")
    package = tmp_path / "package.json"
    package.write_text('{"dependencies":{"moment":"1"}}\n', encoding="utf-8")

    def clean_check(_paths: Sequence[str]) -> int:
        return 0

    monkeypatch.setattr(api, "check", clean_check)

    result = api.Standards(tmp_path).check(["package.json"])

    assert result.status is api.Status.DRIFT
    assert [finding.id for finding in result.findings] == ["LIB102"]


def test_standards_facade_runs_eslint_for_selected_typescript(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "component.ts"
    source.write_text("export const value = 1;\n", encoding="utf-8")
    command = api.Command("ESLint", ("true",), tmp_path)

    def clean_check(_paths: Sequence[str]) -> int:
        return 0

    def selected(_root: Path, _paths: Sequence[str]) -> list[api.Command]:
        return [command]

    def execute(commands: Sequence[api.Command]) -> int:
        return 1 if list(commands) == [command] else 0

    monkeypatch.setattr(api, "check", clean_check)
    monkeypatch.setattr(api, "selected_eslint_commands", selected)
    monkeypatch.setattr(api, "execute", execute)

    result = api.Standards(tmp_path).check(["component.ts"])

    assert result.status is api.Status.DRIFT


def test_standards_facade_init_dry_run_never_writes(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "fixture"\nversion = "0.0.0"\nrequires-python = ">=3.14"\n',
        encoding="utf-8",
    )

    result = api.Standards(tmp_path).init(dry_run=True)

    assert result.status is api.Status.CHANGED
    assert result.changes
    assert any(change.path == tmp_path / ".ruff-strict.toml" for change in result.changes)
    assert not (tmp_path / ".sarj-standards.toml").exists()


def test_standards_facade_init_exposes_project_roots_and_truthful_no_install_preview(tmp_path: Path) -> None:
    python_root = tmp_path / "python"
    python_root.mkdir()
    (python_root / "pyproject.toml").write_text(
        '[project]\nname = "fixture"\nversion = "0.0.0"\nrequires-python = ">=3.14"\n',
        encoding="utf-8",
    )

    result = api.Standards(tmp_path).init(
        configs=("ruff",),
        python_root="python",
        install=False,
        dry_run=True,
    )

    assert result.status is api.Status.CHANGED
    assert any(change.path == python_root / ".ruff-strict.toml" for change in result.changes)
    assert all(change.action != "run" for change in result.changes)
    assert not (python_root / ".ruff-strict.toml").exists()
