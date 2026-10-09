from __future__ import annotations

from typing import TYPE_CHECKING

from sarj_standards._meta import __version__ as __version__


if TYPE_CHECKING:
    from sarj_standards.api import (
        AnalysisReport as AnalysisReport,
        Change as Change,
        Diagnostic as Diagnostic,
        Finding as Finding,
        Result as Result,
        Standards as Standards,
        Status as Status,
        to_github as to_github,
        to_json as to_json,
        to_sarif as to_sarif,
        to_text as to_text,
    )


__all__ = (  # sarj-noqa: SARJ438 -- PEP 562 needs explicit exports to preserve the existing public star-import contract while loading the SDK lazily.
    "AnalysisReport",
    "Change",
    "Diagnostic",
    "Finding",
    "Result",
    "Standards",
    "Status",
    "to_github",
    "to_json",
    "to_sarif",
    "to_text",
)


def __getattr__(name: str) -> object:
    if name not in __all__:
        msg = f"module 'sarj_standards' has no attribute {name!r}"
        raise AttributeError(msg)
    from sarj_standards import api  # ruff: ignore[import-outside-top-level] -- PEP 562 keeps SDK loading off lightweight release paths.

    match name:
        case "AnalysisReport":
            return api.AnalysisReport
        case "Change":
            return api.Change
        case "Diagnostic":
            return api.Diagnostic
        case "Finding":
            return api.Finding
        case "Result":
            return api.Result
        case "Standards":
            return api.Standards
        case "Status":
            return api.Status
        case "to_github":
            return api.to_github
        case "to_json":
            return api.to_json
        case "to_sarif":
            return api.to_sarif
        case "to_text":
            return api.to_text


def __dir__() -> list[str]:
    return sorted(set(globals()).union(__all__))
