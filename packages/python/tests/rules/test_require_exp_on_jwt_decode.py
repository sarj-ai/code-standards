from pathlib import Path

import pytest
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze
from sarj_python_lint.rules.require_exp_on_jwt_decode import RequireExpOnJwtDecode


def _lines(source: str, path: str = "auth.py") -> list[int]:
    return [finding.line for finding in RequireExpOnJwtDecode().check(Path(path), source)]


def test_documented_examples() -> None:
    verify_native_rule(RequireExpOnJwtDecode, analyze)


@pytest.mark.parametrize(
    "source",
    [
        pytest.param("import jwt\njwt.decode(token, key, 'HS256')\n", id="positional-algorithm"),
        pytest.param("import jwt\njwt.decode(token, key, algorithms=['HS256'], audience='a')\n", id="no-options"),
        pytest.param("import jwt\njwt.decode(token, key, options={'verify_exp': True})\n", id="no-require"),
        pytest.param("import jwt\njwt.decode(token, key, options={'require': ['iat']})\n", id="require-without-exp"),
        pytest.param("import jwt as pyjwt\npyjwt.decode_complete(token, key)\n", id="alias-complete"),
        pytest.param("from jwt import decode\ndecode(token, key)\n", id="from-import"),
        pytest.param("from jwt.api_jwt import decode\ndecode(token, key)\n", id="api-module"),
    ],
)
def test_reports_decode_without_required_exp(source: str) -> None:
    assert _lines(source) == [2]


@pytest.mark.parametrize(
    "source",
    [
        pytest.param("import jwt\njwt.decode(token, key, options={'require': ['exp', 'iat']})\n", id="required"),
        pytest.param("import jwt\njwt.decode(token, key, options={'require': ('exp',)})\n", id="tuple-required"),
        pytest.param("import jwt\njwt.decode(token, key, options=OPTIONS)\n", id="named-options"),
        pytest.param("import jwt\njwt.decode(token, key, options={'require': REQUIRED})\n", id="named-require"),
        pytest.param("import jwt\njwt.decode(token, key, options={**BASE})\n", id="spread-options"),
        pytest.param("import jwt\njwt.decode(token, key, **settings)\n", id="keyword-unpack"),
        pytest.param(
            "import jwt\njwt.decode(token, options={'verify_signature': False})\n", id="unverified-claims-read"
        ),
        pytest.param("from jose import jwt\njwt.decode(token, key)\n", id="python-jose"),
        pytest.param("import base64\nbase64.decode(token, key)\n", id="other-decode"),
        pytest.param("decode(token, key)\n", id="unresolved"),
    ],
)
def test_allows_required_exp_or_unresolved_calls(source: str) -> None:
    assert _lines(source) == []


def test_skips_test_modules() -> None:
    assert _lines("import jwt\njwt.decode(token, key)\n", path="tests/test_auth.py") == []
