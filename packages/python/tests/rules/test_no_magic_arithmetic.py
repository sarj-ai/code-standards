from __future__ import annotations

from pathlib import Path

import pytest
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze
from sarj_python_lint.rules.no_magic_arithmetic import NoMagicArithmetic


def test_documented_examples() -> None:
    verify_native_rule(NoMagicArithmetic, analyze)


@pytest.mark.parametrize(
    "source",
    [
        "def normalize(sample: int):\n    return sample / 32768\n",
        "def scale(seconds: float):\n    return seconds * 1000\n",
        "def discount(price: float):\n    return price * 0.85\n",
        "def bucket(value: int):\n    return value % 100\n",
        "def frames(data):\n    return data[0:640]\n",
        "def send(data):\n    return range(0, len(data), 640)\n",
        "import asyncio\nasync def run():\n    async with asyncio.timeout(10):\n        await work()\n",
        "import asyncio as a\nasync def run():\n    await a.sleep(0.05)\n",
        "from time import sleep as pause\ndef run():\n    pause(10)\n",
        "def convert(x):\n    x *= 32000\n    return x\n",
    ],
)
def test_runtime_factors_and_limits_are_named(source: str) -> None:
    assert len(NoMagicArithmetic().check(Path("app/audio.py"), source)) == 1


@pytest.mark.parametrize(
    "source",
    [
        "PCM_SCALE = 2 ** 15\n",
        "class Constants:\n    PCM_SCALE = 2 ** 15\n",
        "def run():\n    PCM_SCALE = 2 ** 15\n    return PCM_SCALE\n",
        "SCALE = 32768\ndef normalize(sample):\n    return sample / SCALE\n",
        "def average(a, b):\n    return (a + b) / 2\n",
        "def next_index(index):\n    return index + 1\n",
        "def midpoint(data):\n    return data[1:-1]\n",
        "def rounded(value):\n    return round(value, 3)\n",
        "def run(timeout: float = 60):\n    return timeout\n",
        "class FieldSpec:\n    timeout: float = 60\n",
        "def run(asyncio):\n    asyncio.timeout(10)\n",
        "def range(*args): ...\ndef run(data):\n    return range(0, len(data), 640)\n",
        "def run(value):\n    return value / 32768  # sarj-noqa: SARJ570 -- This standard-defined transform is kept inline for review.\n",
        "text = 'value / 32768'\n",
        "invalid python !\n",
    ],
)
def test_named_declarations_trivial_math_and_external_contracts(source: str) -> None:
    assert NoMagicArithmetic().check(Path("app/audio.py"), source) == []


def test_test_data_is_excluded() -> None:
    source = "def test_audio():\n    assert normalize(32768) == 1\n"
    assert NoMagicArithmetic().check(Path("tests/test_audio.py"), source) == []
