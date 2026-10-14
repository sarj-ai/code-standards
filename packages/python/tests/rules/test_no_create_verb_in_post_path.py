from pathlib import Path

import pytest
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze
from sarj_python_lint.rules.no_create_verb_in_post_path import NoCreateVerbInPostPath


_HEADER = "from fastapi import APIRouter\n\nrouter = APIRouter(prefix='/items')\n\n"


def _lines(decorator: str, path: str = "api.py") -> list[int]:
    source = f"{_HEADER}{decorator}\nasync def handler() -> None:\n    return None\n"
    return [finding.line for finding in NoCreateVerbInPostPath().check(Path(path), source)]


def test_documented_examples() -> None:
    verify_native_rule(NoCreateVerbInPostPath, analyze)


@pytest.mark.parametrize(
    "decorator",
    [
        pytest.param("@router.post('/create')", id="bare-create"),
        pytest.param("@router.post('/add-users-to-organization')", id="add-words"),
        pytest.param("@router.post('/create-for-user')", id="create-words"),
        pytest.param("@router.post('/desk/create_ticket')", id="nested-underscore"),
        pytest.param("@router.post('/{item_id}/notes/new/')", id="trailing-slash"),
        pytest.param("@router.post(\n    '/tickets/create',\n    status_code=201,\n)", id="multiline"),
        pytest.param("@router.api_route('/create', methods=['POST'])", id="api-route"),
        pytest.param("@router.post(path='/create')", id="path-keyword"),
    ],
)
def test_reports_create_segment_on_post(decorator: str) -> None:
    assert _lines(decorator) == [5]


@pytest.mark.parametrize(
    "decorator",
    [
        pytest.param("@router.post('')", id="collection-root"),
        pytest.param("@router.post('/addresses')", id="word-prefix-only"),
        pytest.param("@router.post('/create/{draft_id}')", id="final-parameter"),
        pytest.param("@router.get('/new')", id="get-route"),
        pytest.param("@router.put('/create')", id="put-route"),
        pytest.param("@router.post(PATH)", id="dynamic-path"),
        pytest.param("@other.post('/create')", id="unknown-receiver"),
    ],
)
def test_allows_collection_paths(decorator: str) -> None:
    assert _lines(decorator) == []


def test_skips_test_modules() -> None:
    assert _lines("@router.post('/create')", path="tests/test_api.py") == []
