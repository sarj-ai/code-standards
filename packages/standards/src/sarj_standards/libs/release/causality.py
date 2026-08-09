"""Require publishable package changes to cause a package version change."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

from .changes import changed_release_targets
from .process import ProcessRunner, run_process
from .tags import RELEASE_TARGETS


if TYPE_CHECKING:
    from collections.abc import Mapping


_ARTIFACT_PREFIXES: Final[Mapping[str, tuple[str, ...]]] = MappingProxyType(
    {
        "python": ("packages/python/src/",),
        "sql": ("packages/sql/src/",),
        "iac": ("packages/iac/src/",),
        "standards": ("packages/standards/src/",),
        "typescript": ("packages/typescript/src/",),
        "tsconfig": ("packages/tsconfig/base.json", "packages/tsconfig/strict.json"),
    }
)
_ARTIFACT_FILES: Final[Mapping[str, tuple[str, ...]]] = MappingProxyType(
    {
        name: tuple(
            path
            for path in (
                target.manifest.as_posix(),
                str(target.manifest.parent / "LICENSE"),
            )
        )
        for name, target in RELEASE_TARGETS.items()
    }
)
_DISPLAY_PATH_LIMIT: Final = 3


@dataclass(frozen=True, slots=True)
class CausalityViolation:
    """Publishable files changed while their authoritative version did not."""

    target: str
    manifest: Path
    changed_paths: tuple[str, ...]

    def render(self) -> str:
        paths = ", ".join(self.changed_paths[:_DISPLAY_PATH_LIMIT])
        suffix = (
            f" (+{len(self.changed_paths) - _DISPLAY_PATH_LIMIT} more)"
            if len(self.changed_paths) > _DISPLAY_PATH_LIMIT
            else ""
        )
        return f"{self.target}: bump {self.manifest} because publishable files changed: {paths}{suffix}"


@dataclass(frozen=True, slots=True)
class ReleaseCausalityReport:
    """Deterministic artifact and version comparison between two revisions."""

    before: str
    after: str
    changed_targets: tuple[str, ...]
    bumped_targets: tuple[str, ...]
    violations: tuple[CausalityViolation, ...]

    @property
    def ok(self) -> bool:
        return not self.violations


def check_release_causality(
    root: Path,
    *,
    before: str,
    after: str,
    runner: ProcessRunner = run_process,
) -> ReleaseCausalityReport:
    """Fail when shipped package content changes under an unchanged version."""
    result = runner(("git", "diff", "--name-only", "-z", before, after, "--"), cwd=root, capture_output=True)
    changed_paths = tuple(sorted(path for path in result.stdout.split("\0") if path))
    bumped = changed_release_targets(root, before=before, after=after, runner=runner)
    by_target = {
        name: tuple(path for path in changed_paths if _belongs_to_artifact(name, path=path)) for name in RELEASE_TARGETS
    }
    changed_targets = tuple(name for name, paths in by_target.items() if paths)
    violations = tuple(
        CausalityViolation(name, RELEASE_TARGETS[name].manifest, by_target[name])
        for name in changed_targets
        if not bumped[name]
    )
    return ReleaseCausalityReport(
        before,
        after,
        changed_targets,
        tuple(name for name, changed in bumped.items() if changed),
        violations,
    )


def _belongs_to_artifact(target: str, *, path: str) -> bool:
    return path in _ARTIFACT_FILES[target] or path.startswith(_ARTIFACT_PREFIXES[target])
