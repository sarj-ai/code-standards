from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rules.fastapi_openapi_contract import FastapiOpenapiContract
from sarj_python_lint.rules.pydantic_at_boundaries import PydanticAtBoundaries


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic, RuleExample


_PUBLIC_EXAMPLES = FastapiOpenapiContract.public_examples()


def _check(source: str, path: str = "api.py") -> list[Diagnostic]:
    return FastapiOpenapiContract().check(Path(path), source)


@pytest.mark.parametrize(
    "example",
    _PUBLIC_EXAMPLES,
    ids=tuple(example.example_id for example in _PUBLIC_EXAMPLES),
)
def test_public_documentation_examples_are_executable(example: RuleExample) -> None:
    focus = example.focus_file

    findings = FastapiOpenapiContract().check(Path(focus.path), focus.source)

    assert len(findings) == example.expected_count


_PRELUDE = """
from typing import Annotated, Any, Optional
from fastapi import APIRouter, Body, Depends, Header, HTTPException, Path, Query, Request, status
from fastapi.responses import FileResponse, Response, StreamingResponse

router = APIRouter()
"""


def _source(suffix: str) -> str:
    return f"{_PRELUDE}{suffix}"


def _temporary_package(tmp_path: Path) -> Path:
    (tmp_path / ".git").mkdir(exist_ok=True)
    package = tmp_path / "app"
    package.mkdir()
    return package


def test_complete_operation_is_clean():
    source = (
        _PRELUDE
        + """
@router.get(
    "/users/{user_id}",
    summary="Read a user",
    description="Returns the public user profile.",
    status_code=status.HTTP_200_OK,
    responses={404: {"description": "User not found"}},
)
async def read_user(
    user_id: Annotated[str, Path(description="Stable user identifier")],
    verbose: Annotated[bool, Query(description="Include optional details")] = False,
    request: Request = None,
) -> UserResponse:
    if not verbose:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return UserResponse(user_id=user_id)
"""
    )
    assert _check(source) == []


def test_metadata_is_required_per_visible_operation():
    source = _source("""
@router.get("/users")
async def users() -> list[UserResponse]:
    return []
""")
    diagnostics = _check(source)
    assert len(diagnostics) == 1
    assert "[metadata]" in diagnostics[0].message
    assert "summary" in diagnostics[0].message
    assert "description" in diagnostics[0].message
    assert "status_code" in diagnostics[0].message


def test_docstring_satisfies_operation_description():
    source = _source('''
@router.get("/users", summary="Read users", status_code=200)
async def users() -> list[UserResponse]:
    """Return the visible users."""
    return []
''')
    assert _check(source) == []


@pytest.mark.parametrize(
    ("parameter", "fragment"),
    [
        ("term: str", "explicit Annotated"),
        ("term: Annotated[str, Query()]", "non-empty description"),
        ("payload: Annotated[dict[str, str], Body(description='Payload')]", "schema-erasing"),
        ("other: Annotated[str, Path(description='Other')]", "not present in route path"),
    ],
)
def test_request_parameter_contract(parameter: str, fragment: str):
    source = (
        _PRELUDE
        + f"""
@router.post("/items", summary="Create item", description="Creates one item.", status_code=201)
async def create_item({parameter}) -> ItemResponse:
    return ItemResponse()
"""
    )
    diagnostics = _check(source)
    assert any("[parameter]" in diagnostic.message and fragment in diagnostic.message for diagnostic in diagnostics)


def test_dependency_marker_does_not_require_description():
    source = _source("""
@router.get("/me", summary="Read me", description="Returns the caller.", status_code=200)
async def me(user: Annotated[User, Depends(current_user)]) -> UserResponse:
    return UserResponse.model_validate(user)
""")
    assert _check(source) == []


def test_same_file_dependency_alias_is_resolved():
    source = _source("""
CurrentUser = Annotated[User, Depends(current_user)]
Actor = CurrentUser

@router.get("/me", summary="Read me", description="Returns the caller.", status_code=200)
async def me(user: Actor) -> UserResponse:
    return UserResponse.model_validate(user)
""")
    assert _check(source) == []


