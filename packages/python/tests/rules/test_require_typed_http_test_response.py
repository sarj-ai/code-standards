from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rules.require_typed_http_test_response import RequireTypedHttpTestResponse


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import RuleExample


@pytest.mark.parametrize(
    "example",
    RequireTypedHttpTestResponse.public_examples(),
    ids=[example.example_id for example in RequireTypedHttpTestResponse.public_examples()],
)
def test_public_examples_are_executable(example: RuleExample) -> None:
    assert (
        len(RequireTypedHttpTestResponse().check(Path(example.focus_file.path), example.focus_file.source))
        == example.expected_count
    )


def test_flags_subscript_and_get_consumption() -> None:
    source = """
def test_response(client):
    response = client.get("/items")
    assert response.json()["id"]
    assert response.json().get("name")
"""
    assert len(RequireTypedHttpTestResponse().check(Path("tests/test_api.py"), source)) == 2


@pytest.mark.parametrize(
    "source",
    [
        "def test_status(client):\n    assert client.get('/').status_code == 204\n",
        "def test_typed(response):\n    body = Result.model_validate(response.json())\n    assert body.id\n",
        "def production(response):\n    return response.json()['id']\n",
    ],
)
def test_allows_status_typed_and_non_test_consumption(source: str) -> None:
    path = "app/client.py" if "production" in source else "tests/test_api.py"
    assert RequireTypedHttpTestResponse().check(Path(path), source) == []
