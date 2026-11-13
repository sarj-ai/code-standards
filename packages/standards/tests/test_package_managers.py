from __future__ import annotations

import json
import shlex
import subprocess
import sys
from typing import TYPE_CHECKING

import pytest
import yaml

from sarj_standards.libs.adoption import lifecycle, manifest, packagemanager, scaffold
from sarj_standards.libs.adoption.packagemanager import PackageManager, YarnVariant
from sarj_standards.libs.typed_containers import is_object_list, is_object_mapping
from tests.oxlint_project import MODULES


if TYPE_CHECKING:
    from pathlib import Path

    from pydantic import JsonValue


def _cli(*args: str) -> subprocess.CompletedProcess[str]:
    command = list(args)
    if command and command[0] == "init":
        command[0] = "setup"
    if command and command[0] == "setup" and "--no-install" not in command:
        command.append("--no-install")
    if "--dest" in command:
        index = command.index("--dest")
        root = command[index + 1]
        command = [*command[:index], *command[index + 2 :]]
        command[0:0] = ["--root", root]
    return subprocess.run(
        [sys.executable, "-m", "sarj_standards", *command],
        capture_output=True,
        text=True,
        check=False,
    )


def _project(root: Path, lockfile: str, package_json: dict[str, JsonValue] | None = None) -> Path:
    (root / "package.json").write_text(json.dumps(package_json or {"name": "web"}, indent=2) + "\n", encoding="utf-8")
    (root / lockfile).write_text("", encoding="utf-8")
    return root


@pytest.mark.parametrize(
    ("lockfile", "expected"),
    [
        ("pnpm-lock.yaml", PackageManager.PNPM),
        ("yarn.lock", PackageManager.YARN),
        ("bun.lock", PackageManager.BUN),
        ("bun.lockb", PackageManager.BUN),
        ("package-lock.json", PackageManager.NPM),
    ],
)
def test_the_lockfile_names_the_client(tmp_path: Path, lockfile: str, expected: PackageManager) -> None:
    assert packagemanager.detect(_project(tmp_path, lockfile)) == expected


def test_a_repo_with_no_lockfile_is_assumed_to_be_npm(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{"name": "web"}\n', encoding="utf-8")
    assert packagemanager.detect(tmp_path) == PackageManager.NPM


def test_the_packagemanager_field_beats_a_stray_lockfile(tmp_path: Path) -> None:
    root = _project(tmp_path, "package-lock.json", {"name": "web", "packageManager": "yarn@4.15.0"})
    assert packagemanager.detect(root) == PackageManager.YARN


def test_an_unsupported_declared_package_manager_fails_closed(tmp_path: Path) -> None:
    root = _project(tmp_path, "package-lock.json", {"name": "web", "packageManager": "deno@2.4.0"})

    with pytest.raises(ValueError, match=r"unsupported packageManager 'deno@2\.4\.0'"):
        packagemanager.detect(root)

    proc = _cli("init", "--dest", str(root))
    assert proc.returncode == 2
    assert "supported managers: npm, pnpm, yarn, bun" in proc.stderr


@pytest.fixture
def synthetic_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- exercises translation of the centrally loaded policy independently of enabled plugins.
        manifest, "typescript_peers", lambda: {"example-peer": "1.2.3"}
    )
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- supplies the matching central policy input without installing obsolete plugin peers.
        manifest, "typescript_overrides", lambda: {"example-plugin": {"example-peer": "$example-peer"}}
    )


@pytest.mark.usefixtures("synthetic_overrides")
def test_npm_keeps_the_nested_form_with_resolved_root_references() -> None:
    overrides = packagemanager.overrides_for(PackageManager.NPM)
    assert overrides.key_path == ("overrides",)
    assert overrides.entries["example-plugin"] == {"example-peer": "1.2.3"}
    assert "$" not in json.dumps(overrides.as_document())


