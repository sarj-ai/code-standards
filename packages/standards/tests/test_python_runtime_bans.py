from __future__ import annotations

from pathlib import Path
import subprocess
import sys

from pydantic import BaseModel, RootModel
import pytest
from sarj_python_lint.rules.no_shared_mutable_default import NoSharedMutableDefault


_CONFIG = Path(__file__).parents[1] / "src/sarj_standards/configs/ruff.strict.toml"
_RUNTIME_RULES = frozenset({"S307", "S102", "T100", "TID251", "PLW0602", "PLW0603", "PLW0604", "F403", "F406", "B006"})


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
        ("exec(payload)\n", ["S102"]),
        ("import builtins\nbuiltins.exec(payload)\n", ["S102"]),
        ("from builtins import exec as execute\nexecute(payload)\n", ["S102"]),
        ("global counter\n", ["PLW0604"]),
        ("counter = 0\ndef increment():\n    global counter\n    counter += 1\n", ["PLW0603"]),
        ("counter = 0\ndef read():\n    global counter\n    return counter\n", ["PLW0602"]),
        ("from application import *\n", ["F403"]),
        ("def batch(values=[]):\n    return values\n", ["B006"]),
        ("def batch(*, values={}):\n    return values\n", ["B006"]),
        ("def batch(values=set()):\n    return values\n", ["B006"]),
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


@pytest.mark.parametrize("name", ["locals", "globals", "compile", "__import__", "getattr", "hasattr", "delattr"])
@pytest.mark.parametrize("form", ["qualified", "import-alias"])
def test_dynamic_builtins_use_native_banned_api(name: str, form: str) -> None:
    source = (
        f"import builtins as native\nnative.{name}(value)\n"
        if form == "qualified"
        else f"from builtins import {name} as operation\noperation(value)\n"
    )
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
    assert result.returncode == 1
    assert not result.stderr
    diagnostics = RuffReport.model_validate_json(result.stdout).root
    assert [diagnostic.code for diagnostic in diagnostics if diagnostic.code in _RUNTIME_RULES] == ["TID251"]


@pytest.mark.parametrize(
    ("source", "native_owner"),
    [
        ("def read(values=[]): pass\n", True),
        ("def read(values={}): pass\n", True),
        ("def read(values=set()): pass\n", True),
        ("def read(values=bytearray()): pass\n", False),
        ("def read(values=list[int]()): pass\n", True),
        ("import collections\ndef read(values=collections.deque()): pass\n", True),
        ("import collections\ndef read(values=collections.defaultdict()): pass\n", True),
        ("import collections\ndef read(values=collections.Counter()): pass\n", True),
        ("import collections\ndef read(values=collections.OrderedDict()): pass\n", True),
        ("import collections\ndef read(values=collections.ChainMap()): pass\n", True),
        ("import collections\ndef read(values=collections.UserList()): pass\n", True),
        ("import collections\ndef read(values=collections.UserDict()): pass\n", True),
        ("import collections\ndef read(values=collections.deque[int]()): pass\n", True),
        ("from collections import deque as make_values\ndef read(values=make_values()): pass\n", True),
        ("import collections\ncontainers = collections\ndef read(values=containers.deque()): pass\n", False),
        ("make_values = list\ndef read(values=make_values()): pass\n", False),
        ("SHARED = []\ndef read(values=SHARED): pass\n", False),
        ("def read(values=(cache := [])): pass\n", True),
        ("def read(values: object=(cache := [])): pass\n", False),
        ("def read(values: object=[]): pass\n", False),
        ("def read(values: object=list[int]()): pass\n", False),
        ("from collections.abc import Sequence\ndef read(values: Sequence[int]=[]): pass\n", False),
        ("def read(values=[] if condition else []): pass\n", False),
        ("def read(values=[] + []): pass\n", False),
        ("def read(values=[1] * 2): pass\n", False),
        ("read = lambda values=[]: values\n", False),
        ("read = lambda values=(cache := []): values\n", False),
        ("from typing import Sequence\nReadonly = Sequence\ndef read(values: Readonly=[]): pass\n", True),
        ("import typing\nannotations = typing\ndef read(values: annotations.Sequence[int]=[]): pass\n", True),
        ("Opaque = object\ndef read(values: Opaque=[]): pass\n", True),
        ("from typing import Sequence\nReadonly = Sequence[int]\ndef read(values: Readonly=[]): pass\n", True),
    ],
)
def test_mutable_defaults_have_exactly_one_owner(source: str, native_owner: bool) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--config",
            str(_CONFIG),
            "--select",
            "B006",
            "--output-format",
            "json",
            "--stdin-filename",
            "service/batch.py",
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
    native = RuffReport.model_validate_json(result.stdout).root
    custom = NoSharedMutableDefault().check(Path("service/batch.py"), source)
    assert len(native) == int(native_owner)
    assert len(custom) == int(not native_owner)
