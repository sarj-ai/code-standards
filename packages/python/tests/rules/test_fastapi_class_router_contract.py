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


@pytest.mark.parametrize("example", FastapiClassRouterContract.public_examples())
def test_deep_annotation_preserves_router_owner_examples(example: RuleExample) -> None:
    annotation = " | ".join(["str"] * 3001 + ["None"])
    source = f"{example.focus_file.source}\nclass AnnotationCarrier:\n    payload: {annotation}\n"
    assert len(FastapiClassRouterContract().check(Path(example.focus_path), source)) == example.expected_count


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


@pytest.mark.parametrize(
    ("binding", "status"),
    [
        ("", "204"),
        ("", "205"),
        ("", "304"),
        ("from fastapi import status", "status.HTTP_204_NO_CONTENT"),
        ("import fastapi as api", "api.status.HTTP_205_RESET_CONTENT"),
        ("from starlette.status import HTTP_204_NO_CONTENT as EMPTY", "EMPTY"),
        ("from starlette import status as codes", "codes.HTTP_205_RESET_CONTENT"),
        ("import starlette.status as codes", "codes.HTTP_304_NOT_MODIFIED"),
        ("from http import HTTPStatus as Codes", "Codes.RESET_CONTENT"),
        ("import http", "http.HTTPStatus.NOT_MODIFIED"),
    ],
)
@pytest.mark.parametrize("annotation", ["None", "Response", "EmptyResponse"])
def test_proven_no_body_status_does_not_require_a_json_model(binding: str, status: str, annotation: str) -> None:
    result = "None" if annotation == "None" else f"{annotation}(status_code={status})"
    source = f"""
from fastapi import APIRouter, Response
{binding}
class EmptyResponse(Response):
    pass
class ClearRouter:
    def build(self) -> APIRouter:
        router = APIRouter()
        @router.delete("/items", status_code={status})
        def clear() -> {annotation}:
            return {result}
        return router
"""
    assert _check(source) == []


@pytest.mark.parametrize(
    "shadow",
    [
        "status = provider",
        "status.HTTP_204_NO_CONTENT = replacement",
        "setattr(status, 'HTTP_204_NO_CONTENT', replacement)",
        "alias = status; alias.HTTP_204_NO_CONTENT = replacement",
    ],
)
def test_unresolved_status_does_not_guess_a_json_response(shadow: str) -> None:
    source = f"""
from fastapi import APIRouter, status
class ItemRouter:
    def build(self) -> APIRouter:
        {shadow}
        router = APIRouter()
        @router.get("/items", status_code=status.HTTP_204_NO_CONTENT)
        def items() -> ItemsResponse:
            return ItemsResponse(items=[])
        return router
"""
    assert _check(source) == []


def test_status_mutation_through_an_imported_alias_invalidates_the_provider() -> None:
    source = """
from fastapi import APIRouter, status
from starlette import status as codes
class ItemRouter:
    def build(self) -> APIRouter:
        codes.HTTP_204_NO_CONTENT = replacement
        router = APIRouter()
        @router.get("/items", status_code=status.HTTP_204_NO_CONTENT)
        def items() -> ItemsResponse:
            return ItemsResponse(items=[])
        return router
"""
    assert _check(source) == []


def test_enclosing_parameter_shadows_a_status_module() -> None:
    source = """
from fastapi import APIRouter, status
class ItemRouter:
    def build(self, status) -> APIRouter:
        router = APIRouter()
        @router.get("/items", status_code=status.HTTP_204_NO_CONTENT)
        def items() -> ItemsResponse:
            return ItemsResponse(items=[])
        return router
"""
    assert _check(source) == []


def test_handler_parameter_and_class_namespace_do_not_shadow_a_decorator_status() -> None:
    source = """
from fastapi import APIRouter, status
class ClearRouter:
    status = provider
    def build(self) -> APIRouter:
        router = APIRouter()
        @router.delete("/items", status_code=status.HTTP_204_NO_CONTENT)
        def clear(status: str) -> None:
            return None
        return router
"""
    assert _check(source) == []


@pytest.mark.parametrize("status", ["", ", status_code=None", ", status_code=200"])
def test_known_default_json_status_still_requires_a_response_model(status: str) -> None:
    source = f"""
from fastapi import APIRouter
class ItemRouter:
    def build(self) -> APIRouter:
        router = APIRouter()
        @router.get("/items"{status})
        def items() -> ItemsResponse:
            return ItemsResponse(items=[])
        return router
"""
    [finding] = _check(source)
    assert "response_model" in finding.message


