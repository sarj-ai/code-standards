"""Detect package-version changes between two repository revisions."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from sarj_lint_configs.libs.release.process import ProcessRunner, run_process
from sarj_lint_configs.libs.release.registry import PublicationChecker, publication_exists, target_requirement
from sarj_lint_configs.libs.release.tags import RELEASE_TARGETS


if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path


_ADDED_JSON_VERSION = re.compile(r'(?m)^\+\s*"version"\s*:')
_ADDED_TOML_VERSION = re.compile(r"(?m)^\+version\s*=")


def changed_release_targets(
    root: Path,
    *,
    before: str,
    after: str,
    runner: ProcessRunner = run_process,
) -> Mapping[str, bool]:
    """Return deterministic target flags for a GitHub release workflow."""
    changed: dict[str, bool] = {}
    for name, target in RELEASE_TARGETS.items():
        result = runner(
            ("git", "diff", "--no-color", before, after, "--", target.manifest.as_posix()),
            cwd=root,
            capture_output=True,
        )
        pattern = _ADDED_JSON_VERSION if target.format == "json" else _ADDED_TOML_VERSION
        changed[name] = pattern.search(result.stdout) is not None
    return changed


def pending_release_targets(
    root: Path,
    *,
    before: str,
    after: str,
    runner: ProcessRunner = run_process,
    checker: PublicationChecker = publication_exists,
) -> Mapping[str, bool]:
    """Return current versions absent from their registry, including interrupted releases.

    Registry versions are immutable.  A manifest diff explains why a release
    workflow ran, but it must never make an already-public version publishable
    again when that workflow is retried.
    """
    _ = changed_release_targets(root, before=before, after=after, runner=runner)
    return {name: not checker(target_requirement(root, name)) for name in RELEASE_TARGETS}