def test_imported_relative_dependency_alias_is_resolved_from_source(tmp_path: Path):
    package = _temporary_package(tmp_path)
    (package / "dependencies.py").write_text(
        "from typing import Annotated\nfrom fastapi import Depends\n"
        "CurrentUser = Annotated[User, Depends(current_user)]\n",
        encoding="utf-8",
    )
    source = _source("""
from .dependencies import CurrentUser as Actor

@router.get("/me", summary="Read me", description="Returns the caller.", status_code=200)
async def me(user: Actor) -> UserResponse:
    return UserResponse.model_validate(user)
""")
    assert _check(source, str(package / "api.py")) == []


def test_imported_absolute_same_package_dependency_alias_is_resolved(tmp_path: Path):
    package = _temporary_package(tmp_path)
    (package / "dependencies.py").write_text(
        "from typing_extensions import Annotated\nimport fastapi as fa\n"
        "CurrentUser = Annotated[User, fa.Security(current_user)]\n",
        encoding="utf-8",
    )
    source = _source("""
import app.dependencies as dependencies

@router.get("/me", summary="Read me", description="Returns the caller.", status_code=200)
async def me(user: dependencies.CurrentUser) -> UserResponse:
    return UserResponse.model_validate(user)
""")
    assert _check(source, str(package / "api.py")) == []


def test_imported_dependency_reexport_is_resolved(tmp_path: Path):
    package = _temporary_package(tmp_path)
    (package / "dependencies.py").write_text(
        "from typing import Annotated\nfrom fastapi import Depends\n"
        "CurrentUser = Annotated[User, Depends(current_user)]\n",
        encoding="utf-8",
    )
    (package / "contracts.py").write_text(
        "from .dependencies import CurrentUser as Actor\n",
        encoding="utf-8",
    )
    source = _source("""
from .contracts import Actor

@router.get("/me", summary="Read me", description="Returns the caller.", status_code=200)
async def me(user: Actor) -> UserResponse:
    return UserResponse.model_validate(user)
""")
    assert _check(source, str(package / "api.py")) == []


@pytest.mark.parametrize(
    "dependency_source",
    [
        "UserId = str\n",
        "class User: ...\n",
        (
            "from typing import Annotated\nfrom fastapi import Depends\n"
            "CurrentUser = Annotated[User, Depends(first), Depends(second)]\n"
        ),
        "CurrentUser =\n",
        "CurrentUser = Other\nOther = CurrentUser\n",
    ],
    ids=("scalar-alias", "model", "multiple-markers", "malformed-module", "alias-cycle"),
)
def test_unproven_imported_annotations_remain_diagnostic(tmp_path: Path, dependency_source: str):
    package = _temporary_package(tmp_path)
    (package / "dependencies.py").write_text(dependency_source, encoding="utf-8")
    imported = "UserId" if dependency_source.startswith("UserId") else "User"
    if dependency_source.startswith(("from typing", "CurrentUser")):
        imported = "CurrentUser"
    source = _source(f"""
from .dependencies import {imported}

@router.get("/items", summary="Read items", description="Returns items.", status_code=200)
async def items(value: {imported}) -> ItemResponse:
    return ItemResponse()
""")
    diagnostics = _check(source, str(package / "api.py"))
    assert any("explicit Annotated metadata" in diagnostic.message for diagnostic in diagnostics)


@pytest.mark.parametrize("rebind_target", ["consumer", "dependency"])
def test_rebound_imported_dependency_alias_remains_diagnostic(tmp_path: Path, rebind_target: str):
    package = _temporary_package(tmp_path)
    dependency_source = (
        "from typing import Annotated\nfrom fastapi import Depends\n"
        "CurrentUser = Annotated[User, Depends(current_user)]\n"
    )
    if rebind_target == "dependency":
        dependency_source += "CurrentUser = User\n"
    (package / "dependencies.py").write_text(dependency_source, encoding="utf-8")
    consumer_rebind = "CurrentUser = User\n" if rebind_target == "consumer" else ""
    source = _source(f"""
from .dependencies import CurrentUser
{consumer_rebind}
@router.get("/me", summary="Read me", description="Returns the caller.", status_code=200)
async def me(user: CurrentUser) -> UserResponse:
    return UserResponse.model_validate(user)
""")
    diagnostics = _check(source, str(package / "api.py"))
    assert any("explicit Annotated metadata" in diagnostic.message for diagnostic in diagnostics)


