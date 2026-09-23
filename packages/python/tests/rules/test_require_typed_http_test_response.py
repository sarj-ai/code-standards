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
    ("source", "expected_lines"),
    [
        (
            """def test_run(client):
    response = client.post('/runs')
    payload = response.json()
    assert payload['status'] == 'pending'
    UUID(payload['task_id'])
""",
            [4, 5],
        ),
        (
            """def test_run(client):
    body = client.post('/runs').json()
    alias = body
    assert alias.get('status') == 'pending'
""",
            [4],
        ),
        (
            """async def test_run(api_client):
    result = await api_client.get('/runs')
    payload = result.json()
    assert payload['id']
""",
            [4],
        ),
    ],
)
def test_flags_local_json_alias_consumption(source: str, expected_lines: list[int]) -> None:
    findings = RequireTypedHttpTestResponse().check(Path("tests/test_api.py"), source)
    assert [finding.line for finding in findings] == expected_lines


@pytest.mark.parametrize(
    "source",
    [
        "def test_typed(response):\n    body = Result.model_validate(response.json())\n    assert body.id\n",
        "def test_other_json(settings):\n    body = settings.json()\n    assert body['id']\n",
        "def test_unproven_response(response):\n    body = response.json()\n    assert body['id']\n",
        "def test_rebound(client):\n    body = client.get('/').json()\n    body = {'id': 1}\n    assert body['id']\n",
        "def test_nested(client):\n    body = client.get('/').json()\n    def helper():\n        assert body['id']\n",
        "def test_branch(client):\n    body = client.get('/').json()\n    if condition:\n        body = {'id': 1}\n    assert body['id']\n",
        "def test_suppressed(client):\n    body = client.get('/').json()\n    assert body['id']  # sarj-noqa: SARJ449 - legacy wire compatibility\n",
    ],
)
def test_does_not_infer_unrelated_or_rebound_aliases(source: str) -> None:
    assert RequireTypedHttpTestResponse().check(Path("tests/test_api.py"), source) == []


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
