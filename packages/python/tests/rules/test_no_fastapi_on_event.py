from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rules.no_fastapi_on_event import NoFastapiOnEvent


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import RuleExample


def _check(source: str):
    return NoFastapiOnEvent().check(Path("app.py"), source)


@pytest.mark.parametrize(
    "example",
    NoFastapiOnEvent.public_examples(),
    ids=tuple(example.example_id for example in NoFastapiOnEvent.public_examples()),
)
def test_public_documentation_examples_are_executable(example: RuleExample) -> None:
    assert (
        len(NoFastapiOnEvent().check(Path(example.focus_file.path), example.focus_file.source))
        == example.expected_count
    )


@pytest.mark.parametrize("event", ["startup", "shutdown"])
def test_reports_fastapi_lifecycle_events(event: str) -> None:
    findings = _check(
        f'from fastapi import FastAPI\napp = FastAPI()\n\n@app.on_event("{event}")\nasync def hook() -> None:\n    pass\n'
    )
    assert len(findings) == 1
    assert findings[0].code == "SARJ427"
    assert findings[0].line == 4


def test_reports_aliased_starlette_application() -> None:
    source = (
        "from starlette.applications import Starlette as Application\n"
        "service = Application()\n\n"
        '@service.on_event("startup")\n'
        "def start() -> None:\n    pass\n"
    )
    assert len(_check(source)) == 1


def test_reports_function_local_application() -> None:
    source = (
        "from fastapi import FastAPI\n"
        "def build() -> FastAPI:\n"
        "    app = FastAPI()\n"
        '    @app.on_event("startup")\n'
        "    async def start() -> None:\n        pass\n"
        "    return app\n"
    )
    assert len(_check(source)) == 1


def test_reports_annotated_application_parameter() -> None:
    source = (
        "from fastapi import FastAPI\n"
        "def register(app: FastAPI) -> None:\n"
        '    @app.on_event("shutdown")\n'
        "    def stop() -> None:\n        pass\n"
    )
    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    "constructor",
    [
        "from fastapi import APIRouter\nrouter = APIRouter()",
        "from starlette.routing import Router\nrouter = Router()",
    ],
)
def test_reports_framework_router_lifecycle_events(constructor: str) -> None:
    source = f'{constructor}\n@router.on_event("startup")\ndef start() -> None:\n    pass\n'
    assert len(_check(source)) == 1


def test_reports_application_router_and_simple_aliases() -> None:
    source = (
        "from fastapi import FastAPI\n"
        "app = FastAPI()\n"
        "router = app.router\n"
        "lifecycle_router = router\n"
        '@lifecycle_router.on_event("shutdown")\n'
        "def stop() -> None:\n    pass\n"
    )
    assert len(_check(source)) == 1


def test_reports_an_annotated_application_binding() -> None:
    source = (
        "from fastapi import FastAPI\n"
        "app: FastAPI\n"
        '@app.on_event("startup")\n'
        "def start() -> None:\n    pass\n"
    )
    assert len(_check(source)) == 1


def test_later_rebinding_removes_application_provenance() -> None:
    source = (
        "from fastapi import FastAPI\n"
        "app = FastAPI()\n"
        "app = event_bus\n"
        '@app.on_event("startup")\n'
        "def start() -> None:\n    pass\n"
    )
    assert _check(source) == []


@pytest.mark.parametrize(
    "source",
    [
        "from fastapi import FastAPI\napp = FastAPI(lifespan=lifespan)\n",
        'class Bus:\n    def on_event(self, name: str): ...\nbus = Bus()\n@bus.on_event("startup")\ndef start(): ...\n',
        'from fastapi import FastAPI\napp = build_app()\n@app.on_event("startup")\ndef start(): ...\n',
        "from fastapi import FastAPI\napp = FastAPI()\n@app.on_event(event_name)\ndef start(): ...\n",
        'from fastapi import FastAPI\napp = FastAPI()\n@app.on_event("message")\ndef message(): ...\n',
        'FastAPI = Factory\napp = FastAPI()\n@app.on_event("startup")\ndef start(): ...\n',
    ],
)
def test_allows_unproven_or_unrelated_patterns(source: str) -> None:
    assert _check(source) == []


def test_syntax_error_is_ignored() -> None:
    assert _check("from fastapi import FastAPI\napp = FastAPI(\n") == []