def test_unresolved_third_party_alias_remains_diagnostic():
    source = _source("""
from external_package.dependencies import CurrentUser

@router.get("/me", summary="Read me", description="Returns the caller.", status_code=200)
async def me(user: CurrentUser) -> UserResponse:
    return UserResponse.model_validate(user)
""")
    diagnostics = _check(source)
    assert any("explicit Annotated metadata" in diagnostic.message for diagnostic in diagnostics)


def test_quoted_imported_alias_remains_diagnostic_without_scope_guessing(tmp_path: Path):
    package = _temporary_package(tmp_path)
    (package / "dependencies.py").write_text(
        "from typing import Annotated\nfrom fastapi import Depends\n"
        "CurrentUser = Annotated[User, Depends(current_user)]\n",
        encoding="utf-8",
    )
    source = _source("""
from .dependencies import CurrentUser

@router.get("/me", summary="Read me", description="Returns the caller.", status_code=200)
async def me(user: "CurrentUser") -> UserResponse:
    return UserResponse.model_validate(user)
""")
    diagnostics = _check(source, str(package / "api.py"))
    assert any("explicit Annotated metadata" in diagnostic.message for diagnostic in diagnostics)


def test_symlinked_dependency_module_remains_diagnostic(tmp_path: Path):
    package = _temporary_package(tmp_path)
    target = tmp_path / "real_dependencies.py"
    target.write_text(
        "from typing import Annotated\nfrom fastapi import Depends\n"
        "CurrentUser = Annotated[User, Depends(current_user)]\n",
        encoding="utf-8",
    )
    (package / "dependencies.py").symlink_to(target)
    source = _source("""
from .dependencies import CurrentUser

@router.get("/me", summary="Read me", description="Returns the caller.", status_code=200)
async def me(user: CurrentUser) -> UserResponse:
    return UserResponse.model_validate(user)
""")
    diagnostics = _check(source, str(package / "api.py"))
    assert any("explicit Annotated metadata" in diagnostic.message for diagnostic in diagnostics)


def test_relative_import_cannot_escape_checkout(tmp_path: Path):
    package = _temporary_package(tmp_path)
    routes = package / "routes"
    routes.mkdir()
    outside = tmp_path.parent / "outside_dependencies.py"
    outside.write_text(
        "from typing import Annotated\nfrom fastapi import Depends\n"
        "CurrentUser = Annotated[User, Depends(current_user)]\n",
        encoding="utf-8",
    )
    source = _source("""
from ....outside_dependencies import CurrentUser

@router.get("/me", summary="Read me", description="Returns the caller.", status_code=200)
async def me(user: CurrentUser) -> UserResponse:
    return UserResponse.model_validate(user)
""")
    diagnostics = _check(source, str(routes / "api.py"))
    assert any("explicit Annotated metadata" in diagnostic.message for diagnostic in diagnostics)


def test_dependency_reexport_depth_is_bounded(tmp_path: Path):
    package = _temporary_package(tmp_path)
    for index in range(8):
        (package / f"dependency_{index}.py").write_text(
            f"from .dependency_{index + 1} import CurrentUser\n",
            encoding="utf-8",
        )
    (package / "dependency_8.py").write_text(
        "from typing import Annotated\nfrom fastapi import Depends\n"
        "CurrentUser = Annotated[User, Depends(current_user)]\n",
        encoding="utf-8",
    )
    source = _source("""
from .dependency_0 import CurrentUser

@router.get("/me", summary="Read me", description="Returns the caller.", status_code=200)
async def me(user: CurrentUser) -> UserResponse:
    return UserResponse.model_validate(user)
""")
    diagnostics = _check(source, str(package / "api.py"))
    assert any("explicit Annotated metadata" in diagnostic.message for diagnostic in diagnostics)


