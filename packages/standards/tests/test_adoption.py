"""Tests for the adoption path: `init`, `doctor`, `peers`, and the manifest."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tomllib
from typing import TYPE_CHECKING

import pytest
import yaml

from sarj_standards import (
    __version__,
)
from sarj_standards._meta import (
    CONFIGS_DIR,
    ESLINT_PEERS,
    ESLINT_STRICT,
)
import sarj_standards.cli.main as cli
from sarj_standards.cli.main import main
from sarj_standards.libs.adoption import doctor, lifecycle, manifest, scaffold, service
from sarj_standards.libs.adoption import hooks as adoption_hooks


if TYPE_CHECKING:
    from collections.abc import Iterable


REPO_ROOT = Path(__file__).resolve().parents[3]


def _cli(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    environment = dict(os.environ)  # ruff: ignore[banned-api] -- make analyzer discovery match the test interpreter.
    environment["PATH"] = f"{Path(sys.executable).parent}{os.pathsep}{environment.get('PATH', '')}"
    return subprocess.run(
        [sys.executable, "-m", "sarj_standards", *args],
        capture_output=True,
        text=True,
        check=False,
        cwd=cwd,
        env=environment,
    )


def _python_repo(root: Path) -> Path:
    (root / "src").mkdir(parents=True, exist_ok=True)
    _ = (root / "pyproject.toml").write_text('[project]\nname = "app"\nversion = "0.1.0"\nrequires-python = ">=3.14"\n')
    return root


def _typescript_repo(root: Path) -> Path:
    _ = (root / "package.json").write_text('{"name": "web", "private": true}\n')
    return root


def _add_python_bundle_pins(root: Path) -> None:
    bundle = ", ".join(f'"{name}=={pin}"' for name, pin in manifest.installed_versions().items())
    with (root / "pyproject.toml").open("a", encoding="utf-8") as handle:
        _ = handle.write(f"\n[dependency-groups]\ndev = [{bundle}]\n")


def test_doctor_leaves_maintainer_repository_policy_to_maintain_check(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / ".sarj-standards.toml").write_text("[repository]\n")

    def clean(_args: object) -> int:
        return 0

    def sync_cleanly(_args: object, *, next_steps: bool) -> int:
        _ = next_steps
        return 0

    def no_custom_rules(_root: Path, *, paths: Iterable[str]) -> int:
        assert tuple(paths) == (".",)
        return 0

    def no_verification_commands(_ecosystems: scaffold.Ecosystems) -> list[lifecycle.Command]:
        return []

    def execute_cleanly(_commands: Iterable[lifecycle.Command]) -> int:
        return 0

    monkeypatch.setattr(cli, "cmd_doctor", clean)
    monkeypatch.setattr(cli, "cmd_sync", sync_cleanly)
    monkeypatch.setattr(lifecycle, "verify_custom_rules", no_custom_rules)
    monkeypatch.setattr(lifecycle, "verification_commands", no_verification_commands)
    monkeypatch.setattr(lifecycle, "execute", execute_cleanly)

    assert cli.main(["--root", str(tmp_path), "doctor"]) == 0


def test_every_eslint_import_has_a_pinned_peer() -> None:
    """The config's imports were a hidden contract; now they are a checked one."""
    imported = set(re.findall(r'^import \w+ from "([^"]+)";', ESLINT_STRICT.read_text(), re.MULTILINE))
    pinned = set(manifest.eslint_peers())
    assert imported - pinned == set(), "eslint.strict.mjs imports a package with no pin in eslint.peers.json"


@pytest.mark.parametrize("config_name", ["eslint.strict.mjs", "eslint.application.mjs"])
def test_eslint_config_degrades_cleanly_without_a_type_project(config_name: str) -> None:
    text = (CONFIGS_DIR / config_name).read_text(encoding="utf-8")

    assert "dirname(fileURLToPath(import.meta.url))" in text
    assert "export function createConfig(options = {})" in text
    assert "[CONFIG_DIRECTORY, process.cwd()].map(normalizeRoot)" in text
    assert "const detectedRoot = candidates.find(hasTypeProject)" in text
    assert "projectService: PROJECT_SERVICE" in text
    assert "tsconfigRootDir: TYPE_PROJECT_ROOT" in text
    assert "PROJECT_SERVICE !== false" in text
    assert "UNTYPED_RULE_OVERRIDES" in text
    assert '"**/eslint.strict.mjs"' in text
    assert '"**/eslint.config.mjs"' in text


def test_peer_pins_are_exact_versions() -> None:
    """A range would reintroduce the failure the file exists to fix.

    The set is only installable because it is exact plus an `overrides` entry:
    the config's unicorn floor pulls `eslint >= 10.4` while the newest published
    `eslint-plugin-react` peers `eslint <= ^9.7`, so resolving anything here to
    "latest" produces a tree npm refuses outright.
    """
    peers = manifest.eslint_peers()
    assert len(peers) >= 9, "every package eslint.strict.mjs imports must be pinned"
    for name, pin in peers.items():
        assert re.fullmatch(r"\d+\.\d+\.\d+", pin), f"{name} must be pinned exactly, got {pin}"


def test_peers_manifest_carries_the_overrides_that_make_it_installable() -> None:
    overrides = manifest.eslint_overrides()
    assert "eslint-plugin-react" in overrides
    assert overrides["eslint-plugin-react"] == {"eslint": "$eslint"}


def test_peers_command_prints_one_install_command() -> None:
    proc = _cli("show", "peers")
    assert proc.returncode == 0
    assert "npm install --ignore-scripts --no-audit --no-fund" in proc.stdout
    for name in manifest.eslint_peers():
        assert name in proc.stdout


def test_eslint_plugin_pin_matches_the_published_package() -> None:
    """The README advertised a floor the config had already outgrown."""
    source = REPO_ROOT / "packages" / "typescript" / "package.json"
    if not source.is_file():
        pytest.skip("running against an installed wheel, outside the source tree")
    parsed: object = json.loads(source.read_text(encoding="utf-8"))  # pyright: ignore[reportAny] — untyped stdlib boundary
    package_json = manifest.as_table(parsed)
    assert manifest.eslint_peers()["@sarj/eslint-plugin"] == package_json["version"]


def test_this_repos_own_overrides_are_the_ones_consumers_get() -> None:
    """The private workaround that made the repo's green CI a lie."""
    source = REPO_ROOT / "packages" / "typescript" / "package.json"
    if not source.is_file():
        pytest.skip("running against an installed wheel, outside the source tree")
    parsed: object = json.loads(source.read_text(encoding="utf-8"))  # pyright: ignore[reportAny] — untyped stdlib boundary
    own = manifest.table_field(manifest.as_table(parsed), "overrides")
    shipped = manifest.eslint_overrides()
    assert shipped, "eslint.peers.json must declare the overrides to compare against"
    assert {name: own.get(name) for name in shipped} == shipped


def test_manifest_round_trips(tmp_path: Path) -> None:
    written = manifest.Manifest(
        version="1.2.3",
        configs=("ruff", "pyright"),
        python_dest=".",
        typescript_dest="web",
        ci_bootstrap=("yarn generate",),
    )
    _ = (tmp_path / manifest.MANIFEST_NAME).write_text(written.render())
    assert manifest.load(tmp_path) == written


@pytest.mark.parametrize("declared", ["not a version", "1.2.3 nope", "v"])
def test_manifest_rejects_non_pep440_versions(tmp_path: Path, declared: str) -> None:
    _ = (tmp_path / manifest.MANIFEST_NAME).write_text(f'schema = 3\nbundle = "{declared}"\n')

    with pytest.raises(ValueError, match="valid PEP 440 version"):
        _ = manifest.load(tmp_path)


def test_manifest_defaults_to_standard_profile(tmp_path: Path) -> None:
    _ = (tmp_path / manifest.MANIFEST_NAME).write_text('schema = 3\nbundle = "1.2.3"\n')
    adopted = manifest.load(tmp_path)
    assert adopted is not None
    assert adopted.profile == "standard"
    assert adopted.verify_paths == (".",)


def test_manifest_loads_contained_custom_verification_paths(tmp_path: Path) -> None:
    _ = (tmp_path / manifest.MANIFEST_NAME).write_text(
        'schema = 3\nbundle = "1.2.3"\n[verify]\npaths = ["src", "README.md"]\n'
    )

    adopted = manifest.load(tmp_path)

    assert adopted is not None
    assert adopted.verify_paths == ("src", "README.md")


@pytest.mark.parametrize("command", [" yarn generate", "yarn generate ", "yarn generate\nnext"])
def test_manifest_rejects_unsafe_ci_bootstrap_shape(tmp_path: Path, command: str) -> None:
    rendered = json.dumps(command)
    _ = (tmp_path / manifest.MANIFEST_NAME).write_text(
        f'schema = 3\nbundle = "1.2.3"\n[ci]\nbootstrap = [{rendered}]\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="trimmed single-line"):
        _ = manifest.load(tmp_path)


def test_manifest_rejects_custom_verification_path_escape(tmp_path: Path) -> None:
    _ = (tmp_path / manifest.MANIFEST_NAME).write_text(
        'schema = 3\nbundle = "1.2.3"\n[verify]\npaths = ["../outside"]\n'
    )

    with pytest.raises(ValueError, match="escapes repository root"):
        _ = manifest.load(tmp_path)


def test_manifest_rejects_unknown_profile(tmp_path: Path) -> None:
    _ = (tmp_path / manifest.MANIFEST_NAME).write_text('schema = 3\nbundle = "1.2.3"\nprofile = "library"\n')
    with pytest.raises(ValueError, match=r"profile.*standard, application"):
        _ = manifest.load(tmp_path)


def test_manifest_renders_as_valid_toml() -> None:
    rendered = manifest.Manifest(version="1.2.3", configs=("ruff",), python_dest=".", typescript_dest=".").render()
    parsed = tomllib.loads(rendered)
    assert parsed["schema"] == 3
    assert parsed["bundle"] == "1.2.3"
    assert parsed["capabilities"]["disable"] == ["pyright", "eslint", "markdownlint", "taplo", "yamllint"]


def test_missing_manifest_is_not_an_error(tmp_path: Path) -> None:
    assert manifest.load(tmp_path) is None


def test_malformed_manifest_is_reported_not_ignored(tmp_path: Path) -> None:
    _ = (tmp_path / manifest.MANIFEST_NAME).write_text("configs = 3\n")
    with pytest.raises(ValueError, match=r"schema.*equal 3"):
        _ = manifest.load(tmp_path)


@pytest.mark.parametrize(
    "text",
    [
        'version = "1.2.3"\nconfigs = ["ruff"]\n',
        'schema = 1\nversion = "1.2.3"\nconfigs = ["ruff"]\n',
        'schema = 2\nbundle = "1.2.3"\n[capabilities]\ndisable = []\n',
    ],
)
def test_manifest_rejects_every_obsolete_schema(tmp_path: Path, text: str) -> None:
    _ = (tmp_path / manifest.MANIFEST_NAME).write_text(text)

    with pytest.raises(ValueError, match=r"schema.*equal 3"):
        _ = manifest.load(tmp_path)


def test_setup_one_way_migrates_the_final_schema_less_manifest(tmp_path: Path) -> None:
    _ = _python_repo(tmp_path)
    _ = (tmp_path / manifest.MANIFEST_NAME).write_text(
        'version = "0.42.0"\nconfigs = ["ruff"]\n\n[dest]\npython = "."\ntypescript = "."\n',
        encoding="utf-8",
    )

    proc = _cli("--root", str(tmp_path), "setup", "--no-install")

    assert proc.returncode == 0, proc.stderr
    adopted = manifest.load(tmp_path)
    assert adopted is not None
    assert adopted.version == manifest.adopted_version()
    assert adopted.configs == ("ruff",)
    assert "schema = 3" in (tmp_path / manifest.MANIFEST_NAME).read_text(encoding="utf-8")


def test_setup_preserves_compatible_policy_from_the_schema_less_manifest(tmp_path: Path) -> None:
    _ = _python_repo(tmp_path)
    manifest_path = tmp_path / manifest.MANIFEST_NAME
    manifest_path.write_text(
        'version = "0.42.0"\nconfigs = [\n  "ruff",\n]\nprofile = "application"\n\n'
        '[dest]\npython = "."\ntypescript = "."\n\n'
        '[verify]\npaths = ["src"]\n\n'
        '[hooks]\nmanager = "none"\n\n'
        '[exclude]\npaths = ["generated/**"]\nrules = ["python:SARJ052"]\n\n'
        '[[exclude.overrides]]\npaths = ["tests/**"]\nrules = ["python:SARJ052"]\nreason = "legacy fixtures"\n\n'
        "[consumer]\nkeep = true\n",
        encoding="utf-8",
    )

    proc = _cli("--root", str(tmp_path), "setup", "--no-install")

    assert proc.returncode == 0, proc.stderr
    adopted = manifest.load(tmp_path)
    assert adopted is not None
    assert adopted.profile == "application"
    assert adopted.verify_paths == ("src",)
    assert adopted.hook_manager == "none"
    assert adopted.excluded_paths == ("generated/**",)
    assert adopted.excluded_rules == ("python:SARJ052",)
    assert adopted.exclusion_overrides == (
        manifest.ExclusionOverride(("tests/**",), ("python:SARJ052",), "legacy fixtures"),
    )
    assert "[consumer]\nkeep = true" in manifest_path.read_text(encoding="utf-8")
    assert not (tmp_path / ".pre-commit-config.yaml").exists()


def test_setup_refuses_to_discard_a_schema_less_python_baseline(tmp_path: Path) -> None:
    _ = _python_repo(tmp_path)
    baseline = tmp_path / "python-baseline.json"
    baseline.write_text('{"src/app.py":{"SARJ052":1}}\n', encoding="utf-8")
    manifest_path = tmp_path / manifest.MANIFEST_NAME
    manifest_path.write_text(
        'version = "0.42.0"\nconfigs = ["ruff"]\n\n'
        '[dest]\npython = "."\ntypescript = "."\n\n'
        '[gradual]\npython_baseline = "python-baseline.json"\n',
        encoding="utf-8",
    )
    before = manifest_path.read_bytes()

    proc = _cli("--root", str(tmp_path), "setup", "--no-install")

    assert proc.returncode == 2
    assert "cannot losslessly migrate legacy [gradual].python_baseline" in proc.stderr
    assert manifest_path.read_bytes() == before
    assert baseline.read_text(encoding="utf-8") == '{"src/app.py":{"SARJ052":1}}\n'


def test_doctor_repair_uses_the_same_one_way_manifest_migration(tmp_path: Path) -> None:
    _ = _typescript_repo(tmp_path)
    _ = (tmp_path / manifest.MANIFEST_NAME).write_text(
        'version = "0.42.0"\nconfigs = ["eslint"]\n\n[dest]\npython = "."\ntypescript = "."\n',
        encoding="utf-8",
    )

    proc = _cli("doctor", "--root", str(tmp_path), "--repair", "--no-install")

    assert proc.returncode == 0, proc.stderr
    adopted = manifest.load(tmp_path)
    assert adopted is not None
    assert adopted.version == manifest.adopted_version()


def test_fix_rejects_an_unadopted_repository_with_setup_guidance(tmp_path: Path) -> None:
    _ = _python_repo(tmp_path)

    proc = _cli("--root", str(tmp_path), "fix")

    assert proc.returncode == 2
    assert not proc.stdout
    assert "sarj-standards setup" in proc.stderr


def test_check_preserves_invalid_configuration_exit_status(tmp_path: Path) -> None:
    _ = (tmp_path / manifest.MANIFEST_NAME).write_text("schema = [", encoding="utf-8")

    proc = _cli("--root", str(tmp_path), "check")

    assert proc.returncode == 2
    assert "doctor.manifest.invalid" in proc.stdout


def test_doctor_repair_does_not_repeat_the_same_manifest_parse_error(tmp_path: Path) -> None:
    _ = (tmp_path / manifest.MANIFEST_NAME).write_text("schema = [", encoding="utf-8")

    proc = _cli("--root", str(tmp_path), "doctor", "--repair", "--no-install")

    assert proc.returncode == 2
    assert proc.stderr.count("Invalid value") == 1


def test_setup_does_not_reinterpret_a_versioned_obsolete_schema(tmp_path: Path) -> None:
    _ = _python_repo(tmp_path)
    original = 'schema = 1\nversion = "0.42.0"\nconfigs = ["ruff"]\n'
    _ = (tmp_path / manifest.MANIFEST_NAME).write_text(original, encoding="utf-8")

    proc = _cli("--root", str(tmp_path), "setup", "--no-install")

    assert proc.returncode == 2
    assert (tmp_path / manifest.MANIFEST_NAME).read_text(encoding="utf-8") == original


@pytest.mark.parametrize("field", ["version", "configs", "gradual"])
def test_schema_three_rejects_removed_fields(tmp_path: Path, field: str) -> None:
    suffix = '[gradual]\npython_baseline = "baseline.json"\n' if field == "gradual" else f'{field} = "removed"\n'
    _ = (tmp_path / manifest.MANIFEST_NAME).write_text(f'schema = 3\nbundle = "1.2.3"\n{suffix}')

    with pytest.raises(ValueError, match=f"removed manifest fields: {field}"):
        _ = manifest.load(tmp_path)


@pytest.mark.parametrize(
    ("python", "typescript", "expected"),
    [
        (True, False, ("ruff", "pyright", "markdownlint", "taplo", "yamllint")),
        (False, True, ("eslint", "markdownlint", "taplo", "yamllint")),
        (True, True, ("ruff", "pyright", "eslint", "markdownlint", "taplo", "yamllint")),
    ],
)
def test_config_set_follows_the_detected_ecosystems(
    *, python: bool, typescript: bool, expected: tuple[str, ...]
) -> None:
    assert manifest.default_configs(has_python=python, has_typescript=typescript) == expected


def test_doctor_respects_the_manifests_config_set(tmp_path: Path) -> None:
    _ = _python_repo(tmp_path)
    assert _cli("--root", str(tmp_path), "setup", "--no-install").returncode == 0
    assert not (tmp_path / "eslint.strict.mjs").exists()

    proc = _cli("--root", str(tmp_path), "doctor")
    assert proc.returncode == 0, proc.stdout
    assert "0 drifted" in proc.stdout


def test_doctor_fails_when_a_synced_config_is_edited(tmp_path: Path) -> None:
    """The vendoring failure, caught at the earliest possible moment."""
    _ = _python_repo(tmp_path)
    assert _cli("--root", str(tmp_path), "setup", "--no-install").returncode == 0
    with (tmp_path / ".ruff-strict.toml").open("a") as handle:
        _ = handle.write("\n# local edit\n")

    proc = _cli("--root", str(tmp_path), "doctor")
    assert proc.returncode == 1
    assert "drifted" in proc.stdout


def test_setup_accepts_several_configs(tmp_path: Path) -> None:
    _ = _python_repo(tmp_path)
    assert (
        _cli("--root", str(tmp_path), "setup", "--config", "ruff", "--config", "pyright", "--no-install").returncode
        == 0
    )
    assert (tmp_path / ".ruff-strict.toml").is_file()
    assert (tmp_path / ".pyright-strict.json").is_file()
    assert not (tmp_path / "eslint.strict.mjs").exists()


def test_init_writes_the_whole_python_wiring(tmp_path: Path) -> None:
    """One command replaces the README's read-then-hand-edit sequence."""
    _ = _python_repo(tmp_path)
    proc = _cli("--root", str(tmp_path), "setup", "--no-install")
    assert proc.returncode == 0, proc.stderr

    assert (tmp_path / ".ruff-strict.toml").is_file()
    assert (tmp_path / ".pyright-strict.json").is_file()
    assert (tmp_path / manifest.MANIFEST_NAME).is_file()
    assert (tmp_path / ".pre-commit-config.yaml").is_file()
    assert '"extends": ".pyright-strict.json"' in (tmp_path / "pyrightconfig.json").read_text()

    pyproject = tomllib.loads((tmp_path / "pyproject.toml").read_text())
    assert pyproject["tool"]["ruff"]["extend"] == ".ruff-strict.toml"


def test_init_wires_an_empty_pyright_config(tmp_path: Path) -> None:
    """An empty JSON object is a valid Pyright config, not an adoption error."""
    _ = _python_repo(tmp_path)
    _ = (tmp_path / "pyrightconfig.json").write_text("{}\n", encoding="utf-8")

    proc = _cli("--root", str(tmp_path), "setup", "--no-install")

    assert proc.returncode == 0, proc.stderr
    assert json.loads((tmp_path / "pyrightconfig.json").read_text()) == {
        "extends": ".pyright-strict.json",
        "pythonVersion": "3.14",
    }


@pytest.mark.parametrize("table", ["pyright", "basedpyright"])
def test_init_refuses_a_pyproject_pyright_authority_that_cannot_extend_json(tmp_path: Path, table: str) -> None:
    _ = _python_repo(tmp_path)
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        f'{pyproject.read_text(encoding="utf-8")}\n[tool.{table}]\nextends = ".pyright-strict.json"\n',
        encoding="utf-8",
    )

    proc = _cli("--root", str(tmp_path), "setup", "--no-install")

    assert proc.returncode == 2
    assert "cannot inherit the canonical JSON configuration" in proc.stderr
    assert not (tmp_path / "pyrightconfig.json").exists()


