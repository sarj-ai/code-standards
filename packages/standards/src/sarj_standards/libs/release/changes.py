from __future__ import annotations

import re
from typing import TYPE_CHECKING

from sarj_standards.libs.release.process import ProcessRunner, run_process
from sarj_standards.libs.release.registry import PublicationChecker, publication_exists, target_requirements
from sarj_standards.libs.release.tags import RELEASE_TARGETS, release_manifests


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
    changed: dict[str, bool] = {}
    for name, target in RELEASE_TARGETS.items():
        changed[name] = any(
            (_ADDED_JSON_VERSION if manifest_format == "json" else _ADDED_TOML_VERSION).search(
                runner(
                    ("git", "diff", "--no-color", before, after, "--", manifest.as_posix()),
                    cwd=root,
                    capture_output=True,
                ).stdout
            )
            is not None
            for manifest, manifest_format in release_manifests(target)
        )
    return changed


def pending_release_targets(
    root: Path,
    *,
    before: str,
    after: str,
    runner: ProcessRunner = run_process,
    checker: PublicationChecker = publication_exists,
) -> Mapping[str, bool]:
    _ = changed_release_targets(root, before=before, after=after, runner=runner)
    return {name: not all(checker(item) for item in target_requirements(root, name)) for name in RELEASE_TARGETS}
