from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Literal

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


def _project(root: Path, tool: Literal["biome", "prettier"], *, catalog: bool = False) -> set[str]:
    _git(root, "init", "--quiet", "--template=")
    package_name, version = ("@biomejs/biome", "2.6.3") if tool == "biome" else ("prettier", "3.9.10")
    package: dict[str, object] = {
        "private": True,
        "scripts": {"format": "biome format --write ." if tool == "biome" else "prettier --write ."},
        "devDependencies": {package_name: "catalog:" if catalog else version},
    }
    (root / "package.json").write_text(json.dumps(package) + "\n", encoding="utf-8")
    if catalog:
        (root / "pnpm-workspace.yaml").write_text(f"catalog:\n  '{package_name}': {version}\n", encoding="utf-8")
        (root / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")
    else:
        (root / "package-lock.json").write_text('{"lockfileVersion":3}\n', encoding="utf-8")
    (root / ("biome.json" if tool == "biome" else ".prettierrc.json")).write_text("{}\n", encoding="utf-8")
    (root / "source.js").write_text("export const value = 1;\n", encoding="utf-8")
    (root / ".gitignore").write_text("node_modules\n", encoding="utf-8")
    directory = root / "node_modules" / package_name
    directory.mkdir(parents=True)
    (directory / "package.json").write_text(
        json.dumps({"name": package_name, "version": version, "bin": {tool: "bin/entry.js"}}) + "\n",
        encoding="utf-8",
    )
    (directory / "bin").mkdir()
    (directory / "bin/entry.js").write_text("// selection fixture only; never executed\n", encoding="utf-8")
    _git(root, "add", "--all")
    return {name for name in _git(root, "ls-files", "-z").decode().split("\0") if name}


@dataclass(frozen=True, slots=True)
class _ESLintProject:
    tracked: frozenset[str]
    node: Path
    entrypoint: Path


def _eslint_project(root: Path) -> _ESLintProject:
    _project(root, "prettier")
    (root / "package.json").write_text('{"private":true,"devDependencies":{"eslint":"10.13.0"}}\n', encoding="utf-8")
    (root / ".prettierrc.json").unlink()
    shutil.rmtree(root / "node_modules/prettier")
    package = root / "node_modules/eslint"
    (package / "bin").mkdir(parents=True)
    (package / "package.json").write_text(
        '{"name":"eslint","version":"10.13.0","bin":{"eslint":"bin/eslint.js"}}\n', encoding="utf-8"
    )
    entrypoint = package / "bin/eslint.js"
    entrypoint.write_text("// Ownership fixture only; never executed.\n", encoding="utf-8")
    node = root / "node_modules/node"
    node.write_bytes(b"Node ownership fixture; never executed\n")
    node.chmod(0o700)
    _git(root, "add", "--all")
    tracked = {name for name in _git(root, "ls-files", "-z").decode().split("\0") if name}
    return _ESLintProject(frozenset(tracked), node, entrypoint)


@pytest.mark.parametrize(("tool", "catalog"), [("biome", True), ("biome", False), ("prettier", False)])
def test_formatter_requires_explicit_script_config_and_matching_installed_exact_pin(
    tmp_path: Path,
    tool: Literal["biome", "prettier"],
    catalog: bool,
) -> None:
    tracked = _project(tmp_path, tool, catalog=catalog)
    owner = directive_formatter.select(tmp_path, "source.js", tracked, _node=lambda _cwd: Path(sys.executable))

    assert owner.invocation.tool == tool
    assert owner.version == ("2.6.3" if tool == "biome" else "3.9.10")
    assert "--write" not in owner.invocation.args
    assert "check" not in owner.invocation.args
    expected = (
        ("format", "--stdin-file-path", str(tmp_path / "source.js"), "--config-path", str(tmp_path / "biome.json"))
        if tool == "biome"
        else ("--config", str(tmp_path / ".prettierrc.json"), "--stdin-filepath", str(tmp_path / "source.js"))
    )
    assert owner.invocation.args == expected
    assert len(owner.runtimes) == 1
    assert len(owner.runtimes[0].sha256) == 64
    assert any(proof.path == tmp_path / "package.json" for proof in owner.inputs)
    directive_formatter.validate(owner)


def test_biome_check_selects_only_its_frozen_formatter_component(tmp_path: Path) -> None:
    tracked = _project(tmp_path, "biome")
    package_path = tmp_path / "package.json"
    package = {
        "private": True,
        "scripts": {"format": "biome check --write ."},
        "devDependencies": {"@biomejs/biome": "2.6.3"},
    }
    package_path.write_text(json.dumps(package) + "\n", encoding="utf-8")
    package_bytes = package_path.read_bytes()
    source_bytes = (tmp_path / "source.js").read_bytes()
    index_bytes = (tmp_path / ".git/index").read_bytes()

    owner = directive_formatter.select(tmp_path, "source.js", tracked, _node=lambda _cwd: Path(sys.executable))

    assert owner.invocation.tool == "biome"
    assert owner.invocation.args == (
        "format",
        "--stdin-file-path",
        str(tmp_path / "source.js"),
        "--config-path",
        str(tmp_path / "biome.json"),
    )
    assert any(proof.path == package_path and proof.contents == package_bytes for proof in owner.inputs)
    directive_formatter.validate(owner)
    assert (tmp_path / "source.js").read_bytes() == source_bytes
    assert (tmp_path / ".git/index").read_bytes() == index_bytes

    package_path.write_bytes(package_bytes + b" ")
    with pytest.raises(ValueError, match="changed"):
        directive_formatter.validate(owner)


@pytest.mark.parametrize(
    "script",
    ["biome check --write --unsafe .", "biome check --write . && echo changed", "node scripts/format.js"],
)
def test_biome_check_does_not_authorize_unsafe_flags_or_arbitrary_wrappers(tmp_path: Path, script: str) -> None:
    tracked = _project(tmp_path, "biome")
    path = tmp_path / "package.json"
    package = {"private": True, "scripts": {"format": script}, "devDependencies": {"@biomejs/biome": "2.6.3"}}
    path.write_text(json.dumps(package) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="unsupported project formatter wrapper"):
        directive_formatter.select(tmp_path, "source.js", tracked, _node=lambda _cwd: Path(sys.executable))


@pytest.mark.parametrize("mutation", ["replace", "remove"])
def test_engine_without_formatter_rejects_changed_cached_runtime(tmp_path: Path, mutation: str) -> None:
    tracked = _project(tmp_path, "prettier")
    (tmp_path / "package.json").write_text('{"devDependencies":{"eslint":"10.13.0"}}\n', encoding="utf-8")
    installed = tmp_path / "node_modules/eslint"
    (installed / "bin").mkdir(parents=True)
    (installed / "package.json").write_text(
        '{"name":"eslint","version":"10.13.0","bin":{"eslint":"bin/eslint.js"}}\n', encoding="utf-8"
    )
    (installed / "bin/eslint.js").write_text("// selection fixture; never executed\n", encoding="utf-8")
    runtime = tmp_path / "private-node"
    runtime.write_bytes(b"private runtime identity fixture\n")
    runtime.chmod(0o700)
    runtimes: dict[Path, directive_formatter.RuntimeProof] = {}

    owner = directive_formatter.eslint_engine(
        tmp_path, tmp_path, tracked, runtimes=runtimes, _node=lambda _cwd: runtime
    )

    assert owner.invocation.tool == "eslint"
    assert owner.invocation.entrypoint == installed / "bin/eslint.js"
    assert not owner.invocation.args
    directive_formatter.validate(owner)
    if mutation == "remove":
        runtime.unlink()
    else:
        runtime.write_bytes(b"replaced runtime identity fixture\n")
    with pytest.raises(directive_formatter.OwnershipChangedError, match="Node runtime changed"):
        directive_formatter.eslint_engine(tmp_path, tmp_path, tracked, runtimes=runtimes, _node=lambda _cwd: runtime)


def test_ownership_input_removed_after_capture_is_drift(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tracked = _project(tmp_path, "prettier")
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
        "missing-script",
        "wrapper",
        "range",
        "wrong-installed",
        "duplicate-config",
        "untracked-config",
        "dynamic-config",
        "embedded-config",
        "plugins",
        "extends",
        "outside-package",
        "missing-lock",
        "two-locks",
        "duplicate-json",
    ],
)
def test_ambiguous_or_unsupported_owner_refuses_before_native_execution(
    tmp_path: Path,
    case: str,
) -> None:
    tracked = _project(tmp_path, "prettier")
    package_path = tmp_path / "package.json"
    package: dict[str, object] = {
        "private": True,
        "scripts": {"format": "prettier --write ."},
        "devDependencies": {"prettier": "3.9.10"},
    }
    match case:
        case "missing-script":
            package.pop("scripts")
        case "wrapper":
            package["scripts"] = {"format": "node scripts/format.js"}
        case "range":
            package["devDependencies"] = {"prettier": "^3.9.10"}
        case "embedded-config":
            package["prettier"] = {"semi": False}
        case "wrong-installed":
            installed = tmp_path / "node_modules/prettier/package.json"
            installed.write_text('{"name":"prettier","version":"3.9.9","bin":"bin/entry.js"}\n', encoding="utf-8")
        case "duplicate-config":
            (tmp_path / ".prettierrc").write_text("{}\n", encoding="utf-8")
            tracked.add(".prettierrc")
        case "untracked-config":
            tracked.remove(".prettierrc.json")
        case "dynamic-config":
            (tmp_path / ".prettierrc.json").unlink()
            (tmp_path / "prettier.config.mjs").write_text("export default {};\n", encoding="utf-8")
            tracked.add("prettier.config.mjs")
        case "plugins" | "extends":
            (tmp_path / ".prettierrc.json").write_text(json.dumps({case: ["external"]}), encoding="utf-8")
        case "outside-package":
            package_directory = tmp_path / "node_modules/prettier"
            foreign = tmp_path.parent / f"foreign-{tmp_path.name}"
            package_directory.rename(foreign)
            package_directory.symlink_to(foreign, target_is_directory=True)
        case "missing-lock":
            (tmp_path / "package-lock.json").unlink()
        case "two-locks":
            (tmp_path / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")
            tracked.add("pnpm-lock.yaml")
        case "duplicate-json":
            (tmp_path / ".prettierrc.json").write_text('{"semi":true,"semi":false}\n', encoding="utf-8")
        case _:
            pytest.fail(f"unknown formatter owner boundary: {case}")
    package_path.write_text(json.dumps(package) + "\n", encoding="utf-8")

    with pytest.raises((OSError, ValueError)):
        directive_formatter.select(tmp_path, "source.js", tracked, _node=lambda _cwd: Path(sys.executable))


def test_catalog_duplicate_keys_are_not_a_pin_proof(tmp_path: Path) -> None:
    tracked = _project(tmp_path, "biome", catalog=True)
    (tmp_path / "pnpm-workspace.yaml").write_text(
        "catalog:\n  '@biomejs/biome': 2.6.3\n  '@biomejs/biome': 2.6.2\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate"):
        directive_formatter.select(tmp_path, "source.js", tracked, _node=lambda _cwd: Path(sys.executable))


@pytest.mark.parametrize(
    "name",
    ["package.json", ".prettierrc.json", "package-lock.json", ".gitignore", "node_modules/prettier/bin/entry.js"],
)
def test_frozen_configuration_and_pin_inputs_reject_later_changes(
    tmp_path: Path,
    name: str,
) -> None:
    tracked = _project(tmp_path, "prettier")
    owner = directive_formatter.select(tmp_path, "source.js", tracked, _node=lambda _cwd: Path(sys.executable))
    path = tmp_path / name
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="changed"):
        directive_formatter.validate(owner)