def test_init_refuses_to_replace_an_existing_pyright_parent(tmp_path: Path) -> None:
    _ = _python_repo(tmp_path)
    config = tmp_path / "pyrightconfig.json"
    original = '{"extends": "./company-pyright.json"}\n'
    config.write_text(original, encoding="utf-8")

    proc = _cli("--root", str(tmp_path), "setup", "--no-install")

    assert proc.returncode == 2
    assert "already extends" in proc.stderr
    assert config.read_text(encoding="utf-8") == original
    assert not (tmp_path / manifest.MANIFEST_NAME).exists()


def test_init_refuses_to_create_a_competing_config_beside_pyright_jsonc(tmp_path: Path) -> None:
    _ = _python_repo(tmp_path)
    config = tmp_path / "pyrightconfig.jsonc"
    original = '{ /* keep this comment */ "typeCheckingMode": "strict" }\n'
    config.write_text(original, encoding="utf-8")

    proc = _cli("--root", str(tmp_path), "setup", "--no-install")

    assert proc.returncode == 2
    assert "pyrightconfig.jsonc" in proc.stderr
    assert config.read_text(encoding="utf-8") == original
    assert not (tmp_path / "pyrightconfig.json").exists()


def test_init_separates_the_tool_runtime_from_an_older_consumer_target(tmp_path: Path) -> None:
    _python_repo(tmp_path)
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        pyproject.read_text(encoding="utf-8").replace('requires-python = ">=3.14"', 'requires-python = ">=3.10"'),
        encoding="utf-8",
    )

    proc = _cli("--root", str(tmp_path), "setup", "--no-install")

    assert proc.returncode == 0, proc.stderr
    parsed: object = json.loads(  # pyright: ignore[reportAny] -- JSON is narrowed at the boundary below.
        (tmp_path / "pyrightconfig.json").read_text(encoding="utf-8")
    )
    pyright = manifest.as_table(parsed)
    assert pyright["pythonVersion"] == "3.10"
    assert "target-version" not in (tmp_path / ".ruff-strict.toml").read_text(encoding="utf-8")
    hook = (tmp_path / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    assert "uvx --isolated --python 3.14" in hook


def test_init_application_profile_selects_application_artifacts(tmp_path: Path) -> None:
    _ = _python_repo(tmp_path)
    proc = _cli("--root", str(tmp_path), "setup", "--profile", "application", "--no-install")
    assert proc.returncode == 0, proc.stderr

    adopted = manifest.load(tmp_path)
    assert adopted is not None
    assert adopted.profile == "application"
    expected = CONFIGS_DIR / "ruff.application.toml"
    assert (tmp_path / ".ruff-strict.toml").read_bytes() == expected.read_bytes()


def test_setup_explicit_configs_update_manifest_without_losing_exclusions(tmp_path: Path) -> None:
    _ = _typescript_repo(tmp_path)
    first = _cli("--root", str(tmp_path), "setup", "--config", "markdownlint", "--no-install")
    assert first.returncode == 0, first.stderr
    assert _cli("--root", str(tmp_path), "exclude", "add", "path", "generated/**").returncode == 0

    second = _cli("--root", str(tmp_path), "setup", "--config", "eslint", "--no-install")

    assert second.returncode == 0, second.stderr
    adopted = manifest.load(tmp_path)
    assert adopted is not None
    assert adopted.configs == ("eslint",)
    assert adopted.excluded_paths == ("generated/**",)
    assert (tmp_path / "eslint.strict.mjs").is_file()


def test_setup_preserves_every_supported_manifest_policy_section(tmp_path: Path) -> None:
    _ = _typescript_repo(tmp_path)
    first = _cli("--root", str(tmp_path), "setup", "--config", "markdownlint", "--no-install")
    assert first.returncode == 0, first.stderr
    path = tmp_path / manifest.MANIFEST_NAME
    default_durable = ", ".join(json.dumps(value) for value in manifest.DEFAULT_DURABLE_ARTIFACTS)
    current = path.read_text(encoding="utf-8").replace(
        f"[artifacts]\ndurable = [{default_durable}]",
        '[artifacts]\ndurable = ["evidence/**"]',
    )
    path.write_text(
        f'{current}\n[text]\nexclude = ["templates/**"]\n\n[doctor]\nexclude = ["tests/fixtures/**"]\n'
        '\n[baseline]\ndiagnostics = "quality/diagnostics.json"\n'
        '\n[ci]\nbootstrap = ["yarn generate"]\n',
        encoding="utf-8",
    )

    second = _cli("--root", str(tmp_path), "setup", "--config", "eslint", "--no-install")

    assert second.returncode == 0, second.stderr
    adopted = manifest.load(tmp_path)
    assert adopted is not None
    assert adopted.durable_artifacts == ("evidence/**",)
    assert adopted.text_excluded_paths == ("templates/**",)
    assert adopted.doctor_excluded_paths == ("tests/fixtures/**",)
    assert adopted.diagnostic_baseline == "quality/diagnostics.json"
    assert adopted.ci_bootstrap == ("yarn generate",)


def test_sync_uses_profile_recorded_in_manifest(tmp_path: Path) -> None:
    _ = _typescript_repo(tmp_path)
    assert _cli("--root", str(tmp_path), "setup", "--profile", "application", "--no-install").returncode == 0
    expected = CONFIGS_DIR / "eslint.application.mjs"
    assert (tmp_path / "eslint.strict.mjs").read_bytes() == expected.read_bytes()
    assert _cli("--root", str(tmp_path), "doctor").returncode == 0


def test_application_ruff_config_rejects_preferred_stack_import(tmp_path: Path) -> None:
    pytest.importorskip("ruff", reason="ruff not installed in this env")
    _ = _python_repo(tmp_path)
    assert _cli("--root", str(tmp_path), "setup", "--profile", "application", "--no-install").returncode == 0
    probe = tmp_path / "probe.py"
    _ = probe.write_text("import argparse\n")

    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--no-cache", str(probe)],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        check=False,
    )

    assert proc.returncode == 1
    assert "banned-api: `argparse` is banned" in proc.stdout
    assert "LIB001" in proc.stdout


@pytest.mark.parametrize("profile", ["standard", "application"])
@pytest.mark.parametrize(("python_floor", "expected_count"), [("3.10", 0), ("3.11", 1)])
def test_adopted_ruff_uses_the_consumer_target_for_str_enum_modernization(
    tmp_path: Path,
    profile: str,
    python_floor: str,
    expected_count: int,
) -> None:
    """UP042 belongs to Ruff and must follow the consumer target, not the tool runtime."""
    pytest.importorskip("ruff", reason="ruff not installed in this env")
    _ = _python_repo(tmp_path)
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        pyproject.read_text(encoding="utf-8").replace(">=3.14", f">={python_floor}"),
        encoding="utf-8",
    )
    assert _cli("--root", str(tmp_path), "setup", "--profile", profile, "--no-install").returncode == 0
    package = tmp_path / "src" / "app"
    package.mkdir()
    (package / "__init__.py").touch()
    (package / "status.py").write_text(
        'from enum import Enum\n\n\nclass Status(str, Enum):\n    ACTIVE = "active"\n    INACTIVE = "inactive"\n',
        encoding="utf-8",
    )

    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--no-cache", "--output-format", "json", "."],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        check=False,
    )
    assert proc.stdout.count('"code": "UP042"') == expected_count
    assert proc.returncode == (1 if expected_count else 0)


def test_init_keeps_standards_out_of_the_consumer_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _ = _python_repo(tmp_path)
    commands: list[lifecycle.Command] = []

    def execute(planned: Iterable[lifecycle.Command]) -> int:
        commands.extend(planned)
        return 0

    monkeypatch.setattr(lifecycle, "execute", execute)

    assert main(["--root", str(tmp_path), "setup", "--no-install"]) == 0
    assert commands == []
    assert "sarj-standards" not in (tmp_path / "pyproject.toml").read_text(encoding="utf-8")