def test_imported_module_is_parsed_once_per_source_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    package = _temporary_package(tmp_path)
    dependency = package / "dependencies.py"
    dependency.write_text(
        "from typing import Annotated\nfrom fastapi import Depends\n"
        "CurrentUser = Annotated[User, Depends(current_user)]\n",
        encoding="utf-8",
    )
    original_read_text = Path.read_text
    reads: list[Path] = []

    def counted_read_text(path: Path, *, encoding: str | None = None, errors: str | None = None) -> str:
        if path == dependency:
            reads.append(path)
        return original_read_text(path, encoding=encoding, errors=errors)

    monkeypatch.setattr(Path, "read_text", counted_read_text)
    source = _source("""
from .dependencies import CurrentUser

@router.get("/me", summary="Read me", description="Returns the caller.", status_code=200)
async def me(actor: CurrentUser, auditor: CurrentUser) -> UserResponse:
    return UserResponse.model_validate(actor)
""")
    assert _check(source, str(package / "api.py")) == []
    assert reads == [dependency]


def test_ruff_owned_annotation_defects_do_not_duplicate():
    source = _source("""
@router.get("/users", summary="Read users", description="Returns users.", status_code=200)
async def users(limit = Query(10)):
    return []
""")
    assert _check(source) == []


@pytest.mark.parametrize(
    ("annotation", "extra"),
    [
        ("Any", ""),
        ("object", ""),
        ("dict[str, str]", ""),
        ("UserResponse", ", response_model=None"),
        ("Optional[UserResponse]", ", response_model=None"),
        ("StreamingResponse", ""),
    ],
)
def test_response_contract_rejects_openapi_erasing_shapes(annotation: str, extra: str):
    source = (
        _PRELUDE
        + f"""
@router.get("/users", summary="Read users", description="Returns users.", status_code=200{extra})
async def users() -> {annotation}:
    raise NotImplementedError
"""
    )
    diagnostics = _check(source)
    assert any("[return]" in diagnostic.message for diagnostic in diagnostics)


def test_explicit_file_response_is_clean():
    source = (
        _PRELUDE
        + """
@router.get(
    "/report",
    summary="Download report",
    description="Returns the generated report.",
    status_code=200,
    response_class=FileResponse,
    response_model=None,
    responses={200: {"content": {"application/pdf": {}}}},
)
async def report() -> FileResponse:
    return FileResponse("report.pdf")
"""
    )
    assert _check(source) == []


def test_no_content_response_has_no_schema():
    source = (
        _PRELUDE
        + """
@router.delete(
    "/items/{item_id}",
    summary="Delete item",
    description="Deletes one item.",
    status_code=204,
    response_model=None,
)
async def delete_item(item_id: Annotated[str, Path(description="Item identifier")]) -> None:
    return None
"""
    )
    assert _check(source) == []


def test_no_content_none_return_does_not_require_redundant_response_model_none():
    source = _source("""
@router.delete("/items", summary="Delete items", description="Deletes items.", status_code=204)
async def delete_items() -> None:
    return None
""")
    assert _check(source) == []


@pytest.mark.parametrize("status_code", ["204", "304", "status.HTTP_204_NO_CONTENT", "status.HTTP_304_NOT_MODIFIED"])
def test_no_content_response_does_not_require_response_class(status_code: str):
    source = _source(f"""
@router.delete("/items", summary="Delete items", description="Deletes items.", status_code={status_code})
async def delete_items() -> Response:
    return Response(status_code={status_code})
""")
    assert _check(source) == []


def test_content_response_still_requires_response_class():
    source = _source("""
@router.get("/items", summary="Read items", description="Returns items.", status_code=200)
async def read_items() -> Response:
    return Response(content="items")
""")
    diagnostics = _check(source)
    assert len(diagnostics) == 1
    assert "response_class" in diagnostics[0].message


def test_no_content_response_rejects_model():
    source = _source("""
@router.delete("/items", summary="Delete items", description="Deletes items.", status_code=204)
async def delete_items() -> ItemResponse:
    return ItemResponse()
""")
    assert any("[return]" in diagnostic.message for diagnostic in _check(source))


@pytest.mark.parametrize("method", ["get", "head"])
def test_get_and_head_body_are_rejected(method: str):
    source = (
        _PRELUDE
        + f"""
@router.{method}("/search", summary="Search", description="Searches items.", status_code=200)
async def search(payload: Annotated[SearchBody, Body(description="Search criteria")]) -> SearchResponse:
    return SearchResponse()
"""
    )
    assert any(
        "[parameter]" in diagnostic.message and "request body" in diagnostic.message for diagnostic in _check(source)
    )