@pytest.mark.parametrize("name", [".prettierrc", ".editorconfig", ".ignore", ".git/info/exclude", ".mise.toml"])
def test_new_configuration_or_ignore_input_invalidates_frozen_absence_proof(
    tmp_path: Path,
    name: str,
) -> None:
    tracked = _project(tmp_path, "prettier")
    owner = directive_formatter.select(tmp_path, "source.js", tracked, _node=lambda _cwd: Path(sys.executable))
    added = tmp_path / name
    added.parent.mkdir(parents=True, exist_ok=True)
    added.write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="changed"):
        directive_formatter.validate(owner)


def test_eslint_engine_binds_its_exact_local_pin_without_requiring_a_formatter(tmp_path: Path) -> None:
    project = _eslint_project(tmp_path)
    with pytest.raises(ValueError, match="explicit project-owned native formatter"):
        directive_formatter.select(tmp_path, "source.js", project.tracked, _node=lambda _cwd: project.node)

    owner = directive_formatter.eslint_engine(tmp_path, tmp_path, project.tracked, _node=lambda _cwd: project.node)

    assert owner.version == "10.13.0"
    assert owner.invocation.tool == "eslint"
    assert owner.invocation.node == project.node
    assert owner.invocation.entrypoint == project.entrypoint
    assert owner.invocation.cwd == tmp_path
    assert not owner.invocation.args
    assert {proof.path for proof in owner.inputs} == {
        tmp_path / "package.json",
        tmp_path / "package-lock.json",
        tmp_path / "node_modules/eslint/package.json",
        project.entrypoint,
    }
    assert [proof.path for proof in owner.runtimes] == [project.node]
    directive_formatter.validate(owner)


