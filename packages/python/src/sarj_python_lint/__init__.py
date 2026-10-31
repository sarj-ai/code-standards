from typing import TYPE_CHECKING as _TYPE_CHECKING

from sarj_python_lint._fixes import apply_fixes as apply_fixes, python_source_hash as python_source_hash
from sarj_python_lint._ratchet_cli import run_ratchet as run_ratchet
from sarj_python_lint._source import python_source_encoding as python_source_encoding
from sarj_python_lint._version import __version__ as __version__
from sarj_python_lint.application_logging import (
    ApplicationLoggingUse as ApplicationLoggingUse,
    application_logging_uses as application_logging_uses,
)


if _TYPE_CHECKING:
    from sarj_python_lint._analysis_session import AnalysisSession as AnalysisSession


def __getattr__(name: str) -> object:
    if name not in {"AnalysisSession", "__all__"}:
        msg = f"module 'sarj_python_lint' has no attribute {name!r}"
        raise AttributeError(msg)
    from sarj_python_lint._analysis_session import AnalysisSession as _AnalysisSession  # ruff: ignore[import-outside-top-level] -- lightweight metadata imports do not need semantic rules.

    globals(  # sarj-noqa: SARJ557 -- Preserve the lazy public module namespace and historical star-import exports.
    )["AnalysisSession"] = _AnalysisSession
    if name == "__all__":
        # Star imports previously exposed the complete post-session public namespace.
        # Discover it on demand instead of freezing a narrower list of exports.
        return tuple(
            public
            for public in globals(  # sarj-noqa: SARJ557 -- Preserve the lazy public module namespace and historical star-import exports.
            )
            if not public.startswith("_")
        )
    return _AnalysisSession


def __dir__() -> list[str]:
    return sorted(
        set(
            globals(  # sarj-noqa: SARJ557 -- Preserve the lazy public module namespace and historical star-import exports.
            )
        ).union({"AnalysisSession"})
    )