def test_response_projection_is_rejected():
    source = (
        _PRELUDE
        + """
@router.get(
    "/users",
    summary="Read users",
    description="Returns users.",
    status_code=200,
    response_model=UserResponse,
    response_model_exclude={"secret"},
)
async def users() -> UserResponse:
    return UserResponse()
"""
    )
    assert any(
        "[return]" in diagnostic.message and "dedicated output model" in diagnostic.message
        for diagnostic in _check(source)
    )


def test_direct_http_exception_requires_documented_response():
    source = (
        _PRELUDE
        + """
@router.get("/users/{user_id}", summary="Read user", description="Returns a user.", status_code=200)
async def user(user_id: Annotated[str, Path(description="User identifier")]) -> UserResponse:
    raise HTTPException(status_code=404)
"""
    )
    assert any("[responses]" in diagnostic.message and "404" in diagnostic.message for diagnostic in _check(source))


def test_http_status_enum_is_resolved():
    source = _source("""
from http import HTTPStatus as HS

@router.get("/users", summary="Read users", description="Returns users.", status_code=HS.OK)
async def users() -> UserResponse:
    raise HTTPException(status_code=HS.NOT_FOUND)
""")
    assert any("[responses]" in diagnostic.message and "404" in diagnostic.message for diagnostic in _check(source))


@pytest.mark.parametrize(
    ("imports", "status_expr"),
    [
        ("from fastapi.status import HTTP_404_NOT_FOUND", "HTTP_404_NOT_FOUND"),
        ("import fastapi.status as http_status", "http_status.HTTP_404_NOT_FOUND"),
        ("import http", "http.HTTPStatus.NOT_FOUND"),
    ],
)
def test_proven_status_import_forms_are_resolved(imports: str, status_expr: str):
    source = (
        _PRELUDE
        + f"""
{imports}

@router.get("/users", summary="Read users", description="Returns users.", status_code=200)
async def users() -> UserResponse:
    raise HTTPException(status_code={status_expr})
"""
    )
    assert any("[responses]" in diagnostic.message and "404" in diagnostic.message for diagnostic in _check(source))


def test_string_response_code_documents_direct_exception():
    source = (
        _PRELUDE
        + """
@router.get(
    "/users",
    summary="Read users",
    description="Returns users.",
    status_code=200,
    responses={"404": {"description": "Not found"}},
)
async def users() -> UserResponse:
    raise HTTPException(status_code=404)
"""
    )
    assert _check(source) == []


def test_direct_alternate_response_requires_documentation():
    source = _source("""
@router.get("/exports", summary="Read export", description="Returns an export.", status_code=200)
async def export() -> ExportResponse:
    return FileResponse("pending.txt", status_code=202)
""")
    assert any("[responses]" in diagnostic.message and "202" in diagnostic.message for diagnostic in _check(source))


def test_dynamic_responses_are_accepted_as_unverifiable():
    source = (
        _PRELUDE
        + """
@router.get(
    "/users/{user_id}",
    summary="Read user",
    description="Returns a user.",
    status_code=200,
    responses=COMMON_RESPONSES,
)
async def user(user_id: Annotated[str, Path(description="User identifier")]) -> UserResponse:
    raise HTTPException(status_code=404)
"""
    )
    assert _check(source) == []


def test_raw_request_body_requires_openapi_extra():
    source = _source("""
@router.post("/events", summary="Receive event", description="Receives an event.", status_code=202)
async def event(request: Request) -> Ack:
    payload = await request.json()
    return Ack(payload=payload)
""")
    assert any(
        "[parameter]" in diagnostic.message and "requestBody" in diagnostic.message for diagnostic in _check(source)
    )


def test_local_duplicate_and_shadowed_routes_are_rejected():
    source = (
        _PRELUDE
        + """
@router.get("/users/{user_id}", summary="Read user", description="Returns a user.", status_code=200)
async def user(user_id: Annotated[str, Path(description="User identifier")]) -> UserResponse: ...

@router.get("/users/me", summary="Read me", description="Returns the caller.", status_code=200)
async def me() -> UserResponse: ...

@router.get("/users/me", summary="Read me again", description="Returns the caller.", status_code=200)
async def me_again() -> UserResponse: ...
"""
    )
    messages = [diagnostic.message for diagnostic in _check(source)]
    assert any("[routing]" in message and "shadowed" in message for message in messages)
    assert any("[routing]" in message and "duplicate" in message for message in messages)


