from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rules.fastapi_class_router_contract import FastapiClassRouterContract


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic, RuleExample


def _check(source: str) -> list[Diagnostic]:
    return FastapiClassRouterContract().check(Path("app/routes.py"), source)


@pytest.mark.parametrize(
    "example",
    FastapiClassRouterContract.public_examples(),
    ids=[example.example_id for example in FastapiClassRouterContract.public_examples()],
)
def test_public_examples_are_executable(example: RuleExample) -> None:
    assert (
        len(FastapiClassRouterContract().check(Path(example.focus_file.path), example.focus_file.source))
        == example.expected_count
    )


@pytest.mark.parametrize(
    "source",
    [
        "from fastapi import APIRouter\nrouter = APIRouter()\n",
        "from fastapi import APIRouter\ndef routes() -> APIRouter:\n    router = APIRouter()\n    return router\n",
        "from fastapi import APIRouter\nclass Routes:\n    def build(self):\n        router = APIRouter()\n        return router\n",
        "from fastapi import APIRouter\nclass ItemRouter:\n    def __init__(self):\n        self.router = APIRouter()\n",
    ],
)
def test_rejects_router_construction_outside_router_build(source: str) -> None:
    assert len(_check(source)) == 1


def test_requires_explicit_matching_object_response_model() -> None:
    source = """
from fastapi import APIRouter
class ItemRouter:
    def build(self) -> APIRouter:
        router = APIRouter()
        @router.get("/items", status_code=200)
        def items() -> list[ItemResponse]:
            return []
        return router
"""
    [finding] = _check(source)
    assert "response_model" in finding.message


def test_accepts_class_router_with_matching_object_response() -> None:
    source = """
from fastapi import APIRouter
class ItemRouter:
    def __init__(self, service: ItemService) -> None:
        self._service = service
    def build(self) -> APIRouter:
        router = APIRouter()
        @router.get("/items", status_code=200, response_model=ItemsResponse)
        def items() -> ItemsResponse:
            return ItemsResponse(items=[])
        return router
"""
    assert _check(source) == []
