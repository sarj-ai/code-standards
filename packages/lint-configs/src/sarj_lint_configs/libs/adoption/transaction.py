"""Best-effort file transaction for adoption and upgrade operations."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Final, Self

from sarj_lint_configs.libs.filesystem import is_link_like


_OWNED_NAMES: Final = frozenset(
    {
        ".pre-commit-config.yaml",
        ".pre-commit-config.yml",
        ".sarj-standards.toml",
        ".ruff-strict.toml",
        ".pyright-strict.json",
        ".markdownlint.yaml",
        ".taplo.toml",
        ".yamllint.yaml",
        "eslint.config.mjs",
        "eslint.strict.mjs",
        "package.json",
        "package-lock.json",
        "pnpm-lock.yaml",
        "yarn.lock",
        "bun.lock",
        "bun.lockb",
        "pyproject.toml",
        "pyrightconfig.json",
        "pyrightconfig.jsonc",
        "uv.lock",
    }
)
_SKIP_DIRS: Final = frozenset({".git", ".venv", "node_modules", "dist", "build", ".next", ".cache"})


def validate_targets(root: Path, paths: tuple[Path, ...]) -> None:
    """Reject mutation targets that escape the repo or traverse a symlink."""
    resolved_root = root.resolve()
    lexical_root = root.absolute()
    for path in paths:
        try:
            relative = path.absolute().relative_to(lexical_root)
        except ValueError as exc:
            msg = f"mutation target {path} escapes repository root {resolved_root}"
            raise OSError(msg) from exc
        current = lexical_root
        for part in relative.parts:
            current /= part
            if is_link_like(current):
                msg = f"refusing symlink mutation target {path}; link traversal at {current}"
                raise OSError(msg)
        if path.exists() and not path.is_file():
            msg = f"refusing non-file mutation target {path}"
            raise OSError(msg)
        try:
            path.resolve().relative_to(resolved_root)
        except (OSError, ValueError) as exc:
            msg = f"mutation target {path} escapes repository root {resolved_root}"
            raise OSError(msg) from exc


@dataclass
class FileTransaction:
    """Snapshot likely mutation targets and restore them after a failed operation."""

    root: Path
    before: dict[Path, bytes | None]

    @classmethod
    def capture(cls, root: Path, extra: tuple[Path, ...] = ()) -> Self:
        resolved = root.resolve()
        candidates = set(extra)
        for parent, directories, names in os.walk(resolved):
            directories[:] = [name for name in directories if name not in _SKIP_DIRS]
            directory = Path(parent)
            candidates.update(directory / name for name in names if name in _OWNED_NAMES)
            if "pyproject.toml" in names:
                candidates.add(directory / "uv.lock")
            if "package.json" in names:
                candidates.update(
                    directory / name
                    for name in ("package-lock.json", "pnpm-lock.yaml", "yarn.lock", "bun.lock", "bun.lockb")
                )
        before: dict[Path, bytes | None] = {}
        for path in candidates:
            try:
                path.resolve().relative_to(resolved)
            except OSError, ValueError:
                continue
            before[path] = path.read_bytes() if path.is_file() else None
        return cls(resolved, before)

    def track(self, *paths: Path) -> None:
        for path in paths:
            if path not in self.before:
                self.before[path] = path.read_bytes() if path.is_file() else None

    def rollback(self) -> None:
        for path, contents in self.before.items():
            if contents is None:
                if path.is_file() or is_link_like(path):
                    path.unlink()
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(contents)
