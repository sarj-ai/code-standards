"""Hook-manager detection and validation shared by init, update, and doctor."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final


if TYPE_CHECKING:
    from pathlib import Path

    from .manifest import HookManager


LEFTHOOK_NAMES: Final = ("lefthook.yml", "lefthook.yaml")
_STAGED_COMMAND: Final = "sarj-standards check --staged"


def lefthook_config(root: Path) -> Path | None:
    """Return the active Lefthook configuration, if present."""
    return next((root / name for name in LEFTHOOK_NAMES if (root / name).is_file()), None)


def detect_manager(root: Path) -> HookManager:
    """Preserve an existing Lefthook setup; otherwise manage pre-commit."""
    return "lefthook" if lefthook_config(root) is not None else "pre-commit"


def lefthook_runs_staged_check(root: Path) -> bool:
    """Require the user-managed hook to invoke the canonical staged command."""
    path = lefthook_config(root)
    if path is None:
        return False
    try:
        text = path.read_text(encoding="utf-8")
    except OSError, UnicodeError:
        return False
    return _STAGED_COMMAND in text and "pre-commit:" in text
