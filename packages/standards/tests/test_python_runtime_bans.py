from __future__ import annotations

from pathlib import Path
import subprocess
import sys

from pydantic import BaseModel, RootModel
import pytest


_CONFIG = Path(__file__).parents[1] / "src/sarj_standards/configs/ruff.strict.toml"
_RUNTIME_RULES = frozenset({"S307", "T100"})


class RuffDiagnostic(BaseModel):
    code: str | None


class RuffReport(RootModel[list[RuffDiagnostic]]):
    pass


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("eval(payload)\n", ["S307"]),
        ('eval("42")\n', ["S307"]),
        ("import builtins\nbuiltins.eval(payload)\n", ["S307"]),
        ("from builtins import eval as evaluate\nevaluate(payload)\n", ["S307"]),
        ("evaluate = eval\n", ["S307"]),
        ("breakpoint()\n", ["T100"]),
        ("import builtins\nbuiltins.breakpoint()\n", ["T100"]),
        ("from builtins import breakpoint as pause\npause()\n", ["T100", "T100"]),
        ("import pdb\npdb.set_trace()\n", ["T100", "T100"]),
        ('description = "eval(payload); breakpoint(); pdb.set_trace()"\n', []),
        ("# eval(payload); breakpoint(); pdb.set_trace()\n", []),
        ("import json\nvalue = json.loads(payload)\n", []),
        (
            (
                "class Runner:\n    def eval(self, value):\n        return value\n"
                "    def breakpoint(self):\n        return None\n"
                'Runner().eval("value")\nRunner().breakpoint()\n'
            ),
            [],
        ),
        (
            (
                "eval(payload)  # ruff: ignore[suspicious-eval-usage] -- This fixture explicitly tests trusted expression evaluation.\n"
                "breakpoint()\n"
            ),
            ["T100"],
        ),
        (
            (
                "breakpoint()  # ruff: ignore[debugger] -- This fixture explicitly exercises the debugger entrypoint.\n"
                "eval(payload)\n"
            ),
            ["S307"],
        ),
    ],
)
def test_runtime_bans_retain_native_ruff_ownership(source: str, expected: list[str]) -> None:
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
            "src/runtime.py",
            "-",
        ],
        input=source,
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )
    assert result.returncode in {0, 1}
    assert not result.stderr
    diagnostics = RuffReport.model_validate_json(result.stdout).root
    assert all(diagnostic.code != "invalid-syntax" for diagnostic in diagnostics)
    assert [diagnostic.code for diagnostic in diagnostics if diagnostic.code in _RUNTIME_RULES] == expected
