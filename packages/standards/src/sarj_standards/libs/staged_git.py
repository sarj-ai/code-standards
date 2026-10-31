from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess  # ruff: ignore[suspicious-subprocess-import] -- bounded read-only Git context queries validate a hook index before source tools run.
from typing import Final

from .diagnostics import initial_import
from .filesystem import is_link_like


_SAFE_ENVIRONMENT: Final = frozenset(
    {"HOME", "LANG", "LC_ALL", "LC_CTYPE", "PATH", "SYSTEMDRIVE", "SYSTEMROOT", "TMPDIR", "XDG_CONFIG_HOME"}
)
_UNSUPPORTED_OBJECT_CONTEXT: Final = frozenset(
    {"GIT_OBJECT_DIRECTORY", "GIT_NAMESPACE", "GIT_SHALLOW", "GIT_QUARANTINE_PATH"}
)


def isolated_environment() -> dict[str, str]:
    environment = {
        name: value
        for name, value in os.environ.items()  # ruff: ignore[banned-api] -- retain only the existing inert Git-query environment, never hook repository routing.
        if name in _SAFE_ENVIRONMENT
    }
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    return environment


def staged_environment(root: Path) -> dict[str, str]:
    environment = isolated_environment()
    supplied = os.environ.get("GIT_INDEX_FILE")  # ruff: ignore[banned-api] -- the native pre-commit protocol selects Git's prepared commit index.
    if supplied is None:
        return environment
    if not supplied:
        message = "active Git index cannot be empty"
        raise ValueError(message)
    try:
        index = _validated_index(root.resolve(), supplied, environment)
        environment["GIT_INDEX_FILE"] = str(index)
        _validate_index(root, environment)
    except (OSError, subprocess.SubprocessError) as exc:
        message = "cannot validate the active Git index; no staged source was changed"
        raise ValueError(message) from exc
    return environment


def _validated_index(root: Path, supplied: str, environment: dict[str, str]) -> Path:
    gitdir = _git_path(root, "--absolute-git-dir", environment)
    worktree = _git_path(root, "--show-toplevel", environment)
    if worktree != root:
        message = "active Git index requires the selected worktree root"
        raise ValueError(message)
    for name, expected in (("GIT_DIR", gitdir), ("GIT_WORK_TREE", worktree)):
        inherited = os.environ.get(name, "")  # ruff: ignore[banned-api] -- reject conflicting hook bindings without forwarding them to any query.
        if inherited and Path(inherited).resolve() != expected:
            message = f"active Git index has a foreign {name} context"
            raise ValueError(message)
    common = os.environ.get("GIT_COMMON_DIR", "")  # ruff: ignore[banned-api] -- a sibling worktree's common directory is not proof of index ownership.
    if common and Path(common).resolve() != _git_path(root, "--git-common-dir", environment):
        message = "active Git index has a foreign GIT_COMMON_DIR context"
        raise ValueError(message)
    if any(os.environ.get(name) for name in _UNSUPPORTED_OBJECT_CONTEXT):  # ruff: ignore[banned-api] -- object-store routing cannot establish the selected worktree's pending-index provenance.
        message = "active Git index has an unsupported object-store context"
        raise ValueError(message)
    # Git interprets a relative INDEX_FILE after -C/cwd selects the repository.
    candidate = Path(supplied)
    if not candidate.is_absolute():
        candidate = root / candidate
    if is_link_like(candidate) or not candidate.is_file() or candidate.parent.resolve() != gitdir:
        message = (
            "active Git index must be a regular non-symlink file directly inside the selected worktree Git directory"
        )
        raise ValueError(message)
    alternate_objects = os.environ.get("GIT_ALTERNATE_OBJECT_DIRECTORIES")  # ruff: ignore[banned-api] -- only an independently validated initial import may borrow its immutable source history.
    if alternate_objects:
        if initial_import.load(root, staged=True) is None:
            message = "active Git index has an unsupported object-store context"
            raise ValueError(message)
        environment["GIT_ALTERNATE_OBJECT_DIRECTORIES"] = alternate_objects
    return candidate.resolve(strict=True)


def _git_path(root: Path, option: str, environment: dict[str, str]) -> Path:
    executable = shutil.which("git")
    if executable is None:
        message = "Git is required to validate the active index"
        raise OSError(message)
    result = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true] -- fixed Git argv and a sanitized environment; optional index writes are disabled.
        (executable, "--no-optional-locks", "rev-parse", option),
        cwd=root,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
        timeout=5,
    )
    value = result.stdout.removesuffix("\n")
    if not value:
        message = "Git returned no worktree index context"
        raise ValueError(message)
    path = Path(value)
    return (path if path.is_absolute() else root / path).resolve(strict=True)


def _validate_index(root: Path, environment: dict[str, str]) -> None:
    executable = shutil.which("git")
    if executable is None:
        message = "Git is required to validate the active index"
        raise OSError(message)
    result = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true] -- parse the selected index before policy/native tools; conflict records make the stage unverifiable.
        (executable, "--no-optional-locks", "ls-files", "--unmerged", "-z"),
        cwd=root,
        env=environment,
        check=True,
        capture_output=True,
        timeout=5,
    )
    if result.stdout:
        message = "active Git index contains unresolved merge entries"
        raise ValueError(message)
