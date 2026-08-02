"""Run every installed Sarj custom rule with one maintainable command."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from . import textlint


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
    TEXT = "text"


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
        ".next",
        ".turbo",
        ".wrangler",
        ".yarn",
        ".tox",
        ".uv-cache",
        ".venv",
        "dist",
        "build",
        "coverage",
        "node_modules",
        "out",
        "target",
        "vendor",
    }
)
_PYTHON_NOISE_RULES = frozenset(
    {
        "docstring-args-restate-signature",
        "docstring-returns-restate-signature",
        "duplicated-override-docstring",
        "no-comment-cruft",
        "no-restated-comment",
        "redundant-class-docstring",
        "redundant-docstring",
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


def run(
    files: Sequence[str],
    *,
    noise_only: bool = False,
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

    if noise_only:
        python_rules = _select_rules(python_rules, _PYTHON_NOISE_RULES)
        sql_rules = _select_rules(sql_rules, frozenset())
        iac_rules = _select_rules(iac_rules, _IAC_NOISE_RULES)

    grouped = group_paths(files)
    statuses = (
        _run(python_main, python_rules, grouped.python),
        _run(sql_main, sql_rules, grouped.sql),
        _run(iac_main, iac_rules, grouped.iac),
        textlint.run(grouped.text),
    )
    return max(statuses)


def _select_rules(registry: Mapping[str, type[_Rule]], selected: frozenset[str]) -> dict[str, type[_Rule]]:
    return {rule_id: rule for rule_id, rule in registry.items() if rule_id in selected}


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
    if not isinstance(checker_module, _CheckerModule) or not isinstance(registry_module, _RegistryModule):
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
                    continue
                if not child.is_file():
                    continue
                _route_path(grouped, child, str(child))
            continue
        _route_path(grouped, path, raw_path)
    return grouped


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
        case None:
            return


def _run(
    checker: Callable[[list[str]], int],
    registry: Mapping[str, type[_Rule]],
    files: Sequence[str],
) -> int:
    if not files or not registry:
        return 0
    return checker(["check", *_rule_args(registry), "--", *files])


def _rule_args(registry: Mapping[str, type[_Rule]]) -> list[str]:
    return [part for rule_id in sorted(registry) for part in ("--rule", rule_id)]


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """Add the all-rule runner arguments to a CLI parser."""
    parser.add_argument(
        "--noise-only",
        action="store_true",
        help="run Python, config-prose, and AI-artifact noise rules (TypeScript uses the ESLint plugin)",
    )
    parser.add_argument("files", nargs="+")
