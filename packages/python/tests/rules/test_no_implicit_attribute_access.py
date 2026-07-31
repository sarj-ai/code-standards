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
        pytest.param('@router.get("")\ndef handler():\n    pass\n', id="empty-route"),
        pytest.param('@app.get("", response_model=X)\nasync def h():\n    pass\n', id="empty-route-kwargs"),
    ],
)
def test_empty_route_decorator_is_not_a_mapping_lookup(source: str):
    """The router-root registration `@router.get("")` is still a decorator.

    The argument test above cannot see it -- `""` neither starts with `/` nor
    contains `://` -- so 23 findings across airflow, litellm and prefect landed
    on a decorator line. Position answers it exactly: nothing in `decorator_list`
    is a payload field read, so the guard costs no recall.
    """
    assert _check(source) == []


@pytest.mark.parametrize(
    "source",
    [
        pytest.param("val = request.meta['download_maxsize']\n", id="meta-subscript"),
        pytest.param("val = request.meta.get('proxy')\n", id="meta-get"),
    ],
)
def test_open_extension_bags_are_not_unparsed_payloads(source: str):
    """`meta` is a framework-guaranteed mapping with author-invented keys.

    Scrapy documents `Request.meta` as the per-request extension dict; the keys
    come from third-party middlewares, so no model can enumerate them.
    """
    assert _check(source) == []


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(
            "from litellm.types import AllMessageValues\n"
            "def f(msg: AllMessageValues):\n"
            "    return msg.get('tool_calls')\n",
            id="imported-typeddict-get",
        ),
        pytest.param(
            "from openai.types import ChatCompletionFileObject\n"
            "def f(part: ChatCompletionFileObject):\n"
            "    return part['file']\n",
            id="imported-typeddict-subscript",
        ),
    ],
)
def test_imported_declared_types_are_already_declarative(source: str):
    """A receiver typed with an IMPORTED name has been given a schema already.

    `_typed_dict_class_names` only ever saw `class X(TypedDict)` written in the
    SAME file, so every cross-module TypedDict was invisible and its subscripts
    -- the declarative form for a TypedDict -- were reported as the absence of a
    schema. `litellm/…/prompt_templates/factory.py:2080` and `:3216` are the
    measured shape.
    """
    assert _check(source) == []


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(
            "from typing import Any\ndef f(payload: Any):\n    return payload['id']\n",
            id="typing-any-declares-nothing",
        ),
        pytest.param("def f(payload: dict):\n    return payload['id']\n", id="bare-dict"),
    ],
)
def test_structureless_annotations_still_fire(source: str):
    """`Any` and `dict` are not schemas, so the guard above must not reach them."""
    diags = _check(source)
    assert len(diags) == 1
    assert diags[0].code == "SARJ083"


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


# --------------------------------------------------------------------------- #
# The five classes found by the 19-repo re-read (24% FP over 48,024 findings). #
# Each pair is one `valid` case that used to fire and one `invalid` case at    #
# the guard's boundary, so the guard cannot widen without a test noticing.     #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "source",
    [
        pytest.param('def f(router: Optional["Router"] = None) -> None:\n    pass\n', id="param-forward-ref"),
        pytest.param('def f() -> Optional["Router"]:\n    pass\n', id="return-forward-ref"),
        pytest.param('handlers: Dict[str, Type["Handler"]] = {}\n', id="annassign-forward-ref"),
        pytest.param('def f(items: List["Thing"]) -> None:\n    pass\n', id="list-forward-ref"),
    ],
)
def test_a_string_forward_reference_in_an_annotation_is_not_a_lookup(source: str):
    """`Optional["Router"]` is a `Subscript` over a `Constant`, and nothing else.

    `_TYPE_SUBSCRIPTS` only catches the wrappers whose own name gives them away;
    a forward reference is written with an ordinary generic. 1,666 of 48,024
    (3.5%). The guard is positional, so it costs exactly zero recall -- an
    annotation is never evaluated as a mapping lookup.
    """
    assert _check(source) == []


def test_a_lookup_beside_an_annotation_still_fires():
    """The boundary: the guard is the annotation SUBTREE, not the statement."""
    assert len(_check('def f(router: Optional["Router"] = None) -> None:\n    x = payload["user_id"]\n')) == 1


