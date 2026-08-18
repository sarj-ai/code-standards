from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum
import json
import math
from pathlib import Path
import re
import time
import tomllib
from types import MappingProxyType
from typing import TYPE_CHECKING, Final, Literal

from sarj_standards.libs.release._values import is_object_dict, string_object_dict
from sarj_standards.libs.release.process import ProcessFailureError, ProcessRunner, run_process


if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from sarj_standards.libs.release.registry import PublicationChecker


ManifestFormat = Literal["json", "toml"]
_GIT_NO_MATCH = 2
_GIT_MISSING_REVISION_CODES = frozenset((1, 128))
_TAGGER_EMAIL = "release-automation@sarj.ai"
_TAGGER_NAME = "sarj-ai release automation"


class ReleaseTargetId(StrEnum):
    TYPESCRIPT = "typescript"
    BOOTSTRAP = "bootstrap"
    PYTHON = "python"
    SQL = "sql"
    IAC = "iac"
    STANDARDS = "standards"
    TSCONFIG = "tsconfig"


@dataclass(frozen=True, slots=True)
class ReleaseTarget:
    manifest: Path
    format: ManifestFormat


@dataclass(frozen=True, slots=True)
class ValidatedReleaseTag:
    tag: str
    target: str
    version: str
    manifest: Path


@dataclass(frozen=True, slots=True)
class TagSyncResult:
    created: tuple[str, ...]
    existing: tuple[str, ...]


RELEASE_TARGETS: Final[Mapping[str, ReleaseTarget]] = MappingProxyType(
    {
        ReleaseTargetId.TYPESCRIPT: ReleaseTarget(Path("packages/typescript/package.json"), "json"),
        ReleaseTargetId.BOOTSTRAP: ReleaseTarget(Path("packages/bootstrap/pyproject.toml"), "toml"),
        ReleaseTargetId.PYTHON: ReleaseTarget(Path("packages/python/pyproject.toml"), "toml"),
        ReleaseTargetId.SQL: ReleaseTarget(Path("packages/sql/pyproject.toml"), "toml"),
        ReleaseTargetId.IAC: ReleaseTarget(Path("packages/iac/pyproject.toml"), "toml"),
        ReleaseTargetId.STANDARDS: ReleaseTarget(Path("packages/standards/pyproject.toml"), "toml"),
        ReleaseTargetId.TSCONFIG: ReleaseTarget(Path("packages/tsconfig/package.json"), "json"),
    }
)
RELEASE_ARTIFACT_PREFIXES: Final[Mapping[str, tuple[str, ...]]] = MappingProxyType(
    {
        ReleaseTargetId.BOOTSTRAP: ("packages/bootstrap/src/",),
        ReleaseTargetId.PYTHON: ("packages/python/src/",),
        ReleaseTargetId.SQL: ("packages/sql/src/",),
        ReleaseTargetId.IAC: ("packages/iac/src/",),
        ReleaseTargetId.STANDARDS: ("packages/standards/src/",),
        ReleaseTargetId.TYPESCRIPT: ("packages/typescript/src/",),
        ReleaseTargetId.TSCONFIG: ("packages/tsconfig/base.json", "packages/tsconfig/strict.json"),
    }
)
RELEASE_ARTIFACT_FILES: Final[Mapping[str, tuple[str, ...]]] = MappingProxyType(
    {
        name: (target.manifest.as_posix(), str(target.manifest.parent / "LICENSE"))
        for name, target in RELEASE_TARGETS.items()
    }
)
_TAG_PATTERN: Final = re.compile(r"^(?P<target>[a-z][a-z0-9-]*)-v(?P<version>[^\s/]+)$")


def read_manifest_version(path: Path, manifest_format: ManifestFormat) -> str:
    try:
        data = _read_manifest(path, manifest_format)
    except (OSError, json.JSONDecodeError, tomllib.TOMLDecodeError) as exc:
        msg = f"could not read release manifest {path}: {exc}"
        raise ValueError(msg) from exc
    version = data.get("version")
    if manifest_format == "toml" and not isinstance(version, str):
        project = data.get("project")
        project_data = string_object_dict(project, label="project table") if is_object_dict(project) else {}
        version = project_data.get("version")
    if not isinstance(version, str) or not version:
        msg = f"release manifest {path} has no non-empty package version"
        raise ValueError(msg)
    return version


