"""Resolve the consumer's declared uv runtime without inheriting its config."""

from __future__ import annotations

import tomllib
from typing import TYPE_CHECKING, Final

from packaging.specifiers import InvalidSpecifier, SpecifierSet


if TYPE_CHECKING:
    from pathlib import Path


_UV_CONFIG: Final = "uv.toml"
_PYPROJECT: Final = "pyproject.toml"


def version_file(project: Path | None) -> Path | None:
    """Return the project file that explicitly constrains uv, when present."""
    if project is None:
        return None
    uv_config = project / _UV_CONFIG
    if required_version(uv_config) is not None:
        return uv_config
    pyproject = project / _PYPROJECT
    return pyproject if required_version(pyproject) is not None else None


def required_version(path: Path) -> str | None:
    """Read uv's PEP 440 ``required-version`` constraint from a supported file."""
    if not path.is_file():
        return None
    try:
        parsed: object = tomllib.loads(path.read_text(encoding="utf-8"))
    except OSError, tomllib.TOMLDecodeError:
        return None
    table = _table(parsed)
    if path.name == _PYPROJECT:
        table = _table(_table(table.get("tool")).get("uv"))
    value = table.get("required-version")
    if not isinstance(value, str) or not value:
        return None
    try:
        _ = SpecifierSet(value)
    except InvalidSpecifier:
        return None
    return value


def _table(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    return {key: item for key, item in value.items() if isinstance(key, str)}  # pyright: ignore[reportUnknownVariableType]


def argv(project: Path, *arguments: str) -> tuple[str, ...]:
    """Run uv arguments with a release satisfying the consumer contract."""
    source = version_file(project)
    required = None if source is None else required_version(source)
    if required is None:
        return ("uv", *arguments)
    return ("uvx", "--no-config", "--isolated", "--from", f"uv{required}", "uv", *arguments)


def lock_argv(project: Path) -> tuple[str, ...]:
    """Run lock resolution with a uv release satisfying the consumer contract."""
    return argv(project, "lock")
