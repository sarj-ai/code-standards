from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rules.no_implicit_attribute_access import NoImplicitAttributeAccess

if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic

_PROD = Path("svc/app/service.py")

def _check(source: str, path: Path = _PROD) -> list[Diagnostic]:
    return NoImplicitAttributeAccess().check(path, source)

@pytest.mark.parametrize(
    "source",
    [
        pytest.param("val = ctx.participant.attributes.get('sip.phoneNumber')\n", id="get-call"),
        pytest.param("val = event.payload.get('user_id')\n", id="payload-get"),
        pytest.param("val = event.meta['user_id']\n", id="meta-subscript"),
        pytest.param("val = ctx.attributes['foo']\n", id="attributes-subscript"),
        pytest.param("val = some_random_dict.get('price')\n", id="random-dict-get"),
        pytest.param("val = any_obj['price']\n", id="random-dict-subscript"),
    ],
)
def test_flags_implicit_access(source: str):
    diags = _check(source)
    assert len(diags) == 1
    assert diags[0].code == "SARJ055"
    assert "Pydantic" in diags[0].message

@pytest.mark.parametrize(
    "source",
    [
        pytest.param("val = attrs.sip_phone_number\n", id="explicit-property-access"),
        pytest.param("val = os.environ.get('foo')\n", id="environ-get"),
        pytest.param("val = headers['Authorization']\n", id="headers-subscript"),
        pytest.param("val = redis.get('my_key')\n", id="redis-get"),
        pytest.param("val = foo.get(dynamic_key)\n", id="dynamic-key-get"),
        pytest.param("val = foo[dynamic_key]\n", id="dynamic-key-subscript"),
    ],
)
def test_allows_valid_access(source: str):
    assert _check(source) == []

def test_exempt_paths():
    assert _check("val = event.payload.get('id')\n", Path("tests/test_something.py")) == []
