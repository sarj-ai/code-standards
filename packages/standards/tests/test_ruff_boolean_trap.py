from __future__ import annotations

from pathlib import Path
import subprocess
import sys

from pydantic import BaseModel, RootModel
import pytest


_CONFIG = Path(__file__).parents[1] / "src/sarj_standards/configs/ruff.strict.toml"


class RuffDiagnostic(BaseModel):
    code: str


class RuffReport(RootModel[list[RuffDiagnostic]]):
    pass


@pytest.mark.parametrize(
    ("source", "path", "expected"),
    [
        ("def run(force: bool) -> None: ...\n", "src/service.py", ["FBT001"]),
        ("def run(force=False) -> None: ...\n", "src/service.py", ["FBT002"]),
        ("run(True)\n", "src/service.py", ["FBT003"]),
        ("run(False)\n", "src/service.py", ["FBT003"]),
        ("def run(force: bool = False) -> None: ...\n", "src/service.py", ["FBT001", "FBT002"]),
        ("def run(force: bool | None) -> None: ...\n", "src/service.py", ["FBT001"]),
        ("def run(force: bool, /) -> None: ...\n", "src/service.py", ["FBT001"]),
        ("async def run(force: bool) -> None: ...\n", "src/service.py", ["FBT001"]),
        ("def run(*, force: bool = False) -> None: ...\n", "src/service.py", []),
        ("run(force=True)\n", "src/service.py", []),
        ("def run(mode: str) -> None: ...\n", "src/service.py", []),
        ("def run() -> bool: return True\n", "src/service.py", []),
        (
            "from typing import override\nclass Service(Base):\n    @override\n    def run(self, force: bool) -> None: ...\n",
            "src/service.py",
            [],
        ),
        (
            (
                "class Service:\n    @property\n    def enabled(self) -> bool: ...\n"
                "    @enabled.setter\n    def enabled(self, value: bool) -> None: ...\n"
            ),
            "src/service.py",
            [],
        ),
        ("def run(force: bool = False) -> None: ...\nrun(True)\n", "tests/test_service.py", []),
    ],
)
def test_shipped_ruff_policy_owns_boolean_traps(source: str, path: str, expected: list[str]) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--config",
            str(_CONFIG),
            "--output-format",
            "json",
            "--stdin-filename",
            path,
            "-",
        ],
        input=source,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode in {0, 1}, result.stderr
    diagnostics = RuffReport.model_validate_json(result.stdout)
    assert [item.code for item in diagnostics.root if item.code.startswith("FBT")] == expected
