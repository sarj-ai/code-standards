"""Release tag parsing and manifest-version validation."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
import tomllib
from typing import TYPE_CHECKING, Final, Literal

from sarj_lint_configs.libs.release._values import is_object_dict, string_object_dict
from sarj_lint_configs.libs.release.process import ProcessFailureError, ProcessRunner, run_process


if TYPE_CHECKING:
    from collections.abc import Mapping


ManifestFormat = Literal["json", "toml"]
_GIT_NO_MATCH = 2


@dataclass(frozen=True, slots=True)
class ReleaseTarget:
    """A release tag prefix and its authoritative manifest."""

    manifest: Path
    format: ManifestFormat


@dataclass(frozen=True, slots=True)
class ValidatedReleaseTag:
    """A tag proven to exactly match its package manifest."""

    tag: str
    target: str
    version: str
    manifest: Path


@dataclass(frozen=True, slots=True)
class TagSyncResult:
    """Remote tags created now and tags that already existed."""

    created: tuple[str, ...]
    existing: tuple[str, ...]


RELEASE_TARGETS: Final[Mapping[str, ReleaseTarget]] = {
    "typescript": ReleaseTarget(Path("packages/typescript/package.json"), "json"),
    "python": ReleaseTarget(Path("packages/python/pyproject.toml"), "toml"),
    "sql": ReleaseTarget(Path("packages/sql/pyproject.toml"), "toml"),
    "iac": ReleaseTarget(Path("packages/iac/pyproject.toml"), "toml"),
    "lint-configs": ReleaseTarget(Path("packages/lint-configs/pyproject.toml"), "toml"),
    "tsconfig": ReleaseTarget(Path("packages/tsconfig/package.json"), "json"),
}
_TAG_PATTERN: Final = re.compile(r"^(?P<target>[a-z][a-z0-9-]*)-v(?P<version>[^\s/]+)$")


def read_manifest_version(path: Path, manifest_format: ManifestFormat) -> str:
    """Read and validate a top-level package version from JSON or TOML."""
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
    """Require ``<target>-v<version>`` to exactly match the target manifest."""
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


def _current_tag(target_name: str, root: Path) -> str:
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
    """Return manifest-derived release tags missing from the ``origin`` remote."""
    resolved = root.resolve()
    tags = (_current_tag(target, resolved) for target in RELEASE_TARGETS)
    return tuple(tag for tag in tags if not _remote_tag_exists(resolved, tag, runner=runner))


def create_release_tags(
    root: Path,
    targets: tuple[str, ...],
    *,
    runner: ProcessRunner = run_process,
) -> TagSyncResult:
    """Idempotently create and push manifest-derived annotated release tags."""
    resolved = root.resolve()
    created: list[str] = []
    existing: list[str] = []
    for target in dict.fromkeys(targets):
        tag = _current_tag(target, resolved)
        if _remote_tag_exists(resolved, tag, runner=runner):
            existing.append(tag)
            continue
        try:
            runner(("git", "rev-parse", "--verify", "--quiet", f"refs/tags/{tag}"), cwd=resolved)
        except ProcessFailureError as exc:
            if exc.returncode != 1:
                raise
            version = tag.removeprefix(f"{target}-v")
            runner(("git", "tag", "-a", tag, "-m", f"{target} {version}"), cwd=resolved)
        runner(("git", "push", "origin", f"refs/tags/{tag}"), cwd=resolved)
        created.append(tag)
    return TagSyncResult(tuple(created), tuple(existing))
