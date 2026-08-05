"""Tests for the adoption path: `init`, `doctor`, `peers`, and the manifest."""

from __future__ import annotations

from importlib.metadata import version
import json
from pathlib import Path
import re
import subprocess
import sys
import tomllib
from typing import TYPE_CHECKING

import pytest

from sarj_lint_configs import (
    ESLINT_PEERS,
    ESLINT_STRICT,
    RUFF_STRICT,
    __version__,
    doctor,
    lifecycle,
    manifest,
    scaffold,
)
from sarj_lint_configs import __main__ as cli
from sarj_lint_configs.__main__ import main


if TYPE_CHECKING:
    from collections.abc import Iterable


REPO_ROOT = Path(__file__).resolve().parents[3]


def _cli(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    command = list(args)
    if command and command[0] == "init" and "--no-install" not in command:
        command.append("--no-install")
    return subprocess.run(
        [sys.executable, "-m", "sarj_lint_configs", *command],
        capture_output=True,
        text=True,
        check=False,
        cwd=cwd,
    )


def _python_repo(root: Path) -> Path:
    (root / "src").mkdir(parents=True, exist_ok=True)
    _ = (root / "pyproject.toml").write_text('[project]\nname = "app"\nversion = "0.1.0"\nrequires-python = ">=3.14"\n')
    return root


def _typescript_repo(root: Path) -> Path:
    _ = (root / "package.json").write_text('{"name": "web", "private": true}\n')
    return root


def test_verify_leaves_maintainer_repository_policy_to_repo_check(
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

    assert cli.main(["verify", "--dest", str(tmp_path)]) == 0


def test_every_eslint_import_has_a_pinned_peer() -> None:
    """The config's imports were a hidden contract; now they are a checked one."""
    imported = set(re.findall(r'^import \w+ from "([^"]+)";', ESLINT_STRICT.read_text(), re.MULTILINE))
    pinned = set(manifest.eslint_peers())
    assert imported - pinned == set(), "eslint.strict.mjs imports a package with no pin in eslint.peers.json"


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
    proc = _cli("peers")
    assert proc.returncode == 0
    assert "npm install -D --save-exact" in proc.stdout
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
    written = manifest.Manifest(version="1.2.3", configs=("ruff", "pyright"), python_dest=".", typescript_dest="web")
    _ = (tmp_path / manifest.MANIFEST_NAME).write_text(written.render())
    assert manifest.load(tmp_path) == written


def test_old_manifest_defaults_to_standard_profile(tmp_path: Path) -> None:
    _ = (tmp_path / manifest.MANIFEST_NAME).write_text('version = "1.2.3"\nconfigs = ["ruff"]\n')
    adopted = manifest.load(tmp_path)
    assert adopted is not None
    assert adopted.profile == "standard"
    assert adopted.verify_paths == (".",)


def test_manifest_loads_contained_custom_verification_paths(tmp_path: Path) -> None:
    _ = (tmp_path / manifest.MANIFEST_NAME).write_text(
        'version = "1.2.3"\nconfigs = []\n[verify]\npaths = ["src", "README.md"]\n'
    )

    adopted = manifest.load(tmp_path)

    assert adopted is not None
    assert adopted.verify_paths == ("src", "README.md")


def test_manifest_rejects_custom_verification_path_escape(tmp_path: Path) -> None:
    _ = (tmp_path / manifest.MANIFEST_NAME).write_text(
        'version = "1.2.3"\nconfigs = []\n[verify]\npaths = ["../outside"]\n'
    )

    with pytest.raises(ValueError, match="escapes repository root"):
        _ = manifest.load(tmp_path)


def test_manifest_rejects_unknown_profile(tmp_path: Path) -> None:
    _ = (tmp_path / manifest.MANIFEST_NAME).write_text('version = "1.2.3"\nprofile = "library"\nconfigs = ["ruff"]\n')
    with pytest.raises(ValueError, match=r"profile.*standard, application"):
        _ = manifest.load(tmp_path)


def test_manifest_renders_as_valid_toml() -> None:
    rendered = manifest.Manifest(version="1.2.3", configs=("ruff",), python_dest=".", typescript_dest=".").render()
    parsed = tomllib.loads(rendered)
    assert parsed["version"] == "1.2.3"
    assert parsed["configs"] == ["ruff"]


def test_missing_manifest_is_not_an_error(tmp_path: Path) -> None:
    assert manifest.load(tmp_path) is None


def test_malformed_manifest_is_reported_not_ignored(tmp_path: Path) -> None:
    _ = (tmp_path / manifest.MANIFEST_NAME).write_text("configs = 3\n")
    with pytest.raises(TypeError, match="must set a string"):
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


def test_sync_respects_the_manifests_config_set(tmp_path: Path) -> None:
    _ = _python_repo(tmp_path)
    assert _cli("init", "--dest", str(tmp_path)).returncode == 0
    assert not (tmp_path / "eslint.strict.mjs").exists()

    proc = _cli("sync", "--check", "--dest", str(tmp_path))
    assert proc.returncode == 0, proc.stdout
    assert "checked 5 config(s); 0 drifted" in proc.stdout


def test_sync_check_fails_when_a_synced_config_is_edited(tmp_path: Path) -> None:
    """The vendoring failure, caught at the earliest possible moment."""
    _ = _python_repo(tmp_path)
    assert _cli("init", "--dest", str(tmp_path)).returncode == 0
    with (tmp_path / ".ruff-strict.toml").open("a") as handle:
        _ = handle.write("\n# local edit\n")

    proc = _cli("sync", "--check", "--dest", str(tmp_path))
    assert proc.returncode == 1
    assert "1 drifted" in proc.stdout


def test_sync_only_accepts_several_configs(tmp_path: Path) -> None:
    assert _cli("sync", "--only", "ruff", "pyright", "--dest", str(tmp_path)).returncode == 0
    assert (tmp_path / ".ruff-strict.toml").is_file()
    assert (tmp_path / ".pyright-strict.json").is_file()
    assert not (tmp_path / "eslint.strict.mjs").exists()


def test_init_writes_the_whole_python_wiring(tmp_path: Path) -> None:
    """One command replaces the README's read-then-hand-edit sequence."""
    _ = _python_repo(tmp_path)
    proc = _cli("init", "--dest", str(tmp_path))
    assert proc.returncode == 0, proc.stderr

    assert (tmp_path / ".ruff-strict.toml").is_file()
    assert (tmp_path / ".pyright-strict.json").is_file()
    assert (tmp_path / manifest.MANIFEST_NAME).is_file()
    assert (tmp_path / ".pre-commit-config.yaml").is_file()
    assert '"extends": ".pyright-strict.json"' in (tmp_path / "pyrightconfig.json").read_text()

    pyproject = tomllib.loads((tmp_path / "pyproject.toml").read_text())
    assert pyproject["tool"]["ruff"]["extend"] == ".ruff-strict.toml"


def test_init_application_profile_selects_application_artifacts(tmp_path: Path) -> None:
    _ = _python_repo(tmp_path)
    proc = _cli("init", "--profile", "application", "--dest", str(tmp_path))
    assert proc.returncode == 0, proc.stderr

    adopted = manifest.load(tmp_path)
    assert adopted is not None
    assert adopted.profile == "application"
    expected = cli.CONFIGS_DIR / "ruff.application.toml"
    assert (tmp_path / ".ruff-strict.toml").read_bytes() == expected.read_bytes()


def test_sync_uses_profile_recorded_in_manifest(tmp_path: Path) -> None:
    _ = _typescript_repo(tmp_path)
    assert _cli("init", "--profile", "application", "--dest", str(tmp_path)).returncode == 0
    expected = cli.CONFIGS_DIR / "eslint.application.mjs"
    assert (tmp_path / "eslint.strict.mjs").read_bytes() == expected.read_bytes()
    assert _cli("sync", "--check", "--dest", str(tmp_path)).returncode == 0


def test_application_ruff_config_rejects_preferred_stack_import(tmp_path: Path) -> None:
    pytest.importorskip("ruff", reason="ruff not installed in this env")
    _ = _python_repo(tmp_path)
    assert _cli("init", "--profile", "application", "--dest", str(tmp_path)).returncode == 0
    probe = tmp_path / "probe.py"
    _ = probe.write_text("import argparse\n")

    proc = subprocess.run(
        ["ruff", "check", "--no-cache", str(probe)],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        check=False,
    )

    assert proc.returncode == 1
    assert "banned-api: `argparse` is banned" in proc.stdout
    assert "LIB001" in proc.stdout


def test_init_installs_dependencies_by_default(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _ = _python_repo(tmp_path)
    commands: list[lifecycle.Command] = []

    def execute(planned: Iterable[lifecycle.Command]) -> int:
        commands.extend(planned)
        return 0

    monkeypatch.setattr(lifecycle, "execute", execute)

    assert main(["init", "--dest", str(tmp_path)]) == 0
    assert commands[0].argv == (
        "uv",
        "add",
        "--dev",
        f"sarj-lint-configs=={__version__}",
        "sarj-python-lint==0.46.0",
        "sarj-sql-lint==0.6.1",
        "sarj-iac-lint==0.5.0",
    )


def test_inspect_reports_detected_adoption(tmp_path: Path) -> None:
    _ = _python_repo(tmp_path)
    assert _cli("init", "--dest", str(tmp_path)).returncode == 0

    parsed: object = json.loads(lifecycle.inspection_json(tmp_path))  # pyright: ignore[reportAny] -- untyped stdlib boundary
    inspected = manifest.as_table(parsed)

    assert inspected["adopted_version"] == __version__
    assert inspected["profile"] == "standard"
    assert inspected["python_root"] == "."


def test_init_writes_a_typescript_entrypoint_with_an_override_seam(tmp_path: Path) -> None:
    """The generated entrypoint has to teach "extend, do not fork"."""
    _ = _typescript_repo(tmp_path)
    proc = _cli("init", "--dest", str(tmp_path))
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
        pytest.param("npm install -D --save-exact", id="install-command"),
        pytest.param("eslint-plugin-unicorn@", id="pinned-peer"),
        pytest.param("overrides", id="npm-overrides-block"),
        pytest.param("eslint-plugin-react", id="the-package-the-overrides-unblock"),
    ],
)
def test_init_gives_a_typescript_repo_everything_npm_needs(tmp_path: Path, expected: str) -> None:
    """Anything missing here sends the reader back to trial-and-error installs."""
    _ = _typescript_repo(tmp_path)
    proc = _cli("init", "--dest", str(tmp_path))
    assert expected in proc.stdout


def test_init_prints_a_ci_snippet_with_the_unified_gate(tmp_path: Path) -> None:
    _ = _python_repo(tmp_path)
    proc = _cli("init", "--dest", str(tmp_path))
    assert "sarj-standards verify" in proc.stdout


def test_ci_snippet_for_a_typescript_repo_does_not_require_a_python_project(
    tmp_path: Path,
) -> None:
    _ = _typescript_repo(tmp_path)
    proc = _cli("init", "--dest", str(tmp_path))
    assert "uv run --frozen" not in proc.stdout
    assert "uvx --from sarj-lint-configs==" in proc.stdout


def test_nested_python_project_is_used_by_generated_hooks_and_ci(tmp_path: Path) -> None:
    python = tmp_path / "python"
    python.mkdir()
    _python_repo(python)

    plan = scaffold.build_plan(tmp_path, force=False)
    hook = next(contents for path, contents in plan.writes if path.name == ".pre-commit-config.yaml")
    snippet = scaffold.ci_snippet(plan, version=manifest.adopted_version())

    assert "uv run --project python --frozen sarj-standards" in hook
    assert "uv run --project python --frozen sarj-standards" in snippet


def test_init_is_idempotent(tmp_path: Path) -> None:
    _ = _python_repo(tmp_path)
    assert _cli("init", "--dest", str(tmp_path)).returncode == 0
    before = (tmp_path / "pyproject.toml").read_text()

    second = _cli("init", "--dest", str(tmp_path))
    assert second.returncode == 0
    assert (tmp_path / "pyproject.toml").read_text() == before
    assert "already extends" in second.stdout


def test_init_dry_run_writes_nothing(tmp_path: Path) -> None:
    _ = _python_repo(tmp_path)
    proc = _cli("init", "--dest", str(tmp_path), "--dry-run")
    assert proc.returncode == 0
    assert "would write" in proc.stdout
    assert not (tmp_path / ".ruff-strict.toml").exists()
    assert not (tmp_path / manifest.MANIFEST_NAME).exists()


def test_init_on_an_empty_directory_says_so(tmp_path: Path) -> None:
    proc = _cli("init", "--dest", str(tmp_path))
    assert proc.returncode == 1
    assert "no pyproject.toml and no package.json" in proc.stdout


def test_generated_precommit_block_carries_no_rev(tmp_path: Path) -> None:
    _ = _python_repo(tmp_path)
    assert _cli("init", "--dest", str(tmp_path)).returncode == 0
    generated = (tmp_path / ".pre-commit-config.yaml").read_text()
    assert "rev:" not in generated
    assert "repo: local" in generated
    assert "sarj-standards doctor" in generated


def test_init_writes_the_npm_overrides_into_package_json(tmp_path: Path) -> None:
    """`init` has to WRITE the overrides, not just talk about them."""
    _ = _typescript_repo(tmp_path)
    proc = _cli("init", "--dest", str(tmp_path))
    assert proc.returncode == 0, proc.stderr

    parsed: object = json.loads((tmp_path / "package.json").read_text(encoding="utf-8"))  # pyright: ignore[reportAny] — untyped stdlib boundary
    written = manifest.as_table(parsed)
    assert manifest.table_field(written, "overrides") == manifest.eslint_overrides()
    assert written["name"] == "web", "the consumer's own keys must survive the merge"


def test_init_does_not_clobber_a_consumers_existing_overrides(tmp_path: Path) -> None:
    """package.json is the consumer's file; only the ESLint entries are ours."""
    _ = (tmp_path / "package.json").write_text(
        json.dumps({"name": "web", "overrides": {"left-pad": "1.3.0"}}, indent=2) + "\n"
    )
    assert _cli("init", "--dest", str(tmp_path)).returncode == 0

    parsed: object = json.loads((tmp_path / "package.json").read_text(encoding="utf-8"))  # pyright: ignore[reportAny] — untyped stdlib boundary
    overrides = manifest.table_field(manifest.as_table(parsed), "overrides")
    assert overrides["left-pad"] == "1.3.0"
    assert "eslint-plugin-react" in overrides


def test_init_leaves_a_package_json_that_already_has_the_overrides_alone(
    tmp_path: Path,
) -> None:
    _ = _typescript_repo(tmp_path)
    assert _cli("init", "--dest", str(tmp_path)).returncode == 0
    before = (tmp_path / "package.json").read_text(encoding="utf-8")

    second = _cli("init", "--dest", str(tmp_path))
    assert second.returncode == 0
    assert (tmp_path / "package.json").read_text(encoding="utf-8") == before
    assert "already carries the npm peer overrides" in second.stdout


def test_init_wires_the_subproject_that_actually_installs_eslint(tmp_path: Path) -> None:
    """The repo root is not the project root, and writing there reaches nobody."""
    (tmp_path / "web").mkdir()
    _ = (tmp_path / "web" / "package.json").write_text('{"name": "web"}\n')
    _ = (tmp_path / "web" / "package-lock.json").write_text("{}\n")
    proc = _cli("init", "--dest", str(tmp_path))
    assert proc.returncode == 0, proc.stderr

    assert (tmp_path / "web" / "eslint.config.mjs").is_file()
    assert (tmp_path / "web" / "eslint.strict.mjs").is_file()
    assert not (tmp_path / "eslint.config.mjs").exists()

    parsed: object = json.loads((tmp_path / "web" / "package.json").read_text(encoding="utf-8"))  # pyright: ignore[reportAny] — untyped stdlib boundary
    assert "eslint-plugin-react" in manifest.table_field(manifest.as_table(parsed), "overrides")


def test_sync_reads_the_subproject_destinations_back_out_of_the_manifest(
    tmp_path: Path,
) -> None:
    """CI runs bare `sync --check`; if it did not know the dests it saw permanent drift."""
    (tmp_path / "web").mkdir()
    _ = (tmp_path / "web" / "package.json").write_text('{"name": "web"}\n')
    _ = (tmp_path / "web" / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n")
    assert _cli("init", "--dest", str(tmp_path)).returncode == 0

    proc = _cli("sync", "--check", "--dest", str(tmp_path))
    assert proc.returncode == 0, proc.stdout
    assert str(tmp_path / "web" / "eslint.strict.mjs") in proc.stdout


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
    assert _cli("init", "--dest", str(tmp_path)).returncode == 0

    entries = _precommit_entries((tmp_path / ".pre-commit-config.yaml").read_text())
    assert len(entries) == 2, "the Python block declares a drift hook and a check hook"
    for entry, pass_filenames_false in entries:
        # Run the CLI the hook names, through the interpreter the tests already
        # use, so this exercises the generated command shape without needing a
        # network fetch or a uv-managed virtualenv inside tmp_path.
        subcommand = entry.split("sarj-standards", 1)[1].split()
        if not pass_filenames_false:
            subcommand.append("src/app.py")
        proc = _cli(*subcommand, cwd=tmp_path)
        assert proc.returncode == 0, f"{entry!r} failed: {proc.stdout}{proc.stderr}"


def test_generated_check_hook_keeps_warning_first_output_visible(tmp_path: Path) -> None:
    _ = _python_repo(tmp_path)

    assert _cli("init", "--dest", str(tmp_path), "--no-install").returncode == 0

    config = (tmp_path / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    check_block = config.split("id: sarj-standards-check", 1)[1]
    assert "verbose: true" in check_block


def test_init_adds_warning_visibility_to_an_existing_complete_check_hook(tmp_path: Path) -> None:
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

    assert _cli("init", "--dest", str(tmp_path), "--no-install").returncode == 0

    updated = config.read_text(encoding="utf-8")
    assert updated.count("verbose: true") == 1
    assert updated.index("verbose: true") > updated.index("id: sarj-standards-check")


def test_a_typescript_only_precommit_hook_does_not_invoke_uv_run(tmp_path: Path) -> None:
    _ = _typescript_repo(tmp_path)
    assert _cli("init", "--dest", str(tmp_path)).returncode == 0

    generated = (tmp_path / ".pre-commit-config.yaml").read_text()
    assert "uv run --frozen" not in generated
    assert f"uvx --from sarj-lint-configs=={__version__}" in generated
    # `check` runs the Python/SQL/IaC registries; a TypeScript repo has nothing
    # to feed them, and a hook that lints nothing is a hook that hides.
    assert "sarj-standards check" in generated


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

    proc = _cli("init", "--dest", str(tmp_path))

    assert proc.returncode == 2
    assert "multiple independent Python roots" in proc.stderr
    assert "--python-dest" in proc.stderr
    assert not (tmp_path / manifest.MANIFEST_NAME).exists()


def test_explicit_project_root_resolves_independent_root_ambiguity(tmp_path: Path) -> None:
    for name in ("api", "worker"):
        project = tmp_path / name
        project.mkdir()
        _python_repo(project)

    proc = _cli("init", "--dest", str(tmp_path), "--python-dest", "api")

    assert proc.returncode == 0, proc.stderr
    assert (tmp_path / "api" / ".ruff-strict.toml").is_file()
    assert not (tmp_path / "worker" / ".ruff-strict.toml").exists()


def test_detection_ignores_node_modules(tmp_path: Path) -> None:
    (tmp_path / "node_modules" / "left-pad").mkdir(parents=True)
    _ = (tmp_path / "node_modules" / "left-pad" / "package.json").write_text("{}\n")
    assert scaffold.detect(tmp_path).typescript is False


def test_doctor_is_clean_after_init(tmp_path: Path) -> None:
    _ = _python_repo(tmp_path)
    assert _cli("init", "--dest", str(tmp_path)).returncode == 0
    proc = _cli("doctor", "--dest", str(tmp_path))
    assert proc.returncode == 0, proc.stdout
    assert "0 drifted" in proc.stdout


def test_doctor_catches_a_stale_pyproject_pin(tmp_path: Path) -> None:
    """The measured case: consumers pin 0.25.0 while main ships 0.33.0."""
    _ = _python_repo(tmp_path)
    _ = (tmp_path / "requirements.txt").write_text("sarj-python-lint==0.25.0\n")
    proc = _cli("doctor", "--dest", str(tmp_path))
    assert proc.returncode == 1
    assert "sarj-python-lint==0.25.0" in proc.stdout


def test_doctor_catches_a_ci_pin_that_differs_from_the_pyproject_pin(tmp_path: Path) -> None:
    _ = _python_repo(tmp_path)
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    _ = (workflows / "ci.yml").write_text(
        "jobs:\n  lint:\n    steps:\n      - run: uvx --from sarj-python-lint==0.12.2 sarj-python-lint check .\n"
    )
    proc = _cli("doctor", "--dest", str(tmp_path))
    assert proc.returncode == 1
    assert "ci.yml" in proc.stdout
    assert "0.12.2" in proc.stdout


def test_doctor_catches_a_stale_package_script_pin(tmp_path: Path) -> None:
    _ = _typescript_repo(tmp_path)
    _ = (tmp_path / "package.json").write_text(
        '{"scripts":{"lint:sarj":"uvx --from sarj-lint-configs==0.1.0 sarj-standards check ."}}\n'
    )

    proc = _cli("doctor", "--dest", str(tmp_path))

    assert proc.returncode == 1
    assert "package.json: sarj-lint-configs==0.1.0" in proc.stdout


def test_doctor_catches_a_stale_precommit_rev(tmp_path: Path) -> None:
    _ = _python_repo(tmp_path)
    _ = (tmp_path / ".pre-commit-config.yaml").write_text(
        "repos:\n  - repo: https://github.com/sarj-ai/standards\n"
        "    rev: python-v0.19.0\n    hooks:\n      - id: sarj-no-comment-cruft\n"
    )
    proc = _cli("doctor", "--dest", str(tmp_path))
    assert proc.returncode == 1
    assert "python-v0.19.0" in proc.stdout


def test_doctor_catches_a_precommit_rev_pinned_to_a_raw_commit(tmp_path: Path) -> None:
    _ = _python_repo(tmp_path)
    _ = (tmp_path / ".pre-commit-config.yaml").write_text(
        "repos:\n  - repo: https://github.com/sarj-ai/standards\n"
        "    rev: 9d073e83b24cd5af788a61996cd9238d85d927d4\n"
        "    hooks:\n      - id: sarj-no-comment-cruft\n"
    )
    proc = _cli("doctor", "--dest", str(tmp_path))
    assert proc.returncode == 1
    assert "9d073e83b24cd5af788a61996cd9238d85d927d4" in proc.stdout
    assert "not a release" in proc.stdout


def test_doctor_catches_a_stale_eslint_plugin_pin(tmp_path: Path) -> None:
    _ = _typescript_repo(tmp_path)
    _ = (tmp_path / "package.json").write_text(
        json.dumps({"name": "web", "devDependencies": {"@sarj/eslint-plugin": "2.16.0"}})
    )
    proc = _cli("doctor", "--dest", str(tmp_path))
    assert proc.returncode == 1
    assert "2.16.0" in proc.stdout


@pytest.mark.parametrize(
    "operator",
    ["", "^", "~", "=", ">=", "==", "~=", "v"],
    ids=["bare", "caret", "tilde", "equals", "gte", "double-equals", "compatible", "v-prefix"],
)
def test_doctor_accepts_every_spelling_of_the_tested_floor(tmp_path: Path, operator: str) -> None:
    """A repo pinned to exactly the tested floor is not drifted, however it spells it."""
    floor = manifest.eslint_peers()["@sarj/eslint-plugin"]
    _ = _typescript_repo(tmp_path)
    _ = (tmp_path / "package.json").write_text(
        json.dumps({"name": "web", "devDependencies": {"@sarj/eslint-plugin": f"{operator}{floor}"}})
    )
    proc = _cli("doctor", "--dest", str(tmp_path))
    assert "matches the tested peer set" in proc.stdout, proc.stdout
    assert "tested against" not in proc.stdout, proc.stdout


def test_doctor_still_reports_a_range_that_is_not_the_floor(tmp_path: Path) -> None:
    """The operator is stripped ONCE, so a malformed pin is not laundered into a match."""
    floor = manifest.eslint_peers()["@sarj/eslint-plugin"]
    _ = _typescript_repo(tmp_path)
    _ = (tmp_path / "package.json").write_text(
        json.dumps({"name": "web", "devDependencies": {"@sarj/eslint-plugin": f"^~{floor}"}})
    )
    proc = _cli("doctor", "--dest", str(tmp_path))
    assert proc.returncode == 1
    assert "tested against" in proc.stdout, proc.stdout


@pytest.mark.parametrize("specifier", ["file:../plugin", "link:../plugin", "workspace:*"])
def test_doctor_ignores_a_local_eslint_plugin_checkout(tmp_path: Path, specifier: str) -> None:
    """A path specifier names a checkout, not a release, so it cannot be stale."""
    _ = (tmp_path / "package.json").write_text(
        json.dumps({"name": "web", "devDependencies": {"@sarj/eslint-plugin": specifier}})
    )
    proc = _cli("doctor", "--dest", str(tmp_path))
    assert "@sarj/eslint-plugin" not in proc.stdout


def test_doctor_skips_vendored_trees(tmp_path: Path) -> None:
    """A pin inside `node_modules` or `.venv` is not the repo's to fix."""
    _ = _python_repo(tmp_path)
    buried = tmp_path / "node_modules" / "junk"
    buried.mkdir(parents=True)
    _ = (buried / "pyproject.toml").write_text('deps = ["sarj-python-lint==0.1.0"]\n')
    proc = _cli("doctor", "--dest", str(tmp_path))
    assert "0.1.0" not in proc.stdout


def test_doctor_warns_when_no_manifest_exists(tmp_path: Path) -> None:
    _ = _python_repo(tmp_path)
    proc = _cli("doctor", "--dest", str(tmp_path))
    assert proc.returncode == 0, "an un-adopted repo is not yet drifted"
    assert "run `sarj-standards init`" in proc.stdout


def test_doctor_reports_manifest_version_drift(tmp_path: Path) -> None:
    _ = _python_repo(tmp_path)
    _ = (tmp_path / manifest.MANIFEST_NAME).write_text(
        manifest.Manifest(version="0.0.1", configs=("ruff",), python_dest=".", typescript_dest=".").render()
    )
    proc = _cli("doctor", "--dest", str(tmp_path))
    assert proc.returncode == 1
    assert __version__ in proc.stdout


def test_doctor_json_has_a_stable_schema_and_actionable_ids(tmp_path: Path) -> None:
    _ = _python_repo(tmp_path)

    proc = _cli("doctor", "--format", "json", "--dest", str(tmp_path))

    assert proc.returncode == 0
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
    assert first["remediation"] == "run `sarj-standards init`"


def test_doctor_reports_a_malformed_manifest_without_a_traceback(tmp_path: Path) -> None:
    _ = (tmp_path / manifest.MANIFEST_NAME).write_text("configs = 3\n", encoding="utf-8")

    proc = _cli("doctor", "--dest", str(tmp_path))

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

    proc = _cli("doctor", "--dest", str(tmp_path))

    assert proc.returncode == 1
    assert "doctor.manifest.destination" in proc.stdout
    assert "escapes the repository root" in proc.stdout


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("sarj-python-lint==0.25.0", {"sarj-python-lint": "0.25.0"}),
        ('"sarj-lint-configs>=0.9.0"', {"sarj-lint-configs": "0.9.0"}),
        ("uvx --from sarj-sql-lint==1.2.3 x", {"sarj-sql-lint": "1.2.3"}),
        ("sarj-iac-lint ~= 0.3.0", {"sarj-iac-lint": "0.3.0"}),
        ("nothing here", {}),
    ],
)
def test_pin_pattern_reads_every_shape_a_pin_takes(text: str, expected: dict[str, str]) -> None:
    assert doctor.parse_pins(text) == expected


def test_rev_pattern_reads_quoted_and_bare_tags() -> None:
    assert doctor.parse_revs('rev: python-v0.19.0\nrev: "lint-configs-v0.10.0"\n') == [
        "python-v0.19.0",
        "lint-configs-v0.10.0",
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
    [REPO_ROOT / "README.md", REPO_ROOT / "packages" / "lint-configs" / "README.md"],
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


def test_the_manifest_filename_is_the_one_adopted_repos_committed() -> None:
    """Every other reference to it is symbolic, so a rename is invisible to the suite."""
    assert manifest.MANIFEST_NAME == ".sarj-standards.toml"
    assert manifest.MANIFEST_NAME in (REPO_ROOT / "README.md").read_text(encoding="utf-8")


def test_the_expected_precommit_rev_names_a_tag_the_release_workflow_publishes() -> None:
    """The main-only release creates the `python-v` rev consumed by pre-commit."""
    expected = manifest.expected_precommit_rev()
    assert expected is not None
    assert expected == f"python-v{version('sarj-python-lint')}"

    workflow = (REPO_ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    prefix = expected.rsplit("-v", 1)[0]
    assert "branches: [main]" in workflow
    assert "tags:" not in workflow.partition("\npermissions:\n")[0]
    assert f"repo release create-tags {prefix} " in workflow, f"release.yml never creates a {prefix}-v tag"


def test_release_version_detection_does_not_short_circuit_git_diff() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "| grep -q" not in workflow


def test_sync_check_treats_a_config_that_was_never_synced_as_drift(tmp_path: Path) -> None:
    """A repo that never ran `sync` must fail `sync --check`, not pass it."""
    proc = _cli("sync", "--check", "--only", "ruff", "pyright", "--dest", str(tmp_path))
    assert proc.returncode == 1, proc.stdout
    assert "2 drifted" in proc.stdout
    assert "ok:" not in proc.stdout


def test_sync_check_reports_drift_after_a_synced_config_is_deleted(tmp_path: Path) -> None:
    _ = _python_repo(tmp_path)
    assert _cli("init", "--dest", str(tmp_path)).returncode == 0
    (tmp_path / ".ruff-strict.toml").unlink()

    proc = _cli("sync", "--check", "--dest", str(tmp_path))
    assert proc.returncode == 1, proc.stdout
    assert "1 drifted" in proc.stdout
    assert f"drift: {tmp_path / '.ruff-strict.toml'}" in proc.stdout


def test_init_replaces_stale_manifest_owned_configs_without_force(tmp_path: Path) -> None:
    _python_repo(tmp_path)
    strict = tmp_path / ".ruff-strict.toml"
    strict.write_text("stale\n", encoding="utf-8")

    proc = _cli("init", "--dest", str(tmp_path))

    assert proc.returncode == 0, proc.stderr
    assert strict.read_bytes() == RUFF_STRICT.read_bytes()


#: Hand-edited fixtures for files owned by `init`.
_SCAFFOLDED_FILES = {
    manifest.MANIFEST_NAME: '# hand-edited\nversion = "0.0.1"\nconfigs = ["ruff"]\n',
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
    proc = _cli("init", "--dest", str(tmp_path))
    assert proc.returncode == 0, proc.stderr
    path = tmp_path / manifest.MANIFEST_NAME
    assert path.read_text() == _SCAFFOLDED_FILES[manifest.MANIFEST_NAME]
    assert f"skip:  {path}" in proc.stdout


def test_init_safely_wires_existing_python_and_typescript_configs(tmp_path: Path) -> None:
    _ = _repo_with_hand_edited_files(tmp_path)

    proc = _cli("init", "--dest", str(tmp_path))

    assert proc.returncode == 0, proc.stderr
    pyright: dict[str, object] = json.loads(  # pyright: ignore[reportAny]
        (tmp_path / "pyrightconfig.json").read_text()
    )
    assert pyright == {"typeCheckingMode": "standard", "extends": ".pyright-strict.json"}
    eslint = (tmp_path / "eslint.config.mjs").read_text()
    assert 'import strict from "./eslint.strict.mjs"' in eslint
    assert "...strict" in eslint
    assert "// hand-rolled" in eslint


def test_init_wires_the_existing_eslint_js_entrypoint_without_creating_a_shadow(tmp_path: Path) -> None:
    _typescript_repo(tmp_path)
    entrypoint = tmp_path / "eslint.config.js"
    entrypoint.write_text("export default [];\n", encoding="utf-8")

    proc = _cli("init", "--dest", str(tmp_path))

    assert proc.returncode == 0, proc.stderr
    assert "eslint.strict.mjs" in entrypoint.read_text(encoding="utf-8")
    assert not (tmp_path / "eslint.config.mjs").exists()


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

    proc = _cli("init", "--dest", str(tmp_path))

    assert proc.returncode == 0, proc.stderr
    assert "already imports eslint.strict.mjs" in proc.stdout
    assert 'export { default } from "./packages/eslint.config.base.js"' in (tmp_path / "eslint.config.js").read_text(
        encoding="utf-8"
    )


def test_init_rejects_ambiguous_eslint_entrypoints_without_changes(tmp_path: Path) -> None:
    _typescript_repo(tmp_path)
    (tmp_path / "eslint.config.js").write_text("export default [];\n", encoding="utf-8")
    (tmp_path / "eslint.config.mjs").write_text("export default [];\n", encoding="utf-8")

    proc = _cli("init", "--dest", str(tmp_path))

    assert proc.returncode == 2
    assert "multiple active ESLint flat configs" in proc.stderr
    assert not (tmp_path / manifest.MANIFEST_NAME).exists()


def test_init_force_replaces_the_owned_manifest_but_preserves_entrypoint_content(tmp_path: Path) -> None:
    _ = _repo_with_hand_edited_files(tmp_path)
    proc = _cli("init", "--force", "--dest", str(tmp_path))
    assert proc.returncode == 0, proc.stderr
    assert (tmp_path / manifest.MANIFEST_NAME).read_text() != _SCAFFOLDED_FILES[manifest.MANIFEST_NAME]
    assert "standard" in json.loads((tmp_path / "pyrightconfig.json").read_text())["typeCheckingMode"]
    assert "// hand-rolled" in (tmp_path / "eslint.config.mjs").read_text()


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

    proc = _cli("init", "--dest", str(tmp_path))
    assert proc.returncode == 0, proc.stderr
    updated = config.read_text()
    assert "id: ruff" in updated
    assert "id: sarj-standards-drift" in updated
    assert "id: sarj-standards-check" in updated


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

    proc = _cli("init", "--dest", str(tmp_path))

    assert proc.returncode == 0, proc.stderr
    updated = config.read_text(encoding="utf-8")
    assert "--baseline python/baseline.json" in updated
    assert "id: sarj-standards-drift" in updated
    assert "id: sarj-standards-check" not in updated


def test_a_repo_with_its_own_ruff_table_is_wired_without_losing_settings(tmp_path: Path) -> None:
    _ = _python_repo(tmp_path)
    pyproject = tmp_path / "pyproject.toml"
    _ = pyproject.write_text(
        '[project]\nname = "app"\nversion = "0.1.0"\nrequires-python = ">=3.14"\n\n[tool.ruff]\nline-length = 100\n'
    )

    proc = _cli("init", "--dest", str(tmp_path))
    assert proc.returncode == 0, proc.stderr
    text = pyproject.read_text()
    assert text.count("[tool.ruff]") == 1
    assert tomllib.loads(text)["tool"]["ruff"]["line-length"] == 100
    assert tomllib.loads(text)["tool"]["ruff"]["extend"] == ".ruff-strict.toml"


def test_init_rejects_a_symlinked_mutation_target(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside.toml"
    outside.write_text('[project]\nname = "outside"\n', encoding="utf-8")
    (tmp_path / "pyproject.toml").symlink_to(outside)

    proc = _cli("init", "--dest", str(tmp_path), "--no-install")

    assert proc.returncode == 2
    assert "symlink mutation target" in proc.stderr
    assert outside.read_text(encoding="utf-8") == '[project]\nname = "outside"\n'
    assert not (tmp_path / manifest.MANIFEST_NAME).exists()


def test_init_does_not_accept_comment_only_ruff_wiring(tmp_path: Path) -> None:
    _python_repo(tmp_path)
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[project]\nname = "app"\nversion = "0.1.0"\n# extend = ".ruff-strict.toml"\n',
        encoding="utf-8",
    )

    proc = _cli("init", "--dest", str(tmp_path), "--no-install")

    assert proc.returncode == 0, proc.stderr
    assert tomllib.loads(pyproject.read_text(encoding="utf-8"))["tool"]["ruff"]["extend"] == ".ruff-strict.toml"


def test_init_does_not_duplicate_a_partially_adopted_hook(tmp_path: Path) -> None:
    _python_repo(tmp_path)
    config = tmp_path / ".pre-commit-config.yaml"
    config.write_text(
        "repos:\n  - repo: local\n    hooks:\n      - id: sarj-standards-drift\n        entry: old doctor\n",
        encoding="utf-8",
    )

    proc = _cli("init", "--dest", str(tmp_path), "--no-install")

    assert proc.returncode == 0, proc.stderr
    updated = config.read_text(encoding="utf-8")
    assert updated.count("id: sarj-standards-drift") == 1
    assert updated.count("id: sarj-standards-check") == 1
