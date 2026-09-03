from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules.no_tautological_expect import NoTautologicalExpect


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic, RuleExample


_PUBLIC_EXAMPLES = NoTautologicalExpect.public_examples()


def _check(source: str, name: str = "tests/test_thing.py") -> list[Diagnostic]:
    return NoTautologicalExpect().check(Path(name), source)


@pytest.mark.parametrize(
    "example",
    _PUBLIC_EXAMPLES,
    ids=tuple(example.example_id for example in _PUBLIC_EXAMPLES),
)
def test_public_documentation_examples_are_executable(example: RuleExample) -> None:
    focus = example.focus_file

    findings = NoTautologicalExpect().check(Path(focus.path), focus.source)

    assert len(findings) == example.expected_count


def _count(source: str) -> int:
    return len(_check(source))


# Positive: the assertion's outcome is decided by its own literals.


def test_flags_bare_assert_true():
    diags = _check("def test_placeholder():\n    assert True\n")
    assert len(diags) == 1
    assert diags[0].code == "SARJ057"
    assert diags[0].line == 2
    assert diags[0].severity is Severity.WARNING


def test_selector_names_the_python_construct_and_preserves_compatibility():
    assert NoTautologicalExpect.id == "no-statically-truthy-assertion"
    assert NoTautologicalExpect.documentation is not None
    assert NoTautologicalExpect.documentation.aliases == ("no-tautological-expect",)


@pytest.mark.parametrize("literal", ["True", "1", "-1", "0.5", "..."])
def test_flags_truthy_constants(literal: str):
    assert _count(f"def test_x():\n    assert {literal}\n") == 1, literal


def test_flags_set_display_wrapping_a_real_condition():
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
    src = 'def test_read_remote_logs_not_found(ti):\n    assert [f"No logs found on hdfs for ti={ti}"]\n'
    diags = _check(src)
    assert len(diags) == 1
    assert "list display" in diags[0].message


@pytest.mark.parametrize(
    ("display", "kind"),
    [("[1]", "list"), ("{1}", "set"), ("{'a': 1}", "dict")],
)
def test_flags_every_non_empty_container_display(display: str, kind: str):
    diags = _check(f"def test_x():\n    assert {display}\n")
    assert len(diags) == 1, display
    assert kind in diags[0].message, display


def test_flags_container_holding_a_runtime_value():
    assert _count("def test_x(x):\n    assert [x]\n") == 1


def test_flags_value_that_slid_into_the_message_slot():
    src = 'def test_hue(cover_result_json):\n    assert True, cover_result_json[0]["success"]["on"]\n'
    diags = _check(src)
    assert len(diags) == 1
    assert "message is never displayed" in diags[0].message
    assert diags[0].severity is Severity.WARNING


@pytest.mark.parametrize("expr", ["1 == 1", '"a" == "a"', "None is None", "(1, 2) == (1, 2)", "-1 == -1"])
def test_leaves_literal_comparisons_to_ruff(expr: str):
    assert _count(f"def test_x():\n    assert {expr}\n") == 0, expr


def test_leaves_unittest_assertions_to_ruff():
    src = (
        "class TestThing(TestCase):\n"
        "    def test_x(self):\n"
        "        self.assertTrue(True)\n"
        "        self.assertFalse(False)\n"
        "        self.assertEqual(1, 1)\n"
        '        self.assertIs("a", "a")\n'
    )
    assert _count(src) == 0


def test_leaves_unittest_literal_variants_and_legacy_alias_to_ruff():
    src = (
        "class TestThing(TestCase):\n"
        "    def test_x(self):\n"
        "        self.assertTrue([value])\n"
        "        self.assertFalse(0)\n"
        "        self.assertFalse([])\n"
        "        self.assertEquals(-1, -1)\n"
    )
    assert _count(src) == 0


def test_flags_each_assertion_separately_and_sorts_by_position():
    src = "def test_x():\n    assert True\n    assert [1]\n    assert 2 == 2\n"
    diags = _check(src)
    assert [d.line for d in diags] == [2, 3]


def test_fires_outside_test_files_too():
    assert len(_check("def guard():\n    assert True\n", "src/app/service.py")) == 1


# SARJ057 owns literal-only tautologies; SARJ064 owns cross-statement construction.


@pytest.mark.parametrize(
    "condition",
    ["True", "1", "1.5", "...", "[1]", "[compute()]", "{1, 2}", "{'a': 1}"],
)
def test_flags_every_constant_condition_sarj064_ceded(condition: str):
    assert _count(f"def test_thing():\n    assert {condition}\n") == 1, condition


def test_flags_a_constant_condition_carrying_a_message():
    diags = _check('def test_thing():\n    assert True, "we got here"\n')
    assert len(diags) == 1
    assert "message is never displayed" in diags[0].message


@pytest.mark.parametrize("condition", ["not False", "not 0", "not ''", "not None", "not 0.0", "not b''"])
def test_flags_not_applied_to_a_falsy_constant(condition: str):
    diags = _check(f"def test_thing():\n    assert {condition}\n")
    assert len(diags) == 1, condition
    assert "constant truthy value" in diags[0].message, condition


