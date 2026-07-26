from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rules.xfail_requires_strict import XfailRequiresStrict


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic


TEST_PATH = "python/noura/tests/test_known_auth_bugs_xfail.py"


def _check(source: str, path: str = TEST_PATH) -> list[Diagnostic]:
    return XfailRequiresStrict().check(Path(path), source)


_ROTTING_PIN = """
import pytest

@pytest.mark.xfail(reason="BUG: returns 404 instead of the error envelope")
def test_thing():
    assert correct_behaviour()
"""


# --------------------------------------------------------------------------- #
# Test-path gating.                                                            #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("path", ["test_x.py", "x_test.py", "conftest.py", "a/tests/h.py"])
def test_fires_in_test_paths(path: str):
    assert len(_check(_ROTTING_PIN, path)) == 1


@pytest.mark.parametrize("path", ["src/service.py", "a/testing/thing.py"])
def test_skips_non_test_paths(path: str):
    assert _check(_ROTTING_PIN, path) == []


# --------------------------------------------------------------------------- #
# Positive: a defect-naming reason with no strict flag.                        #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "reason",
    [
        "BUG: wrong status code",
        "broken since the v2 migration",
        "regression introduced by PLT-1234",
        "returns an incorrect envelope",
        "should return 422 but returns 500",
        "FIXME: ordering is wrong here",
    ],
)
def test_flags_defect_reasons(reason: str):
    src = f"""
import pytest

@pytest.mark.xfail(reason="{reason}")
def test_thing():
    assert correct()
"""
    assert len(_check(src)) == 1


def test_flags_explicit_strict_false():
    src = """
import pytest

@pytest.mark.xfail(reason="BUG: bad envelope", strict=False)
def test_thing():
    assert correct()
"""
    assert len(_check(src)) == 1


def test_flags_reason_built_by_implicit_concatenation():
    src = """
import pytest

@pytest.mark.xfail(
    reason=(
        "BUG: the endpoint returns FastAPI's default detail "
        "instead of the documented envelope"
    ),
)
def test_thing():
    assert correct()
"""
    assert len(_check(src)) == 1


# --------------------------------------------------------------------------- #
# FP guard: strict pins, nondeterministic markers, and environment gates.      #
# The real_llm exemption is mandatory — every non-strict xfail in noura-be     #
# sits on a live-model eval that legitimately cannot be strict.                #
# --------------------------------------------------------------------------- #


def test_strict_true_is_exempt():
    src = """
import pytest

@pytest.mark.xfail(reason="BUG: bad envelope", strict=True)
def test_thing():
    assert correct()
"""
    assert _check(src) == []


@pytest.mark.parametrize("marker", ["real_llm", "flaky", "network", "integration"])
def test_nondeterministic_sibling_marker_is_exempt(marker: str):
    src = f"""
import pytest

@pytest.mark.{marker}
@pytest.mark.xfail(reason="BUG: the model sometimes answers in English")
def test_thing():
    assert correct()
"""
    assert _check(src) == []


@pytest.mark.parametrize(
    "reason",
    [
        "BUG: intermittently returns the wrong language",
        "flaky under load, wrong ordering",
        "sometimes returns an incorrect total",
        "non-deterministic: should be stable",
    ],
)
def test_reason_conceding_nondeterminism_is_exempt(reason: str):
    src = f"""
import pytest

@pytest.mark.xfail(reason="{reason}")
def test_thing():
    assert correct()
"""
    assert _check(src) == []


@pytest.mark.parametrize(
    "reason",
    [
        "no GPU available on CI",
        "clickhouse init script defines the view against postgres_mirror",
        "requires the pubsub emulator",
    ],
)
def test_environment_gate_reasons_are_exempt(reason: str):
    src = f"""
import pytest

@pytest.mark.xfail(reason="{reason}")
def test_thing():
    assert correct()
"""
    assert _check(src) == []


def test_xfail_without_a_reason_is_exempt():
    src = """
import pytest

@pytest.mark.xfail
def test_thing():
    assert correct()
"""
    assert _check(src) == []


def test_called_xfail_without_a_reason_is_exempt():
    src = """
import pytest

@pytest.mark.xfail()
def test_thing():
    assert correct()
"""
    assert _check(src) == []


def test_kwargs_forwarding_is_exempt():
    src = """
import pytest

@pytest.mark.xfail(reason="BUG: bad", **marker_kwargs)
def test_thing():
    assert correct()
"""
    assert _check(src) == []


def test_imperative_pytest_xfail_call_is_exempt():
    src = """
import pytest

def test_thing():
    pytest.xfail("BUG: should not reach here")
"""
    assert _check(src) == []


def test_unrelated_marker_is_not_flagged():
    src = """
import pytest

@pytest.mark.skip(reason="BUG: broken")
def test_thing():
    assert correct()
"""
    assert _check(src) == []


# --------------------------------------------------------------------------- #
# Edge cases.                                                                  #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("source", ["", "  \n\n ", "# comment\n"])
def test_empty_source_is_clean(source: str):
    assert _check(source) == []


def test_syntax_error_returns_no_diagnostics():
    assert _check('@pytest.mark.xfail(reason="BUG")\ndef test_x(:\n') == []


def test_multiple_hits_in_one_file():
    src = """
import pytest

@pytest.mark.xfail(reason="BUG: one")
def test_one():
    assert correct()

@pytest.mark.xfail(reason="BUG: two", strict=True)
def test_two():
    assert correct()

@pytest.mark.xfail(reason="regression: three")
def test_three():
    assert correct()
"""
    assert len(_check(src)) == 2


def test_reports_line_and_column_of_the_marker():
    src = """
import pytest

@pytest.mark.xfail(reason="BUG: bad envelope")
def test_thing():
    assert correct()
"""
    [diag] = _check(src)
    assert diag.line == 4
    assert diag.code == "SARJ046"


def test_diagnostics_are_sorted_by_position():
    src = """
import pytest

@pytest.mark.xfail(reason="BUG: a")
def test_a():
    assert correct()

@pytest.mark.xfail(reason="BUG: b")
def test_b():
    assert correct()
"""
    diags = _check(src)
    assert [d.line for d in diags] == sorted(d.line for d in diags)


def test_async_test_is_covered():
    src = """
import pytest

@pytest.mark.xfail(reason="BUG: bad envelope")
async def test_thing():
    assert await correct()
"""
    assert len(_check(src)) == 1