@pytest.mark.parametrize("constructor", ["FastAPI", "APIRouter"])
def test_unknown_status_preserves_receiver_ownership(constructor: str) -> None:
    source = f"""
from fastapi import FastAPI, APIRouter, Response
receiver = {constructor}()
@receiver.get("/items", status_code=select_status())
def items() -> Response:
    return Response(status_code=204)
"""
    [finding] = _check(source)
    assert "response_model" not in finding.message


def test_unpacked_metadata_does_not_guess_a_json_model() -> None:
    source = """
from fastapi import APIRouter
OPTIONS = {"status_code": 204}
class ClearRouter:
    def build(self) -> APIRouter:
        router = APIRouter()
        @router.delete("/items", **OPTIONS)
        def clear() -> None:
            return None
        return router
"""
    assert _check(source) == []


@pytest.mark.parametrize(
    ("binding", "response_class"),
    [
        ("from fastapi.responses import HTMLResponse as Page", "Page"),
        ("from starlette.responses import FileResponse as Download", "Download"),
        ("import starlette.responses as wire", "wire.PlainTextResponse"),
        ("from fastapi import Response as Raw", "Raw"),
        ("from project.responses import CsvResponse", "CsvResponse"),
        ("class HTMLResponse(Response):\n    media_type = 'text/csv'", "HTMLResponse"),
        ("from fastapi.responses import HTMLResponse as Page\nPage = custom_response", "Page"),
    ],
)
def test_non_json_or_unknown_response_class_does_not_require_a_json_model(binding: str, response_class: str) -> None:
    source = f"""
from fastapi import APIRouter, Response
{binding}
class ExportRouter:
    def build(self) -> APIRouter:
        router = APIRouter()
        @router.get("/export", status_code=200, response_class={response_class})
        def export() -> {response_class}:
            return {response_class}("payload")
        return router
"""
    assert _check(source) == []


@pytest.mark.parametrize(
    ("binding", "response_class"),
    [
        ("", ""),
        ("from starlette.responses import JSONResponse as Json", ", response_class=Json"),
        ("import fastapi.responses as wire", ", response_class=wire.JSONResponse"),
    ],
)
def test_proven_json_response_class_keeps_the_named_model_contract(binding: str, response_class: str) -> None:
    source = f"""
from fastapi import APIRouter
{binding}
class ItemRouter:
    def build(self) -> APIRouter:
        router = APIRouter()
        @router.get("/items", status_code=200{response_class})
        def items() -> ItemsResponse:
            return ItemsResponse(items=[])
        return router
"""
    [finding] = _check(source)
    assert "response_model" in finding.message


def test_unknown_response_class_keeps_receiver_ownership() -> None:
    source = """
from fastapi import FastAPI
from project.responses import CsvResponse
app = FastAPI()
@app.get("/export", status_code=200, response_class=CsvResponse)
def export() -> CsvResponse:
    return CsvResponse("payload")
"""
    [finding] = _check(source)
    assert "include_router" in finding.message


@pytest.mark.parametrize(
    "alias", ["FileResponse", "HTMLResponse", "PlainTextResponse", "RedirectResponse", "StreamingResponse"]
)
def test_precision_repair_preserves_existing_response_name_exemptions(alias: str) -> None:
    source = f"""
from fastapi import APIRouter
from fastapi.responses import JSONResponse as {alias}
class ItemRouter:
    def build(self) -> APIRouter:
        router = APIRouter()
        @router.get("/items", status_code=200, response_class={alias})
        def items() -> {alias}:
            return {alias}({{"items": []}})
        return router
"""
    assert _check(source) == []


