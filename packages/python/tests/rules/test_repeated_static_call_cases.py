from pathlib import Path
import textwrap

import pytest

from sarj_python_lint.rules.duplicate_test_body import DuplicateTestBody
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
    assert "3 static call assertions" in diag.message


def test_flags_async_dotted_calls_with_static_symbol_arguments() -> None:
    source = """
    async def test_lookup():
        assert await client.lookup(Language.AR) is True
        assert await client.lookup(Language.EN) is False
        assert await client.lookup(Language.FR) is False
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


def test_reports_each_distinct_run_once() -> None:
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
    assert [diag.line for diag in _check(source)] == [3, 8]


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


def test_duplicate_test_body_takes_precedence() -> None:
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
        *DuplicateTestBody().check(TEST_PATH, source),
        *RepeatedStaticCallCases().check(TEST_PATH, source),
    ]

    assert [diagnostic.code for diagnostic in diagnostics] == ["SARJ066"]