@pytest.mark.parametrize("condition", ["not x", "not x.errors", "not f(x)", "not []", "not [*items]"])
def test_ignores_not_applied_to_a_runtime_value(condition: str):
    assert _count(f"def test_thing(x, items):\n    assert {condition}\n") == 0, condition


@pytest.mark.parametrize("condition", ["not True", "not 1", "not 'x'"])
def test_ignores_not_applied_to_a_truthy_constant(condition: str):
    assert _count(f"def test_thing():\n    assert {condition}\n") == 0, condition


@pytest.mark.parametrize("condition", ["False", "None", "0", "''", "[]", "{}", "()"])
def test_ignores_falsy_constant_conditions_sarj064_also_ignored(condition: str):
    assert _count(f"def test_thing():\n    assert {condition}\n") == 0, condition


def test_sole_except_body_does_not_hide_a_statically_truthy_assertion():
    src = (
        "def test_connect_failure(hass):\n"
        "    try:\n"
        "        connect()\n"
        "    except HomeAssistantError:\n"
        "        assert not False\n"
    )
    assert _count(src) == 1


def test_benchmark_fixture_does_not_hide_a_statically_truthy_assertion():
    src = "def test_speed(benchmark):\n    assert not False\n    benchmark(go)\n"
    assert _count(src) == 1


def test_benchmark_marker_does_not_hide_a_statically_truthy_assertion():
    src = "@pytest.mark.benchmark\ndef test_speed():\n    assert not False\n"
    assert _count(src) == 1


def test_the_moved_not_shape_obeys_the_failing_match_arm_carve_out():
    src = (
        "def test_wrong_password():\n"
        "    match go():\n"
        "        case Err():\n"
        "            assert not False\n"
        "        case _:\n"
        "            raise AssertionError\n"
    )
    assert _count(src) == 0


def test_the_construction_shapes_stay_sarj064s():
    echo = 'def test_thing():\n    u = User(name="bo")\n    assert u.name == "bo"\n'
    isinstance_check = "def test_thing():\n    u = User()\n    assert isinstance(u, User)\n"
    assert _count(echo) == 0
    assert _count(isinstance_check) == 0


# Negative: self-comparison of a real value.


@pytest.mark.parametrize("expr", ["i == i", "x is x", "obj == obj", "self.value == self.value"])
def test_ignores_identifier_self_comparison(expr: str):
    assert _count(f"def test_x(i, x, obj):\n    assert {expr}\n") == 0, expr


@pytest.mark.parametrize("expr", ["hash(o) == hash(o)", "f(1) == f(1)", "parse('a') is parse('a')"])
def test_ignores_call_self_comparison(expr: str):
    assert _count(f"def test_x(o):\n    assert {expr}\n") == 0, expr


def test_ignores_mixed_literal_and_identifier_comparison():
    assert _count("def test_x(result):\n    assert result == 1\n") == 0
    assert _count("def test_x(result):\n    assert 1 == result\n") == 0


@pytest.mark.parametrize("expr", ["1 == 1 == 1", "1 != 1", "1 is not 1", "1 <= 1", "1 >= 1"])
def test_ignores_chained_and_non_sameness_literal_comparisons(expr: str):
    assert _count(f"def test_x():\n    assert {expr}\n") == 0, expr


@pytest.mark.parametrize("expr", ["[value] == [value]", "{'key': value} == {'key': value}"])
def test_ignores_identical_containers_that_contain_runtime_values(expr: str):
    assert _count(f"def test_x(value):\n    assert {expr}\n") == 0, expr


def test_ignores_unittest_self_comparison_of_a_value():
    src = "class TestThing(TestCase):\n    def test_x(self, i):\n        self.assertEqual(i, i)\n"
    assert _count(src) == 0


# Negative: the carve-outs.


def test_flags_assert_true_as_sole_except_body():
    src = (
        "def test_connect_failure(hass, entry):\n"
        "    try:\n"
        "        assert await hass.config_entries.async_setup(entry.entry_id)\n"
        "    except HomeAssistantError:\n"
        "        assert True\n"
        '    assert "Failed to connect" in caplog.text\n'
    )
    assert _count(src) == 1


def test_flags_assert_true_that_is_not_the_whole_except_body():
    src = "def test_x():\n    try:\n        f()\n    except ValueError:\n        assert True\n        cleanup()\n"
    assert _count(src) == 1


def test_flags_statically_truthy_assertion_in_benchmark_callable():
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
    assert _count(src) == 1


def test_flags_statically_truthy_assertion_in_benchmark_marker_body():
    src = "@pytest.mark.benchmark\ndef test_speed():\n    assert True\n"
    assert _count(src) == 1


def test_flags_statically_truthy_assertion_in_benchmark_marker_with_arguments():
    src = '@pytest.mark.benchmark(group="parse")\ndef test_speed():\n    assert [1]\n'
    assert _count(src) == 1


def test_does_not_treat_an_unrelated_mark_as_a_benchmark():
    src = "@pytest.mark.asyncio\ndef test_speed():\n    assert True\n"
    assert _count(src) == 1