@pytest.mark.parametrize(
    "mutation",
    [
        "wire.JSONResponse = ResetResponse",
        "del wire.JSONResponse",
        "Json.media_type = 'text/csv'",
        "del Json.media_type",
        "alias = Json; alias.media_type = 'text/csv'",
        "alias = wire; alias.JSONResponse = ResetResponse",
        "mutate(wire)",
        "mutate(response_class=Json)",
        "setattr(Json, 'media_type', 'text/csv')",
    ],
)
@pytest.mark.parametrize("metadata", ["", "status_code=200", "response_class=wire.JSONResponse"])
def test_unstable_native_response_providers_do_not_prove_a_json_model(mutation: str, metadata: str) -> None:
    source = f"""
from fastapi import APIRouter
import fastapi.responses as wire
from starlette.responses import JSONResponse as Json
class ResetResponse(wire.Response):
    def __init__(self, content=None, status_code=205, **kwargs):
        super().__init__(content=content, status_code=status_code, **kwargs)
{mutation}
class ClearRouter:
    def build(self) -> APIRouter:
        router = APIRouter()
        @router.get("/clear", {metadata})
        def clear() -> None:
            return None
        return router
"""
    assert _check(source) == []


@pytest.mark.parametrize(
    "registration",
    [
        "app.include_router(router, default_response_class=Json)",
        "router.add_api_route('/other', other, response_class=Json)",
    ],
)
def test_native_registration_consumes_response_classes_without_mutating_them(registration: str) -> None:
    source = f"""
from fastapi import APIRouter, FastAPI
from fastapi.responses import JSONResponse as Json
app = FastAPI(default_response_class=Json)
class ItemRouter:
    def build(self) -> APIRouter:
        router = APIRouter(default_response_class=Json)
        {registration}
        @router.get("/items", status_code=200, response_class=Json)
        def items() -> ItemsResponse:
            return ItemsResponse(items=[])
        return router
"""
    [finding] = _check(source)
    assert "response_model" in finding.message


@pytest.mark.parametrize(
    ("constructor", "operation", "requires_model"),
    [
        ("**OPTIONS", "", False),
        ("**OPTIONS", ", status_code=200", False),
        ("**OPTIONS", ", response_class=Json", True),
        ("default_response_class=Json, **EXTRA", "", True),
    ],
)
def test_constructor_unpack_keeps_default_response_inference_uncertain(
    constructor: str, operation: str, requires_model: bool
) -> None:
    source = f"""
from fastapi import APIRouter
from fastapi.responses import JSONResponse as Json, RedirectResponse
OPTIONS = {{"default_response_class": RedirectResponse}}
EXTRA = {{"prefix": "/v1"}}
class ItemRouter:
    def build(self) -> APIRouter:
        router = APIRouter({constructor})
        @router.get("/items"{operation})
        def items() -> ItemsResponse:
            return ItemsResponse(items=[])
        return router
"""
    findings = _check(source)
    assert bool(findings) is requires_model
    assert all("response_model" in finding.message for finding in findings)


@pytest.mark.parametrize(
    ("binding", "receiver", "decorator"),
    [
        ("from fastapi import FastAPI\napp = FastAPI()", "app", "get('/items', response_model=ItemsResponse)"),
        (
            "from fastapi import FastAPI as Application\napp = Application()",
            "app",
            "post('/items', response_model=ItemsResponse)",
        ),
        ("import fastapi as api\napp = api.FastAPI()", "app", "get('/items', response_model=ItemsResponse)"),
        (
            "from fastapi import FastAPI\napp = FastAPI()\nalias = app",
            "alias",
            "get('/items', response_model=ItemsResponse)",
        ),
        (
            "from fastapi import FastAPI\napp = FastAPI()",
            "app",
            "api_route('/items', methods=['GET', 'POST'], response_model=ItemsResponse)",
        ),
        (
            "from fastapi import FastAPI\napp = FastAPI(openapi_url=None)",
            "app",
            "get('/items', response_model=ItemsResponse)",
        ),
    ],
)
def test_direct_app_routes_require_class_router_ownership(binding: str, receiver: str, decorator: str) -> None:
    source = f"""
{binding}
@{receiver}.{decorator}
def items() -> ItemsResponse:
    return ItemsResponse(items=[])
"""
    [finding] = _check(source)
    assert finding.line == 2 + len(binding.splitlines())
    assert "include_router" in finding.message


def test_bound_app_decorator_requires_class_router_ownership() -> None:
    source = """
from fastapi import FastAPI
app = FastAPI()
register = app.get
@register('/items', response_model=ItemsResponse)
def items() -> ItemsResponse:
    return ItemsResponse(items=[])
"""
    [finding] = _check(source)
    assert finding.line == 5
    assert "include_router" in finding.message


