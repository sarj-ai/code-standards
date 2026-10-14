from pathlib import Path

import pytest
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze
from sarj_python_lint.rules.no_work_verb_get_route import NoWorkVerbGetRoute


_HEADER = "from fastapi import APIRouter\n\nrouter = APIRouter()\n\n"


def _lines(decorator: str, path: str = "api.py") -> list[int]:
    source = f"{_HEADER}{decorator}\nasync def handler() -> None:\n    return None\n"
    return [finding.line for finding in NoWorkVerbGetRoute().check(Path(path), source)]


def test_documented_examples() -> None:
    verify_native_rule(NoWorkVerbGetRoute, analyze)


@pytest.mark.parametrize("verb", ["run", "trigger", "send", "dispatch", "execute", "launch", "enqueue", "retry"])
def test_reports_each_work_verb(verb: str) -> None:
    assert _lines(f"@router.get('/jobs/{{job_id}}/{verb}')") == [5]


@pytest.mark.parametrize(
    "decorator",
    [
        pytest.param("@router.get('/emails/send-now')", id="verb-first-word"),
        pytest.param("@router.api_route('/run', methods=['GET', 'POST'])", id="api-route-with-get"),
        pytest.param("@router.api_route('/run')", id="api-route-default-get"),
        pytest.param("@router.get(\n    '/retry/',\n    status_code=200,\n)", id="multiline-trailing-slash"),
    ],
)
def test_reports_other_shapes(decorator: str) -> None:
    assert _lines(decorator) == [5]


@pytest.mark.parametrize(
    "decorator",
    [
        pytest.param("@router.get('/runs')", id="plural-noun"),
        pytest.param("@router.get('/retry/{attempt_id}')", id="final-parameter"),
        pytest.param("@router.get('/runner')", id="longer-word"),
        pytest.param("@router.post('/run')", id="post"),
        pytest.param("@router.get(PATH)", id="dynamic-path"),
        pytest.param("@router.get('/send-history/items')", id="earlier-segment"),
    ],
)
def test_allows_reads_and_posts(decorator: str) -> None:
    assert _lines(decorator) == []


def test_skips_test_modules() -> None:
    assert _lines("@router.get('/run')", path="tests/test_api.py") == []
