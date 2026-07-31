"""Tests for the adoption path: `init`, `doctor`, `peers`, and the manifest.

Each test here corresponds to something that was measured broken in a real
consumer repo, not to a hypothetical. The docstrings say which.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import sys
import tomllib

import pytest

from sarj_lint_configs import ESLINT_PEERS, ESLINT_STRICT, __version__, doctor, manifest, scaffold


REPO_ROOT = Path(__file__).resolve().parents[3]


def _cli(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "sarj_lint_configs", *args],
        capture_output=True, text=True, check=False, cwd=cwd,
    )


def _python_repo(root: Path) -> Path:
    (root / "src").mkdir(parents=True, exist_ok=True)
    _ = (root / "pyproject.toml").write_text(
        '[project]\nname = "app"\nversion = "0.1.0"\nrequires-python = ">=3.14"\n'
    )
    return root


def _typescript_repo(root: Path) -> Path:
    _ = (root / "package.json").write_text('{"name": "web", "private": true}\n')
    return root


def test_every_eslint_import_has_a_pinned_peer() -> None:
    """The config's imports were a hidden contract; now they are a checked one.

    A consumer following the README hit `Cannot find package 'typescript-eslint'`,
    installed it, hit the next one, and so on for nine rounds. Adding an import to
    `eslint.strict.mjs` without adding its pin recreates that exactly.
    """
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
    """Without these, `npm install` exits ERESOLVE and the config is unreachable.

    Verified by hand: the exact peer set fails to install in a fresh repo, and
    succeeds with `{"overrides": {"eslint-plugin-react": {"eslint": "$eslint"}}}`.
    """
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
    """The README advertised a floor the config had already outgrown.

    `@sarj/eslint-plugin@2.16.0` was documented while the config referenced a rule
    that only exists in 2.17.0+, so anyone who followed the README got "Definition
    for rule was not found". A pin asserted against `package.json` cannot go stale
    silently, which a sentence in a README always can.
    """
    source = REPO_ROOT / "packages" / "typescript" / "package.json"
    if not source.is_file():
        pytest.skip("running against an installed wheel, outside the source tree")
    parsed: object = json.loads(source.read_text(encoding="utf-8"))  # pyright: ignore[reportAny] — untyped stdlib boundary
    package_json = manifest.as_table(parsed)
    assert manifest.eslint_peers()["@sarj/eslint-plugin"] == package_json["version"]


def test_manifest_round_trips(tmp_path: Path) -> None:
    written = manifest.Manifest(
        version="1.2.3", configs=("ruff", "pyright"), python_dest=".", typescript_dest="web"
    )
    _ = (tmp_path / manifest.MANIFEST_NAME).write_text(written.render())
    assert manifest.load(tmp_path) == written


def test_manifest_renders_as_valid_toml() -> None:
    rendered = manifest.Manifest(
        version="1.2.3", configs=("ruff",), python_dest=".", typescript_dest="."
    ).render()
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
    """A Python repo should never be asked to carry an ESLint config.

    `sync` used to write all six unconditionally, so `sync --check` reported
    permanent drift for the two files a repo did not want -- which is why the
    check never made it into anyone's CI.
    """
    assert manifest.default_configs(has_python=python, has_typescript=typescript) == expected


def test_sync_respects_the_manifests_config_set(tmp_path: Path) -> None:
    _ = _python_repo(tmp_path)
    assert _cli("init", "--dest", str(tmp_path)).returncode == 0
    assert not (tmp_path / "eslint.strict.mjs").exists()

    proc = _cli("sync", "--check", "--dest", str(tmp_path))
    assert proc.returncode == 0, proc.stdout
    assert "checked 5 config(s); 0 drifted" in proc.stdout


def test_sync_check_fails_when_a_synced_config_is_edited(tmp_path: Path) -> None:
    """The vendoring failure, caught at the earliest possible moment.

    One consumer copied the ESLint config "verbatim" and then edited it; it drifted
    to 120 rules against a canonical 145, missing 30 and carrying 5 that no longer
    exist upstream. Nothing detected that for as long as it took to measure by hand.
    """
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


def test_init_writes_a_typescript_entrypoint_with_an_override_seam(tmp_path: Path) -> None:
    """The generated entrypoint has to teach "extend, do not fork".

    Repos hand-rolled their own `unicorn/filename-case` because the canonical one
    did not cover their framework, and forking was the only route they knew. An
    override block in the file they own does the same job and keeps upstream rules.
    """
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
def test_init_gives_a_typescript_repo_everything_npm_needs(
    tmp_path: Path, expected: str
) -> None:
    """Anything missing here sends the reader back to trial-and-error installs."""
    _ = _typescript_repo(tmp_path)
    proc = _cli("init", "--dest", str(tmp_path))
    assert expected in proc.stdout


@pytest.mark.parametrize("command", ["doctor", "sync --check", "check ."])
def test_init_prints_a_ci_snippet_naming_all_three_gates(tmp_path: Path, command: str) -> None:
    _ = _python_repo(tmp_path)
    proc = _cli("init", "--dest", str(tmp_path))
    assert f"sarj-lint-configs {command}" in proc.stdout


def test_ci_snippet_for_a_typescript_repo_does_not_require_a_python_project(
    tmp_path: Path,
) -> None:
    """`uv run --frozen` in a repo with no pyproject is an instruction that fails.

    Needing a Python project and lockfile to obtain an ESLint config is a fair
    description of why TypeScript repos copied the file rather than install
    anything, so the generated CI must not ask for one.
    """
    _ = _typescript_repo(tmp_path)
    proc = _cli("init", "--dest", str(tmp_path))
    assert "uv run --frozen" not in proc.stdout
    assert "uvx --from sarj-lint-configs==" in proc.stdout


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
    """The `rev:` was one of the three pin sites; the fix is to delete it.

    A `repo: local` hook runs the CLI from the environment the pyproject pin
    already fixed, so there is no second version string to keep in step -- and no
    second namespace to translate (`python-v0.33.0` for `sarj-lint-configs`
    0.16.0) to get wrong.
    """
    _ = _python_repo(tmp_path)
    assert _cli("init", "--dest", str(tmp_path)).returncode == 0
    generated = (tmp_path / ".pre-commit-config.yaml").read_text()
    assert "rev:" not in generated
    assert "repo: local" in generated
    assert "sarj-lint-configs doctor" in generated


def test_detection_finds_a_package_json_in_a_subproject(tmp_path: Path) -> None:
    """One repo ships the strict config while only 10 of its 52 sub-projects use it.

    Detecting TypeScript only at the root would call that repo fully adopted.
    """
    _ = _python_repo(tmp_path)
    (tmp_path / "services" / "web").mkdir(parents=True)
    _ = (tmp_path / "services" / "web" / "package.json").write_text("{}\n")
    assert scaffold.detect(tmp_path) == scaffold.Ecosystems(python=True, typescript=True)


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
    """The measured case: CI ran `uvx --from sarj-python-lint==0.12.2`.

    That pin lived on a command line in a workflow file, agreed with nothing, and
    no tool had ever looked at it.
    """
    _ = _python_repo(tmp_path)
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    _ = (workflows / "ci.yml").write_text(
        "jobs:\n  lint:\n    steps:\n"
        "      - run: uvx --from sarj-python-lint==0.12.2 sarj-python-lint check .\n"
    )
    proc = _cli("doctor", "--dest", str(tmp_path))
    assert proc.returncode == 1
    assert "ci.yml" in proc.stdout
    assert "0.12.2" in proc.stdout


def test_doctor_catches_a_stale_precommit_rev(tmp_path: Path) -> None:
    _ = _python_repo(tmp_path)
    _ = (tmp_path / ".pre-commit-config.yaml").write_text(
        "repos:\n  - repo: https://github.com/sarj-ai/standards\n"
        "    rev: python-v0.19.0\n    hooks:\n      - id: sarj-no-comment-cruft\n"
    )
    proc = _cli("doctor", "--dest", str(tmp_path))
    assert proc.returncode == 1
    assert "python-v0.19.0" in proc.stdout


def test_doctor_catches_a_stale_eslint_plugin_pin(tmp_path: Path) -> None:
    _ = _typescript_repo(tmp_path)
    _ = (tmp_path / "package.json").write_text(
        json.dumps({"name": "web", "devDependencies": {"@sarj/eslint-plugin": "2.16.0"}})
    )
    proc = _cli("doctor", "--dest", str(tmp_path))
    assert proc.returncode == 1
    assert "2.16.0" in proc.stdout


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
    assert "run `sarj-lint-configs init`" in proc.stdout


def test_doctor_reports_manifest_version_drift(tmp_path: Path) -> None:
    _ = _python_repo(tmp_path)
    _ = (tmp_path / manifest.MANIFEST_NAME).write_text(
        manifest.Manifest(
            version="0.0.1", configs=("ruff",), python_dest=".", typescript_dest="."
        ).render()
    )
    proc = _cli("doctor", "--dest", str(tmp_path))
    assert proc.returncode == 1
    assert __version__ in proc.stdout


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


#: `doctor`'s own report lines. A README that SHOWS drift has to name stale
#: versions -- that is the example -- so those lines are demonstrations, not
#: instructions, and holding them to the current version would make the sample
#: output impossible to write.
_DOCTOR_OUTPUT_LINE = re.compile(r"^(?:ok|warn|drift)\s", re.MULTILINE)


def _documented_pins(text: str) -> dict[str, str]:
    instructions = "\n".join(
        line for line in text.splitlines() if not _DOCTOR_OUTPUT_LINE.match(line)
    )
    pins = doctor.parse_pins(instructions)
    if plugin := re.search(r"@sarj/eslint-plugin@(?P<version>\d+\.\d+\.\d+)", instructions):
        pins["@sarj/eslint-plugin"] = plugin.group("version")
    return pins


@pytest.mark.parametrize(
    "readme",
    [REPO_ROOT / "README.md", REPO_ROOT / "packages" / "lint-configs" / "README.md"],
)
def test_readme_never_advertises_a_version_that_is_not_shipping(readme: Path) -> None:
    """The class of bug this kills, not one instance of it.

    The README advertised a peer floor of `@sarj/eslint-plugin@2.16.0` while the
    config referenced a rule that only exists in 2.17.0+, so anyone who followed
    the README got a broken config. It also pinned `sarj-lint-configs==0.10.0`
    five minor versions after 0.10.0. Both are the same failure: a version literal
    typed into prose, which is true exactly once. Asserting on them makes a stale
    doc a red build instead of a consumer's afternoon.

    Only COPY-PASTEABLE forms count: `name==1.2.3` and `@scope/name@1.2.3`. Prose
    that mentions a historical version without an operator ("pinned at 0.10.0")
    is not something a reader can paste into a terminal, and a README explaining
    which versions used to be wrong has to be able to name them.
    """
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
    """A pin below latest is a claim; it has to carry its evidence.

    Without the reason written down, the next person to run `npm update` undoes
    the only version set that installs.
    """
    parsed: object = json.loads(ESLINT_PEERS.read_text(encoding="utf-8"))  # pyright: ignore[reportAny] — untyped stdlib boundary
    data = manifest.as_table(parsed)
    peers = manifest.table_field(data, "peers")
    ceilings = manifest.table_field(data, "ceilings")
    assert ceilings, "a pin below latest is a claim; it has to carry its evidence"
    for name, reason in ceilings.items():
        assert name in peers
        assert isinstance(reason, str)
        assert len(reason) > 40, f"{name}'s ceiling needs a real explanation"
