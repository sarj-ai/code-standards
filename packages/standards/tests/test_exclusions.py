from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

import pytest

from sarj_standards import api
from sarj_standards.cli.main import main
from sarj_standards.libs.adoption import exclusions, manifest


if TYPE_CHECKING:
    from pathlib import Path


def _adopt(root: Path, *, verify_paths: tuple[str, ...] = (".",), auxiliary_policy: bool = False) -> Path:
    adopted = manifest.Manifest(
        version="1.0.0",
        configs=manifest.ALL_CONFIGS,
        python_dest=".",
        typescript_dest=".",
        verify_paths=verify_paths,
        durable_artifacts=("evidence/**",) if auxiliary_policy else manifest.DEFAULT_DURABLE_ARTIFACTS,
        text_excluded_paths=("templates/**",) if auxiliary_policy else (),
        doctor_excluded_paths=("tests/fixtures/**",) if auxiliary_policy else (),
    )
    path = manifest.manifest_path(root)
    path.write_text(adopted.render(), encoding="utf-8")
    return path


def test_terraform_test_ban_cannot_be_excluded_by_path_rule_or_override(tmp_path: Path) -> None:
    source = tmp_path / "vendor" / "routing.tftest.hcl"
    source.parent.mkdir()
    source.write_text('# sarj-noqa: SARJ206\nrun "routing" {}\n', encoding="utf-8")
    adopted = manifest.Manifest(
        version=api.__version__,
        configs=(),
        python_dest=".",
        typescript_dest=".",
        hook_manager="none",
        excluded_paths=("vendor/**",),
        excluded_rules=("iac:no-terraform-test-file",),
        exclusion_overrides=(
            manifest.ExclusionOverride(
                ("vendor/**",),
                ("iac:no-terraform-test-file",),
                "Prove categorical bans ignore scoped exclusions.",
            ),
        ),
    )
    manifest.manifest_path(tmp_path).write_text(adopted.render(), encoding="utf-8")

    report = api.Standards(tmp_path).analyze([str(source)])

    assert [item.code for item in report.diagnostics] == ["SARJ206"]


def test_tracked_terraform_test_is_checked_outside_verify_paths(tmp_path: Path) -> None:
    source = tmp_path / "outside" / "ROUTING.TFTEST.JSON"
    source.parent.mkdir()
    source.write_text("{}\n", encoding="utf-8")
    selected = tmp_path / "src"
    selected.mkdir()
    adopted = manifest.Manifest(
        version=api.__version__,
        configs=(),
        python_dest=".",
        typescript_dest=".",
        hook_manager="none",
        verify_paths=("src",),
    )
    manifest.manifest_path(tmp_path).write_text(adopted.render(), encoding="utf-8")
    subprocess.run(("git", "init", "-q"), cwd=tmp_path, check=True)
    subprocess.run(("git", "add", "outside/ROUTING.TFTEST.JSON"), cwd=tmp_path, check=True)

    report = api.Standards(tmp_path).analyze()

    assert [item.code for item in report.diagnostics] == ["SARJ206"]


def test_add_and_remove_are_atomic_idempotent_manifest_operations(tmp_path: Path) -> None:
    path = _adopt(tmp_path, verify_paths=("src", "tests"), auxiliary_policy=True)

    added = exclusions.add(tmp_path, "path", "generated\\clients/**")
    first = path.read_bytes()
    duplicate = exclusions.add(tmp_path, "path", "generated/clients/**")

    assert added.changed
    assert not duplicate.changed
    assert path.read_bytes() == first
    assert manifest.load(tmp_path).excluded_paths == ("generated/clients/**",)  # type: ignore[union-attr]
    assert manifest.load(tmp_path).verify_paths == ("src", "tests")  # type: ignore[union-attr]
    assert manifest.load(tmp_path).durable_artifacts == ("evidence/**",)  # type: ignore[union-attr]
    assert manifest.load(tmp_path).text_excluded_paths == ("templates/**",)  # type: ignore[union-attr]
    assert manifest.load(tmp_path).doctor_excluded_paths == ("tests/fixtures/**",)  # type: ignore[union-attr]

    removed = exclusions.remove(tmp_path, "path", "generated/clients/**")
    absent = exclusions.remove(tmp_path, "path", "generated/clients/**")
    assert removed.changed
    assert not absent.changed
    assert manifest.load(tmp_path).excluded_paths == ()  # type: ignore[union-attr]


@pytest.mark.parametrize("value", ["**", "../generated/**", "/outside/**", ".sarj-standards.toml"])
def test_path_exclusions_cannot_escape_or_disable_the_repository(tmp_path: Path, value: str) -> None:
    path = _adopt(tmp_path)
    before = path.read_bytes()

    with pytest.raises(ValueError, match="exclusion"):
        exclusions.add(tmp_path, "path", value)

    assert path.read_bytes() == before


def test_rule_exclusions_require_an_exact_known_engine_selector(tmp_path: Path) -> None:
    _adopt(tmp_path)

    with pytest.raises(ValueError, match="engine:rule"):
        exclusions.add(tmp_path, "rule", "no-explicit-any")
    with pytest.raises(ValueError, match="engine:rule"):
        exclusions.add(tmp_path, "rule", "unknown:no-explicit-any")
    with pytest.raises(ValueError, match="unknown Standards rule"):
        exclusions.add(tmp_path, "rule", "python:this-rule-does-not-exist")
    with pytest.raises(ValueError, match="unknown Standards rule"):
        exclusions.add(tmp_path, "rule", "eslint:@sarj/this-rule-does-not-exist")
    with pytest.raises(ValueError, match="unknown Standards rule"):
        exclusions.add(tmp_path, "rule", "eslint:this-rule-does-not-exist")

    assert exclusions.add(tmp_path, "rule", "eslint:@typescript-eslint/no-explicit-any").changed
    assert exclusions.add(tmp_path, "rule", "eslint:no-console").changed
    assert exclusions.add(tmp_path, "rule", "python:no-comment-cruft").changed
    assert exclusions.add(tmp_path, "rule", "python:LIB001").changed


def test_cli_exposes_one_concise_exclusion_workflow(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _adopt(tmp_path)

    assert main(["--root", str(tmp_path), "exclude", "list"]) == 0
    assert "all rules apply to all paths" in capsys.readouterr().out
    assert main(["--root", str(tmp_path), "exclude", "add", "path", "generated/**"]) == 0
    assert "excluded path: generated/**" in capsys.readouterr().out
    assert main(["--root", str(tmp_path), "exclude", "add", "path", "generated/**"]) == 0
    assert "already excluded path: generated/**" in capsys.readouterr().out
    assert main(["--root", str(tmp_path), "exclude", "list"]) == 0
    assert capsys.readouterr().out == "path  generated/**\n"
    assert main(["--root", str(tmp_path), "exclude", "remove", "path", "generated/**"]) == 0
    assert "included path: generated/**" in capsys.readouterr().out


def test_cli_requires_adoption_before_mutating(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--root", str(tmp_path), "exclude", "add", "path", "generated/**"]) == 2
    assert "run `code-standards setup` first" in capsys.readouterr().err
