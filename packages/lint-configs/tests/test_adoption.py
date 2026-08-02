"""Tests for the adoption path: `init`, `doctor`, `peers`, and the manifest.

Each test here corresponds to something that was measured broken in a real
consumer repo, not to a hypothetical. The docstrings say which.
"""

from __future__ import annotations

from importlib.metadata import version
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


def test_this_repos_own_overrides_are_the_ones_consumers_get() -> None:
    """The private workaround that made the repo's green CI a lie.

    `packages/typescript/package.json` carries
    `{"overrides": {"eslint-plugin-react": {"eslint": "$eslint"}}}`. That block
    existed in nothing shipped, so this repo installed and linted itself fine
    while every consumer's first `npm install` exited ERESOLVE. Pinning the two
    together means the repo can no longer rely on a fix consumers cannot get.
    """
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
    assert f"sarj-standards {command}" in proc.stdout


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
    assert "sarj-standards doctor" in generated


def test_init_writes_the_npm_overrides_into_package_json(tmp_path: Path) -> None:
    """`init` has to WRITE the overrides, not just talk about them.

    `eslint.peers.json` and both READMEs said `init` writes the block, and it
    only ever appended to the printed notes. So the documented one-command
    adoption path ended at `npm error code ERESOLVE`: the shipped config needs
    ESLint 10 and `eslint-plugin-react@7.37.5` peers `eslint <= ^9.7`. The repo
    itself installs only because `packages/typescript/package.json` carries the
    same overrides privately, where no consumer can see them.
    """
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
    """The repo root is not the project root, and writing there reaches nobody.

    Two of the three layouts measured keep their TypeScript one directory down,
    so the root has no `package.json`, no `node_modules` and no `tsconfig.json`.
    `init` wrote `eslint.config.mjs` there anyway and merged the overrides into a
    root `package.json` that does not exist -- ESLint does not search upward for a
    flat config, so the file it wrote could never load.
    """
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
_PRECOMMIT_HOOK = re.compile(
    r"entry:\s*(?P<entry>.+?)\n(?P<rest>(?:\s+\w[^\n]*\n)*)", re.MULTILINE
)


def _precommit_entries(config: str) -> list[tuple[str, bool]]:
    return [
        (match.group("entry").strip(), "pass_filenames: false" in match.group("rest"))
        for match in _PRECOMMIT_HOOK.finditer(config)
    ]


def test_the_generated_precommit_hook_actually_runs(tmp_path: Path) -> None:
    """The one file `init` writes that nothing executed.

    `precommit_block` was a hardcoded constant, so it emitted
    `entry: uv run --frozen sarj-lint-configs doctor` for every repo. In a
    TypeScript-only repo -- no `pyproject.toml`, no lockfile -- `uv run` exits 2
    with `error: Failed to spawn: sarj-lint-configs` on every commit. Asserting
    on the YAML's text could never have caught that; only running the entry can.
    """
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


def test_a_typescript_only_precommit_hook_does_not_invoke_uv_run(tmp_path: Path) -> None:
    """`uv run --frozen` in a repo with no pyproject is `Failed to spawn`, exit 2.

    `ci_snippet` already reasoned about this; `precommit_block` did not, so the
    generated hook contradicted the generated CI job in the same `init` run.
    """
    _ = _typescript_repo(tmp_path)
    assert _cli("init", "--dest", str(tmp_path)).returncode == 0

    generated = (tmp_path / ".pre-commit-config.yaml").read_text()
    assert "uv run --frozen" not in generated
    assert f"uvx --from sarj-lint-configs=={__version__}" in generated
    # `check` runs the Python/SQL/IaC registries; a TypeScript repo has nothing
    # to feed them, and a hook that lints nothing is a hook that hides.
    assert "sarj-standards check" in generated


def test_detection_finds_a_package_json_in_a_subproject(tmp_path: Path) -> None:
    """One repo ships the strict config while only 10 of its 52 sub-projects use it.

    Detecting TypeScript only at the root would call that repo fully adopted.
    """
    _ = _python_repo(tmp_path)
    (tmp_path / "services" / "web").mkdir(parents=True)
    _ = (tmp_path / "services" / "web" / "package.json").write_text("{}\n")
    found = scaffold.detect(tmp_path)
    assert (found.python, found.typescript) == (True, True)
    assert found.python_root == tmp_path
    assert found.typescript_root == tmp_path / "services" / "web"


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


