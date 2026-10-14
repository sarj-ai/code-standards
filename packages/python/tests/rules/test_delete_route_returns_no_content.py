from pathlib import Path

import pytest
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze
from sarj_python_lint.rules.delete_route_returns_no_content import DeleteRouteReturnsNoContent


_HEADER = "from http import HTTPStatus\n\nfrom fastapi import APIRouter, status\n\nrouter = APIRouter()\n\n"


def _lines(decorator: str, path: str = "api.py") -> list[int]:
    source = f"{_HEADER}{decorator}\nasync def handler() -> None:\n    return None\n"
    return [finding.line for finding in DeleteRouteReturnsNoContent().check(Path(path), source)]


def test_documented_examples() -> None:
    verify_native_rule(DeleteRouteReturnsNoContent, analyze)


@pytest.mark.parametrize(
    "decorator",
    [
        pytest.param("@router.delete('/{item_id}')", id="implicit-200"),
        pytest.param("@router.delete('/{item_id}', status_code=200)", id="literal-200"),
        pytest.param("@router.delete('/{item_id}', status_code=status.HTTP_200_OK)", id="starlette-200"),
        pytest.param("@router.delete('/{item_id}', status_code=HTTPStatus.ACCEPTED)", id="http-status-202"),
        pytest.param("@router.api_route('/{item_id}', methods=['DELETE'])", id="api-route"),
        pytest.param("@router.delete(\n    '/{item_id}',\n    response_model=None,\n)", id="multiline"),
    ],
)
def test_reports_delete_without_no_content(decorator: str) -> None:
    assert _lines(decorator) == [7]


@pytest.mark.parametrize(
    "decorator",
    [
        pytest.param("@router.delete('/{item_id}', status_code=204)", id="literal-204"),
        pytest.param("@router.delete('/{item_id}', status_code=status.HTTP_204_NO_CONTENT)", id="starlette-204"),
        pytest.param("@router.delete('/{item_id}', status_code=HTTPStatus.NO_CONTENT)", id="http-status-204"),
        pytest.param("@router.delete('/{item_id}', status_code=NO_CONTENT)", id="unresolved-name"),
        pytest.param("@router.delete('/{item_id}', **OPTIONS)", id="keyword-unpack"),
        pytest.param("@router.api_route('/{item_id}', methods=['GET', 'DELETE'])", id="shared-decorator"),
        pytest.param("@router.post('/{item_id}')", id="post"),
    ],
)
def test_allows_no_content_or_unresolved(decorator: str) -> None:
    assert _lines(decorator) == []


def test_skips_test_modules() -> None:
    assert _lines("@router.delete('/{item_id}')", path="tests/test_api.py") == []
