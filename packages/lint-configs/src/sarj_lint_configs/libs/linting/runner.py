"""Run every installed Sarj custom rule with one maintainable command."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from importlib import import_module
import os
from pathlib import Path
import stat
from types import MappingProxyType
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from sarj_lint_configs.libs.filesystem import is_link_like

from . import textlint


if TYPE_CHECKING:
    import argparse
    from collections.abc import Callable, Iterable, Mapping, Sequence

    from .policy import Policy


class _Rule(Protocol):
    """Registry value shape shared by the three standards linters."""


@runtime_checkable
class _CheckerModule(Protocol):
    """Importable checker entry-point module."""

    def main(self, argv: list[str]) -> int: ...


@runtime_checkable
class _RegistryModule(Protocol):
    """Importable rule-registry module."""

    REGISTRY: Mapping[str, type[_Rule]]


class _Tool(StrEnum):
    PYTHON = "python"
    SQL = "sql"
    IAC = "iac"
    TEXT = "text"
    TYPESCRIPT = "typescript"


_SUFFIX_TO_TOOL = MappingProxyType(
    {
        ".hcl": _Tool.IAC,
        ".py": _Tool.PYTHON,
        ".sql": _Tool.SQL,
        ".tf": _Tool.IAC,
        ".tfvars": _Tool.IAC,
        ".cjs": _Tool.TYPESCRIPT,
        ".cts": _Tool.TYPESCRIPT,
        ".js": _Tool.TYPESCRIPT,
        ".jsx": _Tool.TYPESCRIPT,
        ".mjs": _Tool.TYPESCRIPT,
        ".mts": _Tool.TYPESCRIPT,
        ".ts": _Tool.TYPESCRIPT,
        ".tsx": _Tool.TYPESCRIPT,
        ".yaml": _Tool.IAC,
        ".yml": _Tool.IAC,
    }
)
_IGNORED_DIRS = frozenset(
    {
        ".build",
        ".astro",
        ".cache",
        ".coverage",
        ".gradle",
        ".hypothesis",
        ".git",
        ".mypy_cache",
        ".next",
        ".open-next",
        ".nox",
        ".nuxt",
        ".output",
        ".parcel-cache",
        ".playwright-mcp",
        ".pnpm-store",
        ".pytest_cache",
        ".pytype",
        ".ruff_cache",
        ".svelte-kit",
        ".terraform",
        ".turbo",
        ".uv-cache",
        ".venv",
        ".vite",
        ".wrangler",
        ".yarn",
        ".tox",
        "__pycache__",
        "__generated__",
        "_backups",
        "dist",
        "build",
        "cache",
        "caches",
        "coverage",
        "htmlcov",
        "generated",
        "node_modules",
        "out",
        "storybook-static",
        "target",
        "vendor",
        "venv",
    }
)
_MAX_SOURCE_FILE_BYTES = 2 * 1024 * 1024
_MAX_MARKDOWN_FILE_BYTES = 16 * 1024 * 1024
_IGNORED_DISCOVERED_FILES = frozenset({".env", ".env.mcp"})
_PYTHON_NOISE_RULES = frozenset(
    {
        "docstring-args-restate-signature",
        "docstring-returns-restate-signature",
        "duplicated-override-docstring",
        "no-comment-cruft",
        "no-long-comment",
        "no-restated-comment",
        "no-typed-doc-sections",
        "prefer-self-documenting-constant",
        "prefer-single-sentence-comment",
        "redundant-class-docstring",
        "redundant-docstring",
        "redundant-module-docstring",
        "restated-test-docstring",
        "test-phase-label-comment",
        "trailing-value-narration",
    }
)
_IAC_NOISE_RULES = frozenset({"no-comment-cruft"})


@dataclass
class GroupedPaths:
    """Files routed to the registry that understands their syntax."""

    python: list[str] = field(default_factory=list)
    sql: list[str] = field(default_factory=list)
    iac: list[str] = field(default_factory=list)
    text: list[str] = field(default_factory=list)
    typescript: list[str] = field(default_factory=list)


def run(
    files: Sequence[str],
    *,
    noise_only: bool = False,
    python_baseline: str | None = None,
    policy: Policy | None = None,
) -> int:
    """Dispatch files and directories to every applicable installed registry."""
    grouped = group_paths(files, policy=policy)
    statuses = [
        _run_tool(
            "sarj_python_lint",
            grouped.python,
            selected=_PYTHON_NOISE_RULES if noise_only else None,
            extra_args=("--baseline", python_baseline) if python_baseline is not None else (),
        ),
        _run_tool(
            "sarj_sql_lint",
            grouped.sql,
            selected=frozenset() if noise_only else None,
        ),
        _run_tool(
            "sarj_iac_lint",
            grouped.iac,
            selected=_IAC_NOISE_RULES if noise_only else None,
        ),
    ]
    if grouped.text:
        statuses.append(textlint.run(grouped.text))
    return max(statuses)


def create_python_baseline(files: Sequence[str], output: str, *, policy: Policy | None = None) -> int:
    """Snapshot current Python findings; later checks enforce the shrink-only ceiling."""
    grouped = group_paths(files, policy=policy)
    return _run_tool(
        "sarj_python_lint",
        grouped.python,
        selected=None,
        extra_args=("--update-baseline", output),
    )


def _run_tool(
    package: str,
    files: Sequence[str],
    *,
    selected: frozenset[str] | None,
    extra_args: Sequence[str] = (),
) -> int:
    """Load and run a checker only when files and selected rules require it."""
    if not files or selected == frozenset():
        return 0
    checker, registry = _load_tool(package)
    if selected is not None:
        registry = _select_rules(registry, selected)
    return _run(checker, registry, files, extra_args=extra_args)


def _select_rules(registry: Mapping[str, type[_Rule]], selected: frozenset[str]) -> dict[str, type[_Rule]]:
    return {rule_id: rule for rule_id, rule in registry.items() if rule_id in selected}


def _load_tool(
    package: str,
) -> tuple[Callable[[list[str]], int], Mapping[str, type[_Rule]]]:
    """Load one checker when the all-rules command needs it."""
    checker_module = import_module(f"{package}.__main__")
    registry_module = import_module(f"{package}.rules")
    if not isinstance(checker_module, _CheckerModule) or not isinstance(registry_module, _RegistryModule):
        msg = f"{package} does not expose the expected lint API"
        raise TypeError(msg)
    return checker_module.main, registry_module.REGISTRY


def group_paths(files: Sequence[str], *, policy: Policy | None = None) -> GroupedPaths:
    grouped = GroupedPaths()
    inputs: list[tuple[str, Path, bool]] = []
    for raw_path in files:
        path = Path(raw_path)
        if is_link_like(path):
            msg = f"refusing symlink input: {raw_path}"
            raise ValueError(msg)
        if not path.exists():
            msg = f"input does not exist: {raw_path}"
            raise ValueError(msg)
        if path.is_file() and _owns_path(path):
            _validate_source_file(path, raw_path)
            if policy is not None and not policy.allows_path(path):
                continue
        inputs.append((raw_path, path, path.is_dir()))

    roots = _minimal_roots(path for _raw, path, is_directory in inputs if is_directory)
    walked: set[Path] = set()
    seen: set[Path] = set()
    for raw_path, path, is_directory in inputs:
        if is_directory:
            key = _path_key(path)
            if key in roots and key not in walked:
                _route_directory(grouped, path, seen, policy=policy)
                walked.add(key)
            continue
        _route_unique_path(grouped, path, raw_path, seen)
    return grouped


def accepts_hook_path(path: Path) -> bool:
    """Return whether staged source analysis should receive this path."""
    return _owns_path(path) and not _is_conventionally_generated(path)


def _minimal_roots(paths: Iterable[Path]) -> frozenset[Path]:
    """Return only top-level requested directories, eliminating overlapping walks."""
    resolved = sorted({_path_key(path) for path in paths}, key=lambda path: (len(path.parts), str(path)))
    roots: list[Path] = []
    for path in resolved:
        if any(path.is_relative_to(root) for root in roots):
            continue
        roots.append(path)
    return frozenset(roots)


def _route_directory(grouped: GroupedPaths, path: Path, seen: set[Path], *, policy: Policy | None = None) -> None:
    """Walk one directory without entering dependency, cache, or build trees."""
    for root, dir_names, file_names in os.walk(path, topdown=True, followlinks=False):
        dir_names[:] = sorted(name for name in dir_names if name not in _IGNORED_DIRS)
        for file_name in sorted(file_names):
            if file_name in _IGNORED_DISCOVERED_FILES:
                continue
            child = Path(root, file_name)
            if not _owns_path(child):
                continue
            if _is_conventionally_generated(child):
                continue
            if policy is not None and not policy.allows_path(child):
                continue
            if not _is_routable_discovered_file(child):
                continue
            _route_unique_path(grouped, child, str(child), seen)


def _is_routable_discovered_file(path: Path) -> bool:
    try:
        metadata = path.stat(follow_symlinks=False)
        if not stat.S_ISREG(metadata.st_mode):
            return False
        _validate_source_size(path, metadata.st_size)
    except ValueError:
        if _has_generated_header(path):
            return False
        raise
    except OSError:
        return False
    return True


def _validate_source_file(path: Path, display: str) -> None:
    try:
        metadata = path.stat(follow_symlinks=False)
    except OSError as exc:
        msg = f"cannot inspect source input: {display}"
        raise ValueError(msg) from exc
    if not stat.S_ISREG(metadata.st_mode):
        msg = f"source input is not a regular file: {display}"
        raise ValueError(msg)
    _validate_source_size(path, metadata.st_size)


def _validate_source_size(path: Path, size: int) -> None:
    limit = _MAX_MARKDOWN_FILE_BYTES if path.suffix.lower() in {".md", ".mdx"} else _MAX_SOURCE_FILE_BYTES
    if size > limit:
        msg = f"source input exceeds the {limit // (1024 * 1024)} MiB analysis limit: {path}"
        raise ValueError(msg)


def _is_conventionally_generated(path: Path) -> bool:
    name = path.name.lower()
    return name.endswith((".gen.ts", ".gen.tsx", ".generated.ts", ".generated.tsx")) or name in {
        "next-env.d.ts",
        "worker-configuration.d.ts",
    }


def _has_generated_header(path: Path) -> bool:
    try:
        with path.open("rb") as stream:
            header = stream.read(4096).lower()
    except OSError:
        return False
    generated = b"auto-generated" in header or b"autogenerated" in header or b"@generated" in header
    hands_off = b"do not edit" in header or b"do not hand-edit" in header or b"do not hand edit" in header
    return generated and hands_off


def _owns_path(path: Path) -> bool:
    """Return whether any bundled checker can handle the path."""
    return path.suffix.lower() in _SUFFIX_TO_TOOL or textlint.is_text_path(path)


def _route_unique_path(grouped: GroupedPaths, path: Path, raw_path: str, seen: set[Path]) -> None:
    """Route a physical file once even when inputs overlap."""
    key = _path_key(path)
    if key in seen:
        return
    seen.add(key)
    _route_path(grouped, path, raw_path)


def _path_key(path: Path) -> Path:
    """Normalize a non-symlink path without another filesystem lookup."""
    # resolve() performs a filesystem lookup for every discovered file.
    return Path(os.path.abspath(path))  # ruff: ignore[os-path-abspath]


def _route_path(grouped: GroupedPaths, path: Path, raw_path: str) -> None:
    """Route one path; YAML intentionally belongs to both IaC and text checks."""
    _append_path(grouped, _SUFFIX_TO_TOOL.get(path.suffix.lower()), raw_path)
    if textlint.is_text_path(path):
        grouped.text.append(raw_path)


def _append_path(grouped: GroupedPaths, tool: _Tool | None, path: str) -> None:
    match tool:
        case _Tool.PYTHON:
            grouped.python.append(path)
        case _Tool.SQL:
            grouped.sql.append(path)
        case _Tool.IAC:
            grouped.iac.append(path)
        case _Tool.TEXT:
            grouped.text.append(path)
        case _Tool.TYPESCRIPT:
            grouped.typescript.append(path)
        case None:
            return


def _run(
    checker: Callable[[list[str]], int],
    registry: Mapping[str, type[_Rule]],
    files: Sequence[str],
    *,
    extra_args: Sequence[str] = (),
) -> int:
    if not files or not registry:
        return 0
    return checker(["check", *_rule_args(registry), *extra_args, "--", *files])


def _rule_args(registry: Mapping[str, type[_Rule]]) -> list[str]:
    return [part for rule_id in sorted(registry) for part in ("--rule", rule_id)]


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """Add the all-rule runner arguments to a CLI parser."""
    parser.add_argument(
        "--noise-only",
        action="store_true",
        help="run Python, config-prose, and AI-artifact noise rules (TypeScript uses the ESLint plugin)",
    )
    parser.add_argument(
        "--python-baseline",
        help="apply a sarj-python-lint shrink-only baseline to staged Python files",
    )
    parser.add_argument("files", nargs="+")
