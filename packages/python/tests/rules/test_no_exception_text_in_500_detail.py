from pathlib import Path

import pytest
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze
from sarj_python_lint.rules.no_exception_text_in_500_detail import NoExceptionTextIn500Detail


_HEADER = "import traceback\nfrom http import HTTPStatus\n\nfrom fastapi import HTTPException, status\n\n\n"


def _lines(raise_line: str, path: str = "api.py") -> list[int]:
    source = f"{_HEADER}def load(store):\n    try:\n        store.load()\n    except Exception as exc:\n        {raise_line}\n"
    return [finding.line for finding in NoExceptionTextIn500Detail().check(Path(path), source)]


def test_documented_examples() -> None:
    verify_native_rule(NoExceptionTextIn500Detail, analyze)


@pytest.mark.parametrize(
    "raise_line",
    [
        pytest.param("raise HTTPException(status_code=500, detail=str(exc))", id="str"),
        pytest.param("raise HTTPException(500, f'failed: {exc!r}')", id="positional-fstring"),
        pytest.param("raise HTTPException(status_code=500, detail=repr(exc))", id="repr"),
        pytest.param("raise HTTPException(status_code=500, detail='failed: ' + str(exc))", id="concat"),
        pytest.param("raise HTTPException(status_code=500, detail={'error': str(exc)})", id="mapping"),
        pytest.param(
            "raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))", id="starlette"
        ),
        pytest.param(
            "raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=str(exc))", id="http-status"
        ),
        pytest.param("raise HTTPException(status_code=500, detail=traceback.format_exc())", id="traceback"),
        pytest.param("raise HTTPException(status_code=500, detail=f'in {__file__}')", id="source-path"),
    ],
)
def test_reports_leaking_server_error_detail(raise_line: str) -> None:
    assert _lines(raise_line) == [11]


@pytest.mark.parametrize(
    "raise_line",
    [
        pytest.param("raise HTTPException(status_code=500, detail='load failed') from exc", id="fixed"),
        pytest.param("raise HTTPException(status_code=404, detail=str(exc))", id="not-found"),
        pytest.param("raise HTTPException(status_code=500, detail=exc.code)", id="attribute"),
        pytest.param("raise HTTPException(status_code=code, detail=str(exc))", id="dynamic-status"),
        pytest.param("raise HTTPException(status_code=500, detail=str(other))", id="unbound-name"),
        pytest.param("raise RuntimeError(500, str(exc))", id="other-exception"),
    ],
)
def test_allows_fixed_or_non_server_details(raise_line: str) -> None:
    assert _lines(raise_line) == []


def test_skips_test_modules() -> None:
    assert _lines("raise HTTPException(status_code=500, detail=str(exc))", path="tests/test_api.py") == []


def test_allows_exception_class_name() -> None:
    assert _lines("raise HTTPException(status_code=500, detail=type(exc).__name__)") == []
