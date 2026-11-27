from pathlib import Path

import pytest
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze
from sarj_python_lint.rules.no_http_exception_in_services import NoHttpExceptionInServices


def _lines(source: str, path: str = "app/services/orders.py") -> list[int]:
    return [finding.line for finding in NoHttpExceptionInServices().check(Path(path), source)]


def test_documented_examples() -> None:
    verify_native_rule(NoHttpExceptionInServices, analyze)


@pytest.mark.parametrize(
    "source",
    [
        pytest.param("import fastapi\n\nraise fastapi.HTTPException(404)\n", id="module-attribute"),
        pytest.param("from starlette.exceptions import HTTPException as E\n\nraise E(404)\n", id="starlette-alias"),
        pytest.param("from fastapi import HTTPException\n\nraise HTTPException\n", id="bare-class"),
    ],
)
def test_reports_http_exception_raised_in_a_service(source: str) -> None:
    assert _lines(source) == [3]


@pytest.mark.parametrize(
    ("source", "path"),
    [
        pytest.param(
            "from fastapi import HTTPException\n\nraise HTTPException(404)\n", "app/routers/orders.py", id="router"
        ),
        pytest.param("from fastapi import HTTPException\n\nraise HTTPException(404)\n", "app/services.py", id="module"),
        pytest.param(
            "from fastapi import HTTPException\n\nraise HTTPException(404)\n",
            "tests/services/test_orders.py",
            id="test",
        ),
        pytest.param(
            "from errors import HTTPException\n\nraise HTTPException(404)\n", "app/services/orders.py", id="local"
        ),
        pytest.param(
            "from fastapi import HTTPException\n\ntry:\n    run()\nexcept HTTPException:\n    raise\n",
            "app/services/orders.py",
            id="re-raise",
        ),
    ],
)
def test_allows_other_layers_and_exceptions(source: str, path: str) -> None:
    assert _lines(source, path) == []