def _read_manifest(path: Path, manifest_format: ManifestFormat) -> dict[str, object]:
    if manifest_format == "json":
        untyped: object = json.loads(path.read_text(encoding="utf-8"))  # pyright: ignore[reportAny]
        return string_object_dict(untyped, label="release manifest")
    with path.open("rb") as manifest:
        untyped_toml: object = tomllib.load(manifest)
        return string_object_dict(untyped_toml, label="release manifest")


def validate_release_tag(
    tag: str,
    repo_root: Path,
    *,
    targets: Mapping[str, ReleaseTarget] = RELEASE_TARGETS,
) -> ValidatedReleaseTag:
    match = _TAG_PATTERN.fullmatch(tag)
    if match is None or match["target"] not in targets:
        msg = f"unrecognized release tag: {tag}"
        raise ValueError(msg)
    target_name = match["target"]
    target = targets[target_name]
    resolved_root = repo_root.resolve()
    manifest = (resolved_root / target.manifest).resolve()
    try:
        manifest.relative_to(resolved_root)
    except ValueError as exc:
        msg = f"release manifest escapes repository root: {target.manifest}"
        raise ValueError(msg) from exc
    actual = read_manifest_version(manifest, target.format)
    tagged = match["version"]
    if tagged != actual:
        msg = f"{tag} does not match {target.manifest} version {actual}"
        raise ValueError(msg)
    return ValidatedReleaseTag(tag, target_name, actual, target.manifest)


def _current_tag(target_name: ReleaseTargetId, root: Path) -> str:
    target = RELEASE_TARGETS.get(target_name)
    if target is None:
        msg = f"unsupported release target: {target_name}"
        raise ValueError(msg)
    version = read_manifest_version(root / target.manifest, target.format)
    return f"{target_name}-v{version}"


def _remote_tag_exists(root: Path, tag: str, *, runner: ProcessRunner) -> bool:
    try:
        runner(
            ("git", "ls-remote", "--exit-code", "--tags", "origin", f"refs/tags/{tag}"),
            cwd=root,
            capture_output=True,
        )
    except ProcessFailureError as exc:
        if exc.returncode == _GIT_NO_MATCH:
            return False
        raise
    return True


def missing_remote_release_tags(
    root: Path,
    *,
    runner: ProcessRunner = run_process,
) -> tuple[str, ...]:
    resolved = root.resolve()
    tags = (_current_tag(ReleaseTargetId(target), resolved) for target in RELEASE_TARGETS)
    return tuple(tag for tag in tags if not _remote_tag_exists(resolved, tag, runner=runner))


def verify_remote_release_tags(
    root: Path,
    *,
    commit: str,
    runner: ProcessRunner = run_process,
) -> tuple[str, ...]:
    resolved = root.resolve()
    if not commit or commit.startswith("-"):
        msg = "release tag verification requires an explicit publishing commit"
        raise ValueError(msg)
    resolved_commit = (
        runner(
            ("git", "rev-parse", "--verify", f"{commit}^{{commit}}"),
            cwd=resolved,
            capture_output=True,
        ).stdout.strip()
        or commit
    )
    missing: list[str] = []
    for target_text in RELEASE_TARGETS:
        target_name = ReleaseTargetId(target_text)
        tag = _current_tag(target_name, resolved)
        if not _remote_tag_exists(resolved, tag, runner=runner):
            missing.append(tag)
            continue
        _require_remote_tag_commit(resolved, tag, target_name, resolved_commit, runner=runner)
    return tuple(missing)