@pytest.mark.usefixtures("synthetic_overrides")
def test_pnpm_gets_a_flat_selector_for_its_workspace_policy() -> None:
    overrides = packagemanager.overrides_for(PackageManager.PNPM)
    assert overrides.key_path == ("overrides",)
    assert "example-plugin>example-peer" in overrides.entries


@pytest.mark.usefixtures("synthetic_overrides")
def test_yarn_gets_the_resolved_overrides_as_resolutions() -> None:
    overrides = packagemanager.overrides_for(PackageManager.YARN)
    assert overrides.key_path == ("resolutions",)
    assert overrides.entries == {"example-plugin/example-peer": "1.2.3"}
    assert "$" not in json.dumps(overrides.as_document())


def test_only_the_internal_plugin_is_an_age_gate_exception() -> None:
    approvals = manifest.typescript_age_gate_preapprovals()

    assert approvals == {"@sarj/eslint-plugin": manifest.typescript_peers()["@sarj/eslint-plugin"]}


def test_bun_needs_no_retired_eslint_override() -> None:
    overrides = packagemanager.overrides_for(PackageManager.BUN)
    assert overrides.key_path == ("overrides",)
    assert overrides.entries == {}


@pytest.mark.parametrize(
    ("client", "prefix"),
    [
        (PackageManager.NPM, "npm install --ignore-scripts"),
        (PackageManager.PNPM, "pnpm install --no-frozen-lockfile --ignore-scripts"),
        (PackageManager.YARN, "yarn install --ignore-scripts"),
        (PackageManager.BUN, "bun install --ignore-scripts"),
    ],
)
def test_the_install_command_is_the_one_that_client_understands(client: PackageManager, prefix: str) -> None:
    command = packagemanager.install_command(client)
    assert command.startswith(prefix)
    assert " add " not in command


@pytest.mark.parametrize("client", list(PackageManager))
def test_install_argv_matches_the_printed_script_free_command(client: PackageManager) -> None:
    argv = packagemanager.install_argv(client)
    assert argv == tuple(packagemanager.install_command(client).split())
    assert all("@sarj" not in part for part in argv)


def test_lint_execution_can_never_install_from_the_network() -> None:
    assert packagemanager.exec_argv(PackageManager.NPM, "eslint", "--", "app.ts") == (
        "npm",
        "exec",
        "--offline",
        "--",
        "eslint",
        "--",
        "app.ts",
    )
    assert packagemanager.exec_argv(PackageManager.BUN, "eslint", "--", "app.ts") == (
        "bunx",
        "--bun",
        "--no-install",
        "eslint",
        "--",
        "app.ts",
    )
    assert packagemanager.exec_argv(PackageManager.PNPM, "eslint", "--", "app.ts") == (
        "pnpm",
        "exec",
        "eslint",
        "--",
        "app.ts",
    )


@pytest.mark.parametrize(
    ("package_json", "expected"),
    [
        pytest.param({"name": "web", "packageManager": "yarn@1.22.19"}, YarnVariant.CLASSIC, id="declared-classic"),
        pytest.param({"name": "web", "packageManager": "yarn@4.15.0"}, YarnVariant.BERRY, id="declared-berry"),
        pytest.param({"name": "web"}, YarnVariant.CLASSIC, id="bare-lockfile"),
    ],
)
def test_yarn_dialect_follows_the_declared_package_manager(
    tmp_path: Path, package_json: dict[str, JsonValue], expected: YarnVariant
) -> None:
    root = _project(tmp_path, "yarn.lock", package_json)

    assert packagemanager.yarn_variant(root) is expected


def test_a_yarnrc_yml_marks_a_berry_checkout_without_a_declaration(tmp_path: Path) -> None:
    root = _project(tmp_path, "yarn.lock")
    (root / ".yarnrc.yml").write_text("nodeLinker: node-modules\n", encoding="utf-8")

    assert packagemanager.yarn_variant(root) is YarnVariant.BERRY


