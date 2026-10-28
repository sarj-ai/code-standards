from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import shutil
import subprocess  # ruff: ignore[suspicious-subprocess-import] -- bounded, fixed read-only Git argv except index tree materialization.


_SOURCE_ENV = "SARJ_STANDARDS_INITIAL_IMPORT_SOURCE"
_OID = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
_GIT_INPUTS = frozenset({"GIT_INDEX_FILE", "GIT_ALTERNATE_OBJECT_DIRECTORIES"})


@dataclass(frozen=True, slots=True)
class InitialImport:
    source: str
    tree: str
    parent: str


def git_environment() -> dict[str, str]:
    return {
        name: value
        for name, value in os.environ.items()  # ruff: ignore[banned-api] -- bind reads to the analyzed checkout while retaining explicit prospective index and object access.
        if not name.startswith("GIT_") or name in _GIT_INPUTS
    }


def load(root: Path, *, staged: bool) -> InitialImport | None:
    source = os.environ.get(_SOURCE_ENV)  # ruff: ignore[banned-api] -- explicit process-scoped native initial-import input, never inferred from repository settings.
    if source is None:
        return None
    if not staged or _OID.fullmatch(source) is None:
        msg = f"{_SOURCE_ENV} requires --staged and a full lowercase commit object ID"
        raise ValueError(msg)
    top = _git(root, "rev-parse", "--show-toplevel").removesuffix(b"\n").decode("utf-8", errors="surrogateescape")
    if Path(top).resolve() != root.resolve():
        msg = "initial import requires the analyzed Git worktree root"
        raise ValueError(msg)
    # A symbolic, missing HEAD distinguishes an initial commit from a broken detached checkout.
    branch = _git(root, "symbolic-ref", "--quiet", "HEAD").removesuffix(b"\n").decode("utf-8", errors="surrogateescape")
    if not branch.startswith("refs/heads/"):
        msg = "initial import requires an unborn branch HEAD"
        raise ValueError(msg)
    _git(root, "show-ref", "--verify", "--quiet", branch, allowed=(1,))
    context = _source_commit(root, source)
    if _git(root, "write-tree").strip().decode("ascii") != context.tree:
        msg = "initial-import index must exactly match the source commit tree"
        raise ValueError(msg)
    flags = _git(root, "ls-files", "-v", "-z").split(b"\0")
    if any(entry and entry[:1] != b"H" for entry in flags):
        msg = "initial import requires verifiable index flags"
        raise ValueError(msg)
    # Stat-only differences can return one with no content diff; numstat also captures mode/type changes.
    if _git(
        root,
        "-c",
        "core.filemode=true",
        "diff",
        "--exit-code",
        "--numstat",
        "-z",
        "--no-ext-diff",
        "--no-textconv",
        "--ignore-submodules=none",
        "--",
        allowed=(0, 1),
    ):
        msg = "initial-import tracked worktree must match the index"
        raise ValueError(msg)
    if _git(root, "ls-files", "--others", "--exclude-standard", "-z"):
        msg = "initial import requires all nonignored worktree files to be staged"
        raise ValueError(msg)
    _git(
        root,
        "diff",
        "--no-ext-diff",
        "--no-textconv",
        "--ignore-submodules=none",
        "--numstat",
        "-z",
        context.parent,
        context.source,
        "--",
    )
    return context


def validate(root: Path, context: InitialImport | None, *, staged: bool) -> None:
    source = os.environ.get(_SOURCE_ENV)  # ruff: ignore[banned-api] -- reject context activation as well as removal during an analysis transaction.
    if (context is None and source is not None) or (context is not None and load(root, staged=staged) != context):
        msg = "initial-import source context changed during analysis"
        raise ValueError(msg)


def _source_commit(root: Path, source: str) -> InitialImport:
    if _git(root, "cat-file", "-t", source) != b"commit\n":
        msg = "initial-import source must be an available commit"
        raise ValueError(msg)
    headers = _git(root, "cat-file", "commit", source).split(b"\n\n", 1)[0].splitlines()
    trees = [line.removeprefix(b"tree ").decode("ascii") for line in headers if line.startswith(b"tree ")]
    parents = [line.removeprefix(b"parent ").decode("ascii") for line in headers if line.startswith(b"parent ")]
    if len(trees) != 1 or len(parents) != 1 or any(_OID.fullmatch(oid) is None for oid in (*trees, *parents)):
        msg = "initial-import source must have exactly one available parent"
        raise ValueError(msg)
    if _git(root, "cat-file", "-t", parents[0]) != b"commit\n":
        msg = "initial-import source parent must be an available commit"
        raise ValueError(msg)
    return InitialImport(source, trees[0], parents[0])


def _git(root: Path, *arguments: str, allowed: tuple[int, ...] = (0,)) -> bytes:
    git = shutil.which("git")
    if git is None:
        msg = "initial import requires Git"
        raise ValueError(msg)
    try:
        result = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true] -- fixed Git argv, no shell, replacement objects or network fetches.
            (
                git,
                "--no-replace-objects",
                "--no-lazy-fetch",
                "--literal-pathspecs",
                "-c",
                "diff.autoRefreshIndex=false",
                *arguments,
            ),
            cwd=root,
            check=False,
            capture_output=True,
            timeout=30,
            env=git_environment(),
        )
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        msg = "cannot validate initial-import Git state"
        raise ValueError(msg) from error
    if result.returncode not in allowed:
        msg = f"cannot validate initial-import Git state: {arguments[0]} failed"
        raise ValueError(msg)
    return result.stdout
