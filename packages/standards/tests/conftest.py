from __future__ import annotations

import os

import pytest


@pytest.fixture(autouse=True)
def isolate_enclosing_git_hook(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep an enclosing Git hook from routing fixture commands to the real repo."""
    for name in tuple(os.environ):  # ruff: ignore[banned-api] -- tests must sanitize inherited hook routing.
        if name.startswith("GIT_"):
            monkeypatch.delenv(name)
