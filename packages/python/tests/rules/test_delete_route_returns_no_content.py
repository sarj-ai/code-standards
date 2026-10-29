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


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(
            _HEADER
            + "@router.delete('/{item_id}', response_model=DeleteResponse)\nasync def handler() -> DeleteResponse:\n    return DeleteResponse()\n",
            id="declared-response-model",
        ),
        pytest.param(
            _HEADER
            + "@router.delete('/{item_id}')\nasync def handler() -> MutationResponse:\n    return MutationResponse()\n",
            id="returns-a-body",
        ),
    ],
)
def test_allows_delete_routes_that_return_a_declared_body(source: str) -> None:
    assert [f.line for f in DeleteRouteReturnsNoContent().check(Path("api.py"), source)] == []


@pytest.mark.parametrize("definition", ["def", "async def"])
@pytest.mark.parametrize("annotation", ["None", "'None'", '"None"', "' None '", "'(None)'"])
@pytest.mark.parametrize("prefix", ["", "from __future__ import annotations\n\n"])
def test_literal_and_quoted_none_have_identical_diagnostics(definition: str, annotation: str, prefix: str) -> None:
    before_annotation = f"{prefix}{_HEADER}@router.delete('/{{item_id}}')\n{definition} handler() -> "
    rule = DeleteRouteReturnsNoContent()
    expected = rule.check(Path("api.py"), f"{before_annotation}None:\n    return None\n")
    actual = rule.check(Path("api.py"), f"{before_annotation}{annotation}:\n    return None\n")
    assert len(expected) == 1
    assert actual == expected


@pytest.mark.parametrize(
    "decorator",
    [
        pytest.param("@router.delete('/{item_id}', status_code=204)", id="literal-204"),
        pytest.param("@router.delete('/{item_id}', status_code=status.HTTP_204_NO_CONTENT)", id="starlette-204"),
        pytest.param("@router.delete('/{item_id}', status_code=HTTPStatus.NO_CONTENT)", id="http-status-204"),
        pytest.param("@router.delete('/{item_id}', status_code=NO_CONTENT)", id="unresolved-status"),
        pytest.param("@router.delete('/{item_id}', **OPTIONS)", id="keyword-unpack"),
        pytest.param("@router.api_route('/{item_id}', methods=['GET', 'DELETE'])", id="shared-methods"),
        pytest.param("@router.post('/{item_id}')", id="other-method"),
    ],
)
def test_quoted_none_preserves_status_and_method_exemptions(decorator: str) -> None:
    source = f"{_HEADER}{decorator}\nasync def handler() -> 'None':\n    return None\n"
    assert DeleteRouteReturnsNoContent().check(Path("api.py"), source) == []


@pytest.mark.parametrize(
    ("declarations", "annotation", "body"),
    [
        pytest.param("", "dict[str, str]", "{'deleted': 'yes'}", id="body"),
        pytest.param("", "'dict[str, str]'", "{'deleted': 'yes'}", id="quoted-body"),
        pytest.param("from fastapi import Response\n", "Response", "Response(status_code=204)", id="response"),
        pytest.param("from fastapi import Response\n", "'Response'", "Response(status_code=204)", id="quoted-response"),
        pytest.param("", "'UnknownResponse'", "None", id="unknown"),
        pytest.param("", "'None | dict[str, str]'", "None", id="optional-body"),
        pytest.param("", "'None['", "None", id="malformed"),
        pytest.param("", repr("\udcff"), "None", id="unencodable"),
        pytest.param("", repr(" | ".join(["None"] * 10_000)), "None", id="deep-forward-annotation"),
    ],
)
def test_quoted_return_types_preserve_body_and_unknown_exemptions(
    declarations: str,
    annotation: str,
    body: str,
) -> None:
    source = (
        f"{_HEADER}{declarations}@router.delete('/{{item_id}}')\n"
        f"async def handler() -> {annotation}:\n    return {body}\n"
    )
    assert DeleteRouteReturnsNoContent().check(Path("api.py"), source) == []


def test_quoted_none_preserves_response_model_exemption() -> None:
    source = (
        f"{_HEADER}@router.delete('/{{item_id}}', response_model=DeleteResponse)\n"
        "async def handler() -> 'None':\n    return None\n"
    )
    assert DeleteRouteReturnsNoContent().check(Path("api.py"), source) == []


@pytest.mark.parametrize("body", ["None", "{'deleted': 'yes'}", "Response(status_code=204)"])
def test_return_values_do_not_override_declared_none(body: str) -> None:
    source = (
        f"{_HEADER}from fastapi import Response\n\n@router.delete('/{{item_id}}')\n"
        f"async def handler() -> 'None':\n    return {body}\n"
    )
    assert [finding.line for finding in DeleteRouteReturnsNoContent().check(Path("api.py"), source)] == [9]


@pytest.mark.parametrize(
    "declarations",
    [
        pytest.param("Empty = None\n", id="assignment"),
        pytest.param("from typing import TypeAlias\nEmpty: TypeAlias = None\n", id="explicit-type-alias"),
        pytest.param("type Empty = None\n", id="type-statement"),
        pytest.param("type Empty = None\nEmpty = dict[str, str]\n", id="rebound-alias"),
        pytest.param("type Empty = Missing\n", id="unresolved-alias"),
    ],
)
@pytest.mark.parametrize("annotation", ["Empty", "'Empty'"])
def test_aliases_remain_unresolved(declarations: str, annotation: str) -> None:
    source = (
        f"{_HEADER}{declarations}@router.delete('/{{item_id}}')\n"
        f"async def handler() -> {annotation}:\n    return None\n"
    )
    assert DeleteRouteReturnsNoContent().check(Path("api.py"), source) == []


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(
            _HEADER
            + "type Empty = None\n"
            + "def register(Empty: object) -> None:\n"
            + "    @router.delete('/{item_id}')\n"
            + "    async def handler() -> 'Empty':\n        return None\n",
            id="outer-parameter",
        ),
        pytest.param(
            _HEADER
            + "type Empty = None\nclass Routes:\n    Empty = dict[str, str]\n"
            + "    @router.delete('/{item_id}')\n"
            + "    async def handler(self) -> 'Empty':\n        return None\n",
            id="class-binding",
        ),
        pytest.param(
            _HEADER
            + "type Empty = None\n@router.delete('/{item_id}')\n"
            + "async def handler[Empty]() -> 'Empty':\n    return None\n",
            id="type-parameter",
        ),
        pytest.param(
            _HEADER
            + "def register(router: object) -> None:\n"
            + "    @router.delete('/{item_id}')\n"
            + "    async def handler() -> 'None':\n        return None\n",
            id="receiver-parameter",
        ),
    ],
)
def test_quoted_annotations_preserve_shadowing_boundaries(source: str) -> None:
    assert DeleteRouteReturnsNoContent().check(Path("api.py"), source) == []
