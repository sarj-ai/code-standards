from pathlib import Path
import textwrap

import pytest

from sarj_python_lint.rules.no_repeated_test_body import NoRepeatedTestBody
from sarj_python_lint.rules.repeated_static_call_cases import RepeatedStaticCallCases


TEST_PATH = Path("tests/test_parser.py")


def _check(source: str, path: Path = TEST_PATH):
    return RepeatedStaticCallCases().check(path, textwrap.dedent(source))


def test_flags_three_consecutive_static_call_cases_once() -> None:
    source = """
    def test_parse():
        assert parse("a") == 1
        assert parse("b") == 2
        assert parse("c") == 3
    """
    [diag] = _check(source)
    assert diag.code == "SARJ413"
    assert diag.line == 3
    assert "3 same-shape literal call assertions" in diag.message


def test_flags_async_direct_calls_with_literal_arguments() -> None:
    source = """
    async def test_lookup():
        assert await lookup("ar") is True
        assert await lookup("en") is False
        assert await lookup("fr") is False
    """
    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    "body",
    [
        """
        assert parse("a") == 1
        assert parse("b") == 2
        value = prepare()
        assert parse("c") == 3
        """,
        """
        assert parse("a") == 1
        assert parse("b") == 2
        # The legacy spelling protects a deployed contract.
        assert parse("c") == 3
        """,
        """
        assert parse("a") == 1  # The spelling protects a deployed contract.
        assert parse("b") == 2
        assert parse("c") == 3
        """,
        """
        assert parse(dynamic()) == 1
        assert parse("b") == 2
        assert parse("c") == 3
        """,
        """
        assert first("a") == 1
        assert second("b") == 2
        assert third("c") == 3
        """,
        """
        assert counter.next() == 1
        assert counter.next() == 2
        assert counter.next() == 3
        """,
        """
        assert mock_lookup("a") == 1
        assert mock_lookup("b") == 2
        assert mock_lookup("c") == 3
        """,
        """
        assert payload.get("name") == "example"
        assert payload.get("count") == 2
        assert payload.get("enabled") is True
        """,
    ],
)
def test_excludes_non_case_runs(body: str) -> None:
    assert _check(f"def test_parse():\n{textwrap.indent(textwrap.dedent(body), '    ')}") == []


def test_excludes_multiple_runs_and_shared_setup() -> None:
    source = """
    def test_parse():
        assert parse("a") == 1
        assert parse("b") == 2
        assert parse("c") == 3

        result = prepare()
        assert validate("x") is True
        assert validate("y") is False
        assert validate("z") is False
    """
    assert _check(source) == []


def test_excludes_unittest_classes_and_nested_helpers() -> None:
    source = """
    import unittest

    class ParserTest(unittest.TestCase):
        def test_parse(self):
            assert parse("a") == 1
            assert parse("b") == 2
            assert parse("c") == 3

    def test_outer():
        def test_nested():
            assert parse("a") == 1
            assert parse("b") == 2
            assert parse("c") == 3
        test_nested()
    """
    assert _check(source) == []


def test_skips_generated_non_test_and_malformed_files() -> None:
    source = "def test_parse():\n    assert parse('a') == 1\n    assert parse('b') == 2\n    assert parse('c') == 3\n"
    assert _check(source, Path("src/parser.py")) == []
    assert _check(f"# @generated\n{source}") == []
    assert _check("def test_broken(") == []


def test_repeated_test_body_rule_takes_precedence() -> None:
    source = textwrap.dedent(
        """
        def test_parse_primary():
            assert parse("a") == 1
            assert parse("b") == 2
            assert parse("c") == 3

        def test_parse_copy():
            assert parse("a") == 1
            assert parse("b") == 2
            assert parse("c") == 3
        """
    )

    diagnostics = [
        *NoRepeatedTestBody().check(TEST_PATH, source),
        *RepeatedStaticCallCases().check(TEST_PATH, source),
    ]

    assert [diagnostic.code for diagnostic in diagnostics] == ["SARJ066"]


def test_flags_keyword_only_literal_calls() -> None:
    source = """
    def test_parse():
        assert parse(value="a") == 1
        assert parse(value="b") == 2
        assert parse(value="c") == 3
    """

    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    "callee",
    ["transition", "insert", "register", "send", "execute", "pop", "counter.next"],
)
def test_excludes_likely_stateful_or_attribute_calls(callee: str) -> None:
    source = f"""
    def test_sequence():
        assert {callee}("a") == 1
        assert {callee}("b") == 2
        assert {callee}("c") == 3
    """

    assert _check(source) == []


def test_excludes_symbolic_arguments_evaluated_during_collection() -> None:
    source = """
    def test_parse():
        assert parse(Language.AR) == 1
        assert parse(Language.EN) == 2
        assert parse(Language.FR) == 3
    """

    assert _check(source) == []


def test_excludes_assertions_with_messages() -> None:
    source = """
    def test_parse():
        assert parse("a") == 1, "ascii case"
        assert parse("b") == 2, "second case"
        assert parse("c") == 3, "third case"
    """

    assert _check(source) == []


@pytest.mark.parametrize(
    "signature",
    ["test_parse(parser)", "test_parse(*, parser)", "test_parse(*parsers)", "test_parse(**fixtures)"],
)
def test_excludes_fixture_parameter_tests(signature: str) -> None:
    source = f"""
    def {signature}:
        assert parse("a") == 1
        assert parse("b") == 2
        assert parse("c") == 3
    """

    assert _check(source) == []


