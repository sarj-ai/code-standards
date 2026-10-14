from pathlib import Path

import pytest
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze
from sarj_python_lint.rules.no_slash_collection_root_under_prefix import NoSlashCollectionRootUnderPrefix


def _lines(source: str, path: str = "api.py") -> list[int]:
    return [finding.line for finding in NoSlashCollectionRootUnderPrefix().check(Path(path), source)]


def _module(constructor: str, decorator: str) -> str:
    return (
        f"from fastapi import APIRouter, FastAPI\n\nrouter = {constructor}\n\n"
        f"{decorator}\nasync def handler() -> None:\n    return None\n"
    )


def test_documented_examples() -> None:
    verify_native_rule(NoSlashCollectionRootUnderPrefix, analyze)


@pytest.mark.parametrize(
    "decorator",
    [
        pytest.param("@router.get('/')", id="get"),
        pytest.param("@router.post('/', status_code=201)", id="post"),
        pytest.param("@router.get(\n    '/',\n    status_code=200,\n)", id="multiline"),
        pytest.param("@router.get(path='/')", id="path-keyword"),
    ],
)
def test_reports_slash_root_under_prefix(decorator: str) -> None:
    assert _lines(_module("APIRouter(prefix='/tasks', tags=['tasks'])", decorator)) == [5]


def test_reports_router_built_in_a_method() -> None:
    source = (
        "from fastapi import APIRouter\n\n"
        "class TasksRouter:\n"
        "    def build(self) -> APIRouter:\n"
        "        router = APIRouter(prefix='/tasks')\n\n"
        "        @router.get('/')\n"
        "        async def list_tasks() -> list[str]:\n"
        "            return []\n\n"
        "        return router\n"
    )
    assert _lines(source) == [7]


@pytest.mark.parametrize(
    ("constructor", "decorator"),
    [
        pytest.param("APIRouter(prefix='/tasks')", "@router.get('')", id="empty-path"),
        pytest.param("APIRouter(prefix='/tasks')", "@router.get('/{task_id}')", id="item-path"),
        pytest.param("APIRouter()", "@router.get('/')", id="no-prefix"),
        pytest.param("APIRouter(prefix='')", "@router.get('/')", id="empty-prefix"),
        pytest.param("APIRouter(prefix=PREFIX)", "@router.get('/')", id="dynamic-prefix"),
        pytest.param("FastAPI()", "@router.get('/')", id="application-root"),
    ],
)
def test_allows_unprefixed_or_empty_roots(constructor: str, decorator: str) -> None:
    assert _lines(_module(constructor, decorator)) == []


def test_skips_test_modules() -> None:
    assert _lines(_module("APIRouter(prefix='/tasks')", "@router.get('/')"), path="tests/test_api.py") == []
