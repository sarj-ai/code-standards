from __future__ import annotations

import subprocess
import sys
from typing import TYPE_CHECKING

import pytest

from sarj_standards._meta import RUFF_APPLICATION, RUFF_STRICT


if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("config", [RUFF_STRICT, RUFF_APPLICATION], ids=["strict", "application"])
@pytest.mark.parametrize(
    ("source", "remediation"),
    [
        *[
            (f"from {module} import {symbol}\n", message)
            for module in ("typing", "typing_extensions")
            for symbol, message in (
                ("TypeVar", "Declare type parameters inline"),
                ("ParamSpec", "Declare the parameter specification inline"),
                ("TypeVarTuple", "Declare the variadic parameter inline"),
                ("Generic", "Use a PEP 695 class header"),
                ("AnyStr", "Use a constrained parameter"),
            )
        ],
        ('import typing\nT = typing.TypeVar("T")\n', "Declare type parameters inline"),
        ("import asyncio\nloop = asyncio.get_event_loop()\n", "asyncio.get_running_loop()"),
    ],
)
def test_legacy_generics_and_implicit_event_loops_are_banned(
    config: Path, source: str, remediation: str, tmp_path: Path
) -> None:
    probe = tmp_path / "legacy.py"
    probe.write_text(source)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--no-cache",
            "--select",
            "TID251",
            "--config",
            str(config),
            str(probe),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert remediation in result.stdout
    assert "Found 1 error" in result.stdout


@pytest.mark.parametrize("config", [RUFF_STRICT, RUFF_APPLICATION], ids=["strict", "application"])
@pytest.mark.parametrize(
    "source",
    [
        "def first[T](xs: list[T]) -> T: ...\n",
        "class Box[T]: ...\n",
        "class Box[T = int]: ...\n",
        "import asyncio\nloop = asyncio.get_running_loop()\n",
        "from elsewhere import TypeVar\n",
        "from typing import TypeVar  # noqa: TID251 -- required external compatibility contract.\n",
        "import asyncio\nloop = asyncio.get_event_loop()  # noqa: TID251 -- required external compatibility contract.\n",
    ],
    ids=["function", "class", "default", "running-loop", "unrelated", "import-escape", "call-escape"],
)
def test_modern_forms_and_reasoned_exceptions_are_allowed(config: Path, source: str, tmp_path: Path) -> None:
    probe = tmp_path / "modern.py"
    probe.write_text(source)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--no-cache",
            "--select",
            "TID251",
            "--config",
            str(config),
            str(probe),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
