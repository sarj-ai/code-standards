"""Run every installed Sarj custom rule with one maintainable command."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable


if TYPE_CHECKING:
    import argparse
    from collections.abc import Callable, Mapping, Sequence


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


_SUFFIX_TO_TOOL = {
    ".hcl": _Tool.IAC,
    ".py": _Tool.PYTHON,
    ".sql": _Tool.SQL,
    ".tf": _Tool.IAC,
    ".tfvars": _Tool.IAC,
    ".yaml": _Tool.IAC,
    ".yml": _Tool.IAC,
}
_IGNORED_DIRS = frozenset(
    {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".uv-cache",
        ".venv",
        "dist",
        "node_modules",
        "vendor",
    }
)


@dataclass
class GroupedPaths:
    """Files routed to the registry that understands their syntax."""

    python: list[str] = field(default_factory=list)
    sql: list[str] = field(default_factory=list)
    iac: list[str] = field(default_factory=list)


def run(
    files: Sequence[str],
) -> int:
    """Dispatch files and directories to every applicable installed registry.

    Returns:
        The highest exit status produced by an applicable registry.

    """
    # Keep config-only commands (`sync`, `list`, and `path`) usable directly
    # from a Standards source checkout without installing every lint package.
    # The checker packages are required only for the `check` command.
    python_main, python_rules = _load_tool("sarj_python_lint")
    sql_main, sql_rules = _load_tool("sarj_sql_lint")
    iac_main, iac_rules = _load_tool("sarj_iac_lint")

    grouped = group_paths(files)
    statuses = (
        _run(python_main, python_rules, grouped.python),
        _run(sql_main, sql_rules, grouped.sql),
        _run(iac_main, iac_rules, grouped.iac),
    )
    return max(statuses)


def _load_tool(
    package: str,
) -> tuple[Callable[[list[str]], int], Mapping[str, type[_Rule]]]:
    """Load one checker only when the all-rules command needs it.

    Returns:
        The checker entry point and its complete rule registry.

    Raises:
        TypeError: If an installed checker does not expose the expected API.

    """
    checker_module = import_module(f"{package}.__main__")
    registry_module = import_module(f"{package}.rules")
    if not isinstance(checker_module, _CheckerModule) or not isinstance(
        registry_module, _RegistryModule
    ):
        msg = f"{package} does not expose the expected lint API"
        raise TypeError(msg)
    return checker_module.main, registry_module.REGISTRY


def group_paths(files: Sequence[str]) -> GroupedPaths:
    grouped = GroupedPaths()
    for raw_path in files:
        path = Path(raw_path)
        if path.is_symlink():
            msg = f"refusing symlink input: {raw_path}"
            raise ValueError(msg)
        if not path.exists():
            msg = f"input does not exist: {raw_path}"
            raise ValueError(msg)
        if path.is_dir():
            for child in path.rglob("*"):
                relative_parts = child.relative_to(path).parts
                if any(part in _IGNORED_DIRS for part in relative_parts):
                    continue
                if child.is_symlink():
                    msg = f"refusing symlink input: {child}"
                    raise ValueError(msg)
                if not child.is_file():
                    continue
                tool = _SUFFIX_TO_TOOL.get(child.suffix.lower())
                _append_path(grouped, tool, str(child))
            continue
        tool = _SUFFIX_TO_TOOL.get(path.suffix.lower())
        _append_path(grouped, tool, raw_path)
    return grouped


def _append_path(grouped: GroupedPaths, tool: _Tool | None, path: str) -> None:
    match tool:
        case _Tool.PYTHON:
            grouped.python.append(path)
        case _Tool.SQL:
            grouped.sql.append(path)
        case _Tool.IAC:
            grouped.iac.append(path)
        case None:
            return


def _run(
    checker: Callable[[list[str]], int],
    registry: Mapping[str, type[_Rule]],
    files: Sequence[str],
) -> int:
    if not files:
        return 0
    return checker(["check", *_rule_args(registry), "--", *files])


def _rule_args(registry: Mapping[str, type[_Rule]]) -> list[str]:
    return [part for rule_id in sorted(registry) for part in ("--rule", rule_id)]


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """Add the all-rule runner arguments to a CLI parser."""
    parser.add_argument("files", nargs="+")
