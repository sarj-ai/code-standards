from pathlib import Path

import pytest
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze
from sarj_python_lint.rules.no_folded_bad_request_not_found import NoFoldedBadRequestNotFound


def _lines(source: str, path: str = "client.py") -> list[int]:
    return [finding.line for finding in NoFoldedBadRequestNotFound().check(Path(path), source)]


def test_documented_examples() -> None:
    verify_native_rule(NoFoldedBadRequestNotFound, analyze)


@pytest.mark.parametrize(
    "condition",
    [
        pytest.param("status in (400, 404)", id="tuple"),
        pytest.param("status in [404, 400, 500]", id="list-with-extra"),
        pytest.param("status in {HTTPStatus.BAD_REQUEST, HTTPStatus.NOT_FOUND}", id="http-status"),
        pytest.param("status in (status.HTTP_400_BAD_REQUEST, status.HTTP_404_NOT_FOUND)", id="starlette"),
        pytest.param("code == 400 or code == 404", id="equality-chain"),
        pytest.param("ready and (code == 404 or code == 400)", id="nested-chain"),
    ],
)
def test_reports_folded_conditions(condition: str) -> None:
    assert _lines(f"if {condition}:\n    pass\n") == [1]


def test_reports_match_or_pattern() -> None:
    source = "match status:\n    case 400 | 404:\n        pass\n"
    assert _lines(source) == [2]


def test_one_finding_per_condition() -> None:
    assert _lines("if status in (400, 404) or code == 400 or code == 404:\n    pass\n") == [1]


@pytest.mark.parametrize(
    "source",
    [
        pytest.param("if status == 404:\n    pass\nelif status == 400:\n    raise ValueError\n", id="separate"),
        pytest.param("if status in (401, 404):\n    pass\n", id="other-pair"),
        pytest.param("if a == 400 or b == 404:\n    pass\n", id="different-subjects"),
        pytest.param("if status in ('400', '404'):\n    pass\n", id="string-codes"),
        pytest.param("if status in CODES:\n    pass\n", id="named-collection"),
        pytest.param("if status in (Other.BAD_REQUEST, Other.NOT_FOUND):\n    pass\n", id="unknown-owner"),
        pytest.param("if status == 400 and retry == 404:\n    pass\n", id="and-chain"),
        pytest.param("if status in (400,\n", id="syntax-error"),
    ],
)
def test_allows_separate_or_unrelated_statuses(source: str) -> None:
    assert _lines(source) == []


def test_skips_test_modules() -> None:
    assert _lines("CASES = [s for s in (1,) if s in (400, 404)]\n", path="tests/test_client.py") == []
