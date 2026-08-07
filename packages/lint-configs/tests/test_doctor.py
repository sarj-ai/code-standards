# sarj-doctor-ignore-retired-rules -- this module intentionally embeds retired
# identifiers to prove that doctor diagnoses consumer repositories correctly.

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

import pytest

from sarj_lint_configs import __main__ as cli
from sarj_lint_configs import doctor, manifest, scaffold
from sarj_lint_configs.doctor import Level, check_pyright_deprecated, check_ruff_policy_authority


if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize(
    ("name", "setting"),
    [
        pytest.param("pyrightconfig.json", '"reportDeprecated": false,', id="json-false"),
        pytest.param(".pyright-strict.json", '"reportDeprecated": "warning",', id="json-warning"),
        pytest.param("pyproject.toml", 'reportDeprecated = "none"', id="toml-none"),
    ],
)
def test_doctor_reports_deprecated_api_protection_that_is_not_an_error(tmp_path: Path, name: str, setting: str) -> None:
    _ = (tmp_path / name).write_text(f"{setting}\n", encoding="utf-8")

    findings = list(check_pyright_deprecated(tmp_path))

    assert [finding.level for finding in findings] == [Level.DRIFT]
    assert "reportDeprecated" in findings[0].where
    assert "restore it to keep deprecated APIs visible" in findings[0].detail


@pytest.mark.parametrize(
    ("name", "setting"),
    [
        pytest.param("pyrightconfig.json", '"reportDeprecated": "error",', id="json"),
        pytest.param("pyproject.toml", 'reportDeprecated = "error"', id="toml"),
        pytest.param("pyproject.toml", "reportDeprecated = 'error'", id="toml-single-quoted"),
    ],
)
def test_doctor_accepts_deprecated_api_protection_at_error(tmp_path: Path, name: str, setting: str) -> None:
    _ = (tmp_path / name).write_text(f"{setting}\n", encoding="utf-8")

    assert not list(check_pyright_deprecated(tmp_path))


def test_doctor_rejects_non_string_manifest_destinations_without_a_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / ".sarj-standards.toml").write_text(
        'version = "0.48.0"\nconfigs = []\n[dest]\npython = 3\ntypescript = []\n',
        encoding="utf-8",
    )

    assert cli.main(["doctor", "--dest", str(tmp_path)]) == 2
    assert "must be a non-empty string" in capsys.readouterr().out


def test_staged_adoption_health_does_not_walk_unrelated_sources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "src").mkdir()
    staged = tmp_path / "src" / "changed.py"
    staged.write_text("value = 1\n", encoding="utf-8")

    def unexpected_walk(_root: Path) -> tuple[Path, ...]:
        raise AssertionError

    monkeypatch.setattr(doctor, "_walk", unexpected_walk)

    findings = doctor.diagnose_adoption_health(tmp_path, (staged,))

    assert [finding.id for finding in findings] == ["doctor.manifest.absent"]


def test_staged_relative_paths_are_resolved_from_the_repository_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    selected = tmp_path / "deep" / "nested" / "project" / "pyproject.toml"
    selected.parent.mkdir(parents=True)
    selected.write_text(
        '[tool.ruff]\nextend = ".ruff-strict.toml"\n[tool.ruff.lint]\nselect = ["ALL"]\n',
        encoding="utf-8",
    )
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    findings = doctor.diagnose_adoption_health(tmp_path, (selected.relative_to(tmp_path),))

    assert "doctor.ruff.replaces-policy" in {finding.id for finding in findings}


