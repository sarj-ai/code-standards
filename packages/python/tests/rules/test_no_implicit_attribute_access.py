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
    assert diags[0].code == "SARJ083"
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


# --------------------------------------------------------------------------- #
# Deliberately NOT flagged                                                    #
# --------------------------------------------------------------------------- #
#
# This rule was 1,756 of 4,063 first-party findings (43.2%) -- by far the
# loudest in the registry -- and 63.5% of its own output was one of the three
# shapes below. Each guard is measured on two first-party repos, and together
# they take it to 641 findings whose survivors are the actual defect: reading
# fields out of a payload nobody parsed (`data.get("results")`,
# `fields["will_retry"]`).


@pytest.mark.parametrize(
    "source",
    [
        pytest.param('field_dict["response_body"] = response_body\n', id="store-subscript"),
        pytest.param('params["status"] = status.value\n', id="store-attr-value"),
        pytest.param('del payload["cursor"]\n', id="del-subscript"),
    ],
)
def test_writing_to_a_mapping_is_not_implicit_access(source: str):
    """Building a dict key by key is construction, not unparsed schema access.

    503 of 1,756 findings (28.6%) were assignment targets -- the single largest
    class. A Pydantic model does not replace `field_dict["x"] = x`; the defect
    this rule names is PLUCKING from a payload, and writing is its opposite.
    """
    assert _check(source) == []


@pytest.mark.parametrize(
    "source",
    [
        pytest.param('kind: Literal["voice-conversation"] = "voice-conversation"\n', id="literal"),
        pytest.param('role: Annotated[str, "the speaker"] = "user"\n', id="annotated"),
        pytest.param('x: Required["Thing"]\n', id="required"),
    ],
)
def test_type_subscripts_are_not_dictionary_access(source: str):
    """`Literal["user"]` is a type expression, not a lookup.

    470 of 1,756 findings (26.8%). The advice "parse declaratively with
    Pydantic" is nonsensical here -- the annotation already IS the declarative
    schema, and there is no dictionary involved at any point.
    """
    assert _check(source) == []


@pytest.mark.parametrize(
    "source",
    [
        pytest.param('@router.get("/available-events")\ndef handler():\n    pass\n', id="route-decorator"),
        pytest.param('resp = await self.http_client.get("/v1/agents")\n', id="http-path"),
        pytest.param('resp = requests.get("https://example.com/x")\n', id="absolute-url"),
    ],
)
def test_http_and_route_get_are_not_mapping_lookups(source: str):
    """`.get()` is also an HTTP verb and a route-registration decorator.

    168 of 1,756 findings (9.6%). The method name cannot distinguish them, but
    the ARGUMENT can: a route path or URL is not a dictionary key.
    """
    assert _check(source) == []


@pytest.mark.parametrize(
    "source",
    [
        pytest.param('results = data.get("results", [])\n', id="get-with-default"),
        pytest.param('started = chat_counts["transfer_started"]\n', id="read-subscript"),
        pytest.param('if fields["will_retry"]:\n    pass\n', id="read-in-condition"),
    ],
)
def test_reading_an_unparsed_payload_still_fires(source: str):
    """The surviving population -- the defect the rule actually exists for."""
    assert len(_check(source)) == 1
