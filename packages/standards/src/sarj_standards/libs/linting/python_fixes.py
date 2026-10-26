from __future__ import annotations

from typing import TYPE_CHECKING

from .autofix import fix_paths
from .runner import group_paths


if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from .policy import Policy


def fix_python(files: Sequence[str], *, root: Path, policy: Policy, python_root: Path | None = None) -> int:
    inputs = _owned_inputs(files, root=root, policy=policy, python_root=python_root)
    paths = group_paths(inputs, policy=policy, python_only=True).python
    return len(fix_paths(root, paths, policy=policy))


def _owned_inputs(files: Sequence[str], *, root: Path, policy: Policy, python_root: Path | None) -> list[str]:
    inputs: list[str] = []
    for name in files:
        path = root / name
        policy.relative(path)
        candidate = _owned_input(path, python_root)
        if candidate is None:
            continue
        inputs.append(str(candidate))
    return inputs


def _owned_input(path: Path, python_root: Path | None) -> Path | None:
    if python_root is None or path.resolve().is_relative_to(python_root.resolve()):
        return path
    if path.is_dir() and python_root.resolve().is_relative_to(path.resolve()):
        return python_root
    return None
