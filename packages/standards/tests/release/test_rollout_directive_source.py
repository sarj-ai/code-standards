from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import stat
import subprocess
from types import MappingProxyType
from typing import TYPE_CHECKING

import pytest

from sarj_standards import __version__
from sarj_standards.libs.adoption.lifecycle import Command
from sarj_standards.libs.adoption.manifest import Manifest
from sarj_standards.libs.linting import eslint_directives
from sarj_standards.libs.release import rollout


if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence


_BEFORE = b"// eslint-disable-next-line no-console\nexport const VALUE = 1;\n"
_AFTER = b" \nexport const VALUE = 1;\n"


def _fixture_environment() -> dict[str, str]:
    environment = {
        name: value
        for name, value in os.environ.items()  # ruff: ignore[banned-api] -- private Git fixtures cannot inherit a parent hook's active repository/index.
        if not name.startswith("GIT_")
    }
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    return environment


class _Runner:
    def run(
        self,
        command: Sequence[str],
        *,
        cwd: Path | None = None,
        check: bool = True,
        env: Mapping[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        environment = _fixture_environment()
        if env is not None:
            environment.update({name: value for name, value in env.items() if not name.startswith("GIT_")})
        return rollout.SubprocessRunner(command_timeout=5).run(command, cwd=cwd, check=check, env=environment)


def _git(root: Path, *arguments: str) -> bytes:
    return subprocess.check_output(
        ("git", "--no-optional-locks", "--literal-pathspecs", *arguments),
        cwd=root,
        env=_fixture_environment(),
    )


@dataclass(frozen=True, slots=True)
class _RepositoryFixture:
    source: Path
    base_sha: str


def _repository(root: Path, *, object_format: str = "sha1") -> _RepositoryFixture:
    _git(root, "init", "--template=", f"--object-format={object_format}", "-q")
    _git(root, "config", "core.hooksPath", str(root / ".git/hooks"))
    _git(root, "config", "user.name", "Private native-proof fixture")
    _git(root, "config", "user.email", "fixture@example.invalid")
    _git(root, "config", "commit.gpgsign", "false")
    source = root / "literal[glob].ts"
    source.write_bytes(_BEFORE)
    source.chmod(0o640)
    manifest = Manifest(__version__, ("eslint",), ".", ".")
    (root / ".sarj-standards.toml").write_text(manifest.render(), encoding="utf-8")
    _git(root, "add", "--all")
    _git(root, "commit", "-qm", "fixture base")
    return _RepositoryFixture(source, _git(root, "rev-parse", "HEAD").decode().strip())


def _proof(source: Path) -> Mapping[str, eslint_directives.SourcePostimage]:
    return MappingProxyType(
        {source.name: eslint_directives.SourcePostimage(_BEFORE, _AFTER, stat.S_IMODE(source.stat().st_mode))}
    )


@pytest.mark.parametrize("object_format", ["sha1", "sha256"])
def test_directive_commit_proof_requires_the_actual_git_blob_and_mode(tmp_path: Path, object_format: str) -> None:
    source = _repository(tmp_path, object_format=object_format).source
    expected = _proof(source)
    source.write_bytes(_AFTER)
    runner = _Runner()

    with pytest.raises(rollout.RolloutError, match="committed source differs"):
        rollout.validate_rollout_directives(tmp_path, expected, runner, revision="HEAD")

    _git(tmp_path, "add", "--", source.name)
    _git(tmp_path, "commit", "-qm", "canonical directive projection")
    assert rollout.validate_rollout_directives(tmp_path, expected, runner, revision="HEAD") == frozenset({source.name})
    assert stat.S_IMODE(source.stat().st_mode) == 0o640


@pytest.mark.parametrize("mutation", ["body", "mode", "symlink"])
def test_same_allowed_path_cannot_hide_an_unplanned_source_or_mode_change(tmp_path: Path, mutation: str) -> None:
    source = _repository(tmp_path).source
    expected = _proof(source)
    source.write_bytes(_AFTER)
    match mutation:
        case "body":
            source.write_bytes(_AFTER.replace(b"VALUE", b"RENAMED"))
        case "mode":
            source.chmod(0o600)
        case "symlink":
            target = tmp_path / "outside-allowance.ts"
            target.write_bytes(_AFTER)
            source.unlink()
            source.symlink_to(target)
        case _:
            pytest.fail(f"unknown directive postimage mutation: {mutation}")
    before_index = (tmp_path / ".git/index").read_bytes()
    before_head = _git(tmp_path, "rev-parse", "HEAD")

    with pytest.raises(rollout.RolloutError, match="immutable native ESLint directive postimage"):
        rollout.amend_safe_changes(
            tmp_path,
            _Runner(),
            version="1.2.4",
            allowed_workflow_paths=frozenset(),
            directive_rewrites=expected,
        )

    assert (tmp_path / ".git/index").read_bytes() == before_index
    assert _git(tmp_path, "rev-parse", "HEAD") == before_head


@pytest.mark.parametrize("unrelated", ["other.ts", "suppression-baseline.json"])
def test_directive_allowance_keeps_unrelated_source_and_baseline_gates(tmp_path: Path, unrelated: str) -> None:
    source = _repository(tmp_path).source
    expected = _proof(source)
    source.write_bytes(_AFTER)
    (tmp_path / unrelated).write_text("unplanned change\n", encoding="utf-8")
    before_index = (tmp_path / ".git/index").read_bytes()

    with pytest.raises(rollout.RolloutError, match="protected paths"):
        rollout.amend_safe_changes(
            tmp_path,
            _Runner(),
            version="1.2.4",
            allowed_workflow_paths=frozenset(),
            directive_rewrites=expected,
        )

    assert (tmp_path / ".git/index").read_bytes() == before_index


def test_exact_native_source_projection_can_amend_and_then_converges_without_another_write(
    tmp_path: Path,
) -> None:
    source = _repository(tmp_path).source
    expected = _proof(source)
    source.write_bytes(_AFTER)
    runner = _Runner()

    assert rollout.amend_safe_changes(
        tmp_path,
        runner,
        version="1.2.4",
        allowed_workflow_paths=frozenset(),
        directive_rewrites=expected,
    )
    committed = _git(tmp_path, "rev-parse", "HEAD")
    assert rollout.validate_rollout_directives(tmp_path, expected, runner, revision="HEAD") == frozenset({source.name})
    assert not rollout.amend_safe_changes(
        tmp_path,
        runner,
        version="1.2.4",
        allowed_workflow_paths=frozenset(),
        directive_rewrites=expected,
    )
    assert _git(tmp_path, "rev-parse", "HEAD") == committed
    assert _git(tmp_path, "status", "--porcelain", "-z") == b""


def test_installer_body_changes_cannot_be_laundered_by_a_later_native_directive_plan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _repository(tmp_path)
    source, base = fixture.source, fixture.base_sha
    changed_before = _BEFORE.replace(b"VALUE", b"RENAMED")
    changed_after = _AFTER.replace(b"VALUE", b"RENAMED")
    source.write_bytes(changed_before)
    expected = MappingProxyType({source.name: eslint_directives.SourcePostimage(changed_before, changed_after, 0o640)})

    def canonical_plan(
        root: Path,
        paths: Sequence[str],
        *,
        run: Callable[[Command], subprocess.CompletedProcess[str]],
    ) -> Mapping[str, eslint_directives.SourcePostimage]:
        assert root == tmp_path
        assert tuple(paths) == (source.name,)
        assert callable(run)
        return expected

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- supply only the native-plan protocol to test immutable Git-base rejection before any source write; the native planner has a separate actual ESLint fixture.
        eslint_directives, "plan", canonical_plan
    )
    before_index = (tmp_path / ".git/index").read_bytes()

    with pytest.raises(rollout.RolloutError, match="committed source differs"):
        rollout.prepare_unused_eslint_directives(
            tmp_path,
            _Runner(),
            (),
            environment={},
            version=__version__,
            base_sha=base,
        )

    assert source.read_bytes() == changed_before
    assert (tmp_path / ".git/index").read_bytes() == before_index


class _EnvironmentRunner(_Runner):
    def __init__(self) -> None:
        self.environments: list[dict[str, str]] = []

    def run(
        self,
        command: Sequence[str],
        *,
        cwd: Path | None = None,
        check: bool = True,
        env: Mapping[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        assert env is not None
        self.environments.append(dict(env))
        if tuple(command) == ("fixture-native",):
            assert cwd is not None
            return subprocess.CompletedProcess(command, 0, "", "")
        return super().run(command, cwd=cwd, check=check, env=env)


def test_initial_native_callback_filters_output_overrides_without_mutating_the_supplied_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _repository(tmp_path)
    source, base = fixture.source, fixture.base_sha
    before_index = (tmp_path / ".git/index").read_bytes()
    unsafe = {
        "NODE_OPTIONS": "--require=/outside/injection",
        "NODE_PATH": "/outside/modules",
        "NODE_V8_COVERAGE": str(tmp_path),
        "NODE_COMPILE_CACHE": str(tmp_path),
        "NODE_REDIRECT_WARNINGS": str(source),
        "GIT_DIR": "/outside/git",
        "GIT_INDEX_FILE": "/outside/index",
        "BIOME_BINARY": "/outside/native",
    }
    supplied = MappingProxyType({**unsafe, "CI": "true", "NODE_ENV": "production"})
    runner = _EnvironmentRunner()

    def observe_callback(
        root: Path,
        paths: Sequence[str],
        *,
        run: Callable[[Command], subprocess.CompletedProcess[str]],
    ) -> Mapping[str, eslint_directives.SourcePostimage]:
        assert root == tmp_path
        assert tuple(paths) == (source.name,)
        assert run(Command("observe environment", ("fixture-native",), root)).returncode == 0
        return MappingProxyType({})

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- observe the supplied native callback environment; actual ESLint/formatter execution has a separate native proof and file transactions are not intercepted.
        eslint_directives, "plan", observe_callback
    )
    planned = rollout.prepare_unused_eslint_directives(
        tmp_path, runner, (), environment=supplied, version=__version__, base_sha=base
    )

    assert not planned
    assert len(runner.environments) == 2
    for observed in runner.environments:
        assert all(name not in observed for name in unsafe)
        assert observed["GIT_OPTIONAL_LOCKS"] == "0"
        assert observed["GIT_TERMINAL_PROMPT"] == "0"
        assert observed["CI"] == "true"
        assert observed["NODE_ENV"] == "production"
    assert dict(supplied) == {**unsafe, "CI": "true", "NODE_ENV": "production"}
    assert source.read_bytes() == _BEFORE
    assert (tmp_path / ".git/index").read_bytes() == before_index
