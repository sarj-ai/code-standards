from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from itertools import batched
from pathlib import PurePosixPath
import tomllib
from typing import TYPE_CHECKING

from repo_standards.repository import (
    GitIdentity,
    git_index_identity,
    inspect_repository,
    read_tracked_blob_contents,
)

from sarj_standards.libs.adoption.manifest import (
    MANIFEST_NAME,
    TerraformOutputContract,
    as_table,
    terraform_internal_modules,
    terraform_output_contracts,
)
from sarj_standards.libs.staged_git import has_committed_tree, is_git_worktree, staged_environment


if TYPE_CHECKING:
    from pathlib import Path


_MAX_SOURCE_BYTES = 64 * 1024 * 1024
_BLOB_BATCH = 100


@dataclass(frozen=True, slots=True)
class ModuleOutputSources:
    sources: Mapping[PurePosixPath, str]
    contracts: tuple[TerraformOutputContract, ...]
    internal_modules: tuple[str, ...] = ()


def selected_sources(root: Path, *, staged: bool) -> ModuleOutputSources | None:
    if not (root / ".git").exists():
        return None
    if not staged and not has_committed_tree(root):
        if not is_git_worktree(root):
            message = "Complete Git source evidence requires a readable selected repository"
            raise ValueError(message)
        return None
    if staged:
        staged_environment(root)
    identity = git_index_identity(root) if staged else None
    inspection = inspect_repository(root, identity=identity)
    if identity is None:
        identity = GitIdentity(inspection.source_revision, inspection.tree_digest)
    tracked = frozenset(item.path for item in inspection.tracked_files)
    if len(tracked) != inspection.tracked_file_count:
        message = "Complete tracked source evidence is required for Terraform consumers"
        raise ValueError(message)
    paths = sorted(
        PurePosixPath(path)
        for path in tracked
        if path.endswith((".tf", ".tf.json", ".tfvars", ".tfvars.json")) or PurePosixPath(path).name == "envs.json"
    )
    manifest_path = PurePosixPath(MANIFEST_NAME)
    selected = [*paths, *([manifest_path] if MANIFEST_NAME in tracked else [])]
    contents = _selected_contents(root, identity, selected)
    config = tomllib.loads(contents.get(manifest_path, b"").decode("utf-8"))
    contracts = terraform_output_contracts(as_table(config))
    for contract in contracts:
        if contract.evidence not in tracked:
            message = f"External output evidence is not tracked in the selected Git tree: {contract.evidence}"
            raise ValueError(message)
    return ModuleOutputSources(
        {path: contents[path].decode("utf-8") for path in paths},
        contracts,
        terraform_internal_modules(as_table(config)),
    )


def _selected_contents(root: Path, identity: GitIdentity, paths: list[PurePosixPath]) -> dict[PurePosixPath, bytes]:
    contents: dict[PurePosixPath, bytes] = {}
    size = 0
    for batch in batched(paths, _BLOB_BATCH, strict=False):
        for blob in read_tracked_blob_contents(root, tuple(path.as_posix() for path in batch), identity=identity):
            size += len(blob.content)
            if size > _MAX_SOURCE_BYTES:
                message = "Complete Terraform source snapshot exceeds the 64 MiB safety limit"
                raise ValueError(message)
            contents[PurePosixPath(blob.path)] = blob.content
    if set(contents) != set(paths):
        message = "Complete selected Terraform source evidence is required"
        raise ValueError(message)
    return contents


def staged_module_index(root: Path, inputs: Mapping[Path, bytes]) -> GitIdentity:
    from sarj_iac_lint.terraform import is_terraform  # ruff: ignore[import-outside-top-level] -- Terraform owns supported source representations.

    index = git_index_identity(root)
    snapshot = selected_sources(root, staged=True)
    if snapshot is None or git_index_identity(root) != index:
        message = "Cannot establish a stable staged Terraform module"
        raise ValueError(message)
    directories = {path.parent for path in inputs}
    current = {
        path for directory in directories for path in directory.iterdir() if path.is_file() and is_terraform(path)
    }
    if current != set(inputs):
        message = "Terraform module membership changed during analysis; rerun the command"
        raise ValueError(message)
    staged_sources = {
        root / path: source.removeprefix("\ufeff")
        for path, source in snapshot.sources.items()
        if is_terraform(path) and (root / path).parent in directories
    }
    if set(staged_sources) != set(inputs) or any(
        raw.decode("utf-8-sig") != staged_sources[path] for path, raw in inputs.items()
    ):
        message = "Terraform module context differs from the staged index; stage the intended module sources before checking or fixing"
        raise ValueError(message)
    return index
