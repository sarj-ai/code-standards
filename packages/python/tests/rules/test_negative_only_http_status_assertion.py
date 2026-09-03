from pathlib import Path
import textwrap

import pytest

from sarj_python_lint.rules.negative_only_http_status_assertion import (
    NegativeOnlyHttpStatusAssertion,
)


TEST_PATH = Path("tests/test_router.py")


def _check(source: str, path: Path = TEST_PATH):
    return NegativeOnlyHttpStatusAssertion().check(path, textwrap.dedent(source))


@pytest.mark.parametrize(
    "assertion",
    [
        "assert response.status_code != 500",
        "assert response.status_code != 503",
        "assert response.status_code != HTTPStatus.INTERNAL_SERVER_ERROR",
        "assert response.status_code != status.HTTP_503_SERVICE_UNAVAILABLE",
        "assert response.status_code != HTTP_502_BAD_GATEWAY",
        "assert 500 != response.status_code",
        "assert response.status_code < 500",
        "assert response.status_code <= 499",
        "assert response.status_code not in range(500, 600)",
        "assert response.status_code not in {500, 502, 503}",
        "assert response.status_code // 100 != 5",
        "assert not response.status_code == 500",
        "assert not response.status_code >= 500",
        "assert not 500 <= response.status_code < 600",
    ],
)
def test_flags_negative_only_status_contracts(assertion: str) -> None:
    source = (
        "from http import HTTPStatus\n"
        "from fastapi import status\n"
        "from starlette.status import HTTP_502_BAD_GATEWAY\n\n"
        f"def test_route(client):\n    response = client.get('/x')\n    {assertion}\n"
    )
    [diag] = _check(source)
    assert diag.code == "SARJ408"
    assert diag.line == 7


@pytest.mark.parametrize(
    "assertion",
    [
        "assert response.status_code == 200",
        "assert response.status_code == 401",
        "assert response.status_code in {200, 201}",
        "assert response.status_code != 404",
        "assert response.status_code != HTTPStatus.NOT_FOUND",
        "assert response.status_code != status.HTTP_404_NOT_FOUND",
        "assert response.status_code // 100 != 4",
        "assert result.status != 500",
        "assert response.status_code < 600",
        "assert response.status_code not in {400, 404}",
        "assert not 400 <= response.status_code < 500",
    ],
)
def test_allows_specific_or_non_http_contracts(assertion: str) -> None:
    source = (
        "from http import HTTPStatus\n"
        "from fastapi import status\n\n"
        f"def test_route():\n    {assertion}\n"
    )
    assert _check(source) == []


@pytest.mark.parametrize(
    "source",
    [
        (
            "class DomainStatus:\n    INTERNAL_SERVER_ERROR = 42\n\n"
            "def test_route():\n    assert response.status_code != DomainStatus.INTERNAL_SERVER_ERROR\n"
        ),
        "HTTP_500_OKAY = 42\n\ndef test_route():\n    assert response.status_code != HTTP_500_OKAY\n",
        "class Container:\n    def test_nested(self):\n        assert response.status_code != 500\n",
        "def helper():\n    def test_nested():\n        assert response.status_code != 500\n",
    ],
)
def test_ignores_unproven_constants_and_uncollected_test_shapes(source: str) -> None:
    assert _check(source) == []


@pytest.mark.parametrize(
    "source",
    [
        (
            "from http import HTTPStatus as Status\n\n"
            "def test_route():\n    assert response.status_code != Status.INTERNAL_SERVER_ERROR\n"
        ),
        (
            "from starlette import status as http_status\n\n"
            "def test_route():\n    assert response.status_code != http_status.HTTP_503_SERVICE_UNAVAILABLE\n"
        ),
        (
            "from rest_framework.status import HTTP_502_BAD_GATEWAY as BAD_GATEWAY\n\n"
            "def test_route():\n    assert response.status_code != BAD_GATEWAY\n"
        ),
        (
            "import fastapi.status as http_status\n\n"
            "def test_route():\n    assert response.status_code != http_status.HTTP_500_INTERNAL_SERVER_ERROR\n"
        ),
        (
            "class TestRoutes:\n"
            "    def test_route(self):\n        assert response.status_code != 500\n"
        ),
        (
            "from unittest import TestCase\n\n"
            "class Routes(TestCase):\n"
            "    def test_route(self):\n        assert response.status_code != 500\n"
        ),
    ],
)
def test_reports_proven_constants_and_collected_test_shapes(source: str) -> None:
    assert len(_check(source)) == 1


def test_shadowed_range_is_not_assumed_to_be_the_builtin() -> None:
    source = """
def test_route(range):
    assert response.status_code not in range(500, 600)
"""
    assert _check(source) == []


def test_skips_non_test_files_and_uncollected_helpers() -> None:
    source = "def test_route():\n    assert response.status_code != 500\n"
    assert _check(source, Path("src/router.py")) == []
    assert _check("def helper():\n    assert response.status_code != 500\n") == []


def test_does_not_attribute_a_nested_helper_assertion_to_the_test() -> None:
    source = """
    def test_route():
        def helper():
            assert response.status_code != 500
        helper()
        assert response.status_code == 200
    """
    assert _check(source) == []


def test_malformed_input_is_silent() -> None:
    assert _check("def test_broken(") == []


@pytest.mark.parametrize(
    ("path", "banner"),
    [
        (Path("tests/generated/test_router.py"), ""),
        (TEST_PATH, "# Code generated by route compiler. DO NOT EDIT.\n"),
    ],
)
def test_skips_generated_tests(path: Path, banner: str) -> None:
    source = f"{banner}def test_route():\n    assert response.status_code != 500\n"
    assert _check(source, path) == []
