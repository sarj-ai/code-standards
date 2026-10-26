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