def test_doctor_catches_a_stale_package_script_pin(tmp_path: Path) -> None:
    _ = _typescript_repo(tmp_path)
    _ = (tmp_path / "package.json").write_text(
        '{"scripts":{"lint:sarj":"uvx --from sarj-lint-configs==0.1.0 '
        'sarj-standards check ."}}\n'
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
    """The stalest pin form was the one shape `doctor` could not see.

    A tag-shaped pattern skipped a 40-character SHA entirely, so a repo pinning
    the hooks to a commit dozens behind main was reported as having nothing to
    check -- and a SHA is precisely the pin with no version in it for a human to
    notice going stale either.
    """
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
    """A repo pinned to exactly the tested floor is not drifted, however it spells it.

    `>=6.1.0` was reported as DRIFT against a floor of `6.1.0`. The comparison was
    `pinned.lstrip("^~=")`, a CHARACTER-SET strip: it stops at the leading `>`,
    which is not in the set, so the whole specifier survived and no longer equalled
    the floor. `>=` is the ordinary npm spelling of a floor and the only PEP 440
    spelling of one, so `doctor` told a correctly-pinned repo to change something --
    without being able to say what.
    """
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


@pytest.mark.parametrize(
    "rev",
    ["9d073e83b24cd5af788a61996cd9238d85d927d4", "9d073e8", '"9d073e83b24cd5af788a61996cd9238d85d927d4"'],
)
def test_rev_pattern_reads_a_commit_pin(rev: str) -> None:
    assert doctor.parse_revs(f"rev: {rev}\n") == [rev.strip('"')]


def test_rev_pattern_is_not_fooled_by_a_version_tag() -> None:
    """`v6.0.0` is a tag from some other repo, not a commit; reading it as one would cry wolf."""
    assert doctor.parse_revs("rev: v6.0.0\n") == []


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


def test_the_manifest_filename_is_the_one_adopted_repos_committed() -> None:
    """Every other reference to it is symbolic, so a rename is invisible to the suite.

    The filename is the contract: it is what a consumer commits, what `doctor`
    looks for, what `sync --check` reads its config set from, and what both
    READMEs tell people to expect. Renaming the constant orphans every adopted
    repo at once -- `doctor` starts reporting "absent -- run init" everywhere --
    with no test objecting.
    """
    assert manifest.MANIFEST_NAME == ".sarj-standards.toml"
    assert manifest.MANIFEST_NAME in (REPO_ROOT / "README.md").read_text(encoding="utf-8")


def test_the_expected_precommit_rev_names_a_tag_the_release_workflow_publishes() -> None:
    """The rev namespace is `python-v`, and only the release workflow can confirm it.

    The hooks in `.pre-commit-hooks.yaml` ship from the ROOT package, which is
    `sarj-python-lint`, so the tag is `python-v<its version>` -- not the
    `sarj-lint-configs` version a consumer pinned. Existing tests only assert
    that a WRONG rev drifts, which stays true if the prefix is changed to a
    namespace that is never tagged: `doctor` would then demand
    `lint-configs-v0.24.0` from a repo, and no such tag exists to point at.
    """
    expected = manifest.expected_precommit_rev()
    assert expected is not None
    assert expected == f"python-v{version('sarj-python-lint')}"

    workflow = (REPO_ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    prefix = expected.rsplit("-v", 1)[0]
    assert f"'{prefix}-v*'" in workflow, f"release.yml never triggers on {prefix}-v* tags"
    assert f"maybe_tag {prefix} " in workflow, f"release.yml never creates a {prefix}-v tag"


def test_sync_check_treats_a_config_that_was_never_synced_as_drift(tmp_path: Path) -> None:
    """A repo that never ran `sync` must fail `sync --check`, not pass it.

    The check compared bytes only when the destination already existed, so a
    missing file reported `ok:` and the run exited 0. That is the exact state of
    a repo that adopted the CI snippet and nothing else, which is the population
    the gate exists for.
    """
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


#: Files `init` owns and would otherwise write. Each is given contents a repo
#: could plausibly have hand-edited, so a clobber is visible rather than a no-op.
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


@pytest.mark.parametrize("name", sorted(_SCAFFOLDED_FILES))
def test_init_never_overwrites_an_existing_file_without_force(tmp_path: Path, name: str) -> None:
    """`init` is a generator, not a framework: everything it writes is the repo's.

    Only the `pyproject.toml` append path was covered, so dropping the existence
    check would have silently replaced a repo's tuned `pyrightconfig.json`, its
    hand-rolled `eslint.config.mjs` and its adopted-version manifest on a re-run
    that people are told is safe.
    """
    _ = _repo_with_hand_edited_files(tmp_path)
    proc = _cli("init", "--dest", str(tmp_path))
    assert proc.returncode == 0, proc.stderr
    assert (tmp_path / name).read_text() == _SCAFFOLDED_FILES[name]
    assert f"skip:  {tmp_path / name}" in proc.stdout


@pytest.mark.parametrize("name", sorted(_SCAFFOLDED_FILES))
def test_init_force_does_overwrite_the_files_it_owns(tmp_path: Path, name: str) -> None:
    """The other half of the same guarantee: `--force` has to actually force.

    Without this, `--force` could quietly become a no-op and the documented way
    to re-sync a repo after an upgrade would leave it on the old wiring.
    """
    _ = _repo_with_hand_edited_files(tmp_path)
    proc = _cli("init", "--force", "--dest", str(tmp_path))
    assert proc.returncode == 0, proc.stderr
    assert (tmp_path / name).read_text() != _SCAFFOLDED_FILES[name]
    assert f"wrote: {tmp_path / name}" in proc.stdout


def test_an_existing_precommit_config_is_left_alone_and_the_block_is_printed(tmp_path: Path) -> None:
    """A repo with hooks of its own gets a merge note, never a replacement.

    `.pre-commit-config.yaml` is the one scaffolded file whose contents a repo
    almost always already owns, and overwriting it deletes every other hook the
    repo runs.
    """
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
    assert config.read_text() == existing
    assert "add this to .pre-commit-config.yaml" in proc.stdout
    assert "sarj-standards-drift" in proc.stdout


def test_a_repo_with_its_own_ruff_table_is_told_rather_than_given_a_second_one(tmp_path: Path) -> None:
    """Two `[tool.ruff]` tables is not valid TOML, so the append would break the repo.

    Only the "already extends" and the "no table at all" paths were covered, and
    a repo that sets `line-length` and nothing else is the common shape.
    """
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
    assert "[tool.ruff] table already" in proc.stdout