def test_init_no_install_prints_every_skipped_setup_command(tmp_path: Path) -> None:
    _ = _python_repo(tmp_path)
    (tmp_path / ".git").mkdir()

    proc = _cli("--root", str(tmp_path), "setup", "--no-install")

    assert proc.returncode == 0, proc.stderr
    assert "dependency and hook installation was skipped" in proc.stdout
    assert "uv add --dev" not in proc.stdout
    assert "pre-commit install" in proc.stdout
    hook = (tmp_path / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    assert f"--isolated --python 3.14 --from sarj-standards=={__version__}" in hook


def test_inspect_reports_detected_adoption(tmp_path: Path) -> None:
    _ = _python_repo(tmp_path)
    assert _cli("--root", str(tmp_path), "setup", "--no-install").returncode == 0

    parsed: object = json.loads(lifecycle.inspection_json(tmp_path))  # pyright: ignore[reportAny] -- untyped stdlib boundary
    inspected = manifest.as_table(parsed)

    assert inspected["adopted_version"] == __version__
    assert inspected["profile"] == "standard"
    assert inspected["python_root"] == "."


def test_init_writes_a_typescript_entrypoint_with_an_override_seam(tmp_path: Path) -> None:
    """The generated entrypoint has to teach "extend, do not fork"."""
    _ = _typescript_repo(tmp_path)
    proc = _cli("--root", str(tmp_path), "setup", "--no-install")
    assert proc.returncode == 0, proc.stderr

    entrypoint = (tmp_path / "eslint.config.mjs").read_text()
    assert 'import strict from "./eslint.strict.mjs"' in entrypoint
    assert "repo-specific overrides" in entrypoint
    assert "unicorn/filename-case" in entrypoint
    assert (tmp_path / "eslint.strict.mjs").is_file()
    assert not (tmp_path / ".ruff-strict.toml").exists()


@pytest.mark.parametrize(
    "expected",
    [
        pytest.param("npm install --ignore-scripts", id="install-command"),
        pytest.param("overrides", id="npm-overrides-block"),
        pytest.param("eslint-plugin-react", id="the-package-the-overrides-unblock"),
    ],
)
def test_init_gives_a_typescript_repo_everything_npm_needs(tmp_path: Path, expected: str) -> None:
    """Anything missing here sends the reader back to trial-and-error installs."""
    _ = _typescript_repo(tmp_path)
    proc = _cli("--root", str(tmp_path), "setup", "--no-install")
    assert expected in proc.stdout
    parsed: object = json.loads(  # pyright: ignore[reportAny] -- untyped stdlib boundary
        (tmp_path / "package.json").read_text(encoding="utf-8")
    )
    package = manifest.as_table(parsed)
    assert manifest.table_field(package, "devDependencies") == manifest.eslint_peers()


def test_setup_converges_peers_duplicated_across_dependency_sections(tmp_path: Path) -> None:
    _ = _typescript_repo(tmp_path)
    peers = manifest.eslint_peers()
    package_path = tmp_path / "package.json"
    package_path.write_text(
        json.dumps(
            {
                "name": "web",
                "dependencies": {
                    "@sarj/eslint-plugin": peers["@sarj/eslint-plugin"],
                    "eslint": peers["eslint"],
                    "runtime": "1.0.0",
                },
                "devDependencies": {"@sarj/eslint-plugin": "8.0.0", "eslint": "8.0.0", "test-only": "1.0.0"},
            }
        ),
        encoding="utf-8",
    )

    proc = _cli("--root", str(tmp_path), "setup", "--no-install")

    assert proc.returncode == 0, proc.stderr
    parsed: object = json.loads(package_path.read_text(encoding="utf-8"))  # pyright: ignore[reportAny]
    package = manifest.as_table(parsed)
    runtime = manifest.table_field(package, "dependencies")
    development = manifest.table_field(package, "devDependencies")
    assert runtime["@sarj/eslint-plugin"] == peers["@sarj/eslint-plugin"]
    assert runtime["eslint"] == peers["eslint"]
    assert runtime["runtime"] == "1.0.0"
    assert "@sarj/eslint-plugin" not in development
    assert "eslint" not in development
    assert development["test-only"] == "1.0.0"
    assert _cli("--root", str(tmp_path), "setup", "--no-install").returncode == 0


def test_setup_refuses_to_major_bump_lint_tooling_in_runtime_dependencies(tmp_path: Path) -> None:
    _ = _typescript_repo(tmp_path)
    package_path = tmp_path / "package.json"
    original = json.dumps(
        {
            "name": "web",
            "dependencies": {"eslint": "^9.0.0", "runtime": "1.0.0"},
        }
    )
    package_path.write_text(original, encoding="utf-8")

    proc = _cli("--root", str(tmp_path), "setup", "--no-install")

    assert proc.returncode == 2
    assert "will not silently change its major version" in proc.stderr
    assert "Move lint tooling to devDependencies" in proc.stderr
    assert package_path.read_text(encoding="utf-8") == original


def test_setup_conservatively_excludes_detected_generated_python_clients(tmp_path: Path) -> None:
    python = tmp_path / "python"
    python.mkdir()
    _ = _python_repo(python)

    platform = python / "platform_client"
    package = platform / "platform_client"
    package.mkdir(parents=True)
    (package / "client.py").write_text("CLIENT = object()\n", encoding="utf-8")
    (platform / "codegen.config.yml").write_text("package_name_override: platform_client\n", encoding="utf-8")
    (platform / "generate.py").write_text("# invokes openapi-python-client\n", encoding="utf-8")
    (platform / "pyproject.toml").write_text(
        '[project]\nname = "platform-client"\ndescription = "Generated API client"\n'
        '[tool.hatch.build.targets.wheel]\npackages = ["platform_client"]\n',
        encoding="utf-8",
    )

    sdk = python / "sdk"
    generated_source = sdk / "src" / "sdk" / "client.py"
    generated_source.parent.mkdir(parents=True)
    generated_source.write_text(
        '"""Code generated by Speakeasy (https://speakeasy.com). DO NOT EDIT."""\n', encoding="utf-8"
    )
    (sdk / ".speakeasy").mkdir()
    (sdk / ".speakeasy" / "gen.yaml").write_text("configVersion: 2.0.0\n", encoding="utf-8")
    (sdk / "pyproject.toml").write_text('[project]\nname = "sdk"\n', encoding="utf-8")

    manual = python / "manual_sdk"
    (manual / "src" / "manual_sdk").mkdir(parents=True)
    (manual / ".speakeasy").mkdir()
    (manual / ".speakeasy" / "gen.yaml").write_text("configVersion: 2.0.0\n", encoding="utf-8")
    (manual / "src" / "manual_sdk" / "client.py").write_text("# maintained by hand\n", encoding="utf-8")
    (manual / "pyproject.toml").write_text('[project]\nname = "manual-sdk"\n', encoding="utf-8")

    proc = _cli("--root", str(tmp_path), "setup", "--no-install")

    assert proc.returncode == 0, proc.stderr
    adopted = manifest.load(tmp_path)
    assert adopted is not None
    assert adopted.excluded_paths == (
        "python/platform_client/platform_client/**",
        "python/sdk/**",
    )


def test_init_prints_a_ci_snippet_with_the_unified_gate(tmp_path: Path) -> None:
    _ = _python_repo(tmp_path)
    proc = _cli("--root", str(tmp_path), "setup", "--no-install")
    assert ".github/workflows/standards.yml" in proc.stdout
    assert "add this CI step" not in proc.stdout


def test_ci_snippet_for_a_typescript_repo_does_not_require_a_python_project(
    tmp_path: Path,
) -> None:
    _ = _typescript_repo(tmp_path)
    proc = _cli("--root", str(tmp_path), "setup", "--no-install")
    assert "uv run --frozen" not in proc.stdout
    assert ".github/workflows/standards.yml" in proc.stdout


def test_setup_repairs_an_outdated_managed_yarn_workflow(tmp_path: Path) -> None:
    package = _typescript_repo(tmp_path) / "package.json"
    package.write_text('{"name":"web","private":true,"packageManager":"yarn@4.15.0"}\n', encoding="utf-8")
    (tmp_path / "yarn.lock").write_text("__metadata:\n  version: 8\n", encoding="utf-8")
    first = _cli("--root", str(tmp_path), "setup", "--no-install")
    workflow = tmp_path / ".github" / "workflows" / "standards.yml"
    workflow.write_text(
        workflow.read_text(encoding="utf-8").replace("--mode=skip-build", "--mode=skip-builds"),
        encoding="utf-8",
    )

    second = _cli("--root", str(tmp_path), "setup", "--no-install")

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    assert "--mode=skip-builds" not in workflow.read_text(encoding="utf-8")
    assert "--mode=skip-build" in workflow.read_text(encoding="utf-8")


def test_nested_python_project_uses_the_same_isolated_launcher(tmp_path: Path) -> None:
    python = tmp_path / "python"
    python.mkdir()
    _python_repo(python)

    plan = scaffold.build_plan(tmp_path, force=False)
    hook = next(contents for path, contents in plan.writes if path.name == ".pre-commit-config.yaml")
    snippet = scaffold.ci_snippet(plan, version=manifest.adopted_version())

    expected = f"uvx --isolated --python 3.14 --from sarj-standards=={manifest.adopted_version()}"
    assert expected in hook
    assert expected in snippet
    assert "--project python" not in hook


def test_init_is_idempotent(tmp_path: Path) -> None:
    _ = _python_repo(tmp_path)
    assert _cli("--root", str(tmp_path), "setup", "--no-install").returncode == 0
    before = (tmp_path / "pyproject.toml").read_text()

    second = _cli("--root", str(tmp_path), "setup", "--no-install")
    assert second.returncode == 0
    assert (tmp_path / "pyproject.toml").read_text() == before
    assert "already extends" in second.stdout


def test_init_dry_run_writes_nothing(tmp_path: Path) -> None:
    _ = _python_repo(tmp_path)
    proc = _cli("--root", str(tmp_path), "setup", "--dry-run", "--no-install")
    assert proc.returncode == 0
    assert "would write" in proc.stdout
    assert not (tmp_path / ".ruff-strict.toml").exists()
    assert not (tmp_path / manifest.MANIFEST_NAME).exists()


def test_init_on_an_empty_directory_says_so(tmp_path: Path) -> None:
    proc = _cli("--root", str(tmp_path), "setup", "--no-install")
    assert proc.returncode == 1
    assert "no pyproject.toml and no package.json" in proc.stdout


def test_init_adopts_shared_configs_without_an_ecosystem(tmp_path: Path) -> None:
    proc = _cli(
        "--root",
        str(tmp_path),
        "setup",
        "--config",
        "markdownlint",
        "--config",
        "taplo",
        "--config",
        "yamllint",
        "--no-install",
    )

    assert proc.returncode == 0, proc.stderr
    adopted = manifest.load(tmp_path)
    assert adopted is not None
    assert adopted.configs == ("markdownlint", "taplo", "yamllint")
    assert (tmp_path / ".markdownlint.yaml").is_file()
    assert (tmp_path / ".taplo.toml").is_file()
    assert (tmp_path / ".yamllint.yaml").is_file()
    assert (tmp_path / ".pre-commit-config.yaml").is_file()


@pytest.mark.parametrize("config", ["ruff", "pyright", "eslint"])
def test_init_rejects_ecosystem_config_without_its_project(tmp_path: Path, config: str) -> None:
    proc = _cli("--root", str(tmp_path), "setup", "--config", config, "--no-install")

    assert proc.returncode == 2
    assert "ecosystem-specific" in proc.stderr
    assert not (tmp_path / manifest.MANIFEST_NAME).exists()


def test_generated_precommit_block_carries_no_rev(tmp_path: Path) -> None:
    _ = _python_repo(tmp_path)
    assert _cli("--root", str(tmp_path), "setup", "--no-install").returncode == 0
    generated = (tmp_path / ".pre-commit-config.yaml").read_text()
    assert "rev:" not in generated
    assert "repo: local" in generated
    assert "sarj-standards check --staged --" in generated
    assert "always_run: true" in generated
    assert "package\\.json|pyrightconfig\\.json" in generated
    assert generated.count("id: sarj-standards-check") == 1


@pytest.mark.parametrize("heading", ["repos: []\n", "repos: [] # keep this comment\n"])
def test_init_opens_an_inline_empty_precommit_repo_list(tmp_path: Path, heading: str) -> None:
    _ = _python_repo(tmp_path)
    config = tmp_path / ".pre-commit-config.yaml"
    config.write_text(heading, encoding="utf-8")

    proc = _cli("--root", str(tmp_path), "setup", "--no-install")

    assert proc.returncode == 0, proc.stderr
    updated = config.read_text(encoding="utf-8")
    assert "repos: []" not in updated
    assert "id: sarj-standards-check" in updated
    if "#" in heading:
        assert "# keep this comment" in updated


def test_init_preserves_an_existing_lefthook_manager(tmp_path: Path) -> None:
    _ = _python_repo(tmp_path)
    (tmp_path / "lefthook.yml").write_text(
        "pre-commit:\n  commands:\n    standards:\n      run: sarj-standards check --staged\n", encoding="utf-8"
    )

    proc = _cli("--root", str(tmp_path), "setup", "--no-install")

    assert proc.returncode == 0, proc.stderr
    assert not (tmp_path / ".pre-commit-config.yaml").exists()
    adopted = manifest.load(tmp_path)
    assert adopted is not None
    assert adopted.hook_manager == "lefthook"


def test_switching_to_lefthook_retires_only_the_generated_precommit_hook(tmp_path: Path) -> None:
    _ = _python_repo(tmp_path)
    assert _cli("--root", str(tmp_path), "setup", "--no-install").returncode == 0
    config = tmp_path / ".pre-commit-config.yaml"
    original = config.read_text(encoding="utf-8")
    config.write_text(
        original.replace(
            "      - id: sarj-standards-check\n",
            "      - id: keep-consumer-hook\n"
            "        name: keep consumer hook\n"
            "        entry: true\n"
            "        language: system\n"
            "      - id: sarj-standards-check\n",
        ),
        encoding="utf-8",
    )
    (tmp_path / "lefthook.yml").write_text(
        "pre-commit:\n  jobs:\n    - name: consumer\n      run: true\n",
        encoding="utf-8",
    )

    proc = _cli("--root", str(tmp_path), "setup", "--hooks", "lefthook", "--no-install")

    assert proc.returncode == 0, proc.stderr
    updated = config.read_text(encoding="utf-8")
    assert "id: keep-consumer-hook" in updated
    assert "id: sarj-standards-check" not in updated
    assert "id: sarj-standards-drift" not in updated
    assert adoption_hooks.lefthook_runs_staged_check(tmp_path)
    adopted = manifest.load(tmp_path)
    assert adopted is not None
    assert adopted.hook_manager == "lefthook"
    assert not [finding for finding in doctor.diagnose(tmp_path) if finding.id == "doctor.hooks.manager-conflict"]


def test_switching_to_lefthook_refuses_a_customized_generated_precommit_hook(tmp_path: Path) -> None:
    _ = _python_repo(tmp_path)
    assert _cli("--root", str(tmp_path), "setup", "--no-install").returncode == 0
    config = tmp_path / ".pre-commit-config.yaml"
    config.write_text(
        config.read_text(encoding="utf-8").replace(
            "        stages: [pre-commit]\n",
            "        stages: [pre-commit]\n        args: [--consumer-scope]\n",
        ),
        encoding="utf-8",
    )
    (tmp_path / "lefthook.yml").write_text(
        "pre-commit:\n  jobs:\n    - name: consumer\n      run: true\n",
        encoding="utf-8",
    )

    proc = _cli("--root", str(tmp_path), "setup", "--hooks", "lefthook", "--no-install")

    assert proc.returncode == 2
    assert "consumer-owned keys: args" in proc.stderr
    assert "id: sarj-standards-check" in config.read_text(encoding="utf-8")


def test_init_accepts_a_runner_wrapped_lefthook_command(tmp_path: Path) -> None:
    _ = _python_repo(tmp_path)
    (tmp_path / "lefthook.yml").write_text(
        "pre-commit:\n  commands:\n    standards:\n"
        "      run: uv run --frozen sarj-standards check --staged -- {staged_files}\n",
        encoding="utf-8",
    )

    proc = _cli("--root", str(tmp_path), "setup", "--no-install")

    assert proc.returncode == 0, proc.stderr


@pytest.mark.parametrize(
    "run",
    [
        "echo 'sarj-standards check --staged'",
        "printf 'sarj-standards check --staged'",
        "true && sarj-standards check --staged",
    ],
)
def test_init_repairs_inert_or_compound_lefthook_commands(tmp_path: Path, run: str) -> None:
    _ = _python_repo(tmp_path)
    (tmp_path / "lefthook.yml").write_text(
        f"pre-commit:\n  commands:\n    standards:\n      run: {run}\n",
        encoding="utf-8",
    )

    proc = _cli("--root", str(tmp_path), "setup", "--no-install")

    assert proc.returncode == 0, proc.stderr
    updated = (tmp_path / "lefthook.yml").read_text(encoding="utf-8")
    assert "--from sarj-standards==" in updated
    assert "sarj-standards check --staged --trust-repository-code -- {staged_files}" in updated


def test_init_repairs_a_commented_out_lefthook_command(tmp_path: Path) -> None:
    _ = _python_repo(tmp_path)
    (tmp_path / "lefthook.yml").write_text(
        "pre-commit:\n  commands: {}\n# sarj-standards check --staged\n",
        encoding="utf-8",
    )

    proc = _cli("--root", str(tmp_path), "setup", "--no-install")

    assert proc.returncode == 0, proc.stderr
    updated = (tmp_path / "lefthook.yml").read_text(encoding="utf-8")
    assert "# sarj-standards check --staged" in updated
    assert "sarj-standards check --staged --trust-repository-code -- {staged_files}" in updated


def test_init_rejects_malformed_lefthook_yaml(tmp_path: Path) -> None:
    _ = _python_repo(tmp_path)
    (tmp_path / "lefthook.yml").write_text(
        "pre-commit:\n  commands: [\n    # sarj-standards check --staged\n",
        encoding="utf-8",
    )

    proc = _cli("--root", str(tmp_path), "setup", "--no-install")

    assert proc.returncode == 2
    assert "cannot safely wire lefthook.yml" in proc.stderr


def test_init_can_explicitly_disable_hook_management(tmp_path: Path) -> None:
    _ = _python_repo(tmp_path)

    proc = _cli("--root", str(tmp_path), "setup", "--hooks", "none", "--no-install")

    assert proc.returncode == 0, proc.stderr
    assert not (tmp_path / ".pre-commit-config.yaml").exists()
    adopted = manifest.load(tmp_path)
    assert adopted is not None
    assert adopted.hook_manager == "none"


def test_init_repairs_unwired_but_rejects_missing_lefthook_management(tmp_path: Path) -> None:
    _ = _python_repo(tmp_path)
    missing = _cli("--root", str(tmp_path), "setup", "--hooks", "lefthook", "--no-install")
    assert missing.returncode == 2
    assert "requires lefthook" in missing.stderr

    (tmp_path / "lefthook.yml").write_text("pre-commit:\n  commands: {}\n", encoding="utf-8")
    unwired = _cli("--root", str(tmp_path), "setup", "--hooks", "lefthook", "--no-install")
    assert unwired.returncode == 0, unwired.stderr
    assert "sarj-standards check --staged --trust-repository-code -- {staged_files}" in (
        tmp_path / "lefthook.yml"
    ).read_text(encoding="utf-8")


def test_init_repairs_final_lefthook_commands_key_without_a_newline(tmp_path: Path) -> None:
    _ = _python_repo(tmp_path)
    config = tmp_path / "lefthook.yml"
    config.write_text("pre-commit:\n  commands:", encoding="utf-8")

    proc = _cli("--root", str(tmp_path), "setup", "--hooks", "lefthook", "--no-install")

    assert proc.returncode == 0, proc.stderr
    assert adoption_hooks.lefthook_runs_staged_check(tmp_path)


def test_init_preserves_and_extends_lefthook_v2_jobs(tmp_path: Path) -> None:
    _ = _python_repo(tmp_path)
    config = tmp_path / "lefthook.yml"
    original_job = "    - name: existing\n      run: make lint\n"
    config.write_text(f"pre-commit:\n  jobs:\n{original_job}\npre-push:\n  commands: {{}}\n", encoding="utf-8")

    proc = _cli("--root", str(tmp_path), "setup", "--hooks", "lefthook", "--no-install")

    assert proc.returncode == 0, proc.stderr
    updated = config.read_text(encoding="utf-8")
    assert original_job in updated
    assert "- name: sarj-standards\n      run: uvx --isolated" in updated
    assert "sarj-standards check --staged --trust-repository-code -- {staged_files}" in updated
    assert "pre-push:\n  commands: {}" in updated
    assert adoption_hooks.lefthook_runs_staged_check(tmp_path)


def test_nested_lefthook_v2_job_can_already_run_staged_check(tmp_path: Path) -> None:
    _ = _python_repo(tmp_path)
    config = tmp_path / "lefthook.yml"
    original = (
        "pre-commit:\n  jobs:\n    - name: checks\n      group:\n        jobs:\n"
        "          - name: standards\n            run: sarj-standards check --staged\n"
    )
    config.write_text(original, encoding="utf-8")

    proc = _cli("--root", str(tmp_path), "setup", "--hooks", "lefthook", "--no-install")

    assert proc.returncode == 0, proc.stderr
    updated = config.read_text(encoding="utf-8")
    assert updated != original
    assert "--from sarj-standards==" in updated
    assert "sarj-standards check --staged --trust-repository-code -- {staged_files}" in updated


def test_lefthook_cycle_fails_closed_without_recursing(tmp_path: Path) -> None:
    (tmp_path / "lefthook.yml").write_text(
        "pre-commit:\n  jobs: &jobs\n    - name: recursive\n      group:\n        jobs: *jobs\n",
        encoding="utf-8",
    )

    assert not adoption_hooks.lefthook_runs_staged_check(tmp_path)


@pytest.mark.parametrize("suffix", ["js", "jsx", "mjs", "cjs", "ts", "tsx", "mts", "cts"])
def test_generated_precommit_block_routes_every_supported_javascript_suffix(tmp_path: Path, suffix: str) -> None:
    _ = _typescript_repo(tmp_path)
    assert _cli("--root", str(tmp_path), "setup", "--no-install").returncode == 0

    generated = (tmp_path / ".pre-commit-config.yaml").read_text()
    match = re.search(r"(?m)^\s*files:\s*'(?P<pattern>[^']+)'$", generated)
    assert match is not None
    assert re.search(match.group("pattern"), f"src/example.{suffix}") is not None


def test_init_writes_the_npm_overrides_into_package_json(tmp_path: Path) -> None:
    """`init` has to WRITE the overrides, not just talk about them."""
    _ = _typescript_repo(tmp_path)
    proc = _cli("--root", str(tmp_path), "setup", "--no-install")
    assert proc.returncode == 0, proc.stderr

    parsed: object = json.loads((tmp_path / "package.json").read_text(encoding="utf-8"))  # pyright: ignore[reportAny] — untyped stdlib boundary
    written = manifest.as_table(parsed)
    overrides = manifest.table_field(written, "overrides")
    assert set(overrides) == set(manifest.eslint_overrides())
    assert manifest.table_field(overrides, "eslint-plugin-react")["eslint"] == manifest.eslint_peers()["eslint"]
    assert written["name"] == "web", "the consumer's own keys must survive the merge"


def test_init_does_not_clobber_a_consumers_existing_overrides(tmp_path: Path) -> None:
    """package.json is the consumer's file; only the ESLint entries are ours."""
    _ = (tmp_path / "package.json").write_text(
        json.dumps({"name": "web", "overrides": {"left-pad": "1.3.0"}}, indent=2) + "\n"
    )
    assert _cli("--root", str(tmp_path), "setup", "--no-install").returncode == 0

    parsed: object = json.loads((tmp_path / "package.json").read_text(encoding="utf-8"))  # pyright: ignore[reportAny] — untyped stdlib boundary
    overrides = manifest.table_field(manifest.as_table(parsed), "overrides")
    assert overrides["left-pad"] == "1.3.0"
    assert "eslint-plugin-react" in overrides


def test_init_leaves_a_package_json_that_already_has_the_overrides_alone(
    tmp_path: Path,
) -> None:
    _ = _typescript_repo(tmp_path)
    assert _cli("--root", str(tmp_path), "setup", "--no-install").returncode == 0
    before = (tmp_path / "package.json").read_text(encoding="utf-8")

    second = _cli("--root", str(tmp_path), "setup", "--no-install")
    assert second.returncode == 0
    assert (tmp_path / "package.json").read_text(encoding="utf-8") == before
    assert "already pins the tested ESLint peers and npm overrides" in second.stdout


def test_init_wires_the_subproject_that_actually_installs_eslint(tmp_path: Path) -> None:
    """The repo root is not the project root, and writing there reaches nobody."""
    (tmp_path / "web").mkdir()
    _ = (tmp_path / "web" / "package.json").write_text('{"name": "web"}\n')
    _ = (tmp_path / "web" / "package-lock.json").write_text("{}\n")
    proc = _cli("--root", str(tmp_path), "setup", "--no-install")
    assert proc.returncode == 0, proc.stderr

    assert (tmp_path / "web" / "eslint.config.mjs").is_file()
    assert (tmp_path / "web" / "eslint.strict.mjs").is_file()
    assert not (tmp_path / "eslint.config.mjs").exists()

    parsed: object = json.loads((tmp_path / "web" / "package.json").read_text(encoding="utf-8"))  # pyright: ignore[reportAny] — untyped stdlib boundary
    assert "eslint-plugin-react" in manifest.table_field(manifest.as_table(parsed), "overrides")


def test_doctor_reads_the_subproject_destinations_back_out_of_the_manifest(
    tmp_path: Path,
) -> None:
    """CI runs bare `sync --check`; if it did not know the dests it saw permanent drift."""
    (tmp_path / "web").mkdir()
    _ = (tmp_path / "web" / "package.json").write_text('{"name": "web"}\n')
    _ = (tmp_path / "web" / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n")
    assert _cli("--root", str(tmp_path), "setup", "--no-install").returncode == 0

    proc = _cli("--root", str(tmp_path), "doctor")
    assert proc.returncode == 0, proc.stdout
    assert "0 drifted" in proc.stdout


def test_doctor_keeps_shared_configs_at_repo_root_after_subproject_adoption(
    tmp_path: Path,
) -> None:
    """A recorded Python destination must not capture repository-wide configs."""
    project = tmp_path / "python" / "api"
    project.mkdir(parents=True)
    _ = (project / "pyproject.toml").write_text(
        '[project]\nname = "api"\nversion = "0.1.0"\nrequires-python = ">=3.14"\n'
    )
    assert _cli("--root", str(tmp_path), "setup", "--no-install").returncode == 0

    second = _cli("--root", str(tmp_path), "doctor")

    assert second.returncode == 0, second.stdout
    assert (tmp_path / ".markdownlint.yaml").is_file()
    assert str(project / ".markdownlint.yaml") not in second.stdout


#: A hook that does not say `pass_filenames: false` receives the staged files
#: pre-commit matched for it, so replaying one without a path is not the command
#: that actually runs.
_PRECOMMIT_HOOK = re.compile(r"entry:\s*(?P<entry>.+?)\n(?P<rest>(?:\s+\w[^\n]*\n)*)", re.MULTILINE)


def _precommit_entries(config: str) -> list[tuple[str, bool]]:
    return [
        (match.group("entry").strip(), "pass_filenames: false" in match.group("rest"))
        for match in _PRECOMMIT_HOOK.finditer(config)
    ]


def test_the_generated_precommit_hook_actually_runs(tmp_path: Path) -> None:
    """The one file `init` writes that nothing executed."""
    _ = _python_repo(tmp_path)
    _ = (tmp_path / "src" / "app.py").write_text("VALUE: int = 1\n")
    assert _cli("--root", str(tmp_path), "setup", "--no-install").returncode == 0
    environment = {
        name: value
        for name, value in os.environ.items()  # ruff: ignore[banned-api] -- isolate fixture Git from enclosing hooks.
        if not name.startswith("GIT_")
    }
    subprocess.run(("git", "init", "-q"), cwd=tmp_path, check=True, env=environment)
    subprocess.run(("git", "add", "src/app.py"), cwd=tmp_path, check=True, env=environment)

    entries = _precommit_entries((tmp_path / ".pre-commit-config.yaml").read_text())
    assert len(entries) == 1, "one orchestrator avoids duplicate uv startup and whole-repo scans"
    for entry, pass_filenames_false in entries:
        # Run the CLI the hook names, through the interpreter the tests already
        # use, so this exercises the generated command shape without needing a
        # network fetch or a uv-managed virtualenv inside tmp_path.
        subcommand = entry.rsplit(" sarj-standards ", 1)[1].split()
        if not pass_filenames_false:
            subcommand.append("src/app.py")
        proc = _cli(*subcommand, cwd=tmp_path)
        assert proc.returncode == 0, f"{entry!r} failed: {proc.stdout}{proc.stderr}"


def test_generated_check_hook_uses_normal_precommit_output_behavior(tmp_path: Path) -> None:
    _ = _python_repo(tmp_path)

    assert _cli("--root", str(tmp_path), "setup", "--no-install").returncode == 0

    config = (tmp_path / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    check_block = config.split("id: sarj-standards-check", 1)[1]
    assert "verbose: true" not in check_block


def test_doctor_detects_a_disabled_generated_precommit_hook(tmp_path: Path) -> None:
    _ = _python_repo(tmp_path)
    assert _cli("--root", str(tmp_path), "setup", "--no-install").returncode == 0
    config = tmp_path / ".pre-commit-config.yaml"
    config.write_text(
        config.read_text(encoding="utf-8").replace("check --staged --", "echo standards-disabled"),
        encoding="utf-8",
    )

    findings = doctor.diagnose(tmp_path)

    assert [finding for finding in findings if finding.id == "doctor.hooks.precommit"]


def test_doctor_detects_competing_canonical_hook_managers(tmp_path: Path) -> None:
    _ = _python_repo(tmp_path)
    assert _cli("--root", str(tmp_path), "setup", "--no-install").returncode == 0
    (tmp_path / "lefthook.yml").write_text(
        "pre-commit:\n  jobs:\n    - name: standards\n"
        f"      run: uvx --isolated --python 3.14 --from sarj-standards=={__version__} "
        "sarj-standards check --staged --trust-repository-code -- {staged_files}\n",
        encoding="utf-8",
    )

    conflicts = [finding for finding in doctor.diagnose(tmp_path) if finding.id == "doctor.hooks.manager-conflict"]

    assert len(conflicts) == 1
    assert conflicts[0].level is doctor.Level.DRIFT
    assert "canonical lefthook Standards hook is also active" in conflicts[0].detail


def test_doctor_detects_a_precommit_migration_chain_with_legacy_lefthook(tmp_path: Path) -> None:
    _ = _python_repo(tmp_path)
    assert _cli("--root", str(tmp_path), "setup", "--no-install").returncode == 0
    subprocess.run(("git", "init", "-q"), cwd=tmp_path, check=True, env={})
    hook = tmp_path / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\n# pre_commit hook-type=pre-commit\n", encoding="utf-8")
    hook.with_name("pre-commit.legacy").write_text(
        "#!/bin/sh\nexport LEFTHOOK_BIN=.git/hooks/.sarj-lefthook\n",
        encoding="utf-8",
    )

    conflicts = [finding for finding in doctor.diagnose(tmp_path) if finding.id == "doctor.hooks.manager-conflict"]

    assert len(conflicts) == 1
    assert conflicts[0].level is doctor.Level.DRIFT
    assert "installed hook chain includes lefthook" in conflicts[0].detail


def test_doctor_warns_when_selected_lefthook_is_not_installed(tmp_path: Path) -> None:
    _ = _python_repo(tmp_path)
    subprocess.run(("git", "init", "-q"), cwd=tmp_path, check=True, env={})
    (tmp_path / "lefthook.yml").write_text(
        "pre-commit:\n  jobs:\n    - name: consumer\n      run: true\n",
        encoding="utf-8",
    )
    assert _cli("--root", str(tmp_path), "setup", "--hooks", "lefthook", "--no-install").returncode == 0

    warnings = [finding for finding in doctor.diagnose(tmp_path) if finding.id == "doctor.hooks.lefthook-install"]

    assert len(warnings) == 1
    assert warnings[0].level is doctor.Level.WARN
    assert warnings[0].remediation == "run `sarj-standards maintain hooks install`"


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("files: '(?i)", "files: '$^"),
        ("stages: [pre-commit]", "stages: [pre-push]"),
        ("pass_filenames: true", "pass_filenames: false"),
        ("require_serial: true", "require_serial: false"),
        ("always_run: true", "always_run: false"),
    ],
)
def test_doctor_rejects_inert_or_semantically_changed_precommit_hook(tmp_path: Path, old: str, new: str) -> None:
    _ = _python_repo(tmp_path)
    assert _cli("--root", str(tmp_path), "setup", "--no-install").returncode == 0
    config = tmp_path / ".pre-commit-config.yaml"
    contents = config.read_text(encoding="utf-8")
    assert old in contents
    config.write_text(contents.replace(old, new), encoding="utf-8")

    findings = doctor.diagnose(tmp_path)

    assert [finding for finding in findings if finding.id == "doctor.hooks.precommit"]


def test_doctor_warns_when_the_checkout_hook_is_not_installed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    consumer = _python_repo(tmp_path / "consumer")
    outer = tmp_path / "outer"
    outer.mkdir()
    subprocess.run(("git", "init", "-q"), cwd=consumer, check=True, env={})
    subprocess.run(("git", "init", "-q"), cwd=outer, check=True, env={})
    monkeypatch.setenv("GIT_DIR", str(outer / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(outer))
    assert _cli("--root", str(consumer), "setup", "--no-install").returncode == 0

    findings = doctor.diagnose(consumer)

    assert [
        finding
        for finding in findings
        if finding.id == "doctor.hooks.precommit-install" and finding.level is doctor.Level.WARN
    ]
    hook_location = subprocess.run(
        ("git", "rev-parse", "--git-path", "hooks/pre-commit"),
        cwd=consumer,
        check=True,
        capture_output=True,
        env={},
        text=True,
    ).stdout.strip()
    hook = Path(hook_location)
    if not hook.is_absolute():
        hook = consumer / hook
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text("#!/bin/sh\n# pre_commit hook-type=pre-commit\n", encoding="utf-8")
    assert not [finding for finding in doctor.diagnose(consumer) if finding.id == "doctor.hooks.precommit-install"]


def test_doctor_repair_converges_configuration_without_installing(tmp_path: Path) -> None:
    _ = _python_repo(tmp_path)
    assert _cli("--root", str(tmp_path), "setup", "--no-install").returncode == 0
    config = tmp_path / ".pre-commit-config.yaml"
    config.write_text(
        config.read_text(encoding="utf-8").replace("stages: [pre-commit]", "stages: [pre-push]"),
        encoding="utf-8",
    )

    repaired = _cli("--root", str(tmp_path), "doctor", "--repair", "--no-install")

    assert repaired.returncode == 0, repaired.stdout + repaired.stderr
    assert "stages: [pre-commit]" in config.read_text(encoding="utf-8")


def test_doctor_repair_restores_owned_config_while_reporting_manual_retired_rule_debt(tmp_path: Path) -> None:
    _ = _python_repo(tmp_path)
    assert _cli("--root", str(tmp_path), "setup", "--no-install").returncode == 0
    config = tmp_path / ".ruff-strict.toml"
    config.unlink()
    retired = "@sarj/no-" + "unsafe-cast"
    (tmp_path / "legacy-eslint.config.mjs").write_text(f'export default [{{ rules: {{ "{retired}": "off" }} }}];\n')

    repaired = _cli("--root", str(tmp_path), "doctor", "--repair", "--no-install")

    assert repaired.returncode == 1
    assert config.is_file()
    assert "doctor.rule.retired" in repaired.stdout


@pytest.mark.parametrize("path", ["requirements.txt", "requirements-dev.in", "requirements/prod.txt"])
def test_generated_check_hook_includes_application_requirement_manifests(tmp_path: Path, path: str) -> None:
    _ = _python_repo(tmp_path)
    assert _cli("--root", str(tmp_path), "setup", "--no-install").returncode == 0

    config = (tmp_path / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    pattern_text = re.search(r"(?m)^\s*files: '(?P<pattern>.+)'$", config)
    assert pattern_text is not None
    assert re.search(pattern_text.group("pattern"), path), path


def test_init_migrates_existing_generated_hooks_to_one_staged_hook(tmp_path: Path) -> None:
    _python_repo(tmp_path)
    config = tmp_path / ".pre-commit-config.yaml"
    config.write_text(
        "repos:\n"
        "  - repo: local\n"
        "    hooks:\n"
        "      - id: sarj-standards-drift\n"
        "        entry: sarj-standards doctor\n"
        "      - id: sarj-standards-check\n"
        "        entry: sarj-standards check\n",
        encoding="utf-8",
    )

    assert _cli("--root", str(tmp_path), "setup", "--no-install").returncode == 0

    updated = config.read_text(encoding="utf-8")
    assert "verbose: true" not in updated
    assert updated.count("id: sarj-standards-check") == 1
    assert "id: sarj-standards-drift" not in updated
    assert "check --staged" in updated


def test_setup_migrates_plain_official_per_rule_hooks_to_umbrella(tmp_path: Path) -> None:
    _python_repo(tmp_path)
    config = tmp_path / ".pre-commit-config.yaml"
    config.write_text(
        "repos:\n"
        "  - repo: https://github.com/sarj-ai/standards\n"
        "    rev: python-v0.51.0\n"
        "    hooks:\n"
        "      - id: sarj-no-comment-cruft\n"
        "      - id: sarj-no-sequential-await\n",
        encoding="utf-8",
    )

    assert _cli("--root", str(tmp_path), "setup", "--no-install").returncode == 0

    updated = config.read_text(encoding="utf-8")
    assert "github.com/sarj-ai/standards" not in updated
    assert "sarj-no-comment-cruft" not in updated
    assert "sarj-no-sequential-await" not in updated
    assert updated.count("id: sarj-standards-check") == 1


def test_init_consolidates_owned_hooks_across_local_repository_blocks(tmp_path: Path) -> None:
    _python_repo(tmp_path)
    config = tmp_path / ".pre-commit-config.yaml"
    config.write_text(
        "repos:\n"
        "  - repo: local\n"
        "    hooks:\n"
        "      - id: keep-first\n"
        "        entry: true\n"
        "      - id: sarj-standards-drift\n"
        "        entry: sarj-standards doctor\n"
        "  - repo: local\n"
        "    hooks:\n"
        "      - id: sarj-standards-check\n"
        "        entry: sarj-standards check\n"
        "      - id: keep-second\n"
        "        entry: true\n",
        encoding="utf-8",
    )

    assert _cli("--root", str(tmp_path), "setup", "--no-install").returncode == 0
    first = config.read_text(encoding="utf-8")
    assert first.count("id: sarj-standards-check") == 1
    assert "id: sarj-standards-drift" not in first
    assert "id: keep-first" in first
    assert "id: keep-second" in first
    assert not [
        finding
        for finding in doctor.diagnose(tmp_path)
        if finding.id == "doctor.hooks.precommit" and finding.level is doctor.Level.DRIFT
    ]

    assert _cli("--root", str(tmp_path), "update", "--offline", "--no-install").returncode == 0
    assert config.read_text(encoding="utf-8") == first


def test_init_refuses_to_discard_custom_local_hook_scope(tmp_path: Path) -> None:
    _python_repo(tmp_path)
    config = tmp_path / ".pre-commit-config.yaml"
    config.write_text(
        "repos:\n"
        "  - repo: local\n"
        "    hooks:\n"
        "      - id: sarj-standards-check\n"
        "        entry: sarj-standards check --staged --\n"
        "        exclude: ^generated/\n",
        encoding="utf-8",
    )
    before = config.read_bytes()

    result = _cli("--root", str(tmp_path), "setup", "--no-install")

    assert result.returncode == 2
    assert "customized local Sarj hook (exclude)" in result.stderr
    assert config.read_bytes() == before


def test_init_preserves_zero_indented_precommit_repository_style(tmp_path: Path) -> None:
    _python_repo(tmp_path)
    config = tmp_path / ".pre-commit-config.yaml"
    config.write_text(
        "default_language_version:\n  python: python3\nrepos:\n- repo: local\n  hooks:\n"
        "  - id: existing\n    name: existing\n    entry: true\n    language: system\n",
        encoding="utf-8",
    )

    assert _cli("--root", str(tmp_path), "setup", "--no-install").returncode == 0

    parsed: object = yaml.safe_load(config.read_text(encoding="utf-8"))  # pyright: ignore[reportAny] -- narrowed below.
    repositories = manifest.list_field(manifest.as_table(parsed), "repos")
    assert len(repositories) == 2
    assert adoption_hooks.precommit_runs_staged_check(tmp_path)


def test_init_refuses_to_create_duplicate_ruff_additive_keys(tmp_path: Path) -> None:
    _python_repo(tmp_path)
    pyproject = tmp_path / "pyproject.toml"
    current = pyproject.read_text(encoding="utf-8")
    pyproject.write_text(
        f'{current}\n[tool.ruff.lint]\nselect = ["E4"]\nextend-select = ["ASYNC"]\n',
        encoding="utf-8",
    )
    before = pyproject.read_bytes()

    result = _cli("--root", str(tmp_path), "setup", "--no-install")

    assert result.returncode == 2
    assert "defines both select/extend-select" in result.stderr
    assert pyproject.read_bytes() == before


def test_init_deduplicates_redundant_select_all_before_extending_ruff(tmp_path: Path) -> None:
    _python_repo(tmp_path)
    pyproject = tmp_path / "pyproject.toml"
    current = pyproject.read_text(encoding="utf-8")
    pyproject.write_text(
        f'{current}\n[tool.ruff.lint]\nselect = ["ALL"]\nextend-select = ["ASYNC"]\n',
        encoding="utf-8",
    )

    result = _cli("--root", str(tmp_path), "setup", "--no-install")

    assert result.returncode == 0, result.stderr
    parsed = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    tool = manifest.table_field(manifest.as_table(parsed), "tool")
    ruff = manifest.table_field(tool, "ruff")
    assert "select" not in manifest.table_field(ruff, "lint")


def test_a_typescript_only_precommit_hook_does_not_invoke_uv_run(tmp_path: Path) -> None:
    _ = _typescript_repo(tmp_path)
    assert _cli("--root", str(tmp_path), "setup", "--no-install").returncode == 0

    generated = (tmp_path / ".pre-commit-config.yaml").read_text()
    assert "uv run --frozen" not in generated
    assert f"uvx --isolated --python 3.14 --from sarj-standards=={__version__}" in generated
    # `check` runs the Python/SQL/IaC registries; a TypeScript repo has nothing
    # to feed them, and a hook that lints nothing is a hook that hides.
    assert "sarj-standards check" in generated


@pytest.mark.parametrize("ecosystem", ["python", "typescript"])
def test_show_ci_renders_a_complete_pinned_workflow(tmp_path: Path, ecosystem: str) -> None:
    _ = _python_repo(tmp_path) if ecosystem == "python" else _typescript_repo(tmp_path)
    assert _cli("--root", str(tmp_path), "setup", "--no-install").returncode == 0

    rendered = _cli("--root", str(tmp_path), "show", "ci")

    assert rendered.returncode == 0, rendered.stderr
    parsed: object = yaml.safe_load(rendered.stdout)  # pyright: ignore[reportAny] -- parser result is narrowed below.
    assert isinstance(parsed, dict)
    assert "permissions:\n  contents: read" in rendered.stdout
    assert "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1" in rendered.stdout
    assert "astral-sh/setup-uv@c771a70e6277c0a99b617c7a806ffedaca235ff9" in rendered.stdout
    uv_config = manifest.as_table(tomllib.loads((REPO_ROOT / "uv.toml").read_text(encoding="utf-8")))
    uv_required = manifest.text_field(uv_config, "required-version")
    assert uv_required is not None
    uv_version = uv_required.removeprefix("==")
    assert f"version: '{uv_version}'" in rendered.stdout
    assert "sarj-standards check" in rendered.stdout
    if ecosystem == "python":
        assert "uv sync --locked" not in rendered.stdout
    else:
        assert "actions/setup-node@820762786026740c76f36085b0efc47a31fe5020" in rendered.stdout
        assert "npm ci --no-audit --no-fund" in rendered.stdout


def test_show_ci_syncs_every_uv_workspace_package_and_runs_configured_bootstrap(tmp_path: Path) -> None:
    python = tmp_path / "python"
    python.mkdir()
    (python / "pyproject.toml").write_text(
        "[project]\nname='root'\nversion='0'\n[tool.uv.workspace]\nmembers=['packages/*']\n",
        encoding="utf-8",
    )
    (python / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    adopted = manifest.Manifest(
        __version__,
        manifest.default_configs(has_python=True, has_typescript=False),
        "python",
        ".",
        ci_bootstrap=("uv run --project python generate-api", "yarn generate"),
    )
    (tmp_path / manifest.MANIFEST_NAME).write_text(adopted.render(), encoding="utf-8")

    rendered = _cli("--root", str(tmp_path), "show", "ci")

    assert rendered.returncode == 0, rendered.stderr
    assert "uv sync --locked --project python --all-packages" in rendered.stdout
    assert 'run: "uv run --project python generate-api"' in rendered.stdout
    assert 'run: "yarn generate"' in rendered.stdout


def test_generated_ci_is_recognized_as_an_executable_standards_gate(tmp_path: Path) -> None:
    _ = _python_repo(tmp_path)
    assert _cli("--root", str(tmp_path), "setup", "--no-install").returncode == 0

    assert scaffold.standards_check_workflows(tmp_path) == (tmp_path / ".github" / "workflows" / "standards.yml",)


@pytest.mark.parametrize(
    "command",
    [
        "echo sarj-standards check",
        "# sarj-standards check",
        "false && sarj-standards check",
        "uvx echo sarj-standards check",
        "sarj-standards --help check",
    ],
)
def test_ci_detection_rejects_inert_standards_text(tmp_path: Path, command: str) -> None:
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    _ = (workflows / "inert.yml").write_text(
        f"jobs:\n  lint:\n    steps:\n      - run: |\n          {command}\n",
        encoding="utf-8",
    )

    assert scaffold.standards_check_workflows(tmp_path) == ()


def test_detection_finds_a_package_json_in_a_subproject(tmp_path: Path) -> None:
    _ = _python_repo(tmp_path)
    (tmp_path / "services" / "web").mkdir(parents=True)
    _ = (tmp_path / "services" / "web" / "package.json").write_text("{}\n")
    found = scaffold.detect(tmp_path)
    assert (found.python, found.typescript) == (True, True)
    assert found.python_root == tmp_path
    assert found.typescript_root == tmp_path / "services" / "web"


def test_init_fails_loudly_on_independent_project_roots(tmp_path: Path) -> None:
    for name in ("api", "worker"):
        project = tmp_path / name
        project.mkdir()
        _python_repo(project)

    proc = _cli("--root", str(tmp_path), "setup", "--no-install")

    assert proc.returncode == 2
    assert "multiple independent Python roots" in proc.stderr
    assert "--python-dest" in proc.stderr
    assert not (tmp_path / manifest.MANIFEST_NAME).exists()


def test_explicit_project_root_resolves_independent_root_ambiguity(tmp_path: Path) -> None:
    for name in ("api", "worker"):
        project = tmp_path / name
        project.mkdir()
        _python_repo(project)

    proc = _cli("--root", str(tmp_path), "setup", "--python-dest", "api", "--no-install")

    assert proc.returncode == 0, proc.stderr
    assert (tmp_path / "api" / ".ruff-strict.toml").is_file()
    assert not (tmp_path / "worker" / ".ruff-strict.toml").exists()


def test_detection_ignores_node_modules(tmp_path: Path) -> None:
    (tmp_path / "node_modules" / "left-pad").mkdir(parents=True)
    _ = (tmp_path / "node_modules" / "left-pad" / "package.json").write_text("{}\n")
    assert scaffold.detect(tmp_path).typescript is False


def test_doctor_accepts_isolated_python_adoption_without_consumer_bundle(tmp_path: Path) -> None:
    _ = _python_repo(tmp_path)
    assert _cli("--root", str(tmp_path), "setup", "--no-install").returncode == 0
    proc = _cli("--root", str(tmp_path), "doctor")
    assert proc.returncode == 0, proc.stdout
    assert "doctor.python.legacy-in-project-tool" not in proc.stdout


def test_doctor_explains_source_controlled_config_drift(tmp_path: Path) -> None:
    _python_repo(tmp_path)
    assert _cli("--root", str(tmp_path), "setup", "--no-install").returncode == 0
    target = tmp_path / ".ruff-strict.toml"
    source = tmp_path / "canonical-ruff.toml"
    source.write_text("stale\n", encoding="utf-8")
    target.unlink()
    target.symlink_to(source.name)

    proc = _cli("--root", str(tmp_path), "doctor")

    assert proc.returncode == 1, proc.stdout
    assert "doctor.config.source-drift" in proc.stdout
    assert "update or rebase the Standards source checkout" in proc.stdout


def test_doctor_migrates_the_exact_legacy_in_project_bundle(tmp_path: Path) -> None:
    _ = _python_repo(tmp_path)
    assert _cli("--root", str(tmp_path), "setup", "--no-install").returncode == 0
    _add_python_bundle_pins(tmp_path)

    proc = _cli("--root", str(tmp_path), "doctor")

    assert proc.returncode == 1, proc.stdout
    assert "doctor.python.legacy-in-project-tool" in proc.stdout
    assert "uv remove --dev sarj-standards" in proc.stdout


def test_doctor_accepts_exact_local_bundle_projects_for_source_workspace(tmp_path: Path) -> None:
    versions = manifest.installed_versions()
    first_name, first_version = next(iter(versions.items()))
    (tmp_path / "src").mkdir()
    (tmp_path / "pyproject.toml").write_text(
        f'[project]\nname = "{first_name}"\nversion = "{first_version}"\nrequires-python = ">=3.14"\n',
        encoding="utf-8",
    )
    assert _cli("--root", str(tmp_path), "setup", "--no-install").returncode == 0
    for name, package_version in tuple(versions.items())[1:]:
        project = tmp_path / "packages" / name
        project.mkdir(parents=True, exist_ok=True)
        (project / "pyproject.toml").write_text(
            f'[project]\nname = "{name}"\nversion = "{package_version}"\n',
            encoding="utf-8",
        )

    proc = _cli("--root", str(tmp_path), "doctor")

    assert proc.returncode == 0, proc.stdout
    assert "doctor.python.legacy-in-project-tool" not in proc.stdout


@pytest.mark.parametrize("contents", ["{\n", "[]\n"], ids=["malformed", "non-object"])
def test_doctor_rejects_an_invalid_adopted_typescript_package_json(tmp_path: Path, contents: str) -> None:
    _typescript_repo(tmp_path)
    assert _cli("--root", str(tmp_path), "setup", "--no-install").returncode == 0
    (tmp_path / "package.json").write_text(contents, encoding="utf-8")

    proc = _cli("--root", str(tmp_path), "doctor")

    assert proc.returncode == 2
    assert "doctor.package-json.invalid package.json" in proc.stdout
    assert "fix: repair package.json, then rerun doctor" in proc.stdout


def test_doctor_rejects_non_exact_python_bundle_range(tmp_path: Path) -> None:
    _ = _python_repo(tmp_path)
    assert _cli("--root", str(tmp_path), "setup", "--no-install").returncode == 0
    versions = manifest.installed_versions()
    bundle = ", ".join(f'"{name}{">=" if name == "sarj-standards" else "=="}{pin}"' for name, pin in versions.items())
    with (tmp_path / "pyproject.toml").open("a", encoding="utf-8") as handle:
        _ = handle.write(f"\n[dependency-groups]\ndev = [{bundle}]\n")

    proc = _cli("--root", str(tmp_path), "doctor")

    assert proc.returncode == 1, proc.stdout
    assert "exact `==` pins" in proc.stdout
    assert "doctor.python.legacy-in-project-tool" in proc.stdout


def test_doctor_catches_a_stale_pyproject_pin(tmp_path: Path) -> None:
    """The measured case: consumers pin 0.25.0 while main ships 0.33.0."""
    _ = _python_repo(tmp_path)
    _ = (tmp_path / "requirements.txt").write_text("sarj-python-lint==0.25.0\n")
    proc = _cli("--root", str(tmp_path), "doctor")
    assert proc.returncode == 1
    assert "sarj-python-lint==0.25.0" in proc.stdout


def test_doctor_catches_a_ci_pin_that_differs_from_the_pyproject_pin(tmp_path: Path) -> None:
    _ = _python_repo(tmp_path)
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    _ = (workflows / "ci.yml").write_text(
        "jobs:\n  lint:\n    steps:\n      - run: uvx --from sarj-python-lint==0.12.2 sarj-python-lint check .\n"
    )
    proc = _cli("--root", str(tmp_path), "doctor")
    assert proc.returncode == 1
    assert "ci.yml" in proc.stdout
    assert "0.12.2" in proc.stdout


def test_doctor_catches_a_stale_package_script_pin(tmp_path: Path) -> None:
    _ = _typescript_repo(tmp_path)
    _ = (tmp_path / "package.json").write_text(
        '{"scripts":{"lint:sarj":"uvx --from sarj-standards==0.1.0 sarj-standards check ."}}\n'
    )

    proc = _cli("--root", str(tmp_path), "doctor")

    assert proc.returncode == 1
    assert "package.json: sarj-standards==0.1.0" in proc.stdout


@pytest.mark.parametrize(
    "repository",
    [
        "https://github.com/not-sarj-ai/standards",
        "https://github.com/sarj-ai/standards-fork",
    ],
)
def test_doctor_does_not_claim_lookalike_precommit_repositories(tmp_path: Path, repository: str) -> None:
    _ = _python_repo(tmp_path)
    _ = (tmp_path / ".pre-commit-config.yaml").write_text(
        f"repos:\n  - repo: {repository}\n    rev: stale\n    hooks:\n      - id: sarj-standards\n",
        encoding="utf-8",
    )

    proc = _cli("--root", str(tmp_path), "doctor")

    assert "rev stale" not in proc.stdout


def test_init_does_not_rewrite_a_remote_hook_with_a_generated_id(tmp_path: Path) -> None:
    _ = _python_repo(tmp_path)
    config = tmp_path / ".pre-commit-config.yaml"
    remote = (
        "  - repo: https://github.com/example/custom-hooks\n"
        "    rev: v1\n"
        "    hooks:\n"
        "      - id: sarj-standards-check\n"
        "        args: [--custom]\n"
    )
    config.write_text(f"repos:\n{remote}", encoding="utf-8")

    assert _cli("--root", str(tmp_path), "setup", "--no-install").returncode == 0

    generated = config.read_text(encoding="utf-8")
    assert remote in generated
    assert generated.count("id: sarj-standards-check") == 2
    assert "args: [--custom]" in generated


def test_init_recognizes_a_quoted_commented_local_generated_hook(tmp_path: Path) -> None:
    _ = _python_repo(tmp_path)
    config = tmp_path / ".pre-commit-config.yaml"
    config.write_text(
        "repos:\n"
        "  - repo: local\n"
        "    hooks:\n"
        "      - id: 'sarj-standards-check' # generated\n"
        "        entry: stale\n"
        "        language: system\n",
        encoding="utf-8",
    )

    assert _cli("--root", str(tmp_path), "setup", "--no-install").returncode == 0

    generated = config.read_text(encoding="utf-8")
    assert generated.count("id: sarj-standards-check") == 1
    assert "entry: stale" not in generated


def test_doctor_catches_a_stale_eslint_plugin_pin(tmp_path: Path) -> None:
    _ = _typescript_repo(tmp_path)
    _ = (tmp_path / "package.json").write_text(
        json.dumps({"name": "web", "devDependencies": {"@sarj/eslint-plugin": "2.16.0"}})
    )
    proc = _cli("--root", str(tmp_path), "doctor")
    assert proc.returncode == 1
    assert "2.16.0" in proc.stdout


@pytest.mark.parametrize(
    "operator",
    ["", "=", "=="],
    ids=["bare", "equals", "double-equals"],
)
def test_doctor_accepts_only_exact_spellings_of_the_tested_floor(tmp_path: Path, operator: str) -> None:
    floor = manifest.eslint_peers()["@sarj/eslint-plugin"]
    _ = _typescript_repo(tmp_path)
    _ = (tmp_path / "package.json").write_text(
        json.dumps({"name": "web", "devDependencies": {"@sarj/eslint-plugin": f"{operator}{floor}"}})
    )
    proc = _cli("--root", str(tmp_path), "doctor")
    assert "matches the tested peer set" in proc.stdout, proc.stdout
    assert "tested against" not in proc.stdout, proc.stdout


@pytest.mark.parametrize("operator", ["^", "~", ">=", ">", "<", "~=", "v"])
def test_doctor_rejects_ranges_even_when_they_name_the_tested_floor(tmp_path: Path, operator: str) -> None:
    floor = manifest.eslint_peers()["@sarj/eslint-plugin"]
    _ = _typescript_repo(tmp_path)
    _ = (tmp_path / "package.json").write_text(
        json.dumps({"name": "web", "devDependencies": {"@sarj/eslint-plugin": f"{operator}{floor}"}})
    )

    proc = _cli("--root", str(tmp_path), "doctor")

    assert proc.returncode == 1
    assert "tested against" in proc.stdout


def test_doctor_still_reports_a_range_that_is_not_the_floor(tmp_path: Path) -> None:
    """The operator is stripped ONCE, so a malformed pin is not laundered into a match."""
    floor = manifest.eslint_peers()["@sarj/eslint-plugin"]
    _ = _typescript_repo(tmp_path)
    _ = (tmp_path / "package.json").write_text(
        json.dumps({"name": "web", "devDependencies": {"@sarj/eslint-plugin": f"^~{floor}"}})
    )
    proc = _cli("--root", str(tmp_path), "doctor")
    assert proc.returncode == 1
    assert "tested against" in proc.stdout, proc.stdout


@pytest.mark.parametrize("specifier", ["file:../plugin", "link:../plugin", "workspace:*"])
def test_doctor_warns_that_a_local_eslint_plugin_checkout_is_unverified(tmp_path: Path, specifier: str) -> None:
    _ = (tmp_path / "package.json").write_text(
        json.dumps({"name": "web", "devDependencies": {"@sarj/eslint-plugin": specifier}})
    )
    proc = _cli("--root", str(tmp_path), "doctor")
    assert proc.returncode == 1
    assert "doctor.eslint.plugin-unverified" in proc.stdout


def test_doctor_verifies_an_in_repository_file_plugin_at_the_tested_version(tmp_path: Path) -> None:
    floor = manifest.eslint_peers()["@sarj/eslint-plugin"]
    plugin = tmp_path / "packages" / "typescript"
    plugin.mkdir(parents=True)
    _ = (plugin / "package.json").write_text(
        json.dumps({"name": "@sarj/eslint-plugin", "version": floor}),
        encoding="utf-8",
    )
    app = tmp_path / "apps" / "docs"
    app.mkdir(parents=True)
    _ = (app / "package.json").write_text(
        json.dumps(
            {
                "name": "docs",
                "devDependencies": {"@sarj/eslint-plugin": "file:../../packages/typescript"},
            }
        ),
        encoding="utf-8",
    )

    findings = doctor.diagnose(tmp_path)

    plugin_findings = [finding for finding in findings if finding.where.startswith("apps/docs/package.json")]
    assert [(finding.level, finding.id) for finding in plugin_findings] == [(doctor.Level.OK, "doctor.eslint.plugin")]


def test_adopted_workspace_checks_the_install_root_not_nested_plugin_ranges(tmp_path: Path) -> None:
    web = tmp_path / "web"
    package = web / "packages" / "legacy"
    package.mkdir(parents=True)
    (web / "package.json").write_text(
        json.dumps({"name": "web", "packageManager": "yarn@4.8.1", "workspaces": ["packages/*"]}),
        encoding="utf-8",
    )
    (web / "yarn.lock").write_text("", encoding="utf-8")
    (package / "package.json").write_text(
        json.dumps({"name": "legacy", "devDependencies": {"@sarj/eslint-plugin": "^0.2.0"}}),
        encoding="utf-8",
    )
    assert _cli("--root", str(tmp_path), "setup", "--no-install").returncode == 0

    findings = doctor.diagnose(tmp_path)

    assert not [finding for finding in findings if finding.where.startswith("web/packages/legacy/package.json")]
    assert not [finding for finding in findings if finding.id == "doctor.eslint.peer"]
    parsed: object = json.loads(  # pyright: ignore[reportAny] -- untyped stdlib boundary
        (web / "package.json").read_text(encoding="utf-8")
    )
    install_package = manifest.as_table(parsed)
    assert manifest.table_field(install_package, "devDependencies") == manifest.eslint_peers()


def test_doctor_skips_vendored_trees(tmp_path: Path) -> None:
    """A pin inside `node_modules` or `.venv` is not the repo's to fix."""
    _ = _python_repo(tmp_path)
    buried = tmp_path / "node_modules" / "junk"
    buried.mkdir(parents=True)
    _ = (buried / "pyproject.toml").write_text('deps = ["sarj-python-lint==0.1.0"]\n')
    proc = _cli("--root", str(tmp_path), "doctor")
    assert "0.1.0" not in proc.stdout


def test_doctor_git_walk_isolates_hook_environment_and_prunes_generated_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Git hook repository variables cannot redirect a consumer scan."""
    kept = tmp_path / "pyproject.toml"
    skipped = tmp_path / "node_modules" / "junk" / "pyproject.toml"
    generated = tmp_path / ".playwright-mcp" / "page.yml"
    skipped.parent.mkdir(parents=True)
    generated.parent.mkdir()
    _ = kept.write_text('[project]\nname = "app"\nversion = "0.1.0"\n', encoding="utf-8")
    _ = skipped.write_text('deps = ["sarj-python-lint==0.1.0"]\n', encoding="utf-8")
    _ = generated.write_text('entry: "@sarj/no-implicit-attribute-access"\n', encoding="utf-8")
    monkeypatch.setenv("GIT_DIR", "/wrong/repository/.git")
    monkeypatch.setenv("GIT_WORK_TREE", "/wrong/repository")
    monkeypatch.setenv("GIT_PREFIX", "nested/")
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "core.bare")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "true")

    def git_files(*_args: object, **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        environment = kwargs["env"]
        assert isinstance(environment, dict)
        assert "GIT_DIR" not in environment
        assert "GIT_WORK_TREE" not in environment
        assert "GIT_PREFIX" not in environment
        assert "GIT_CONFIG_COUNT" not in environment
        assert "GIT_CONFIG_KEY_0" not in environment
        assert "GIT_CONFIG_VALUE_0" not in environment
        return subprocess.CompletedProcess(
            args=(),
            returncode=0,
            stdout=b"pyproject.toml\0node_modules/junk/pyproject.toml\0.playwright-mcp/page.yml\0",
            stderr=b"",
        )

    monkeypatch.setattr(doctor.subprocess, "run", git_files)  # pyright: ignore[reportPrivateLocalImportUsage]

    findings = doctor.diagnose(tmp_path)

    assert not [finding for finding in findings if "node_modules" in finding.where]
    assert not [finding for finding in findings if ".playwright-mcp" in finding.where]


def test_doctor_warns_when_no_manifest_exists(tmp_path: Path) -> None:
    _ = _python_repo(tmp_path)
    proc = _cli("--root", str(tmp_path), "doctor")
    assert proc.returncode == 1, "an unadopted repo requires an actionable init"
    assert "run `sarj-standards setup`" in proc.stdout
    assert "fix: run `sarj-standards setup`" in proc.stdout
    assert "fix: run `sarj-standards update`" not in proc.stdout


def test_doctor_reports_manifest_version_drift(tmp_path: Path) -> None:
    _ = _python_repo(tmp_path)
    _ = (tmp_path / manifest.MANIFEST_NAME).write_text(
        manifest.Manifest(version="0.0.1", configs=("ruff",), python_dest=".", typescript_dest=".").render()
    )
    proc = _cli("--root", str(tmp_path), "doctor")
    assert proc.returncode == 1
    assert __version__ in proc.stdout


def test_doctor_json_has_a_stable_schema_and_actionable_ids(tmp_path: Path) -> None:
    _ = _python_repo(tmp_path)

    proc = _cli("--root", str(tmp_path), "doctor", "--format", "json")

    assert proc.returncode == 1
    payload: dict[str, object] = json.loads(proc.stdout)  # pyright: ignore[reportAny]
    assert payload["schema"] == 1
    assert manifest.as_table(payload["summary"]) == {
        "checked": 1,
        "drifted": 0,
        "warnings": 1,
        "invalid": 0,
    }
    findings = manifest.list_field(payload, "findings")
    first = manifest.as_table(findings[0])
    assert first["id"] == "doctor.manifest.absent"
    assert first["remediation"] == "run `sarj-standards setup`"


def test_doctor_reports_a_malformed_manifest_without_a_traceback(tmp_path: Path) -> None:
    _ = (tmp_path / manifest.MANIFEST_NAME).write_text("configs = 3\n", encoding="utf-8")

    proc = _cli("--root", str(tmp_path), "doctor")

    assert proc.returncode == 2
    assert "doctor.manifest.invalid" in proc.stdout
    assert "Traceback" not in proc.stderr


def test_doctor_rejects_manifest_destinations_that_escape_the_repo(tmp_path: Path) -> None:
    adopted = manifest.Manifest(
        version=manifest.adopted_version(),
        configs=("ruff",),
        python_dest="..",
        typescript_dest=".",
    )
    _ = (tmp_path / manifest.MANIFEST_NAME).write_text(adopted.render(), encoding="utf-8")

    proc = _cli("--root", str(tmp_path), "doctor")

    assert proc.returncode == 2
    assert "doctor.manifest.destination" in proc.stdout
    assert "escapes the repository root" in proc.stdout


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("sarj-python-lint==0.25.0", {"sarj-python-lint": "0.25.0"}),
        ('"sarj-standards>=0.9.0"', {"sarj-standards": "0.9.0"}),
        ("uvx --from sarj-sql-lint==1.2.3 x", {"sarj-sql-lint": "1.2.3"}),
        ("sarj-iac-lint ~= 0.3.0", {"sarj-iac-lint": "0.3.0"}),
        ("nothing here", {}),
    ],
)
def test_pin_pattern_reads_every_shape_a_pin_takes(text: str, expected: dict[str, str]) -> None:
    assert doctor.parse_pins(text) == expected


def test_rev_pattern_reads_quoted_and_bare_tags() -> None:
    assert doctor.parse_revs('rev: python-v0.19.0\nrev: "standards-v0.10.0"\n') == [
        "python-v0.19.0",
        "standards-v0.10.0",
    ]


@pytest.mark.parametrize(
    "rev",
    ["9d073e83b24cd5af788a61996cd9238d85d927d4", "9d073e8", '"9d073e83b24cd5af788a61996cd9238d85d927d4"'],
)
def test_rev_pattern_reads_a_commit_pin(rev: str) -> None:
    assert doctor.parse_revs(f"rev: {rev}\n") == [rev.strip('"')]


def test_rev_pattern_is_not_fooled_by_a_version_tag() -> None:
    """`v6.0.0` is a tag from some other repo, not a commit; reading it as one would cry wolf."""
    assert doctor.parse_revs("rev: v6.0.0\n") == []


#: Doctor output is illustrative and excluded from documented-pin checks.
_DOCTOR_OUTPUT_LINE = re.compile(r"^(?:ok|warn|drift)\s", re.MULTILINE)


def _documented_pins(text: str) -> dict[str, str]:
    instructions = "\n".join(line for line in text.splitlines() if not _DOCTOR_OUTPUT_LINE.match(line))
    pins = doctor.parse_pins(instructions)
    if plugin := re.search(r"@sarj/eslint-plugin@(?P<version>\d+\.\d+\.\d+)", instructions):
        pins["@sarj/eslint-plugin"] = plugin.group("version")
    return pins


@pytest.mark.parametrize(
    "readme",
    [REPO_ROOT / "README.md", REPO_ROOT / "packages" / "standards" / "README.md"],
)
def test_readme_never_advertises_a_version_that_is_not_shipping(readme: Path) -> None:
    """The class of bug this kills, not one instance of it."""
    if not readme.is_file():
        pytest.skip(f"{readme} not present")
    current = {
        **manifest.installed_versions(),
        "@sarj/eslint-plugin": manifest.eslint_peers()["@sarj/eslint-plugin"],
    }
    stale = {
        name: pin
        for name, pin in _documented_pins(readme.read_text(encoding="utf-8")).items()
        if name in current and pin != current[name]
    }
    assert stale == {}, f"{readme.name} documents versions that are no longer shipping: {stale}"


def test_peers_json_documents_why_each_ceiling_exists() -> None:
    parsed: object = json.loads(ESLINT_PEERS.read_text(encoding="utf-8"))  # pyright: ignore[reportAny] — untyped stdlib boundary
    data = manifest.as_table(parsed)
    peers = manifest.table_field(data, "peers")
    ceilings = manifest.table_field(data, "ceilings")
    assert ceilings, "a pin below latest is a claim; it has to carry its evidence"
    for name, reason in ceilings.items():
        assert name in peers
        assert isinstance(reason, str)
        assert len(reason) > 40, f"{name}'s ceiling needs a real explanation"


def test_the_manifest_filename_is_a_stable_public_contract() -> None:
    assert manifest.MANIFEST_NAME == ".sarj-standards.toml"


def test_release_version_detection_does_not_short_circuit_git_diff() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "| grep -q" not in workflow  # sarj-noqa: SARJ402 -- workflow text is the release-policy contract


def test_doctor_treats_a_repository_that_was_never_setup_as_drift(tmp_path: Path) -> None:
    proc = _cli("--root", str(tmp_path), "doctor")
    assert proc.returncode == 1, proc.stdout
    assert "doctor.manifest.absent" in proc.stdout


def test_doctor_reports_drift_after_a_synced_config_is_deleted(tmp_path: Path) -> None:
    _ = _python_repo(tmp_path)
    assert _cli("--root", str(tmp_path), "setup", "--no-install").returncode == 0
    (tmp_path / ".ruff-strict.toml").unlink()

    proc = _cli("--root", str(tmp_path), "doctor")
    assert proc.returncode == 1, proc.stdout
    assert ".ruff-strict.toml" in proc.stdout


def test_doctor_rejects_an_eslint_import_whose_strict_target_is_missing(tmp_path: Path) -> None:
    _typescript_repo(tmp_path)
    setup = _cli("--root", str(tmp_path), "setup", "--no-install")
    assert setup.returncode == 0, setup.stderr
    (tmp_path / "eslint.strict.mjs").unlink()

    proc = _cli("--root", str(tmp_path), "doctor")

    assert proc.returncode == 1
    assert "doctor.config.missing" in proc.stdout
    assert "doctor.eslint.wiring" in proc.stdout
    assert "does not reference eslint.strict.mjs" in proc.stdout


def test_init_refuses_to_replace_unadopted_configs_without_force(tmp_path: Path) -> None:
    _python_repo(tmp_path)
    strict = tmp_path / ".ruff-strict.toml"
    strict.write_text("stale\n", encoding="utf-8")

    proc = _cli("--root", str(tmp_path), "setup", "--no-install")

    assert proc.returncode == 2
    assert "refusing to overwrite pre-existing lint configuration" in proc.stderr
    assert strict.read_text(encoding="utf-8") == "stale\n"
    assert not (tmp_path / manifest.MANIFEST_NAME).exists()


def test_init_force_replaces_reviewed_unadopted_config(tmp_path: Path) -> None:
    _python_repo(tmp_path)
    strict = tmp_path / ".ruff-strict.toml"
    strict.write_text("stale\n", encoding="utf-8")

    proc = _cli("--root", str(tmp_path), "setup", "--force", "--no-install")

    assert proc.returncode == 0, proc.stderr
    assert strict.read_text(encoding="utf-8") != "stale\n"
    assert (tmp_path / manifest.MANIFEST_NAME).is_file()


#: Hand-edited fixtures for files owned by `init`.
_SCAFFOLDED_FILES = {
    manifest.MANIFEST_NAME: (
        f'# hand-edited\nschema = 3\nbundle = "{manifest.adopted_version()}"\nprofile = "standard"\n'
        'rule_profile = "all"\n\n'
        '[capabilities]\ndisable = []\n\n[dest]\npython = "."\ntypescript = "."\n\n'
        '[hooks]\nmanager = "pre-commit"\n'
    ),
    "pyrightconfig.json": '{ "typeCheckingMode": "standard" }\n',
    "eslint.config.mjs": "export default [];  // hand-rolled\n",
}


def _repo_with_hand_edited_files(root: Path) -> Path:
    _ = _python_repo(root)
    _ = _typescript_repo(root)
    for name, body in _SCAFFOLDED_FILES.items():
        _ = (root / name).write_text(body)
    return root


def test_init_preserves_an_existing_manifest_without_force(tmp_path: Path) -> None:
    _ = _repo_with_hand_edited_files(tmp_path)
    proc = _cli("--root", str(tmp_path), "setup", "--no-install")
    assert proc.returncode == 0, proc.stderr
    path = tmp_path / manifest.MANIFEST_NAME
    assert path.read_text() == _SCAFFOLDED_FILES[manifest.MANIFEST_NAME]
    assert f"skip:  {path}" in proc.stdout


def test_init_safely_wires_existing_python_and_typescript_configs(tmp_path: Path) -> None:
    _ = _repo_with_hand_edited_files(tmp_path)

    proc = _cli("--root", str(tmp_path), "setup", "--no-install")

    assert proc.returncode == 0, proc.stderr
    pyright: dict[str, object] = json.loads(  # pyright: ignore[reportAny]
        (tmp_path / "pyrightconfig.json").read_text()
    )
    assert pyright == {
        "typeCheckingMode": "standard",
        "extends": ".pyright-strict.json",
        "pythonVersion": "3.14",
    }
    eslint = (tmp_path / "eslint.config.mjs").read_text()
    assert 'import strict from "./eslint.strict.mjs"' in eslint
    assert "...strict" in eslint
    assert "// hand-rolled" in eslint


def test_init_wires_the_existing_eslint_js_entrypoint_without_creating_a_shadow(tmp_path: Path) -> None:
    _typescript_repo(tmp_path)
    entrypoint = tmp_path / "eslint.config.js"
    entrypoint.write_text("export default [];\n", encoding="utf-8")

    proc = _cli("--root", str(tmp_path), "setup", "--no-install")

    assert proc.returncode == 0, proc.stderr
    assert "eslint.strict.mjs" in entrypoint.read_text(encoding="utf-8")
    assert not (tmp_path / "eslint.config.mjs").exists()


def test_setup_composes_a_define_config_entrypoint(tmp_path: Path) -> None:
    _typescript_repo(tmp_path)
    entrypoint = tmp_path / "eslint.config.js"
    entrypoint.write_text(
        'import { defineConfig } from "eslint/config";\nexport default defineConfig([{ rules: {} }]);\n',
        encoding="utf-8",
    )

    proc = _cli("--root", str(tmp_path), "setup", "--no-install")

    assert proc.returncode == 0, proc.stderr
    updated = entrypoint.read_text(encoding="utf-8")
    assert 'import strict from "./eslint.strict.mjs"' in updated
    assert "export default defineConfig([\n  ...strict," in updated


def test_init_accepts_an_eslint_entrypoint_that_reexports_a_wired_local_config(tmp_path: Path) -> None:
    _typescript_repo(tmp_path)
    packages = tmp_path / "packages"
    packages.mkdir()
    (tmp_path / "eslint.config.js").write_text(
        'export { default } from "./packages/eslint.config.base.js";\n',
        encoding="utf-8",
    )
    base = packages / "eslint.config.base.js"
    base.write_text('import strict from "../eslint.strict.mjs";\nexport default [...strict];\n', encoding="utf-8")

    proc = _cli("--root", str(tmp_path), "setup", "--no-install")

    assert proc.returncode == 0, proc.stderr
    assert "already imports eslint.strict.mjs" in proc.stdout
    assert 'export { default } from "./packages/eslint.config.base.js"' in (tmp_path / "eslint.config.js").read_text(
        encoding="utf-8"
    )


def test_setup_accepts_nested_eslint_configs_that_reexport_repository_policy(tmp_path: Path) -> None:
    _typescript_repo(tmp_path)
    (tmp_path / "eslint.config.mjs").write_text(
        'import strict from "./eslint.strict.mjs";\nexport default [...strict];\n', encoding="utf-8"
    )
    nested = tmp_path / "apps" / "web"
    nested.mkdir(parents=True)
    (nested / "eslint.config.mjs").write_text('export { default } from "../../eslint.config.mjs";\n', encoding="utf-8")

    proc = _cli("--root", str(tmp_path), "setup", "--no-install")

    assert proc.returncode == 0, proc.stderr
    assert (nested / "eslint.config.mjs").read_text(encoding="utf-8") == (
        'export { default } from "../../eslint.config.mjs";\n'
    )


def test_setup_wires_a_conventional_nested_named_eslint_export(tmp_path: Path) -> None:
    _typescript_repo(tmp_path)
    (tmp_path / "eslint.config.mjs").write_text(
        'import strict from "./eslint.strict.mjs";\nexport default [...strict];\n', encoding="utf-8"
    )
    nested = tmp_path / "apps" / "legacy"
    nested.mkdir(parents=True)
    config = nested / "eslint.config.mjs"
    config.write_text("const eslintConfig = [];\nexport default eslintConfig;\n", encoding="utf-8")

    proc = _cli("--root", str(tmp_path), "setup", "--no-install")

    assert proc.returncode == 0, proc.stderr
    updated = config.read_text(encoding="utf-8")
    assert 'import sarjStrict from "../../eslint.strict.mjs"' in updated
    assert "export default [...sarjStrict, ...eslintConfig];" in updated


def test_setup_does_not_spread_a_nested_object_default_export(tmp_path: Path) -> None:
    _typescript_repo(tmp_path)
    nested = tmp_path / "apps" / "legacy"
    nested.mkdir(parents=True)
    config = nested / "eslint.config.mjs"
    original = "const eslintConfig = { rules: {} };\nexport default eslintConfig;\n"
    config.write_text(original, encoding="utf-8")

    proc = _cli("--root", str(tmp_path), "setup", "--no-install")

    assert proc.returncode == 2
    assert "cannot be merged safely" in proc.stderr
    assert config.read_text(encoding="utf-8") == original
    assert not (tmp_path / "eslint.strict.mjs").exists()


def test_setup_ignores_nested_eslint_when_the_capability_is_not_selected(tmp_path: Path) -> None:
    _typescript_repo(tmp_path)
    nested = tmp_path / "apps" / "legacy"
    nested.mkdir(parents=True)
    config = nested / "eslint.config.mjs"
    original = "export default { rules: {} };\n"
    config.write_text(original, encoding="utf-8")

    proc = _cli("--root", str(tmp_path), "setup", "--config", "markdownlint", "--no-install")

    assert proc.returncode == 0, proc.stderr
    assert config.read_text(encoding="utf-8") == original
    assert not (tmp_path / "eslint.strict.mjs").exists()


def test_init_rejects_ambiguous_eslint_entrypoints_without_changes(tmp_path: Path) -> None:
    _typescript_repo(tmp_path)
    (tmp_path / "eslint.config.js").write_text("export default [];\n", encoding="utf-8")
    (tmp_path / "eslint.config.mjs").write_text("export default [];\n", encoding="utf-8")

    proc = _cli("--root", str(tmp_path), "setup", "--no-install")

    assert proc.returncode == 2
    assert "multiple active ESLint flat configs" in proc.stderr
    assert not (tmp_path / manifest.MANIFEST_NAME).exists()


def test_an_existing_precommit_config_is_extended_without_losing_hooks(tmp_path: Path) -> None:
    _ = _python_repo(tmp_path)
    existing = (
        "repos:\n"
        "  - repo: https://github.com/astral-sh/ruff-pre-commit\n"
        "    rev: v0.16.0\n"
        "    hooks:\n"
        "      - id: ruff\n"
    )
    config = tmp_path / ".pre-commit-config.yaml"
    _ = config.write_text(existing)

    proc = _cli("--root", str(tmp_path), "setup", "--no-install")
    assert proc.returncode == 0, proc.stderr
    updated = config.read_text()
    assert "id: ruff" in updated
    assert "id: sarj-standards-check" in updated
    assert "check --staged" in updated


def test_init_extends_the_existing_precommit_yml_spelling(tmp_path: Path) -> None:
    _ = _python_repo(tmp_path)
    config = tmp_path / ".pre-commit-config.yml"
    config.write_text("repos:\n", encoding="utf-8")

    proc = _cli("--root", str(tmp_path), "setup", "--no-install")

    assert proc.returncode == 0, proc.stderr
    assert "check --staged" in config.read_text(encoding="utf-8")
    assert not (tmp_path / ".pre-commit-config.yaml").exists()


def test_init_rejects_ambiguous_precommit_config_spellings_without_changes(tmp_path: Path) -> None:
    _ = _python_repo(tmp_path)
    first = tmp_path / ".pre-commit-config.yaml"
    second = tmp_path / ".pre-commit-config.yml"
    first.write_text("repos:\n", encoding="utf-8")
    second.write_text("repos:\n", encoding="utf-8")

    proc = _cli("--root", str(tmp_path), "setup", "--no-install")

    assert proc.returncode == 2
    assert "multiple pre-commit configurations" in proc.stderr
    assert first.read_text(encoding="utf-8") == "repos:\n"
    assert second.read_text(encoding="utf-8") == "repos:\n"


def test_init_preserves_an_existing_baselined_sarj_hook_without_adding_a_bypass(tmp_path: Path) -> None:
    _python_repo(tmp_path)
    config = tmp_path / ".pre-commit-config.yaml"
    config.write_text(
        "repos:\n"
        "  - repo: local\n"
        "    hooks:\n"
        "      - id: sarj-standards\n"
        "        entry: python/check_sarj_standards.py --baseline python/baseline.json\n",
        encoding="utf-8",
    )

    proc = _cli("--root", str(tmp_path), "setup", "--no-install")

    assert proc.returncode == 0, proc.stderr
    updated = config.read_text(encoding="utf-8")
    assert "--baseline python/baseline.json" in updated
    assert "id: sarj-standards-check" not in updated


def test_a_repo_with_its_own_ruff_table_is_wired_without_losing_settings(tmp_path: Path) -> None:
    _ = _python_repo(tmp_path)
    pyproject = tmp_path / "pyproject.toml"
    _ = pyproject.write_text(
        '[project]\nname = "app"\nversion = "0.1.0"\nrequires-python = ">=3.14"\n\n[tool.ruff]\nline-length = 100\n'
    )

    proc = _cli("--root", str(tmp_path), "setup", "--no-install")
    assert proc.returncode == 0, proc.stderr
    text = pyproject.read_text()
    assert text.count("[tool.ruff]") == 1
    assert tomllib.loads(text)["tool"]["ruff"]["line-length"] == 100
    assert tomllib.loads(text)["tool"]["ruff"]["extend"] == ".ruff-strict.toml"


def test_init_fails_closed_when_ruff_already_extends_another_config(tmp_path: Path) -> None:
    _ = _python_repo(tmp_path)
    pyproject = tmp_path / "pyproject.toml"
    original = (
        '[project]\nname = "app"\nversion = "0.1.0"\nrequires-python = ">=3.14"\n\n[tool.ruff]\nextend = "team.toml"\n'
    )
    pyproject.write_text(original, encoding="utf-8")

    proc = _cli("--root", str(tmp_path), "setup", "--no-install")

    assert proc.returncode == 2
    assert "already extends" in proc.stderr
    assert pyproject.read_text(encoding="utf-8") == original


def test_init_makes_existing_ruff_policy_additive_and_immediately_doctor_clean(tmp_path: Path) -> None:
    _ = _python_repo(tmp_path)
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[project]\nname = "app"\nversion = "0.1.0"\nrequires-python = ">=3.14"\n\n'
        "[tool.ruff]\nline-length = 88\n\n"
        "[tool.ruff.lint]\n"
        'select = [\n    "ALL",  # keep this comment\n]\n'
        'ignore = ["D"]\n\n'
        '[tool.ruff.lint.isort]\nknown-first-party = ["app"]\n',
        encoding="utf-8",
    )

    proc = _cli("--root", str(tmp_path), "setup", "--no-install")

    assert proc.returncode == 0, proc.stderr
    text = pyproject.read_text(encoding="utf-8")
    parsed = tomllib.loads(text)
    assert parsed["tool"]["ruff"]["lint"]["extend-select"] == ["ALL"]
    assert parsed["tool"]["ruff"]["lint"]["extend-ignore"] == ["D"]
    assert "# keep this comment" in text
    assert "\n\n[tool.ruff]\n" in text
    assert not [finding for finding in doctor.diagnose(tmp_path) if finding.level is doctor.Level.DRIFT]


def test_init_rejects_a_symlinked_mutation_target(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside.toml"
    outside.write_text('[project]\nname = "outside"\n', encoding="utf-8")
    (tmp_path / "pyproject.toml").symlink_to(outside)

    proc = _cli("--root", str(tmp_path), "setup", "--no-install")

    assert proc.returncode == 2
    assert "symlink mutation target" in proc.stderr
    assert outside.read_text(encoding="utf-8") == '[project]\nname = "outside"\n'
    assert not (tmp_path / manifest.MANIFEST_NAME).exists()


def test_init_rejects_a_symlinked_parent_of_a_mutation_target(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    (real / "pyproject.toml").write_text('[project]\nname = "app"\nversion = "0.1.0"\n', encoding="utf-8")
    (tmp_path / "python").symlink_to(real, target_is_directory=True)

    proc = _cli("--root", str(tmp_path), "setup", "--python-dest", "python", "--no-install")

    assert proc.returncode == 2
    assert "traverses a symlink or junction" in proc.stderr
    assert not (real / ".ruff-strict.toml").exists()


def test_failed_typescript_install_cleans_new_node_modules_and_normalizes_status(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _typescript_repo(tmp_path)
    plan = service.plan_init(tmp_path, configs=("eslint",), hook_manager="none", force=True)

    def failed_install(_commands: object) -> int:
        partial = tmp_path / "node_modules" / "partial-install"
        partial.parent.mkdir()
        partial.write_text("partial\n", encoding="utf-8")
        return 1

    monkeypatch.setattr(service.lifecycle, "execute", failed_install)

    result = service.apply_init(plan)

    assert result.status == 2
    assert result.failure is service.InitFailure.INSTALL
    assert result.error == "dependency or hook installer exited with status 1"
    assert not (tmp_path / "node_modules").exists()
    assert not (tmp_path / manifest.MANIFEST_NAME).exists()


def test_failed_install_preserves_preexisting_node_modules(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _typescript_repo(tmp_path)
    existing = tmp_path / "node_modules" / "keep.txt"
    existing.parent.mkdir()
    existing.write_text("keep\n", encoding="utf-8")
    plan = service.plan_init(tmp_path, configs=("eslint",), hook_manager="none", force=True)

    def fail_install(_commands: Iterable[lifecycle.Command]) -> int:
        return 1

    monkeypatch.setattr(service.lifecycle, "execute", fail_install)

    result = service.apply_init(plan)

    assert result.status == 2
    assert existing.read_text(encoding="utf-8") == "keep\n"


def test_init_does_not_accept_comment_only_ruff_wiring(tmp_path: Path) -> None:
    _python_repo(tmp_path)
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[project]\nname = "app"\nversion = "0.1.0"\n# extend = ".ruff-strict.toml"\n',
        encoding="utf-8",
    )

    proc = _cli("--root", str(tmp_path), "setup", "--no-install")

    assert proc.returncode == 0, proc.stderr
    assert tomllib.loads(pyproject.read_text(encoding="utf-8"))["tool"]["ruff"]["extend"] == ".ruff-strict.toml"


def test_init_replaces_a_partially_adopted_hook(tmp_path: Path) -> None:
    _python_repo(tmp_path)
    config = tmp_path / ".pre-commit-config.yaml"
    config.write_text(
        "repos:\n  - repo: local\n    hooks:\n      - id: sarj-standards-drift\n        entry: old doctor\n",
        encoding="utf-8",
    )

    proc = _cli("--root", str(tmp_path), "setup", "--no-install")

    assert proc.returncode == 0, proc.stderr
    updated = config.read_text(encoding="utf-8")
    assert "id: sarj-standards-drift" not in updated
    assert updated.count("id: sarj-standards-check") == 1
    assert "check --staged" in updated