@pytest.mark.parametrize("timed_out_argument", ["--is-inside-work-tree", "--git-path"])
def test_git_discovery_timeouts_are_nonfatal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    timed_out_argument: str,
) -> None:
    (tmp_path / ".pre-commit-config.yaml").write_text(
        f"repos:\n{scaffold.precommit_block(python=True, version=manifest.adopted_version())}",
        encoding="utf-8",
    )

    def run(command: tuple[str, ...], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        if timed_out_argument in command:
            raise subprocess.TimeoutExpired(command, 5)
        return subprocess.CompletedProcess(command, 0, "true\n", "")

    def which(_name: str) -> str:
        return "/usr/bin/git"

    monkeypatch.setattr("sarj_lint_configs.libs.adoption.doctor.shutil.which", which)
    monkeypatch.setattr("sarj_lint_configs.libs.adoption.doctor.subprocess.run", run)

    assert doctor.diagnose_adoption_health(tmp_path)


@pytest.mark.parametrize("key", ["ignore", "select"])
def test_doctor_rejects_replacement_rule_policy_in_extending_ruff_config(tmp_path: Path, key: str) -> None:
    (tmp_path / "pyproject.toml").write_text(
        f'[tool.ruff]\nextend = ".ruff-strict.toml"\n\n[tool.ruff.lint]\n{key} = ["ALL"]\n',
        encoding="utf-8",
    )

    findings = list(check_ruff_policy_authority(tmp_path))

    assert [finding.level for finding in findings] == [Level.DRIFT]
    assert findings[0].where == f"pyproject.toml: [tool.ruff.lint].{key}"
    assert f"use `extend-{key}`" in findings[0].detail


def test_doctor_accepts_additive_rule_policy_in_extending_ruff_config(tmp_path: Path) -> None:
    (tmp_path / "ruff.toml").write_text(
        'extend = ".ruff-strict.toml"\n\n[lint]\nextend-select = ["B904"]\nextend-ignore = ["D417"]\n',
        encoding="utf-8",
    )

    assert not list(check_ruff_policy_authority(tmp_path))


def test_doctor_rejects_a_ruff_chain_that_never_reaches_strict(tmp_path: Path) -> None:
    root_config = tmp_path / "python" / "pyproject.toml"
    root_config.parent.mkdir()
    root_config.write_text("[tool.ruff]\nline-length = 100\n", encoding="utf-8")
    child_config = tmp_path / "python" / "agent" / "pyproject.toml"
    child_config.parent.mkdir()
    child_config.write_text('[tool.ruff]\nextend = "../pyproject.toml"\n', encoding="utf-8")

    findings = list(check_ruff_policy_authority(tmp_path))

    assert [finding.where for finding in findings] == ["python/agent/pyproject.toml: Ruff config"]
    assert "canonical .ruff-strict.toml" in findings[0].detail
    assert findings[0].id == "doctor.ruff.authority"


def test_doctor_accepts_a_monorepo_ruff_chain_that_terminates_at_strict(tmp_path: Path) -> None:
    central = tmp_path / "python" / "pyproject.toml"
    central.parent.mkdir()
    central.write_text('[tool.ruff]\nextend = "../.ruff-strict.toml"\n', encoding="utf-8")
    leaf = tmp_path / "python" / "agent" / "pyproject.toml"
    leaf.parent.mkdir()
    leaf.write_text('[tool.ruff]\nextend = "../pyproject.toml"\n', encoding="utf-8")

    assert not list(check_ruff_policy_authority(tmp_path))


def test_doctor_accepts_symlinked_canonical_ruff_config(tmp_path: Path) -> None:
    generated = tmp_path / "generated" / "ruff.strict.toml"
    generated.parent.mkdir()
    generated.write_text('[lint]\nselect = ["ALL"]\n', encoding="utf-8")
    (tmp_path / ".ruff-strict.toml").symlink_to(generated)
    (tmp_path / "pyproject.toml").write_text(
        '[tool.ruff]\nextend = ".ruff-strict.toml"\n',
        encoding="utf-8",
    )

    assert not list(check_ruff_policy_authority(tmp_path))


def test_doctor_rejects_a_cyclic_ruff_chain(tmp_path: Path) -> None:
    first = tmp_path / "ruff.toml"
    second = tmp_path / "nested" / "ruff.toml"
    second.parent.mkdir()
    first.write_text('extend = "nested/ruff.toml"\n', encoding="utf-8")
    second.write_text('extend = "../ruff.toml"\n', encoding="utf-8")

    findings = list(check_ruff_policy_authority(tmp_path))

    assert len(findings) == 2
    assert all(finding.id == "doctor.ruff.authority" for finding in findings)


def test_doctor_accepts_one_standalone_ruff_config(tmp_path: Path) -> None:
    (tmp_path / "ruff.toml").write_text('[lint]\nselect = ["ALL"]\n', encoding="utf-8")

    assert not list(check_ruff_policy_authority(tmp_path))


def test_doctor_honors_gitignore_when_scanning_rule_references(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _ = subprocess.run(("git", "init", "-q", str(tmp_path)), check=True, env={})
    (tmp_path / ".gitignore").write_text("generated/\n", encoding="utf-8")
    generated = tmp_path / "generated"
    generated.mkdir()
    (generated / "fixture.py").write_text("# sarj-noqa: SARJ061\n", encoding="utf-8")
    monkeypatch.setenv("GIT_DIR", "/wrong/repository/.git")
    monkeypatch.setenv("GIT_PREFIX", "nested/")
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "core.bare")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "true")

    findings = doctor.diagnose(tmp_path)

    assert not [finding for finding in findings if finding.id == "doctor.rule.retired"]


