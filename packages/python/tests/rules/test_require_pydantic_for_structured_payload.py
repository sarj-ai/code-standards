from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rules.require_pydantic_for_structured_payload import RequirePydanticForStructuredPayload


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import RuleExample


@pytest.mark.parametrize(
    "example",
    RequirePydanticForStructuredPayload.public_examples(),
    ids=[example.example_id for example in RequirePydanticForStructuredPayload.public_examples()],
)
def test_public_examples_are_executable(example: RuleExample) -> None:
    assert (
        len(RequirePydanticForStructuredPayload().check(Path(example.focus_file.path), example.focus_file.source))
        == example.expected_count
    )


def test_flags_get_subscript_and_pop_on_nested_route_mapping() -> None:
    source = """
from fastapi import APIRouter
router = APIRouter()
@router.post("/actions")
def action(body: RequestModel):
    payload = body.payload
    payload["one"]
    payload.get("two")
    payload.pop("three")
"""
    assert len(RequirePydanticForStructuredPayload().check(Path("app/routes.py"), source)) == 3


def test_ignores_non_route_and_dynamic_access() -> None:
    source = """
def helper(body: RequestModel, key: str):
    payload = body.payload
    return payload[key]
"""
    assert RequirePydanticForStructuredPayload().check(Path("app/service.py"), source) == []