def test_nested_factory_direct_app_routes_require_class_router_ownership() -> None:
    source = """
from fastapi import FastAPI
def create_app() -> FastAPI:
    application = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)
    @application.get('/v1/model', response_model=ModelResponse)
    async def model() -> ModelResponse:
        return ModelResponse(model='loaded')
    return application
"""
    [finding] = _check(source)
    assert finding.line == 5
    assert "include_router" in finding.message


@pytest.mark.parametrize(
    "source",
    [
        "from fastapi import FastAPI\napp = FastAPI()\napp.include_router(ItemRouter(service).build())\n",
        (
            "from fastapi import FastAPI\ndef create_app():\n    app = FastAPI()\n"
            "    app.include_router(ItemRouter(service).build())\n    return app\n"
        ),
        "from fastapi import FastAPI\napp = FastAPI()\n@app.websocket('/events')\nasync def events(): ...\n",
        (
            "from fastapi import FastAPI\napp = FastAPI()\n@app.get('/health', include_in_schema=False)\n"
            "def health(): ...\n"
        ),
        "from fastapi import FastAPI\napp = FastAPI(include_in_schema=False)\n@app.get('/health')\ndef health(): ...\n",
        "from framework import FastAPI\napp = FastAPI()\n@app.get('/items')\ndef items(): ...\n",
        (
            "from fastapi import FastAPI\napp = FastAPI()\ndef register(app):\n"
            "    @app.get('/items')\n    def items(): ...\n"
        ),
    ],
)
def test_preserves_app_composition_hidden_routes_and_unproven_receivers(source: str) -> None:
    assert _check(source) == []


@pytest.mark.parametrize("path", ["tests/test_routes.py", "app/generated/routes.py"])
def test_direct_app_route_preserves_path_exclusions(path: str) -> None:
    source = "from fastapi import FastAPI\napp = FastAPI()\n@app.get('/items')\ndef items(): ...\n"
    assert FastapiClassRouterContract().check(Path(path), source) == []


def test_malformed_direct_app_route_is_ignored() -> None:
    assert _check("from fastapi import FastAPI\napp = FastAPI(\n") == []


@pytest.mark.parametrize(
    "source",
    [
        "from fastapi import APIRouter\nAPIRouter = OtherRouter\nrouter = APIRouter()\n",
        "import fastapi as api\napi = other_api\nrouter = api.APIRouter()\n",
        "from fastapi import APIRouter\ndef factory(APIRouter):\n    return APIRouter()\n",
        "import fastapi as api\ndef factory(api):\n    return api.APIRouter()\n",
        (
            "from fastapi import FastAPI\nFastAPI = OtherApplication\napp = FastAPI()\n"
            "@app.get('/items')\ndef items(): ...\n"
        ),
        "import fastapi as api\napi = other_api\napp = api.FastAPI()\n@app.get('/items')\ndef items(): ...\n",
        (
            "from fastapi import FastAPI\ndef create_app(FastAPI):\n    app = FastAPI()\n"
            "    @app.get('/items')\n    def items(): ...\n"
        ),
        (
            "import fastapi as api\ndef create_app(api):\n    app = api.FastAPI()\n"
            "    @app.get('/items')\n    def items(): ...\n"
        ),
    ],
)
def test_rebound_or_shadowed_constructors_are_not_framework_proof(source: str) -> None:
    assert _check(source) == []


@pytest.mark.parametrize(
    "binding",
    [
        "    FastAPI, = (other_constructor,)",
        "    [FastAPI] = [other_constructor]",
        "    FastAPI, *rest = values",
        "    FastAPI = other = other_constructor",
        "    FastAPI += other_constructor",
        "    del FastAPI",
        "    match values:\n        case FastAPI:\n            pass",
        "    match values:\n        case [*FastAPI]:\n            pass",
        "    match values:\n        case {**FastAPI}:\n            pass",
    ],
)
def test_local_binding_forms_do_not_prove_fastapi_constructor(binding: str) -> None:
    source = f"""
from fastapi import FastAPI
def create_app(other_constructor, values):
{binding}
    app = FastAPI()
    @app.get('/items', response_model=ItemsResponse)
    def items() -> ItemsResponse: ...
    return app
"""
    assert _check(source) == []


def test_unrelated_function_binding_does_not_shadow_constructor() -> None:
    source = """
from fastapi import FastAPI
def unrelated(value):
    FastAPI, = (value,)
def create_app():
    app = FastAPI()
    @app.get('/items', response_model=ItemsResponse)
    def items() -> ItemsResponse: ...
    return app
"""
    [finding] = _check(source)
    assert "include_router" in finding.message


