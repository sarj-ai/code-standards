from pathlib import Path
from typing import TYPE_CHECKING

from sarj_python_lint.rules.no_tautological_expect import NoTautologicalExpect


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic


def _check(source: str, name: str = "tests/test_thing.py") -> list[Diagnostic]:
    return NoTautologicalExpect().check(Path(name), source)


def _count(source: str) -> int:
    return len(_check(source))


# ---------------------------------------------------------------------------
# Positive: the assertion's outcome is decided by its own literals.
# ---------------------------------------------------------------------------


def test_flags_bare_assert_true():
    diags = _check("def test_placeholder():\n    assert True\n")
    assert len(diags) == 1
    assert diags[0].code == "SARJ057"
    assert diags[0].line == 2


def test_flags_truthy_constants():
    for literal in ("True", "1", "-1", "0.5", '"text"', "b'bytes'", "..."):
        assert _count(f"def test_x():\n    assert {literal}\n") == 1, literal


def test_flags_set_display_wrapping_a_real_condition():
    """The Home Assistant shape: braces instead of parentheses make it a set literal."""
    src = (
        "def test_via_device_missing(caplog):\n"
        "    assert {\n"
        '        "calls `device_registry.async_get_or_create` "\n'
        '        "referencing a non existing `via_device` " in caplog.text\n'
        "    }\n"
    )
    diags = _check(src)
    assert len(diags) == 1
    assert "set display" in diags[0].message


def test_flags_list_display_that_lost_its_comparison():
    """The Airflow shape: `assert [msg]` where the `== messages` was dropped."""
    src = 'def test_read_remote_logs_not_found(ti):\n    assert [f"No logs found on hdfs for ti={ti}"]\n'
    diags = _check(src)
    assert len(diags) == 1
    assert "list display" in diags[0].message


def test_flags_every_non_empty_container_display():
    for display, kind in (("[1]", "list"), ("{1}", "set"), ("{'a': 1}", "dict"), ("(1, 2)", "tuple")):
        diags = _check(f"def test_x():\n    assert {display}\n")
        assert len(diags) == 1, display
        assert kind in diags[0].message, display


def test_flags_container_holding_a_runtime_value():
    """A non-empty display is truthy whatever it holds, so `[x]` still cannot fail."""
    assert _count("def test_x(x):\n    assert [x]\n") == 1


def test_flags_value_that_slid_into_the_message_slot():
    """The emulated_hue shape: `assert True, <the thing you meant to check>`."""
    src = 'def test_hue(cover_result_json):\n    assert True, cover_result_json[0]["success"]["on"]\n'
    diags = _check(src)
    assert len(diags) == 1
    assert "assertion-message slot" in diags[0].message


def test_flags_identical_literal_comparison():
    for expr in ("1 == 1", '"a" == "a"', "None is None", "(1, 2) == (1, 2)", "-1 == -1"):
        assert _count(f"def test_x():\n    assert {expr}\n") == 1, expr


def test_flags_unittest_assertions():
    src = (
        "class TestThing(TestCase):\n"
        "    def test_x(self):\n"
        "        self.assertTrue(True)\n"
        "        self.assertFalse(False)\n"
        "        self.assertEqual(1, 1)\n"
        '        self.assertIs("a", "a")\n'
    )
    assert _count(src) == 4


def test_flags_each_assertion_separately_and_sorts_by_position():
    src = "def test_x():\n    assert True\n    assert [1]\n    assert 2 == 2\n"
    diags = _check(src)
    assert [d.line for d in diags] == [2, 3, 4]


def test_fires_outside_test_files_too():
    """A never-failing assertion in production code is the same defect."""
    assert len(_check("def guard():\n    assert True\n", "src/app/service.py")) == 1


# ---------------------------------------------------------------------------
# Negative: self-comparison of a real value. Measured ~95% false positives —
# reflexivity, determinism and memoization are exactly what these tests verify.
# ---------------------------------------------------------------------------


def test_ignores_identifier_self_comparison():
    for expr in ("i == i", "x is x", "obj == obj", "self.value == self.value"):
        assert _count(f"def test_x(i, x, obj):\n    assert {expr}\n") == 0, expr


def test_ignores_call_self_comparison():
    """`hash(o) == hash(o)` is a determinism test on a custom `__hash__`."""
    for expr in ("hash(o) == hash(o)", "f(1) == f(1)", "parse('a') is parse('a')"):
        assert _count(f"def test_x(o):\n    assert {expr}\n") == 0, expr