def test_each_yarn_dialect_gets_flags_it_actually_enforces() -> None:
    classic = packagemanager.install_command(PackageManager.YARN, yarn=YarnVariant.CLASSIC)
    berry = packagemanager.install_command(PackageManager.YARN, yarn=YarnVariant.BERRY)

    assert classic == "yarn install --ignore-scripts"
    assert berry == "yarn install --no-immutable --mode=skip-build"
    assert packagemanager.install_argv(PackageManager.YARN, yarn=YarnVariant.BERRY) == tuple(berry.split())


def test_only_the_berry_note_mentions_berry_only_configuration() -> None:
    classic = packagemanager.install_note(PackageManager.YARN, yarn=YarnVariant.CLASSIC)
    berry = packagemanager.install_note(PackageManager.YARN, yarn=YarnVariant.BERRY)

    assert classic is not None
    assert berry is not None
    assert "resolutions" in classic
    assert "npmMinimalAgeGate" not in classic
    assert "npmMinimalAgeGate" in berry
    assert "npmMinimalAgeGate: 0" not in berry
    assert "npmPreapprovedPackages" in berry
    assert "wait" in berry.lower()


def test_ci_workflow_speaks_the_detected_yarn_dialect(tmp_path: Path) -> None:
    _project(tmp_path, "yarn.lock")

    classic = scaffold.github_ci_workflow(tmp_path)
    (tmp_path / "package.json").write_text(
        json.dumps({"name": "web", "packageManager": "yarn@4.15.0"}) + "\n", encoding="utf-8"
    )
    berry = scaffold.github_ci_workflow(tmp_path)

    assert "yarn install --frozen-lockfile" in classic
    assert "--immutable" not in classic
    assert "yarn install --immutable" in berry


def test_ci_installs_nested_javascript_project_from_its_install_root(tmp_path: Path) -> None:
    web = tmp_path / "services" / "web"
    web.mkdir(parents=True)
    (web / "package.json").write_text('{"name":"web"}\n', encoding="utf-8")
    (web / "package-lock.json").write_text('{"lockfileVersion":3}\n', encoding="utf-8")

    workflow = scaffold.github_ci_workflow(tmp_path)

    assert "run: npm ci --no-audit --no-fund" in workflow
    assert "npm install --global" not in workflow
    assert 'working-directory: "services/web"' in workflow


def test_ci_yaml_quotes_a_nested_install_root_with_shell_metacharacters(tmp_path: Path) -> None:
    web = tmp_path / "services" / "web # production"
    web.mkdir(parents=True)
    (web / "package.json").write_text('{"name":"web"}\n', encoding="utf-8")
    (web / "package-lock.json").write_text('{"lockfileVersion":3}\n', encoding="utf-8")

    workflow = scaffold.github_ci_workflow(tmp_path)

    assert 'working-directory: "services/web # production"' in workflow


@pytest.mark.parametrize(
    "declaration",
    [
        pytest.param("npm@12.1.0", id="version"),
        pytest.param("npm@12.1.0+sha512.abcdef", id="version-with-integrity"),
    ],
)
def test_ci_activates_the_exact_declared_npm_version(tmp_path: Path, declaration: str) -> None:
    _project(tmp_path, "package-lock.json", {"name": "web", "packageManager": declaration})

    workflow = scaffold.github_ci_workflow(tmp_path)

    activation = "run: npm install --global npm@12.1.0 --ignore-scripts"
    assert activation in workflow
    assert workflow.index(activation) < workflow.index("run: npm ci")


def test_ci_rejects_a_non_exact_declared_npm_version(tmp_path: Path) -> None:
    _project(tmp_path, "package-lock.json", {"name": "web", "packageManager": "npm@latest"})

    with pytest.raises(ValueError, match="must pin an exact semantic version"):
        scaffold.github_ci_workflow(tmp_path)