def create_release_tags(
    root: Path,
    targets: tuple[str, ...],
    *,
    commit: str,
    runner: ProcessRunner = run_process,
    publication_checker: PublicationChecker | None = None,
    attempts: int = 1,
    delay: timedelta = timedelta(0),
    sleeper: Callable[[float], object] = time.sleep,
) -> TagSyncResult:
    from sarj_standards.libs.release.registry import (  # ruff: ignore[import-outside-top-level] -- avoid the tags/registry import cycle
        publication_exists,
        require_publication,
        target_requirement,
    )

    resolved = root.resolve()
    if not commit or commit.startswith("-"):
        msg = "release tag creation requires an explicit publishing commit"
        raise ValueError(msg)
    if attempts < 1:
        msg = "publication attempts must be at least one"
        raise ValueError(msg)
    delay_seconds = delay.total_seconds()
    if not math.isfinite(delay_seconds) or delay_seconds < 0:
        msg = "publication retry delay must be finite and non-negative"
        raise ValueError(msg)
    resolved_commit = (
        runner(
            ("git", "rev-parse", "--verify", f"{commit}^{{commit}}"),
            cwd=resolved,
            capture_output=True,
        ).stdout.strip()
        or commit
    )
    checker = publication_exists if publication_checker is None else publication_checker
    created: list[str] = []
    existing: list[str] = []
    for target_text in dict.fromkeys(targets):
        try:
            target = ReleaseTargetId(target_text)
        except ValueError as exc:
            msg = f"unsupported release target: {target_text}"
            raise ValueError(msg) from exc
        tag = _current_tag(target, resolved)
        if _remote_tag_exists(resolved, tag, runner=runner):
            _require_remote_tag_commit(resolved, tag, target, resolved_commit, runner=runner)
            existing.append(tag)
            continue
        requirement = target_requirement(resolved, target)
        for attempt in range(attempts):
            try:
                require_publication(requirement, checker=checker)
                break
            except OSError, ValueError:
                if attempt + 1 == attempts:
                    raise
                _ = sleeper(delay_seconds)
        if not _require_local_tag_commit(resolved, tag, resolved_commit, runner=runner):
            version = tag.removeprefix(f"{target}-v")
            runner(
                (
                    "git",
                    "-c",
                    f"user.name={_TAGGER_NAME}",
                    "-c",
                    f"user.email={_TAGGER_EMAIL}",
                    "tag",
                    "-a",
                    tag,
                    commit,
                    "-m",
                    f"{target} {version}",
                ),
                cwd=resolved,
            )
        runner(("git", "push", "origin", f"refs/tags/{tag}"), cwd=resolved)
        created.append(tag)
    return TagSyncResult(tuple(created), tuple(existing))


def _require_remote_tag_commit(
    root: Path,
    tag: str,
    target_name: ReleaseTargetId,
    commit: str,
    *,
    runner: ProcessRunner,
) -> None:
    result = runner(
        (
            "git",
            "ls-remote",
            "--exit-code",
            "--tags",
            "origin",
            f"refs/tags/{tag}",
            f"refs/tags/{tag}^{{}}",
        ),
        cwd=root,
        capture_output=True,
    )
    references = dict(line.split("\t", 1)[::-1] for line in result.stdout.splitlines() if "\t" in line)
    actual = references.get(f"refs/tags/{tag}^{{}}", references.get(f"refs/tags/{tag}"))
    if actual is None:
        msg = f"existing remote tag {tag} has no resolvable object"
        raise ValueError(msg)
    try:
        actual_commit = runner(
            ("git", "rev-parse", "--verify", f"{actual}^{{commit}}"),
            cwd=root,
            capture_output=True,
        ).stdout.strip()
    except ProcessFailureError as exc:
        msg = f"existing remote tag {tag} does not resolve to a commit"
        raise ValueError(msg) from exc
    if not actual_commit:
        msg = f"existing remote tag {tag} does not resolve to a commit"
        raise ValueError(msg)
    actual = actual_commit
    if actual == commit:
        return
    try:
        runner(
            ("git", "merge-base", "--is-ancestor", actual, commit),
            cwd=root,
            capture_output=True,
        )
    except ProcessFailureError as exc:
        msg = f"existing remote tag {tag} points to {actual}, which is not an ancestor of publishing commit {commit}"
        raise ValueError(msg) from exc
    target_paths = (*RELEASE_ARTIFACT_FILES[target_name], *RELEASE_ARTIFACT_PREFIXES[target_name])
    try:
        runner(
            ("git", "diff", "--quiet", actual or tag, commit, "--", *target_paths),
            cwd=root,
            capture_output=True,
        )
    except ProcessFailureError:
        pass
    else:
        return
    msg = f"existing remote tag {tag} points to {actual or 'an unknown object'}, not publishing commit {commit}"
    raise ValueError(msg)


def _require_local_tag_commit(root: Path, tag: str, commit: str, *, runner: ProcessRunner) -> bool:
    try:
        result = runner(
            ("git", "rev-parse", "--verify", f"refs/tags/{tag}^{{commit}}"),
            cwd=root,
            capture_output=True,
        )
    except ProcessFailureError as exc:
        if exc.returncode in _GIT_MISSING_REVISION_CODES:
            return False
        raise
    actual = result.stdout.strip()
    if actual == commit:
        return True
    msg = f"existing local tag {tag} points to {actual or 'an unknown object'}, not publishing commit {commit}"
    raise ValueError(msg)
