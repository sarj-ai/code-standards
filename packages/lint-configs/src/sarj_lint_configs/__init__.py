from __future__ import annotations

from importlib import import_module
from types import FunctionType
from typing import TYPE_CHECKING

from sarj_lint_configs._meta import (
    CONFIGS_DIR,
    ESLINT_APPLICATION,
    ESLINT_PEERS,
    ESLINT_STRICT,
    MARKDOWNLINT_STRICT,
    PYRIGHT_STRICT,
    RUFF_APPLICATION,
    RUFF_STRICT,
    TAPLO_STRICT,
    YAMLLINT_STRICT,
    __version__,
)


if TYPE_CHECKING:
    from sarj_lint_configs.api import (
        AnalysisReport,
        Change,
        Diagnostic,
        Finding,
        Result,
        Standards,
        Status,
        UpdateTarget,
        to_github,
        to_json,
        to_sarif,
        to_text,
    )


_API_EXPORTS = frozenset(  # ruff: ignore[non-empty-init-module] -- lazy exports keep CLI startup lightweight.
    {
        "AnalysisReport",
        "Change",
        "Diagnostic",
        "Finding",
        "Result",
        "Standards",
        "Status",
        "UpdateTarget",
        "to_github",
        "to_json",
        "to_sarif",
        "to_text",
    }
)


def __getattr__(name: str) -> object:
    """Load the rich facade lazily so metadata-only CLI launches stay lightweight."""
    if name not in _API_EXPORTS:
        raise AttributeError(name)
    candidate = vars(import_module("sarj_lint_configs.api")).get(name)
    if not isinstance(candidate, (type, FunctionType)):  # pragma: no cover - static export table is tested.
        raise AttributeError(name)  # ruff: ignore[type-check-without-type-error] -- required by the module protocol.
    value: object = candidate
    globals()[name] = value
    return value


__all__ = [
    "CONFIGS_DIR",
    "ESLINT_APPLICATION",
    "ESLINT_PEERS",
    "ESLINT_STRICT",
    "MARKDOWNLINT_STRICT",
    "PYRIGHT_STRICT",
    "RUFF_APPLICATION",
    "RUFF_STRICT",
    "TAPLO_STRICT",
    "YAMLLINT_STRICT",
    "AnalysisReport",
    "Change",
    "Diagnostic",
    "Finding",
    "Result",
    "Standards",
    "Status",
    "UpdateTarget",
    "__version__",
    "to_github",
    "to_json",
    "to_sarif",
    "to_text",
]
