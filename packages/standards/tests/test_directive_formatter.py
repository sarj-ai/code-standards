from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from sarj_standards.libs.linting import directive_formatter
from sarj_standards.libs.staged_git import isolated_environment


def _git(root: Path, *arguments: str) -> bytes:
    return subprocess.run(
        ("git", "--no-optional-locks", "-C", str(root), *arguments),
        env=isolated_environment(),
        capture_output=True,
        check=True,
        timeout=30,
    ).stdout


def _project(root: Path, *, catalog: bool = False, config: str = ".oxfmtrc.json") -> set[str]:
    _git(root, "init", "--quiet", "--template=")
    package: dict[str, object] = {"private": True, "devDependencies": {"oxfmt": "catalog:" if catalog else "0.76.0"}}
    (root / "package.json").write_text(json.dumps(package) + "\n", encoding="utf-8")
    if catalog:
        (root / "pnpm-workspace.yaml").write_text("catalog:\n  oxfmt: 0.76.0\n", encoding="utf-8")
        (root / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")
    else:
        (root / "package-lock.json").write_text('{"lockfileVersion":3}\n', encoding="utf-8")
    (root / config).write_text("{}\n" if config.endswith(".json") else "export default {};\n", encoding="utf-8")
    if config.endswith(".mts"):
        (root / "oxfmt.strict.mts").write_text("export function createConfig() {}\n", encoding="utf-8")
    (root / "source.js").write_text("export const value = 1;\n", encoding="utf-8")
    (root / ".gitignore").write_text("node_modules\n", encoding="utf-8")
    directory = root / "node_modules" / "oxfmt"
    directory.mkdir(parents=True)
    (directory / "package.json").write_text(
        json.dumps({"name": "oxfmt", "version": "0.76.0", "bin": {"oxfmt": "bin/entry.js"}}) + "\n",
        encoding="utf-8",
    )
    (directory / "bin").mkdir()
    (directory / "bin/entry.js").write_text("// selection fixture only; never executed\n", encoding="utf-8")
    _git(root, "add", "--all")
    return {name for name in _git(root, "ls-files", "-z").decode().split("\0") if name}


@pytest.mark.parametrize(
    ("catalog", "config"), [(False, ".oxfmtrc.json"), (True, ".oxfmtrc.json"), (False, "oxfmt.config.mts")]
)
def test_formatter_requires_a_config_and_matching_installed_exact_pin(
    tmp_path: Path, *, catalog: bool, config: str
) -> None:
    tracked = _project(tmp_path, catalog=catalog, config=config)
    owner = directive_formatter.select(tmp_path, "source.js", tracked, _node=lambda _cwd: Path(sys.executable))

    assert owner.invocation.tool == "oxfmt"
    assert owner.version == "0.76.0"
    assert owner.invocation.cwd == tmp_path
    assert owner.invocation.args == (f"--config={tmp_path / config}", f"--stdin-filepath={tmp_path / 'source.js'}")
    assert len(owner.runtimes) == 1
    assert len(owner.runtimes[0].sha256) == 64
    proven = {proof.path for proof in owner.inputs}
    assert {tmp_path / "package.json", tmp_path / config} <= proven
    # The managed TypeScript config spreads the synced policy module, so it is an input too.
    assert (tmp_path / "oxfmt.strict.mts" in proven) is config.endswith(".mts")
    assert directive_formatter.configured(tmp_path, "source.js")
    directive_formatter.validate(owner)


def test_sources_without_an_oxfmt_config_have_no_formatter(tmp_path: Path) -> None:
    _project(tmp_path)
    (tmp_path / ".oxfmtrc.json").unlink()

    assert not directive_formatter.configured(tmp_path, "source.js")


@pytest.mark.parametrize("mutation", ["replace", "remove"])
def test_formatter_rejects_a_changed_cached_runtime(tmp_path: Path, mutation: str) -> None:
    tracked = _project(tmp_path)
    runtime = tmp_path / "private-node"
    runtime.write_bytes(b"private runtime identity fixture\n")
    runtime.chmod(0o700)
    runtimes: dict[Path, directive_formatter.RuntimeProof] = {}

    owner = directive_formatter.select(tmp_path, "source.js", tracked, runtimes=runtimes, _node=lambda _cwd: runtime)

    assert owner.invocation.tool == "oxfmt"
    directive_formatter.validate(owner)
    if mutation == "remove":
        runtime.unlink()
    else:
        runtime.write_bytes(b"replaced runtime identity fixture\n")
    with pytest.raises(directive_formatter.OwnershipChangedError, match="Node runtime changed"):
        directive_formatter.select(tmp_path, "source.js", tracked, runtimes=runtimes, _node=lambda _cwd: runtime)


def test_ownership_input_removed_after_capture_is_drift(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tracked = _project(tmp_path)
    package = tmp_path / "package.json"
    read_bytes = Path.read_bytes

    def read_then_remove(path: Path) -> bytes:
        captured = read_bytes(path)
        if path == package:
            path.unlink()
        return captured

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- remove the private manifest after its real read to exercise public owner validation.
        Path, "read_bytes", read_then_remove
    )
    with pytest.raises(directive_formatter.OwnershipChangedError, match="ownership input changed while reading"):
        directive_formatter.select(tmp_path, "source.js", tracked, _node=lambda _cwd: Path(sys.executable))


@pytest.mark.parametrize(
    "case",
    [
        "missing-config",
        "range",
        "wrong-installed",
        "duplicate-config",
        "untracked-config",
        "outside-package",
        "missing-lock",
        "two-locks",
    ],
)
def test_ambiguous_or_unsupported_owner_refuses_before_native_execution(
    tmp_path: Path,
    case: str,
) -> None:
    tracked = _project(tmp_path)
    package_path = tmp_path / "package.json"
    package: dict[str, object] = {"private": True, "devDependencies": {"oxfmt": "0.76.0"}}
    match case:
        case "missing-config":
            (tmp_path / ".oxfmtrc.json").unlink()
        case "range":
            package["devDependencies"] = {"oxfmt": "^0.76.0"}
        case "wrong-installed":
            installed = tmp_path / "node_modules/oxfmt/package.json"
            installed.write_text('{"name":"oxfmt","version":"0.75.0","bin":"bin/entry.js"}\n', encoding="utf-8")
        case "duplicate-config":
            (tmp_path / ".oxfmtrc.jsonc").write_text("{}\n", encoding="utf-8")
            tracked.add(".oxfmtrc.jsonc")
        case "untracked-config":
            tracked.remove(".oxfmtrc.json")
        case "outside-package":
            package_directory = tmp_path / "node_modules/oxfmt"
            foreign = tmp_path.parent / f"foreign-{tmp_path.name}"
            package_directory.rename(foreign)
            package_directory.symlink_to(foreign, target_is_directory=True)
        case "missing-lock":
            (tmp_path / "package-lock.json").unlink()
        case "two-locks":
            (tmp_path / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")
            tracked.add("pnpm-lock.yaml")
        case _:
            pytest.fail(f"unknown formatter owner boundary: {case}")
    package_path.write_text(json.dumps(package) + "\n", encoding="utf-8")

    with pytest.raises((OSError, ValueError)):
        directive_formatter.select(tmp_path, "source.js", tracked, _node=lambda _cwd: Path(sys.executable))


def test_catalog_duplicate_keys_are_not_a_pin_proof(tmp_path: Path) -> None:
    tracked = _project(tmp_path, catalog=True)
    (tmp_path / "pnpm-workspace.yaml").write_text("catalog:\n  oxfmt: 0.76.0\n  oxfmt: 0.75.0\n", encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        directive_formatter.select(tmp_path, "source.js", tracked, _node=lambda _cwd: Path(sys.executable))


@pytest.mark.parametrize(
    "name",
    ["package.json", ".oxfmtrc.json", "package-lock.json", ".gitignore", "node_modules/oxfmt/bin/entry.js"],
)
def test_frozen_configuration_and_pin_inputs_reject_later_changes(
    tmp_path: Path,
    name: str,
) -> None:
    tracked = _project(tmp_path)
    owner = directive_formatter.select(tmp_path, "source.js", tracked, _node=lambda _cwd: Path(sys.executable))
    path = tmp_path / name
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="changed"):
        directive_formatter.validate(owner)


@pytest.mark.parametrize(
    "name", [".oxfmtrc.jsonc", ".prettierignore", ".editorconfig", ".ignore", ".git/info/exclude", ".mise.toml"]
)
def test_new_configuration_or_ignore_input_invalidates_frozen_absence_proof(
    tmp_path: Path,
    name: str,
) -> None:
    tracked = _project(tmp_path)
    owner = directive_formatter.select(tmp_path, "source.js", tracked, _node=lambda _cwd: Path(sys.executable))
    added = tmp_path / name
    added.parent.mkdir(parents=True, exist_ok=True)
    added.write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="changed"):
        directive_formatter.validate(owner)


def _link_from_pnpm_global_virtual_store(root: Path, *, linker: str = "isolated", recorded: str = "links") -> Path:
    store = root.parent / f"pnpm-store-{root.name}" / "v11"
    package = store / "links/@/oxfmt/0.76.0/0123abcd/node_modules/oxfmt"
    local = root / "node_modules/oxfmt"
    package.parent.mkdir(parents=True)
    local.rename(package)
    local.symlink_to(package, target_is_directory=True)
    state = {"nodeLinker": linker, "virtualStoreDir": os.path.relpath(store / recorded, root / "node_modules")}
    (root / "node_modules/.modules.yaml").write_text(json.dumps(state) + "\n", encoding="utf-8")
    return package


def test_pnpm_global_virtual_store_install_is_the_formatter_owner(tmp_path: Path) -> None:
    tracked = _project(tmp_path, catalog=True)
    package = _link_from_pnpm_global_virtual_store(tmp_path)

    owner = directive_formatter.select(tmp_path, "source.js", tracked, _node=lambda _cwd: Path(sys.executable))

    assert owner.version == "0.76.0"
    assert owner.invocation.entrypoint == (package / "bin/entry.js").resolve()
    (tmp_path / "node_modules/.modules.yaml").write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="changed"):
        directive_formatter.validate(owner)


@pytest.mark.parametrize(("linker", "recorded"), [("hoisted", "links"), ("isolated", "elsewhere/links")])
def test_formatter_outside_the_recorded_pnpm_virtual_store_is_refused(
    tmp_path: Path, linker: str, recorded: str
) -> None:
    tracked = _project(tmp_path, catalog=True)
    _link_from_pnpm_global_virtual_store(tmp_path, linker=linker, recorded=recorded)

    with pytest.raises(ValueError, match="outside repository-local node_modules"):
        directive_formatter.select(tmp_path, "source.js", tracked, _node=lambda _cwd: Path(sys.executable))
