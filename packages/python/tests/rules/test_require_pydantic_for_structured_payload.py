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


@pytest.mark.parametrize("record_base", ["TypedDict", "BaseModel"])
def test_named_validated_nested_record_is_not_treated_as_open_mapping(record_base: str) -> None:
    record_import = "from typing import TypedDict" if record_base == "TypedDict" else ""
    source = f"""
from fastapi import APIRouter
from pydantic import BaseModel
{record_import}
router = APIRouter()
class CardPayload({record_base}):
    name_on_card: str
class RequestModel(BaseModel):
    payload: CardPayload
@router.post('/actions')
def action(body: RequestModel):
    payload = body.payload
    return payload['name_on_card']
"""
    assert RequirePydanticForStructuredPayload().check(Path("app/routes.py"), source) == []


def test_named_field_on_unvalidated_outer_class_remains_reportable() -> None:
    source = """
from fastapi import APIRouter
from typing import TypedDict
router = APIRouter()
class CardPayload(TypedDict):
    name_on_card: str
class RequestModel:
    payload: CardPayload
@router.post('/actions')
def action(body: RequestModel):
    payload = body.payload
    return payload['name_on_card']
"""
    assert len(RequirePydanticForStructuredPayload().check(Path("app/routes.py"), source)) == 1