def test_doctor_rejects_consumer_config_that_reenables_conflicting_docstring_rules(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[tool.ruff]\nextend = ".ruff-strict.toml"\n\n[tool.ruff.lint]\nselect = ["ALL"]\nignore = ["D417"]\n',
        encoding="utf-8",
    )

    findings = list(check_ruff_policy_authority(tmp_path))

    assert {finding.where for finding in findings} == {
        "pyproject.toml: [tool.ruff.lint].ignore",
        "pyproject.toml: [tool.ruff.lint].select",
    }
    assert all(finding.level is Level.DRIFT for finding in findings)
    assert all("canonical config remains authoritative" in finding.detail for finding in findings)


def test_doctor_honors_explicit_fixture_exclusions(tmp_path: Path) -> None:
    retired = tmp_path / "tests" / "fixtures" / "retired.ts"
    retired.parent.mkdir(parents=True)
    retired.write_text("// eslint-disable-next-line @sarj/no-implicit-attribute-access\n", encoding="utf-8")
    adopted = manifest.Manifest(
        version=manifest.adopted_version(),
        configs=(),
        python_dest=".",
        typescript_dest=".",
    )
    (tmp_path / manifest.MANIFEST_NAME).write_text(
        f'{adopted.render()}\n[doctor]\nexclude = ["tests/fixtures/**"]\n',
        encoding="utf-8",
    )

    findings = doctor.diagnose(tmp_path)

    assert not [finding for finding in findings if finding.id == "doctor.rule.retired"]


def test_doctor_honors_explicit_retired_rule_fixture_directive(tmp_path: Path) -> None:
    fixture = tmp_path / "test_rule_history.py"
    fixture.write_text(
        "# sarj-doctor-ignore-retired-rules -- intentional compatibility fixture\n# sarj-noqa: SARJ061\n",
        encoding="utf-8",
    )

    findings = doctor.diagnose(tmp_path)

    assert not [finding for finding in findings if finding.id == "doctor.rule.retired"]


def test_doctor_deduplicates_indistinguishable_pin_findings(tmp_path: Path) -> None:
    (tmp_path / "requirements.txt").write_text(
        "sarj-lint-configs==0.0.1\nsarj-lint-configs==0.0.1\n",
        encoding="utf-8",
    )

    findings = [finding for finding in doctor.diagnose(tmp_path) if finding.id == "doctor.version.pin"]

    assert len(findings) == 1


def test_doctor_ignores_malformed_unrelated_nested_package_json(tmp_path: Path) -> None:
    fixture = tmp_path / "tests" / "fixtures" / "broken" / "package.json"
    fixture.parent.mkdir(parents=True)
    fixture.write_text("{\n", encoding="utf-8")

    findings = doctor.diagnose(tmp_path)

    assert not [finding for finding in findings if finding.id == "doctor.package-json.invalid"]


def test_doctor_reports_malformed_nested_package_json_that_names_the_plugin(tmp_path: Path) -> None:
    package = tmp_path / "packages" / "broken" / "package.json"
    package.parent.mkdir(parents=True)
    package.write_text('{"devDependencies":{"@sarj/eslint-plugin":\n', encoding="utf-8")

    findings = doctor.diagnose(tmp_path)

    assert [finding for finding in findings if finding.id == "doctor.package-json.invalid"]


def test_doctor_reports_excessively_nested_package_json_without_recursing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = tmp_path / "packages" / "broken" / "package.json"
    package.parent.mkdir(parents=True)
    package.write_text('{"devDependencies":{"@sarj/eslint-plugin":"1"}}', encoding="utf-8")

    def too_deep(_text: str) -> str | None:
        raise RecursionError

    monkeypatch.setattr(doctor, "_package_json_pin_text", too_deep)

    findings = doctor.diagnose(tmp_path)

    assert [finding for finding in findings if finding.id == "doctor.package-json.invalid"]


def test_doctor_keeps_independent_findings_when_one_destination_is_invalid(tmp_path: Path) -> None:
    adopted = manifest.Manifest(
        version=manifest.adopted_version(),
        configs=("unknown-config", "ruff"),
        python_dest="..",
        typescript_dest=".",
        hook_manager="none",
    )
    (tmp_path / manifest.MANIFEST_NAME).write_text(adopted.render(), encoding="utf-8")

    findings = doctor.diagnose(tmp_path)

    assert {finding.id for finding in findings} >= {
        "doctor.config.unknown",
        "doctor.manifest.destination",
    }


def test_doctor_falls_back_to_bounded_filesystem_walk_when_git_times_out(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / "requirements.txt").write_text("sarj-lint-configs==0.0.1\n", encoding="utf-8")

    def timed_out(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        command = "git"
        raise subprocess.TimeoutExpired(command, 5)

    monkeypatch.setattr(doctor.subprocess, "run", timed_out)

    findings = doctor.diagnose(tmp_path)

    assert [finding for finding in findings if finding.id == "doctor.version.pin"]