def test_ignores_mixed_literal_and_identifier_comparison():
    assert _count("def test_x(result):\n    assert result == 1\n") == 0
    assert _count("def test_x(result):\n    assert 1 == result\n") == 0


def test_ignores_unittest_self_comparison_of_a_value():
    src = "class TestThing(TestCase):\n    def test_x(self, i):\n        self.assertEqual(i, i)\n"
    assert _count(src) == 0


# ---------------------------------------------------------------------------
# Negative: the carve-outs.
# ---------------------------------------------------------------------------


def test_ignores_assert_true_as_sole_except_body():
    """The deliberate 'this exception is the acceptable outcome' marker."""
    src = (
        "def test_connect_failure(hass, entry):\n"
        "    try:\n"
        "        assert await hass.config_entries.async_setup(entry.entry_id)\n"
        "    except HomeAssistantError:\n"
        "        assert True\n"
        '    assert "Failed to connect" in caplog.text\n'
    )
    assert _count(src) == 0


def test_flags_assert_true_that_is_not_the_whole_except_body():
    """Only a lone marker is exempt; an except handler doing real work is not."""
    src = "def test_x():\n    try:\n        f()\n    except ValueError:\n        assert True\n        cleanup()\n"
    assert _count(src) == 1


def test_ignores_benchmark_fixture_body():
    """pydantic-core's timed failing-validation path: `assert False` / `assert True`."""
    src = (
        "def test_core_validation_error(benchmark):\n"
        "    def validate_with_expected_error():\n"
        "        try:\n"
        "            v.validate_python(2)\n"
        "            assert False\n"
        "        except CoreValidationError:\n"
        "            assert True\n"
        "\n"
        "    benchmark(validate_with_expected_error)\n"
    )
    assert _count(src) == 0


def test_ignores_benchmark_marker_body():
    src = "@pytest.mark.benchmark\ndef test_speed():\n    assert True\n"
    assert _count(src) == 0


def test_ignores_benchmark_marker_with_arguments():
    src = '@pytest.mark.benchmark(group="parse")\ndef test_speed():\n    assert [1]\n'
    assert _count(src) == 0


def test_does_not_treat_an_unrelated_mark_as_a_benchmark():
    src = "@pytest.mark.asyncio\ndef test_speed():\n    assert True\n"
    assert _count(src) == 1


def test_does_not_treat_a_declared_but_unused_benchmark_param_as_a_benchmark():
    src = "def test_speed(benchmark):\n    assert True\n"
    assert _count(src) == 1


# ---------------------------------------------------------------------------
# Negative: assertions whose truth the code decides.
# ---------------------------------------------------------------------------


def test_ignores_assert_false():
    """The standard unreachable marker — and an always-failing assert is loud, not silent."""
    assert _count('def test_x():\n    assert False, "unreachable"\n') == 0


def test_ignores_empty_container():
    """`assert []` always fails, which surfaces on the first run."""
    for display in ("[]", "()", "{}"):
        assert _count(f"def test_x():\n    assert {display}\n") == 0, display


def test_ignores_splatted_container():
    """`[*items]` is empty when `items` is, so its truth is a runtime question."""
    assert _count("def test_x(items):\n    assert [*items]\n") == 0
    assert _count("def test_x(extra):\n    assert {**extra}\n") == 0


def test_ignores_fstring():
    assert _count('def test_x(value):\n    assert f"{value}"\n') == 0


def test_ignores_ordinary_assertions():
    src = (
        "def test_x(client, payload):\n"
        "    response = client.post(payload)\n"
        "    assert response.status == 200\n"
        '    assert response.json() == {"ok": True}\n'
        "    assert not response.errors\n"
        '    assert "id" in response.json()\n'
    )
    assert _count(src) == 0


def test_ignores_non_assertion_literals():
    """A literal in a return, a call argument or a default is nobody's assertion."""
    src = 'def build():\n    values = [1]\n    check(True)\n    return {"a": 1}\n'
    assert _count(src) == 0


def test_flags_unittest_equality_carrying_only_a_msg_keyword():
    """`msg=` is the failure text; it changes nothing about the outcome."""
    src = "class T(TestCase):\n    def test_x(self):\n        self.assertEqual(1, 1, msg='x')\n"
    assert _count(src) == 1


def test_ignores_a_look_alike_method_taking_other_keywords():
    src = "class T(TestCase):\n    def test_x(self):\n        self.assertEqual(1, 1, places=3)\n"
    assert _count(src) == 0


def test_ignores_syntax_error():
    assert _count("def broken(:\n") == 0


def test_ignores_empty_source():
    assert _count("") == 0