def test_independent_router_factories_do_not_conflict():
    source = _source("""
def first() -> APIRouter:
    router = APIRouter()

    @router.get("/items", summary="Read first", description="Returns first items.", status_code=200)
    async def items() -> FirstResponse: ...
    return router

def second() -> APIRouter:
    router = APIRouter()

    @router.get("/items", summary="Read second", description="Returns second items.", status_code=200)
    async def items() -> SecondResponse: ...
    return router
""")
    assert _check(source) == []


def test_hidden_websocket_test_generated_and_unrelated_routes_are_ignored():
    hidden = _source("""
@router.get("/internal", include_in_schema=False)
async def internal(value):
    return value

@router.websocket("/ws")
async def ws(socket): ...
""")
    assert _check(hidden) == []
    assert _check(_source("@router.get('/x')\nasync def x(): ...\n"), "tests/api.py") == []
    assert _check(f"# Generated by openapi-generator\n{_source("@router.get('/x')\nasync def x(): ...\n")}") == []
    assert _check("@client.get('/x')\ndef x(): return {}\n") == []


def test_router_level_schema_exclusion_is_inherited_without_cross_scope_leakage():
    source = """
from fastapi import APIRouter

def hidden_factory() -> APIRouter:
    router = APIRouter(include_in_schema=False)

    @router.get("/internal")
    async def internal(value):
        return value
    return router

def visible_factory() -> APIRouter:
    router = APIRouter()

    @router.get("/public")
    async def public() -> PublicResponse:
        return PublicResponse()
    return router
"""
    diagnostics = _check(source)
    assert len(diagnostics) == 1
    assert diagnostics[0].line == 15
    assert "[metadata]" in diagnostics[0].message


def test_path_marker_alias_matches_the_route_contract_name():
    source = (
        _PRELUDE
        + """
@router.get(
    "/items/{item_id}",
    summary="Read item",
    description="Returns an item.",
    status_code=200,
)
async def item(identifier: Annotated[str, Path(alias="item_id", description="Item identifier")]) -> ItemResponse:
    return ItemResponse()
"""
    )
    assert _check(source) == []


def test_proven_self_router_is_recognized_but_unproven_attribute_is_not():
    source = """
from fastapi import APIRouter

class Routes:
    def __init__(self) -> None:
        self.router = APIRouter()

        @self.router.get("/items")
        async def items() -> ItemResponse:
            return ItemResponse()

class Client:
    def register(self) -> None:
        @self.router.get("/remote")
        async def remote():
            return {}
"""
    diagnostics = _check(source)
    assert len(diagnostics) == 1
    assert diagnostics[0].line == 8
    assert "[metadata]" in diagnostics[0].message


def test_typed_legacy_parameter_marker_requires_annotated():
    source = _source("""
@router.post("/items", summary="Create item", description="Creates an item.", status_code=201)
async def create_item(payload: dict[str, str] = Body(description="Payload")) -> ItemResponse:
    return ItemResponse()
""")
    diagnostics = _check(source)
    assert any("[parameter]" in diagnostic.message and "Annotated" in diagnostic.message for diagnostic in diagnostics)


def test_direct_response_requires_response_class_but_not_response_model_none():
    clean = (
        _PRELUDE
        + """
@router.get(
    "/report",
    summary="Download report",
    description="Returns the generated report.",
    status_code=200,
    response_class=FileResponse,
    responses={200: {"content": {"application/pdf": {}}}},
)
async def report() -> FileResponse:
    return FileResponse("report.pdf")
"""
    )
    assert _check(clean) == []

    incomplete = clean.replace('    responses={200: {"content": {"application/pdf": {}}}},\n', "")
    diagnostics = _check(incomplete)
    assert len(diagnostics) == 1
    assert "responses content schema" in diagnostics[0].message


