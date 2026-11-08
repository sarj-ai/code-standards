from __future__ import annotations

from dataclasses import asdict
import json
import re
import shutil
import subprocess  # ruff: ignore[suspicious-subprocess-import] -- immutable Git provenance, never deployment operations.
import tomllib
from typing import TYPE_CHECKING

from sarj_standards.libs.adoption.manifest import as_table, load, terraform_guard_contract_option
from sarj_standards.libs.json_boundary import parse_unique_json
from sarj_standards.libs.staged_git import isolated_environment, staged_environment
from sarj_standards.libs.typed_containers import is_object_list, is_object_mapping


if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from sarj_iac_lint.guard_contracts import GuardContract, GuardContracts


CONTRACT_PATH = ".sarj-terraform-guards.json"
_OID = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")
_LIMIT = 500_000


class CoreIAC:
    def __init__(self, root: Path, *, staged: bool = False) -> None:
        self.root = root.resolve()
        self.staged = staged
        self.environment = staged_environment(self.root) if staged else isolated_environment()

    def initialize(self, paths: Sequence[str], *, original_revision: str) -> str:
        self._revision(original_revision)
        if self._introductions() or (self.root / CONTRACT_PATH).exists():
            message = "guard contracts already exist; regeneration is prohibited"
            raise ValueError(message)
        if self._git("rev-parse", "--verify", "HEAD").strip() != original_revision:
            message = "initial contracts require the exact immutable original HEAD"
            raise ValueError(message)
        entries = self._original_entries(original_revision, tuple(paths))
        self._verify_current(entries)
        return self._serialize(entries)

    def prepare(self) -> GuardContracts | None:
        active = self._configured_manifest()
        if active is None:
            return None
        from sarj_iac_lint.guard_contracts import GuardContracts  # ruff: ignore[import-outside-top-level] -- load only for selected IaC contract analysis.

        introductions, current = active
        self._check_staged_manifest(current)
        paths = self._manifest_paths(current)
        entries = self._original_entries(self._original_revision(introductions, current), paths)
        if parse_unique_json(current) != parse_unique_json(self._serialize(entries)):
            message = "guard contracts differ from immutable original source"
            raise ValueError(message)
        self._verify_current(entries)
        return GuardContracts(self.root, frozenset(entries))

    def _configured_manifest(self) -> tuple[tuple[str, ...], str] | None:
        manifest = load(self.root)
        option = None if manifest is None else manifest.terraform_guard_contracts
        exists = (self.root / CONTRACT_PATH).exists()
        # Non-Git consumers without this option retain the established rule.
        if option is None and not exists and not (self.root / ".git").exists():
            return None
        introductions = self._introductions()
        if option is None and not exists and not introductions:
            return None
        if option != CONTRACT_PATH:
            message = "existing guard contracts require their SARJ222 rule option"
            raise ValueError(message)
        return introductions, self._read_file(CONTRACT_PATH)

    def _check_staged_manifest(self, current: str) -> None:
        if not self.staged:
            return
        if self._git("show", f":{CONTRACT_PATH}") != current:
            message = "staged guard contract manifest differs from analyzed worktree"
            raise ValueError(message)
        staged_config: object = tomllib.loads(self._git("show", ":.sarj-standards.toml"))
        if terraform_guard_contract_option(as_table(staged_config)) != CONTRACT_PATH:
            message = "staged SARJ222 rule option is missing or malformed"
            raise ValueError(message)

    def _original_revision(self, introductions: tuple[str, ...], current: str) -> str:
        if len(introductions) > 1:
            message = "guard contract manifest was removed and reintroduced"
            raise ValueError(message)
        if not introductions:
            return self._git("rev-parse", "--verify", "HEAD").strip()
        introduced = introductions[0]
        if self._git("show", f"{introduced}:{CONTRACT_PATH}") != current:
            message = "immutable guard contract manifest was changed"
            raise ValueError(message)
        # An integration commit may be the first addition on this branch. Its
        # parent independently proves these guards already existed here, without
        # depending on feature-branch commit IDs that squash/rebase can discard.
        return self._git("rev-parse", "--verify", f"{introduced}^1").strip()

    def _manifest_paths(self, source: str) -> tuple[str, ...]:
        value = as_table(parse_unique_json(source))
        if set(value) != {"schema", "guards"}:
            message = "malformed Terraform guard contract manifest"
            raise ValueError(message)
        if type(value["schema"]) is not int or value["schema"] != 1:
            message = "unsupported Terraform guard contract schema"
            raise ValueError(message)
        guards = value["guards"]
        if not is_object_list(guards) or not guards:
            message = "guard contracts must contain existing guards"
            raise ValueError(message)
        return tuple(sorted({_entry_path(guard) for guard in guards}))

    def _original_entries(self, revision: str, paths: Sequence[str]) -> tuple[GuardContract, ...]:
        from sarj_iac_lint.guard_contracts import contracts_for_source, relative_tf_path  # ruff: ignore[import-outside-top-level] -- load only for selected IaC contract analysis.

        if not paths or len(set(paths)) != len(paths):
            message = "guard contract capture needs unique existing paths"
            raise ValueError(message)
        entries: list[GuardContract] = []
        for path in sorted(paths):
            relative_tf_path(path)
            self._contained(path)
            mode = self._git("ls-tree", revision, "--", path).split(maxsplit=1)
            if not mode or mode[0] != "100644":
                message = "guard original must be a regular immutable Git blob"
                raise ValueError(message)
            found = contracts_for_source(path, self._git("show", f"{revision}:{path}"))
            if not found:
                message = "unowned or stale guard contract path"
                raise ValueError(message)
            entries.extend(found)
        return tuple(entries)

    def _verify_current(self, entries: Sequence[GuardContract]) -> None:
        from sarj_iac_lint.guard_contracts import verify_sources  # ruff: ignore[import-outside-top-level] -- load only for selected IaC contract analysis.

        paths = sorted({entry.path for entry in entries})
        verify_sources(frozenset(entries), {path: self._read_file(path) for path in paths})
        if self.staged:
            verify_sources(frozenset(entries), {path: self._index_file(path) for path in paths})

    def _index_file(self, path: str) -> str:
        mode = self._git("ls-files", "--stage", "--", path).split(maxsplit=1)
        if not mode or mode[0] != "100644":
            message = "contracted guard missing or not a regular file in active index"
            raise ValueError(message)
        return self._git("show", f":{path}")

    def _contained(self, path: str) -> Path:
        candidate = self.root / path
        if candidate.resolve() != candidate or candidate.is_symlink():
            message = "guard contract paths cannot traverse symlinks"
            raise ValueError(message)
        candidate.resolve().relative_to(self.root)
        return candidate

    def _read_file(self, path: str) -> str:
        candidate = self._contained(path)
        if not candidate.is_file() or candidate.stat().st_size > _LIMIT:
            message = "guard contract input is missing, non-regular or oversized"
            raise ValueError(message)
        return candidate.read_text(encoding="utf-8")

    def _introductions(self) -> tuple[str, ...]:
        if not self._git("rev-parse", "--verify", "--quiet", "HEAD", absent_ok=True):
            return ()
        return tuple(
            self._git(
                "log", "--first-parent", "--diff-filter=A", "--format=%H", "HEAD", "--", CONTRACT_PATH
            ).splitlines()
        )

    def _git(self, *arguments: str, absent_ok: bool = False) -> str:
        git = shutil.which("git")
        if git is None:
            message = "guard contract provenance requires Git"
            raise ValueError(message)
        result = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true] -- fixed read-only argv, no shell or replacement objects.
            [git, "--no-replace-objects", "--no-lazy-fetch", "--literal-pathspecs", "-C", str(self.root), *arguments],
            env=self.environment,
            capture_output=True,
            check=False,
            timeout=10,
        )
        if absent_ok and result.returncode == 1:
            return ""
        result.check_returncode()
        if len(result.stdout) > _LIMIT:
            message = "immutable guard contract Git input exceeds analysis limit"
            raise ValueError(message)
        return result.stdout.decode("utf-8")

    @staticmethod
    def _revision(value: str) -> None:
        if _OID.fullmatch(value) is None:
            message = "guard contract original revision must be a full commit ID"
            raise ValueError(message)

    @staticmethod
    def _serialize(entries: Sequence[GuardContract]) -> str:
        return json.dumps({"schema": 1, "guards": [asdict(entry) for entry in entries]}, indent=2) + "\n"


def _entry_path(value: object) -> str:
    from sarj_iac_lint.guard_contracts import relative_tf_path  # ruff: ignore[import-outside-top-level] -- load only for selected IaC contract analysis.

    if not is_object_mapping(value) or set(value) != {"path", "owner", "kind", "shape"}:
        message = "malformed guard contract entry"
        raise ValueError(message)
    path = value["path"]
    if not isinstance(path, str):
        message = "guard contract path must be a string"
        raise TypeError(message)
    return relative_tf_path(path)