def test_does_not_treat_a_declared_but_unused_benchmark_param_as_a_benchmark():
    src = "def test_speed(benchmark):\n    assert True\n"
    assert _count(src) == 1


# Negative: assertions whose truth the code decides.


def test_ignores_assert_false():
    assert _count('def test_x():\n    assert False, "unreachable"\n') == 0


@pytest.mark.parametrize("display", ["[]", "()", "{}"])
def test_ignores_empty_container(display: str):
    assert _count(f"def test_x():\n    assert {display}\n") == 0, display


def test_ignores_splatted_container():
    assert _count("def test_x(items):\n    assert [*items]\n") == 0
    assert _count("def test_x(extra):\n    assert {**extra}\n") == 0


@pytest.mark.parametrize(
    "display",
    ["[*items, expected]", "{*items, expected}", '{**extra, "status": expected}'],
)
def test_flags_display_that_is_definitely_nonempty_despite_unpacking(display: str):
    assert _count(f"def test_x(items, extra, expected):\n    assert {display}\n") == 1


def test_leaves_nonempty_tuple_to_ruff():
    assert _count("def test_x(value):\n    assert (*value, 1)\n") == 0


def test_ignores_fstring():
    assert _count('def test_x(value):\n    assert f"{value}"\n') == 0


@pytest.mark.parametrize("literal", ['"text"', "b'bytes'"])
def test_leaves_string_literals_to_ruff(literal: str):
    assert _count(f"def test_x():\n    assert {literal}\n") == 0


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
    src = 'def build():\n    values = [1]\n    check(True)\n    return {"a": 1}\n'
    assert _count(src) == 0


def test_leaves_unittest_equality_carrying_only_a_msg_keyword_to_ruff():
    src = "class T(TestCase):\n    def test_x(self):\n        self.assertEqual(1, 1, msg='x')\n"
    assert _count(src) == 0


def test_ignores_a_look_alike_method_taking_other_keywords():
    src = "class T(TestCase):\n    def test_x(self):\n        self.assertEqual(1, 1, places=3)\n"
    assert _count(src) == 0


def test_ignores_custom_and_free_assertion_apis():
    src = (
        "def test_x(recorder):\n"
        "    recorder.assertEqual(1, 1)\n"
        "    assertEqual(1, 1)\n"
        "    recorder.assertTrue(True)\n"
    )
    assert _count(src) == 0


def test_ignores_invalid_unittest_arity():
    src = "class T:\n    def test_x(self):\n        self.assertEqual(1, 1, 'message', 'extra')\n"
    assert _count(src) == 0


@pytest.mark.parametrize("expr", ["[] is []", "(1,) is (1,)", "1000 is 1000"])
def test_leaves_literal_identity_to_ruff(expr: str):
    assert _count(f"def test_x():\n    assert {expr}\n") == 0


def test_excludes_generated_python():
    source = "# Generated by schema compiler. DO NOT EDIT.\ndef test_x():\n    assert True\n"
    assert _check(source, "generated/test_models.py") == []


def test_ignores_syntax_error():
    assert _count("def broken(:\n") == 0


def test_ignores_empty_source():
    assert _count("") == 0


# `match` arms.


def test_ignores_assert_true_marking_a_match_arm_beside_a_raising_arm():
    src = (
        "def test_wrong_password(tmpdir):\n"
        "    match PROCESSOR.process(source_file=protected, password='not right'):\n"
        "        case PDFProcessError(error=DecryptionError.INCORRECT_PASSWORD):\n"
        "            assert True\n"
        "        case _:\n"
        "            raise AssertionError\n"
    )
    assert _count(src) == 0


def test_ignores_a_match_arm_marker_beside_a_pytest_fail_arm():
    src = (
        "def test_x():\n"
        "    match go():\n"
        "        case Err():\n"
        "            assert True\n"
        "        case _:\n"
        "            pytest.fail('wrong shape')\n"
    )
    assert _count(src) == 0


def test_ignores_a_match_arm_marker_beside_an_assert_false_arm():
    src = (
        "def test_x():\n"
        "    match go():\n"
        "        case Err():\n"
        "            assert True\n"
        "        case _:\n"
        "            assert False\n"
    )
    assert _count(src) == 0


def test_flags_a_match_arm_marker_when_no_arm_can_fail():
    src = (
        "def test_x():\n"
        "    match go():\n"
        "        case Err():\n"
        "            assert True\n"
        "        case _:\n"
        "            pass\n"
    )
    assert _count(src) == 1


def test_flags_a_container_condition_even_as_the_sole_success_arm_statement():
    src = (
        "def test_x():\n"
        "    match go():\n"
        "        case Ok(value):\n"
        "            assert [value > 0]\n"
        "        case _:\n"
        "            raise AssertionError\n"
    )
    assert _count(src) == 1


def test_flags_a_constant_assert_outside_the_match_that_has_a_failing_arm():
    src = (
        "def test_x():\n"
        "    match go():\n"
        "        case Err():\n"
        "            assert True\n"
        "        case _:\n"
        "            raise AssertionError\n"
        "    assert True\n"
    )
    assert _count(src) == 1