def test_no_content_return_contract_problems_are_aggregated_per_handler():
    source = _source("""
@router.get(
    "/stream",
    summary="Stream report",
    description="Streams the generated report.",
    status_code=204,
    response_model=ItemResponse,
)
async def stream() -> StreamingResponse:
    return StreamingResponse(iter(()))
""")
    diagnostics = [diagnostic for diagnostic in _check(source) if "[return]" in diagnostic.message]
    assert len(diagnostics) == 1
    assert "response_class" not in diagnostics[0].message
    assert "must not declare a response model" in diagnostics[0].message


def test_unrelated_framework_shaped_symbols_are_ignored():
    source = """
from typing import Annotated as RealAnnotated
from fastapi import APIRouter
import aiohttp
import fake

router = APIRouter()

class Query: ...
class Annotated:
    def __class_getitem__(cls, value): ...

@router.get("/items", summary="Read items", description="Returns items.", status_code=200)
async def items(
    request: fake.Request,
    value: Annotated[str, Query(description="Fake")],
) -> aiohttp.Response:
    raise fake.HTTPException(status_code=fake.NOT_HTTP_404_VALUE)
"""
    diagnostics = _check(source)
    messages = [diagnostic.message for diagnostic in diagnostics]
    assert messages == [
        "[parameter] `request` requires explicit Annotated metadata.",
        "[parameter] `value` requires explicit Annotated metadata.",
    ]


def test_api_route_literal_methods_drive_body_and_conflict_checks():
    source = _source("""
@router.api_route(
    "/items",
    methods=["GET"],
    summary="Read items",
    description="Returns items.",
    status_code=200,
)
async def items(payload: Annotated[ItemBody, Body(description="Filter")]) -> ItemResponse: ...

@router.get("/items", summary="Read items again", description="Returns items.", status_code=200)
async def items_again() -> ItemResponse: ...
""")
    messages = [diagnostic.message for diagnostic in _check(source)]
    assert any("GET operations must not declare a request body" in message for message in messages)
    assert any("duplicate GET /items" in message for message in messages)


def test_path_placeholder_requires_path_marker_and_dynamic_alias_is_unverifiable():
    wrong = (
        _PRELUDE
        + """
@router.get("/items/{item_id}", summary="Read item", description="Returns an item.", status_code=200)
async def item(item_id: Annotated[str, Query(description="Item identifier")]) -> ItemResponse: ...
"""
    )
    assert any("requires a Path marker" in diagnostic.message for diagnostic in _check(wrong))

    dynamic = (
        _PRELUDE
        + """
@router.get("/items/{item_id}", summary="Read item", description="Returns an item.", status_code=200)
async def item(identifier: Annotated[str, Path(alias=PATH_NAME, description="Item identifier")]) -> ItemResponse: ...
"""
    )
    assert _check(dynamic) == []


@pytest.mark.parametrize(
    ("parameter", "expected"),
    [
        ("item_id: str", "explicit Annotated metadata"),
        ("item_id: Annotated[str, Metadata()]", "exactly one FastAPI parameter marker"),
    ],
)
def test_invalid_path_parameter_metadata_has_one_actionable_diagnostic(parameter: str, expected: str):
    source = _source(f"""
@router.get("/items/{{item_id}}", summary="Read item", description="Returns an item.", status_code=200)
async def item({parameter}) -> ItemResponse: ...
""")
    diagnostics = [diagnostic for diagnostic in _check(source) if "[parameter]" in diagnostic.message]
    assert [diagnostic.message for diagnostic in diagnostics] == [f"[parameter] `item_id` requires {expected}."]


def test_absent_path_parameter_still_requires_path_marker():
    source = _source("""
@router.get("/items/{item_id}", summary="Read item", description="Returns an item.", status_code=200)
async def item() -> ItemResponse: ...
""")
    diagnostics = [diagnostic for diagnostic in _check(source) if "[parameter]" in diagnostic.message]
    assert [diagnostic.message for diagnostic in diagnostics] == [
        "[parameter] route path `item_id` requires a Path marker."
    ]


