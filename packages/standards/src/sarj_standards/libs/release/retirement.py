from __future__ import annotations

import stat
from typing import TYPE_CHECKING, NamedTuple

from sarj_standards import __version__
from sarj_standards.libs.adoption import doctor, retired_suppressions


if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path


class NativePinRewrite(NamedTuple):
    contents: bytes
    mode: str


def expected_rewrites(
    root: Path, managed_paths: frozenset[str], *, target_version: str = __version__
) -> dict[str, bytes]:
    expected = {
        rewrite.path.relative_to(root).as_posix(): rewrite.contents.encode("utf-8")
        for rewrite in retired_suppressions.plan(doctor.authored_files(root))
        if rewrite.path.relative_to(root).as_posix() not in managed_paths
        and (rewrite.path.suffix in {".py", ".pyi"} or rewrite.path.name == "suppression-baseline.json")
    }
    if expected and target_version != __version__:
        msg = (
            f"retired suppression planning requires controller {target_version}; running {__version__}. "
            "Run the rollout controller from the exact target bundle."
        )
        raise ValueError(msg)
    return expected


def validate_rewrites(root: Path, expected: Mapping[str, bytes]) -> frozenset[str]:
    for relative, contents in expected.items():
        path = root / relative
        if (
            not path.resolve().is_relative_to(root.resolve())
            or path.is_symlink()
            or not path.is_file()
            or path.read_bytes() != contents
        ):
            msg = f"retired suppression migration differs from the canonical rewrite: {relative}"
            raise ValueError(msg)
    return frozenset(expected)


def validate_native_pins(root: Path, expected: Mapping[str, NativePinRewrite]) -> frozenset[str]:
    try:
        validate_rewrites(root, {relative: rewrite.contents for relative, rewrite in expected.items()})
    except ValueError as exc:
        msg = "source differs from the canonical native bootstrap pin rewrite"
        raise ValueError(msg) from exc
    for relative, rewrite in expected.items():
        path = root / relative
        if rewrite.mode not in {"100644", "100755"} or bool(
            path.stat().st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        ) != (rewrite.mode == "100755"):
            msg = f"source differs from the canonical native bootstrap pin rewrite: {relative}"
            raise ValueError(msg)
    return frozenset(expected)
