from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from .changes import changed_release_targets
from .process import ProcessRunner, run_process
from .tags import (
    RELEASE_ARTIFACT_FILES,
    RELEASE_ARTIFACT_PREFIXES,
    RELEASE_TARGETS,
    ReleaseTargetId,
    has_verified_release_tag,
    read_manifest_version_text,
)


_DISPLAY_PATH_LIMIT = 3


if TYPE_CHECKING:
    from collections.abc import Callable

    type ReleaseTagChecker = Callable[..., bool]


@dataclass(frozen=True, slots=True)
class CausalityViolation:
    target: str
    manifest: Path
    version_field: str
    changed_paths: tuple[str, ...]

    def render(self) -> str:
        paths = ", ".join(self.changed_paths[:_DISPLAY_PATH_LIMIT])
        suffix = (
            f" (+{len(self.changed_paths) - _DISPLAY_PATH_LIMIT} more)"
            if len(self.changed_paths) > _DISPLAY_PATH_LIMIT
            else ""
        )
        return (
            f"{self.target}: bump {self.version_field} in {self.manifest}; publishable files changed: {paths}{suffix}"
        )


@dataclass(frozen=True, slots=True)
class SupersededReleaseViolation:
    target: str
    manifest: Path
    prior_tag: str

    def render(self) -> str:
        return f"{self.target}: cannot supersede unverified prior release {self.prior_tag}"


@dataclass(frozen=True, slots=True)
class ReleaseCausalityReport:
    before: str
    after: str
    changed_targets: tuple[str, ...]
    bumped_targets: tuple[str, ...]
    violations: tuple[CausalityViolation | SupersededReleaseViolation, ...]

    @property
    def ok(self) -> bool:
        return not self.violations


def check_release_causality(
    root: Path,
    *,
    before: str,
    after: str,
    runner: ProcessRunner = run_process,
    tag_checker: ReleaseTagChecker = has_verified_release_tag,
) -> ReleaseCausalityReport:
    result = runner(("git", "diff", "--name-only", "-z", before, after, "--"), cwd=root, capture_output=True)
    changed_paths = tuple(sorted(path for path in result.stdout.split("\0") if path))
    bumped = changed_release_targets(root, before=before, after=after, runner=runner)
    by_target = {
        name: tuple(path for path in changed_paths if _belongs_to_artifact(name, path=path)) for name in RELEASE_TARGETS
    }
    changed_targets = tuple(name for name, paths in by_target.items() if paths)
    causality_violations = tuple(
        CausalityViolation(
            name,
            RELEASE_TARGETS[name].manifest,
            'top-level "version"' if RELEASE_TARGETS[name].format == "json" else "[project].version",
            by_target[name],
        )
        for name in changed_targets
        if not bumped[name]
    )
    supersession_violations: list[SupersededReleaseViolation] = []
    for name, changed in bumped.items():
        if not changed:
            continue
        target = RELEASE_TARGETS[name]
        prior_contents = runner(
            ("git", "show", f"{before}:{target.manifest.as_posix()}"),
            cwd=root,
            capture_output=True,
        ).stdout
        prior_version = read_manifest_version_text(
            prior_contents,
            target.format,
            label=f"{before}:{target.manifest}",
        )
        target_name = ReleaseTargetId(name)
        if not tag_checker(root, target_name, version=prior_version, commit=before, runner=runner):
            supersession_violations.append(
                SupersededReleaseViolation(name, target.manifest, f"{name}-v{prior_version}")
            )
    return ReleaseCausalityReport(
        before,
        after,
        changed_targets,
        tuple(name for name, changed in bumped.items() if changed),
        (*causality_violations, *supersession_violations),
    )


def _belongs_to_artifact(target: str, *, path: str) -> bool:
    return path in RELEASE_ARTIFACT_FILES[target] or path.startswith(RELEASE_ARTIFACT_PREFIXES[target])