def test_typed_path_converter_does_not_shadow_incompatible_static_route():
    source = (
        _PRELUDE
        + """
@router.get("/users/{user_id:int}", summary="Read user", description="Returns a user.", status_code=200)
async def user(user_id: Annotated[int, Path(description="User identifier")]) -> UserResponse: ...

@router.get("/users/me", summary="Read me", description="Returns me.", status_code=200)
async def me() -> UserResponse: ...
"""
    )
    assert _check(source) == []


def test_receiver_resolution_obeys_shadowing_classes_and_closure_scopes():
    shadowed = """
from fastapi import APIRouter
router = APIRouter()

def attach(router):
    @router.get("/remote")
    async def remote():
        return {}
"""
    assert _check(shadowed) == []

    classes = """
from fastapi import APIRouter

class Hidden:
    router = APIRouter(include_in_schema=False)

    @router.get("/hidden")
    async def hidden(self): ...

class Visible:
    router = APIRouter()

    @router.get("/visible")
    async def visible(self) -> VisibleResponse: ...
"""
    diagnostics = _check(classes)
    assert len(diagnostics) == 1
    assert "[metadata]" in diagnostics[0].message


def test_scoped_import_and_loop_targets_shadow_outer_router():
    source = """
from fastapi import APIRouter
router = APIRouter()

def imported() -> None:
    import client as router

    @router.get("/remote")
    async def remote(): ...

def looped(clients) -> None:
    for router in clients:
        @router.get("/remote")
        async def remote(): ...
"""
    assert _check(source) == []


def test_hidden_routes_still_participate_in_runtime_ordering():
    source = (
        _PRELUDE
        + """
@router.get("/users/{name}", include_in_schema=False)
async def hidden(name): ...

@router.get("/users/me", summary="Read me", description="Returns me.", status_code=200)
async def me() -> UserResponse: ...
"""
    )
    diagnostics = _check(source)
    assert len(diagnostics) == 1
    assert "[routing]" in diagnostics[0].message
    assert "shadowed" in diagnostics[0].message


def test_direct_response_class_must_match_concrete_return_type():
    source = (
        _PRELUDE
        + """
from fastapi.responses import JSONResponse

@router.get(
    "/report",
    summary="Download report",
    description="Returns the generated report.",
    status_code=200,
    response_class=JSONResponse,
    responses={200: {"content": {"application/pdf": {}}}},
)
async def report() -> FileResponse:
    return FileResponse("report.pdf")
"""
    )
    diagnostics = _check(source)
    assert len(diagnostics) == 1
    assert "conflicts with response_class" in diagnostics[0].message

    closure = """
from fastapi import APIRouter

def factory() -> APIRouter:
    router = APIRouter()

    def register() -> None:
        @router.get("/items")
        async def items() -> ItemResponse: ...

    register()
    return router
"""
    diagnostics = _check(closure)
    assert len(diagnostics) == 1
    assert "[metadata]" in diagnostics[0].message


def test_aliases_are_resolved_without_receiver_name_guesses():
    source = """
import fastapi as fa
from typing import Annotated as A

api = fa.FastAPI()
read = api.get

@read("/items/{item_id}", summary="Read item", description="Returns an item.", status_code=200)
async def item(item_id: A[str, fa.Path(description="Item identifier")]) -> ItemResponse:
    return ItemResponse()
"""
    assert _check(source) == []


def test_sarj008_cedes_proven_routes_to_sarj094():
    source = (
        _PRELUDE
        + """
@router.get("/health")
async def health() -> dict[str, Any]:
    return {"status": "ok"}
"""
    )
    assert PydanticAtBoundaries().check(Path("api.py"), source) == []
    assert FastapiOpenapiContract().check(Path("api.py"), source)


def test_sarj008_keeps_hidden_and_unannotated_route_ownership():
    hidden = """
from fastapi import APIRouter
from typing import Any
router = APIRouter(include_in_schema=False)

@router.get("/health")
async def health() -> dict[str, Any]:
    return {"status": "ok"}
"""
    assert FastapiOpenapiContract().check(Path("api.py"), hidden) == []
    assert len(PydanticAtBoundaries().check(Path("api.py"), hidden)) == 1

    unannotated = _PRELUDE + "\n@router.get('/health')\nasync def health():\n    return {'status': 'ok'}\n"
    assert len(PydanticAtBoundaries().check(Path("api.py"), unannotated)) == 1