def test_excludes_decorated_test() -> None:
    source = """
    @pytest.mark.usefixtures("database")
    def test_parse():
        assert parse("a") == 1
        assert parse("b") == 2
        assert parse("c") == 3
    """

    assert _check(source) == []


@pytest.mark.parametrize("class_header", ["Helper", "ParserHelper", "TestParser(Base)"])
def test_excludes_uncollected_or_inherited_test_class(class_header: str) -> None:
    source = f"""
    class {class_header}:
        def test_parse(self):
            assert parse("a") == 1
            assert parse("b") == 2
            assert parse("c") == 3
    """

    assert _check(source) == []


@pytest.mark.parametrize("constructor", ["__init__", "__new__"])
def test_excludes_test_class_with_constructor(constructor: str) -> None:
    source = f"""
    class TestParser:
        def {constructor}(self):
            pass

        def test_parse(self):
            assert parse("a") == 1
            assert parse("b") == 2
            assert parse("c") == 3
    """

    assert _check(source) == []


def test_flags_method_on_collectable_plain_test_class() -> None:
    source = """
    class TestParser:
        def test_parse(self):
            assert parse("a") == 1
            assert parse("b") == 2
            assert parse("c") == 3
    """

    assert len(_check(source)) == 1


@pytest.mark.parametrize("false_value", ["False", "0", "None", '""', "()", "[]", "{}", "set()"])
def test_excludes_module_disabled_from_pytest_collection(false_value: str) -> None:
    source = f"""
    __test__ = {false_value}

    def test_parse():
        assert parse("a") == 1
        assert parse("b") == 2
        assert parse("c") == 3
    """

    assert _check(source) == []


@pytest.mark.parametrize("false_value", ["False", "0", "None", '""', "()", "[]", "{}", "set()"])
def test_excludes_class_disabled_from_pytest_collection(false_value: str) -> None:
    source = f"""
    class TestParser:
        __test__ = {false_value}

        def test_parse(self):
            assert parse("a") == 1
            assert parse("b") == 2
            assert parse("c") == 3
    """

    assert _check(source) == []


@pytest.mark.parametrize("false_value", ["False", "0", "None", '""', "()", "[]", "{}", "set()"])
def test_excludes_function_disabled_from_pytest_collection(false_value: str) -> None:
    source = f"""
    def test_parse():
        assert parse("a") == 1
        assert parse("b") == 2
        assert parse("c") == 3

    test_parse.__test__ = {false_value}
    """

    assert _check(source) == []


@pytest.mark.parametrize(
    ("definition", "alias"),
    [
        (
            'def test_parse():\n    assert parse("a") == 1\n    assert parse("b") == 2\n    assert parse("c") == 3',
            "disabled = test_parse",
        ),
        (
            """class TestParser:
    def test_parse(self):
        assert parse("a") == 1
        assert parse("b") == 2
        assert parse("c") == 3""",
            "disabled = TestParser",
        ),
    ],
)
def test_excludes_collection_disabled_through_simple_alias(definition: str, alias: str) -> None:
    source = f"{definition}\n\n{alias}\ndisabled.__test__ = False\n"

    assert _check(source) == []


def test_conservatively_excludes_all_roots_of_reassigned_collection_alias() -> None:
    source = """
    def test_first():
        assert parse_first("a") == 1
        assert parse_first("b") == 2
        assert parse_first("c") == 3

    def test_second():
        assert parse_second("a") == 1
        assert parse_second("b") == 2
        assert parse_second("c") == 3

    disabled = test_first
    disabled.__test__ = False
    disabled = test_second
    """

    assert _check(source) == []


@pytest.mark.parametrize(
    "disable",
    ["test_parse.__test__ = set()", "disabled = test_parse\ndisabled.__test__ = False"],
)
def test_excludes_method_disabled_from_collection_inside_class(disable: str) -> None:
    source = (
        "class TestParser:\n"
        "    def test_parse(self):\n"
        '        assert parse("a") == 1\n'
        '        assert parse("b") == 2\n'
        '        assert parse("c") == 3\n\n'
        f"{textwrap.indent(disable, '    ')}\n"
    )

    assert _check(source) == []


@pytest.mark.parametrize(
    "disable",
    [
        "TestParser.test_parse.__test__ = False",
        "method = TestParser.test_parse\nmethod.__test__ = set()",
        "Alias = TestParser\nAlias.test_parse.__test__ = False",
        "Alias = TestParser\nmethod = Alias.test_parse\nmethod.__test__ = False",
    ],
)
def test_excludes_qualified_method_disabled_from_module_scope(disable: str) -> None:
    definition = """class TestParser:
    def test_parse(self):
        assert parse("a") == 1
        assert parse("b") == 2
        assert parse("c") == 3"""
    source = f"{definition}\n\n{disable}\n"

    assert _check(source) == []


@pytest.mark.parametrize(
    "alias_setup",
    ["from state import transition as apply", "from state import transition\napply = transition"],
)
def test_excludes_aliases_of_likely_mutators(alias_setup: str) -> None:
    source = f"""
    {alias_setup}

    def test_sequence():
        assert apply("a") == 1
        assert apply("b") == 2
        assert apply("c") == 3
    """

    assert _check(source) == []


def test_inline_suppression_is_honored() -> None:
    source = """
    def test_parse():
        assert parse("a") == 1  # sarj-noqa: SARJ413
        assert parse("b") == 2
        assert parse("c") == 3
    """

    assert _check(source) == []


def test_unrelated_inline_suppression_does_not_hide_finding() -> None:
    source = """
    def test_parse():
        assert parse("a") == 1  # sarj-noqa: SARJ999
        assert parse("b") == 2
        assert parse("c") == 3
    """

    assert len(_check(source)) == 1