def test_ci_bootstraps_bun_without_unneeded_node_or_corepack(tmp_path: Path) -> None:
    _project(tmp_path, "bun.lock")

    workflow = scaffold.github_ci_workflow(tmp_path)

    assert "oven-sh/setup-bun@0c5077e51419868618aeaa5fe8019c62421857d6 # v2" in workflow
    assert "actions/setup-node" not in workflow
    assert "corepack enable" not in workflow
    assert "run: bun install --frozen-lockfile" in workflow


def test_ci_pins_node_for_bun_on_a_configured_runner(tmp_path: Path) -> None:
    _project(tmp_path, "bun.lock")
    (tmp_path / manifest.MANIFEST_NAME).write_text(
        'schema = 4\nbundle = "1.2.3"\n[ci]\nrunner = "blacksmith-2vcpu-ubuntu-2404"\n', encoding="utf-8"
    )

    workflow = scaffold.github_ci_workflow(tmp_path)

    document: object = yaml.safe_load(workflow)  # pyright: ignore[reportAny] -- narrow generated YAML at the parser boundary.
    assert is_object_mapping(document)
    jobs = document["jobs"]
    assert is_object_mapping(jobs)
    job = jobs["standards"]
    assert is_object_mapping(job)
    assert job["runs-on"] == "blacksmith-2vcpu-ubuntu-2404"
    steps = job["steps"]
    assert is_object_list(steps)
    actions = [(index, step) for index, step in enumerate(steps) if is_object_mapping(step) and "uses" in step]
    bun_index, _ = next((index, step) for index, step in actions if str(step["uses"]).startswith("oven-sh/setup-bun@"))
    node_index, node = next(
        (index, step) for index, step in actions if str(step["uses"]).startswith("actions/setup-node@")
    )
    assert bun_index < node_index
    assert node["with"] == {"node-version": 24, "check-latest": True}
    install_index = next(
        index
        for index, step in enumerate(steps)
        if is_object_mapping(step)
        and isinstance(run := step.get("run"), str)
        and shlex.split(run)[:2] == ["bun", "install"]
    )
    assert node_index < install_index
    install = steps[install_index]
    assert is_object_mapping(install)
    command = install["run"]
    assert isinstance(command, str)
    assert {"--frozen-lockfile", "--ignore-scripts"} <= set(shlex.split(command))


def test_ci_resolves_the_newest_node_before_npm_activation_on_a_configured_runner(tmp_path: Path) -> None:
    _project(tmp_path, "package-lock.json", {"name": "web", "packageManager": "npm@12.0.2"})
    (tmp_path / manifest.MANIFEST_NAME).write_text(
        'schema = 4\nbundle = "1.2.3"\n[ci]\nrunner = "blacksmith-2vcpu-ubuntu-2404"\n', encoding="utf-8"
    )

    workflow = scaffold.github_ci_workflow(tmp_path)

    node = "          node-version: 24\n          check-latest: true\n"
    assert node in workflow
    assert workflow.index(node) < workflow.index("run: npm install --global npm@12.0.2 --ignore-scripts")


def test_ci_keeps_the_image_node_on_github_hosted_linux(tmp_path: Path) -> None:
    _project(tmp_path, "package-lock.json", {"name": "web", "packageManager": "npm@12.0.2"})

    workflow = scaffold.github_ci_workflow(tmp_path)

    assert "          node-version: 24\n" in workflow
    assert "check-latest" not in workflow


