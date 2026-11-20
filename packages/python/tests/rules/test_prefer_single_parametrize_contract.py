from pathlib import Path
import subprocess
import sys

import pytest
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze
from sarj_python_lint.rules.prefer_single_parametrize_contract import PreferSingleParametrizeContract


def test_documented_examples() -> None:
    verify_native_rule(PreferSingleParametrizeContract, analyze)


_BEFORE = PreferSingleParametrizeContract.public_examples()[0].focus_file.source
_AFTER = PreferSingleParametrizeContract.public_examples()[1].focus_file.source


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("['a', 'b']", "modes"),
        ("['a', 'b']", "[pytest.param('a', marks=pytest.mark.slow), 'b']"),
        ("['a', 'b'])", "['a', 'b'], ids=['a', 'b'])"),
        ("['a', 'b'])", "['a', 'b'], indirect=True)"),
        ("'mode'", "'kind'"),
        ("'mode'", "'invalid,name'"),
        ("[1, 2]", "[]"),
        ("[1, 2]", "list(range(1000))"),
        ("import pytest", "import other as pytest"),
        ("def test_value", "@pytest.mark.asyncio\ndef test_value"),
    ],
)
def test_collection_options_dynamic_and_malformed_axes_remain_allowed(old: str, new: str) -> None:
    assert PreferSingleParametrizeContract().check(Path("tests/test_value.py"), _BEFORE.replace(old, new)) == []


def test_native_pytest_collects_the_same_order_ids_and_cardinality(tmp_path: Path) -> None:
    path = tmp_path / "test_value.py"
    collected: list[list[str]] = []
    for source in (_BEFORE, _AFTER):
        path.write_text(source)
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "--collect-only", "-q", "-o", "addopts=", str(path)],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        collected.append([line for line in result.stdout.splitlines() if "::test_value[" in line])
    assert collected[0] == collected[1]
    assert len(collected[0]) == 4


def test_one_warning_covers_the_complete_stack_and_honors_suppression() -> None:
    findings = PreferSingleParametrizeContract().check(Path("tests/test_value.py"), _BEFORE)
    assert len(findings) == 1
    assert findings[0].fixes == ()
    lines = _BEFORE.splitlines()
    lines[findings[0].line - 1] += "  # sarj-noqa: SARJ583 -- Separate collection contract."
    suppressed = "\n".join(lines) + "\n"
    assert PreferSingleParametrizeContract().check(Path("tests/test_value.py"), suppressed) == []


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("[1, 2]", "[[1], [2]]"),
        ("[1, 2]", "[1, 1]"),
        ("[1, 2]", "[1, '1']"),
        ("[1, 2]", "[None, 'None']"),
        ("[1, 2]", "[b'a', b'b']"),
        ("[1, 2]", r"[b'\\n', '\n']"),
        ("[1, 2]", r"[b'\\xe9', 'é']"),
    ],
    ids=[
        "composite-placeholder",
        "duplicate-scalar",
        "mixed-ID-collision",
        "none-ID-collision",
        "bytes",
        "bytes-newline-ID-collision",
        "bytes-unicode-ID-collision",
    ],
)
def test_native_axis_id_changes_are_not_recommended(old: str, new: str) -> None:
    assert PreferSingleParametrizeContract().check(Path("tests/test_value.py"), _BEFORE.replace(old, new)) == []


def test_colliding_joined_ids_are_not_recommended() -> None:
    source = _BEFORE.replace("[1, 2]", "['a-b', 'a']").replace("['a', 'b']", "['c', 'b-c']")
    assert PreferSingleParametrizeContract().check(Path("tests/test_value.py"), source) == []


@pytest.mark.parametrize(
    "source",
    [
        "__test__ = False\n" + _BEFORE,
        _BEFORE + "test_value.__test__ = False\n",
        _BEFORE + "def pytest_make_parametrize_id(config, value, argname): return 'custom'\n",
        _BEFORE.replace("import pytest\n", "import pytest\nclass TestValue:\n    __test__ = False\n")
        .replace("@pytest", "    @pytest")
        .replace("def test_value(kind, mode):", "    def test_value(self, kind, mode):")
        .replace("    assert kind", "        assert kind"),
    ],
    ids=["disabled-module", "disabled-function", "visible-ID-hook", "disabled-class"],
)
def test_native_uncollected_owners_and_id_hooks_abstain(source: str) -> None:
    assert PreferSingleParametrizeContract().check(Path("tests/test_value.py"), source) == []


def test_signed_scalar_axes_keep_one_explicit_contract() -> None:
    source = _BEFORE.replace("[1, 2]", "[-1, +2]")
    assert len(PreferSingleParametrizeContract().check(Path("tests/test_value.py"), source)) == 1
