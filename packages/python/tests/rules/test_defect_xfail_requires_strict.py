from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rules.defect_xfail_requires_strict import DefectXfailRequiresStrict


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic, RuleExample


TEST_PATH = "python/app/tests/test_known_auth_bugs_xfail.py"


def _check(source: str, path: str = TEST_PATH) -> list[Diagnostic]:
    return DefectXfailRequiresStrict().check(Path(path), source)


_PUBLIC_EXAMPLES = DefectXfailRequiresStrict.public_examples()


@pytest.mark.parametrize("example", _PUBLIC_EXAMPLES, ids=tuple(e.example_id for e in _PUBLIC_EXAMPLES))
def test_public_documentation_examples_are_executable(example: RuleExample) -> None:
    focus = example.focus_file
    assert len(_check(focus.source, str(focus.path))) == example.expected_count


_ROTTING_PIN = """
import pytest

@pytest.mark.xfail(reason="BUG: returns 404 instead of the error envelope")
def test_thing():
    assert correct_behaviour()
"""


# Test-path gating.                                                            #


@pytest.mark.parametrize("path", ["test_x.py", "x_test.py", "conftest.py", "a/tests/h.py"])
def test_fires_in_test_paths(path: str):
    assert len(_check(_ROTTING_PIN, path)) == 1


@pytest.mark.parametrize("path", ["src/service.py", "a/testing/thing.py"])
def test_skips_non_test_paths(path: str):
    assert _check(_ROTTING_PIN, path) == []


# Positive: a defect-naming reason with no strict flag.                        #


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


# FP guard: strict pins, nondeterministic markers, and environment gates.      #
# The real_llm exemption is mandatory — every non-strict xfail in one          #
# first-party repo sits on a live-model eval that cannot be strict.            #


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


@pytest.mark.parametrize(
    "decorator",
    [
        "@given(st.text())",
        "@given(value=st.integers())",
        "@known_bug_schema.parametrize()",
        "@schema.parametrize()",
        "@self.schema.parametrize()",
    ],
)
def test_property_based_tests_are_exempt(decorator: str):
    # One test function expands into many generated inputs; a documented bug is
    # usually tripped by only a subset, so the rest legitimately XPASS and
    # strict=True would turn every passing input into a failure.
    src = f"""
import pytest

{decorator}
@pytest.mark.xfail(reason="BUG: unroutable ids return the wrong envelope", strict=False)
def test_thing(case):
    case.call_and_validate()
"""
    assert _check(src) == []


def test_pytest_mark_parametrize_is_still_flagged():
    # A fixed case table is not a generator — every case runs the same code path,
    # so a bug pin over it can and should be strict.
    src = """
import pytest

@pytest.mark.parametrize("value", ["a", "b"])
@pytest.mark.xfail(reason="BUG: wrong envelope")
def test_thing(value):
    assert correct(value)
"""
    assert len(_check(src)) == 1


def test_flags_class_level_bug_pin() -> None:
    src = """
import pytest

@pytest.mark.xfail(reason="BUG: wrong envelope")
class TestEnvelope:
    def test_get(self):
        assert correct()
"""

    diagnostics = _check(src)

    assert len(diagnostics) == 1
    assert diagnostics[0].line == 4


@pytest.mark.parametrize("marker", ["real_llm", "flaky", "network", "integration"])
def test_class_level_nondeterministic_sibling_exempts_bug_pin(marker: str) -> None:
    src = f"""
import pytest

@pytest.mark.{marker}
@pytest.mark.xfail(reason="BUG: wrong envelope")
class TestEnvelope:
    def test_get(self):
        assert correct()
"""

    assert _check(src) == []


@pytest.mark.parametrize(
    "declaration",
    [
        'pytestmark = pytest.mark.xfail(reason="BUG: wrong envelope")',
        'pytestmark = [pytest.mark.xfail(reason="BUG: wrong envelope")]',
        'pytestmark: object = (pytest.mark.xfail(reason="BUG: wrong envelope"),)',
    ],
)
def test_flags_module_pytestmark_bug_pin(declaration: str) -> None:
    src = f"""import pytest

{declaration}

def test_get():
    assert correct()
"""

    assert len(_check(src)) == 1


@pytest.mark.parametrize("marker", ["real_llm", "flaky", "network", "integration"])
def test_module_pytestmark_nondeterministic_sibling_exempts_bug_pin(marker: str) -> None:
    src = f"""import pytest

pytestmark = [
    pytest.mark.xfail(reason="BUG: wrong envelope"),
    pytest.mark.{marker},
]

def test_get():
    assert correct()
"""

    assert _check(src) == []


def test_dynamic_or_rebound_module_pytestmark_is_exempt() -> None:
    src = """import pytest

pytestmark = markers()
pytestmark = [pytest.mark.xfail(reason="BUG: wrong envelope")]

def test_get():
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


def test_dynamic_strict_value_is_exempt():
    src = """
import pytest

@pytest.mark.xfail(reason="BUG: bad", strict=STRICT_XFAILS)
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


def test_xfail_used_as_pytest_param_marker_is_exempt():
    src = """
import pytest

@pytest.mark.parametrize(
    "value",
    [pytest.param("bad", marks=pytest.mark.xfail(reason="BUG: wrong envelope"))],
)
def test_thing(value):
    assert correct(value)
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


# Edge cases.                                                                  #


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


# FP-hardening (famous-repo sweep): an environment-gated conditional xfail      #
# pins a third-party defect on the environments that carry it, not our bug.     #


def test_allows_interpreter_gated_conditional_xfail():
    # Minimized from anyio's tests/streams/test_text.py.
    src = """
import platform
import sys

@pytest.mark.xfail(
    platform.python_implementation() == "PyPy" and sys.pypy_version_info < (7, 3, 2),
    reason="PyPy has a bug in its incremental UTF-8 decoder (#3274)",
)
async def test_receive_encoding_error():
    assert decode() == "x"
"""
    assert _check(src) == []


def test_allows_os_gated_conditional_xfail():
    src = """
@pytest.mark.xfail(sys.platform == "win32", reason="broken on Windows only")
def test_paths():
    assert resolve() == "/tmp"
"""
    assert _check(src) == []


@pytest.mark.parametrize(
    "condition",
    [
        'condition=sys.platform == "win32"',
        "condition=\"sys.platform == 'win32'\"",
        "\"sys.platform == 'win32'\"",
    ],
)
def test_allows_keyword_and_string_environment_conditions(condition: str) -> None:
    src = f"""\
import pytest
import sys

@pytest.mark.xfail({condition}, reason="BUG: broken on Windows only")
def test_windows_behavior():
    pass
"""
    assert _check(src) == []


def test_keyword_non_environment_condition_still_requires_strict() -> None:
    src = """\
import pytest

@pytest.mark.xfail(condition=FEATURE_ROLLED_OUT, reason="BUG: wrong envelope")
def test_feature():
    pass
"""
    assert len(_check(src)) == 1


def test_flags_unconditional_bug_pin_in_same_file_as_gated_one():
    src = """
@pytest.mark.xfail(sys.platform == "win32", reason="broken on Windows only")
def test_paths():
    assert resolve() == "/tmp"

@pytest.mark.xfail(reason="Bug: returns 404 instead of the error envelope")
def test_envelope():
    assert envelope() == {}
"""
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].line == 6


def test_flags_conditional_xfail_gated_on_a_non_environment_flag():
    src = """
@pytest.mark.xfail(FEATURE_ROLLED_OUT, reason="Bug: the new path drops the envelope")
def test_envelope():
    assert envelope() == {}
"""
    assert len(_check(src)) == 1