def test_ci_only_runs_locked_uv_sync_for_a_uv_project(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname="demo"\nversion="0.1.0"\n', encoding="utf-8")

    unlocked = scaffold.github_ci_workflow(tmp_path)
    (tmp_path / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    locked = scaffold.github_ci_workflow(tmp_path)

    assert "uv sync" not in unlocked
    assert "run: uv sync --locked" in locked


def test_ci_emits_first_class_github_annotations(tmp_path: Path) -> None:
    workflow = scaffold.github_ci_workflow(tmp_path)

    assert "check --trust-repository-code --format github" in workflow


def test_init_speaks_classic_yarn_when_only_the_lockfile_names_it(tmp_path: Path) -> None:
    _project(tmp_path, "yarn.lock")

    proc = _cli("init", "--dest", str(tmp_path))

    assert proc.returncode == 0, proc.stderr
    assert "yarn install --ignore-scripts" in proc.stdout
    assert "--mode=skip-build" not in proc.stdout
    assert "npmMinimalAgeGate" not in proc.stdout


def test_lifecycle_install_preserves_the_yarn_dialect(tmp_path: Path) -> None:
    ecosystems = scaffold.Ecosystems(
        False,
        True,
        typescript_root=tmp_path,
        typescript_install_root=tmp_path,
        client=PackageManager.YARN,
        yarn=YarnVariant.BERRY,
    )

    commands = lifecycle.install_commands(tmp_path, ecosystems, hook_manager="none")

    assert commands[0].argv == ("yarn", "install", "--no-immutable", "--mode=skip-build")


def _prepared_install(root: Path, client: PackageManager, yarn: YarnVariant = YarnVariant.CLASSIC) -> lifecycle.Command:
    ecosystems = scaffold.Ecosystems(
        False, True, typescript_root=root, typescript_install_root=root, client=client, yarn=yarn
    )
    (command,) = lifecycle.install_commands(root, ecosystems, hook_manager="none", include_devops=False)
    assert command.prepare is not None
    with command.prepare(command) as prepared:
        return prepared


def test_pnpm_installs_exempt_exactly_the_managed_versions_on_the_command_line(tmp_path: Path) -> None:
    policy = (
        "minimumReleaseAge: 20160\n"
        "minimumReleaseAgeExclude:\n  - glob@14.0.3\n"
        "trustPolicy: no-downgrade\n"
        "trustPolicyExclude:\n  - semver@6.3.1\n"
    )
    (tmp_path / "pnpm-workspace.yaml").write_text(policy, encoding="utf-8")
    tsrs = manifest.typescript_peers()["tsrs"]

    prepared = _prepared_install(tmp_path, PackageManager.PNPM)

    exemptions = [part for part in prepared.argv if part.startswith("--config.")]
    managed = manifest.typescript_installed_versions()
    # An inline list replaces the workspace's own, so the authored entries come first.
    assert exemptions == [
        *(f"--config.minimumReleaseAgeExclude={entry}" for entry in ("glob@14.0.3", *managed)),
        *(f"--config.trustPolicyExclude={entry}" for entry in ("semver@6.3.1", *managed)),
    ]
    assert f"tsrs@{tsrs}" in managed
    assert f"@tsrs/linux-x64-gnu@{tsrs}" in managed
    assert "@typescript/typescript6@6.0.2" in managed
    assert (tmp_path / "pnpm-workspace.yaml").read_text(encoding="utf-8") == policy


def test_yarn_berry_installs_preapprove_the_managed_versions_in_the_environment(tmp_path: Path) -> None:
    policy = 'npmMinimalAgeGate: 3d\nnpmPreapprovedPackages:\n  - "body-parser@2.4.0"\n'
    (tmp_path / ".yarnrc.yml").write_text(policy, encoding="utf-8")

    prepared = _prepared_install(tmp_path, PackageManager.YARN, YarnVariant.BERRY)

    assert prepared.argv == ("yarn", "install", "--no-immutable", "--mode=skip-build")
    approved = ",".join(("body-parser@2.4.0", *manifest.typescript_installed_versions()))
    assert prepared.environment == (("YARN_NPM_PREAPPROVED_PACKAGES", approved),)
    assert (tmp_path / ".yarnrc.yml").read_text(encoding="utf-8") == policy


def test_npm_installs_carry_no_policy_exemption(tmp_path: Path) -> None:
    prepared = _prepared_install(tmp_path, PackageManager.NPM)

    assert prepared.argv == packagemanager.install_argv(PackageManager.NPM)
    assert prepared.environment == ()


def test_platform_packages_match_what_each_locked_peer_installs() -> None:
    parsed: object = json.loads(manifest.PEERS_JSON.read_text(encoding="utf-8"))  # pyright: ignore[reportAny] -- untyped stdlib boundary
    declared = manifest.table_field(manifest.as_table(parsed), "platformPackages")
    for name, pin in manifest.typescript_peers().items():
        package_json = MODULES / name / "package.json"
        if not package_json.is_file():
            continue
        installed: object = json.loads(package_json.read_text(encoding="utf-8"))  # pyright: ignore[reportAny] -- untyped stdlib boundary
        optional = manifest.table_field(manifest.as_table(installed), "optionalDependencies")
        assert sorted(optional) == declared.get(name, []), name
        assert all(version == pin for version in optional.values()), name


def test_pnpm_workspace_install_targets_the_workspace_root() -> None:
    assert "--ignore-workspace" not in packagemanager.install_argv(PackageManager.PNPM, workspace=True)
    assert "--ignore-workspace" in packagemanager.install_argv(PackageManager.PNPM)


def test_conflicting_lockfiles_fail_instead_of_selecting_by_accident(tmp_path: Path) -> None:
    _project(tmp_path, "pnpm-lock.yaml")
    (tmp_path / "yarn.lock").write_text("", encoding="utf-8")

    with pytest.raises(ValueError, match="conflicting package-manager lockfiles"):
        packagemanager.detect(tmp_path)


def test_init_writes_pnpm_overrides_into_workspace_yaml_for_a_standalone_repo(tmp_path: Path) -> None:
    _project(tmp_path, "pnpm-lock.yaml")
    proc = _cli("init", "--dest", str(tmp_path))
    assert proc.returncode == 0, proc.stderr

    parsed: object = json.loads((tmp_path / "package.json").read_text(encoding="utf-8"))  # pyright: ignore[reportAny] — untyped stdlib boundary
    written = manifest.as_table(parsed)
    assert "overrides" not in written, "a bare `overrides` key is ignored by pnpm"
    assert "pnpm" not in written, "pnpm 11 ignores package.json#pnpm.overrides"
    workspace = (tmp_path / "pnpm-workspace.yaml").read_text(encoding="utf-8")
    assert "eslint" not in workspace
    assert "pnpm install --no-frozen-lockfile --ignore-scripts" in proc.stdout
    assert "--ignore-workspace" not in proc.stdout


def test_pnpm_11_workspace_overrides_are_merged_in_the_workspace_yaml(tmp_path: Path) -> None:
    _project(tmp_path, "pnpm-lock.yaml")
    workspace = tmp_path / "pnpm-workspace.yaml"
    workspace.write_text("overrides:\n  rollup@<4: '>=4'\n\nallowBuilds:\n  esbuild: true\n", encoding="utf-8")

    proc = _cli("init", "--dest", str(tmp_path))

    assert proc.returncode == 0, proc.stderr
    text = workspace.read_text(encoding="utf-8")
    assert "eslint" not in text
    assert "rollup@<4" in text
    assert "allowBuilds" in text
    package: dict[str, object] = json.loads(  # pyright: ignore[reportAny] -- inspect the stdlib decoder's untyped JSON payload before asserting the serialized contract.
        (tmp_path / "package.json").read_text(encoding="utf-8")
    )
    assert "pnpm" not in package


@pytest.mark.parametrize(
    "flow",
    ["overrides: {}\n", 'overrides: {"rollup": ">=4"}\n', '"overrides": {}\n'],
)
def test_pnpm_workspace_flow_overrides_fail_without_duplicate_keys(tmp_path: Path, flow: str) -> None:
    _project(tmp_path, "pnpm-lock.yaml")
    workspace = tmp_path / "pnpm-workspace.yaml"
    workspace.write_text(flow, encoding="utf-8")

    proc = _cli("init", "--dest", str(tmp_path))

    assert proc.returncode == 2
    assert "flow-style `overrides` is unsupported" in proc.stderr
    assert workspace.read_text(encoding="utf-8") == flow


def test_init_omits_unused_yarn_override_container(tmp_path: Path) -> None:
    _project(tmp_path, "yarn.lock", {"name": "web", "packageManager": "yarn@4.15.0"})
    proc = _cli("init", "--dest", str(tmp_path))
    assert proc.returncode == 0, proc.stderr

    parsed: object = json.loads((tmp_path / "package.json").read_text(encoding="utf-8"))  # pyright: ignore[reportAny] — untyped stdlib boundary
    written = manifest.as_table(parsed)
    assert "overrides" not in written, "a bare `overrides` key is ignored by Yarn"
    assert "resolutions" not in written
    assert "yarn install --no-immutable --mode=skip-build" in proc.stdout


def test_init_bun_requires_no_retired_peer_overrides(tmp_path: Path) -> None:
    _project(tmp_path, "bun.lock", {"name": "web", "packageManager": "bun@1.2.0"})
    proc = _cli("init", "--dest", str(tmp_path))
    assert proc.returncode == 0, proc.stderr

    parsed: object = json.loads(  # pyright: ignore[reportAny] -- inspect the stdlib decoder's untyped JSON payload before asserting the serialized contract.
        (tmp_path / "package.json").read_text(encoding="utf-8")
    )
    overrides = manifest.table_field(manifest.as_table(parsed), "overrides")
    assert overrides == {}


def test_npm_preserves_an_unmanaged_override(tmp_path: Path) -> None:
    _project(
        tmp_path,
        "package-lock.json",
        {"name": "web", "overrides": {"example-plugin": "7.37.4"}},
    )

    proc = _cli("init", "--dest", str(tmp_path))

    assert proc.returncode == 0, proc.stderr
    parsed: object = json.loads((tmp_path / "package.json").read_text(encoding="utf-8"))  # pyright: ignore[reportAny] -- inspect the stdlib decoder's untyped JSON payload before asserting the serialized contract.
    overrides = manifest.table_field(manifest.as_table(parsed), "overrides")
    assert overrides["example-plugin"] == "7.37.4"


def test_npm_direct_peer_override_tracks_the_exact_pin_without_escaping_unicode(tmp_path: Path) -> None:
    _project(
        tmp_path,
        "package-lock.json",
        {
            "name": "web",
            "description": "Customer dashboard — browser client",
            "devDependencies": {"typescript": "6.0.3"},
            "overrides": {"typescript": "^6.0.3"},
        },
    )

    proc = _cli("init", "--dest", str(tmp_path))

    assert proc.returncode == 0, proc.stderr
    package_text = (tmp_path / "package.json").read_text(encoding="utf-8")
    parsed: object = json.loads(package_text)  # pyright: ignore[reportAny] -- inspect the stdlib decoder's untyped JSON payload before asserting the serialized contract.
    package = manifest.as_table(parsed)
    assert manifest.table_field(package, "devDependencies")["typescript"] == "npm:@typescript/typescript6@6.0.2"
    assert manifest.table_field(package, "overrides")["typescript"] == "$typescript"
    assert package["description"] == "Customer dashboard — browser client"
    assert "—" in package_text
    assert r"\u2014" not in package_text


def test_pnpm_workspace_policy_keeps_unrelated_package_json_pnpm_settings(tmp_path: Path) -> None:
    _project(
        tmp_path,
        "pnpm-lock.yaml",
        {"name": "web", "pnpm": {"onlyBuiltDependencies": ["esbuild"]}},
    )
    assert _cli("init", "--dest", str(tmp_path)).returncode == 0

    parsed: object = json.loads((tmp_path / "package.json").read_text(encoding="utf-8"))  # pyright: ignore[reportAny] — untyped stdlib boundary
    pnpm = manifest.table_field(manifest.as_table(parsed), "pnpm")
    assert pnpm["onlyBuiltDependencies"] == ["esbuild"]
    assert "overrides" not in pnpm
    assert "eslint" not in (tmp_path / "pnpm-workspace.yaml").read_text(encoding="utf-8")


def test_a_second_init_on_a_pnpm_repo_changes_nothing(tmp_path: Path) -> None:
    _project(tmp_path, "pnpm-lock.yaml")
    assert _cli("init", "--dest", str(tmp_path)).returncode == 0
    before_package = (tmp_path / "package.json").read_text(encoding="utf-8")
    before_workspace = (tmp_path / "pnpm-workspace.yaml").read_text(encoding="utf-8")

    second = _cli("init", "--dest", str(tmp_path))
    assert second.returncode == 0
    assert (tmp_path / "package.json").read_text(encoding="utf-8") == before_package
    assert (tmp_path / "pnpm-workspace.yaml").read_text(encoding="utf-8") == before_workspace
    assert "already pins the tested TypeScript peers and pnpm overrides" in second.stdout


def test_doctor_rejects_obsolete_package_json_pnpm_overrides(tmp_path: Path) -> None:
    _project(tmp_path, "pnpm-lock.yaml")
    assert _cli("init", "--dest", str(tmp_path)).returncode == 0
    (tmp_path / "pnpm-workspace.yaml").unlink()

    proc = _cli("doctor", "--dest", str(tmp_path))

    assert proc.returncode != 0
    assert "required pnpm 11 workspace policy is missing" in proc.stdout
    assert "pnpm-workspace.yaml" in proc.stdout


def test_the_project_root_is_the_lockfiles_directory_not_the_topmost_package_json(
    tmp_path: Path,
) -> None:
    (tmp_path / "package.json").write_text('{"packageManager": "yarn@4.15.0"}\n')
    (tmp_path / "typescript").mkdir()
    _project(tmp_path / "typescript", "yarn.lock")

    found = scaffold.detect(tmp_path)
    assert found.typescript_root == tmp_path / "typescript"
    assert found.client == PackageManager.YARN


def test_ecosystem_detection_ignores_package_metadata_inside_tool_caches(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "service"\nversion = "0.1.0"\n')
    cached = tmp_path / ".uv-cache" / "archive-v0" / "basedpyright"
    cached.mkdir(parents=True)
    (cached / "package.json").write_text('{"name":"cached-tool"}\n', encoding="utf-8")

    found = scaffold.detect(tmp_path)

    assert found.python_root == tmp_path
    assert found.typescript_root is None


def test_an_explicit_dest_overrides_detection(tmp_path: Path) -> None:
    (tmp_path / "frontend").mkdir()
    _project(tmp_path / "frontend", "package-lock.json")
    (tmp_path / "other").mkdir()
    _project(tmp_path / "other", "pnpm-lock.yaml")

    found = scaffold.detect(tmp_path, typescript_dest="other")
    assert found.typescript_root == tmp_path / "other"
    assert found.client == PackageManager.PNPM


def test_nested_lockfile_beats_an_unrelated_root_package_json(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{"name": "tooling"}\n', encoding="utf-8")
    project = tmp_path / "typescript"
    project.mkdir()
    _project(project, "yarn.lock")

    found = scaffold.detect(tmp_path)

    assert found.typescript_root == project
    assert found.typescript_install_root == project
    assert found.client is PackageManager.YARN


def test_nested_pnpm_preview_matches_the_applied_install_guidance(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{"name": "tooling"}\n', encoding="utf-8")
    project = tmp_path / "typescript"
    project.mkdir()
    _project(project, "pnpm-lock.yaml", {"name": "web", "packageManager": "pnpm@10.0.0"})

    preview = _cli("init", "--dest", str(tmp_path), "--dry-run")
    applied = _cli("init", "--dest", str(tmp_path))

    assert preview.returncode == 0, preview.stderr
    assert applied.returncode == 0, applied.stderr
    expected = "pnpm install --no-frozen-lockfile --ignore-scripts"
    assert expected in preview.stdout
    assert expected in applied.stdout
    assert "pnpm add -w" not in preview.stdout
    assert "pnpm add -w" not in applied.stdout