def test_a_typed_dict_receiver_is_already_the_declarative_access():
    """A TypedDict key is checked by the type checker, so the remedy is taken.

    This is the shape of `pydantic/docs/plugins/algolia.py:166`, where the rule
    told Pydantic's own docs tooling to use a declarative model instead of the
    declarative model it was already using. 3,018 of 48,024 (6.3%), of which the
    same-file half -- all this AST can resolve -- is 499.
    """
    source = (
        "class AlgoliaRecord(TypedDict):\n"
        "    title: str\n"
        "\n"
        "def emit(record: AlgoliaRecord) -> str:\n"
        '    return record["title"]\n'
    )
    assert _check(source) == []


def test_a_receiver_typed_as_a_plain_mapping_still_fires():
    """The boundary: `dict[str, Any]` is the unparsed payload, not a schema."""
    source = "def emit(record: dict[str, Any]) -> str:\n    return record['title']\n"
    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    "source",
    [
        pytest.param('errors["attributes"].append(error)\n', id="defaultdict-append"),
        pytest.param('buckets["ready"].add(item)\n', id="set-add"),
        pytest.param('index["by_id"].update(rows)\n', id="dict-update"),
        pytest.param('counts["retries"] += 1\n', id="augmented-assignment"),
    ],
)
def test_building_a_collection_in_place_is_not_plucking(source: str):
    """`Store` targets are already exempt; these are the `Load`-context spellings.

    `errors["attributes"].append(x)` on a `defaultdict(list)` is the same
    construction the write guard exempts, written as a method call. 324 of
    48,024 (0.7%). The augmented-assignment case needs no guard of its own --
    CPython gives an `AugAssign` target `ctx=Store()`.
    """
    assert _check(source) == []


def test_reading_a_field_and_then_calling_a_method_on_it_still_fires():
    """The boundary: `.strip()` is not a collection mutator."""
    assert len(_check('name = payload["user_name"].strip()\n')) == 1


def test_configparser_section_option_get_is_not_a_mapping_lookup():
    """`conf.get("api", "ssl_cert", fallback="")` is `ConfigParser.get(section, option)`.

    `dict.get` has no `fallback` parameter, so the keyword identifies the call
    exactly rather than guessing from the receiver's name. 178 of 48,024 (0.4%),
    0 first-party.
    """
    assert _check('secure = bool(conf.get("api", "ssl_cert", fallback=""))\n') == []


def test_a_two_argument_get_without_fallback_still_fires():
    """The boundary: `data.get("key", "default")` is the ordinary `dict.get`."""
    assert len(_check('value = data.get("api", "default")\n')) == 1


def test_a_constant_lookup_table_declared_in_this_file_is_not_a_payload():
    """A literal table IS the schema; there is no boundary and nothing to parse.

    `zulip/zerver/models/realms.py:722` reads a table declared 29 lines above it
    in the same class body. 118 of 48,024 (0.2%), 0 first-party.
    """
    source = 'GIF_RATING_POLICY_OPTIONS = {"g": {"id": 1}}\ndefault = GIF_RATING_POLICY_OPTIONS["g"]["id"]\n'
    assert _check(source) == []


@pytest.mark.parametrize(
    "source",
    [
        pytest.param('default = RESOURCE_MAP["dag"]["prefix"]\n', id="imported-not-declared-here"),
        pytest.param('options = {"g": {"id": 1}}\nx = options["g"]["id"]\n', id="not-screaming-case"),
        pytest.param('TABLE = load_table()\nx = TABLE["g"]\n', id="not-a-literal"),
    ],
)
def test_a_table_that_is_not_a_local_literal_still_fires(source: str):
    """The boundary: all three conditions carry weight.

    The SCREAMING_CASE test alone would be 253 of 48,024 rather than 118, and
    the 135 it adds are constants imported from elsewhere or built by a call --
    neither of which this file can see the shape of.
    """
    assert _check(source)


@pytest.mark.parametrize(
    "source",
    [
        pytest.param('name = frame.f_globals["__name__"]\n', id="frame-globals"),
        pytest.param('mod = f_locals["__module__"]\n', id="frame-locals"),
        pytest.param('cls = globals()["Handler"]\n', id="globals-call"),
        pytest.param('ret = get_type_hints(fn).get("return", Any)\n', id="type-hints"),
    ],
)
def test_language_reflection_namespaces_are_not_payloads(source: str):
    """CPython defines these keys; no Pydantic model replaces `__name__`.

    54 dunder keys plus 16 reflection receivers, of 48,024 (0.1%), 0
    first-party. Recall cost zero.
    """
    assert _check(source) == []


def test_a_dunder_like_key_on_an_ordinary_payload_is_still_a_reflection_key():
    """The boundary: the dunder arm keys on the KEY, and a payload key is not one."""
    assert len(_check('value = payload["user__id"]\n')) == 1