@pytest.mark.parametrize(
    "name",
    ["package.json", "package-lock.json", "node_modules/eslint/package.json", "node_modules/eslint/bin/eslint.js"],
)
def test_eslint_engine_rejects_changed_ownership_even_without_a_formatter(tmp_path: Path, name: str) -> None:
    project = _eslint_project(tmp_path)
    owner = directive_formatter.eslint_engine(tmp_path, tmp_path, project.tracked, _node=lambda _cwd: project.node)
    path = tmp_path / name
    path.write_bytes(path.read_bytes() + b" ")

    with pytest.raises(ValueError, match="changed"):
        directive_formatter.validate(owner)


@pytest.mark.parametrize("change", ["bytes", "removed"])
def test_eslint_engine_never_rebinds_a_previously_established_runtime(tmp_path: Path, change: str) -> None:
    project = _eslint_project(tmp_path)
    runtimes: dict[Path, directive_formatter.RuntimeProof] = {}
    owner = directive_formatter.eslint_engine(
        tmp_path, tmp_path, project.tracked, runtimes=runtimes, _node=lambda _cwd: project.node
    )
    if change == "removed":
        project.node.unlink()
    else:
        project.node.write_bytes(project.node.read_bytes() + b" changed")

    with pytest.raises((OSError, ValueError)):
        directive_formatter.validate(owner)
    with pytest.raises((OSError, ValueError)):
        directive_formatter.eslint_engine(
            tmp_path, tmp_path, project.tracked, runtimes=runtimes, _node=lambda _cwd: project.node
        )