@pytest.mark.parametrize(
    "iteration",
    [
        "[FastAPI for FastAPI in values]",
        "{FastAPI for FastAPI in values}",
        "{FastAPI: None for FastAPI in values}",
        "(FastAPI for FastAPI in values)",
    ],
)
def test_comprehension_binding_does_not_shadow_enclosing_constructor(iteration: str) -> None:
    source = f"""
from fastapi import FastAPI
def create_app(values):
    unused = {iteration}
    app = FastAPI()
    @app.get('/items', response_model=ItemsResponse)
    def items() -> ItemsResponse: ...
    return app
"""
    [finding] = _check(source)
    assert "include_router" in finding.message


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("lambda APIRouter: APIRouter()", 0),
        ("lambda *APIRouter: APIRouter()", 0),
        ("lambda **APIRouter: APIRouter()", 0),
        ("lambda *, APIRouter: APIRouter()", 0),
        ("lambda APIRouter: (lambda: APIRouter())", 0),
        ("lambda: APIRouter()", 1),
        ("lambda: (lambda: APIRouter())", 1),
        ("lambda APIRouter=APIRouter(): APIRouter()", 1),
        ("[APIRouter() for APIRouter in factories]", 0),
        ("{APIRouter() for APIRouter in factories}", 0),
        ("{APIRouter: APIRouter() for APIRouter in factories}", 0),
        ("(APIRouter() for APIRouter in factories)", 0),
        ("[APIRouter() for factory in factories]", 1),
        ("{APIRouter() for factory in factories}", 1),
        ("{factory: APIRouter() for factory in factories}", 1),
        ("(APIRouter() for factory in factories)", 1),
        ("[value for APIRouter in APIRouter()]", 1),
        ("[value for APIRouter in factories for value in APIRouter()]", 0),
    ],
)
def test_implicit_constructor_scopes_preserve_shadowing_and_proof(expression: str, expected: int) -> None:
    source = f"from fastapi import APIRouter\nvalue = {expression}\n"
    assert len(_check(source)) == expected


@pytest.mark.parametrize(("receiver", "expected"), [("FastAPI", 0), ("unrelated", 1)])
def test_async_with_target_preserves_constructor_scope(receiver: str, expected: int) -> None:
    source = f"""
from fastapi import FastAPI
async def create_app(factory):
    async with factory() as {receiver}:
        pass
    app = FastAPI()
    @app.get('/items', response_model=ItemsResponse)
    def items() -> ItemsResponse: ...
    return app
"""
    assert len(_check(source)) == expected


def test_comprehension_assignment_expression_binds_enclosing_scope() -> None:
    source = """
from fastapi import FastAPI
def create_app(values):
    unused = [(FastAPI := value) for value in values]
    app = FastAPI()
    @app.get('/items', response_model=ItemsResponse)
    def items() -> ItemsResponse: ...
    return app
"""
    assert _check(source) == []


def test_function_default_is_evaluated_outside_its_parameter_scope() -> None:
    source = """
from fastapi import APIRouter
def create_router(APIRouter=APIRouter()):
    return APIRouter
"""
    assert len(_check(source)) == 1


def test_class_decorator_is_evaluated_outside_class_bindings() -> None:
    source = """
from fastapi import APIRouter
@decorate(APIRouter())
class Factory:
    APIRouter = OtherRouter
"""
    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    ("binding", "constructor"),
    [
        ("from fastapi import APIRouter as Router", "Router"),
        ("from fastapi.routing import APIRouter as Router", "Router"),
        ("import fastapi.routing as routing", "routing.APIRouter"),
    ],
)
def test_router_construction_keeps_supported_import_aliases(binding: str, constructor: str) -> None:
    source = f"{binding}\nrouter = {constructor}()\n"
    [finding] = _check(source)
    assert "construct APIRouter" in finding.message


@pytest.mark.parametrize(
    "binding",
    [
        "from fastapi.applications import FastAPI\napp = FastAPI()",
        "import fastapi.applications as applications\napp = applications.FastAPI()",
    ],
)
def test_direct_app_routes_keep_secondary_import_paths(binding: str) -> None:
    source = f"{binding}\n@app.get('/items', response_model=ItemsResponse)\ndef items() -> ItemsResponse: ...\n"
    [finding] = _check(source)
    assert "include_router" in finding.message
