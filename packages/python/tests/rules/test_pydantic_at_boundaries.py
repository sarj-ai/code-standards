from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rules.pydantic_at_boundaries import PydanticAtBoundaries


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic, RuleExample


_PUBLIC_EXAMPLES = PydanticAtBoundaries.public_examples()


def _check(source: str, path: str = "svc.py") -> list[Diagnostic]:
    typed_source = (
        f"{source}\nfrom typing import Annotated, Any, Dict, List, Optional, Union, overload\nimport typing\n"
    )
    return PydanticAtBoundaries().check(Path(path), typed_source)


@pytest.mark.parametrize(
    "example",
    _PUBLIC_EXAMPLES,
    ids=tuple(example.example_id for example in _PUBLIC_EXAMPLES),
)
def test_public_documentation_examples_are_executable(example: RuleExample) -> None:
    focus = example.focus_file

    findings = PydanticAtBoundaries().check(Path(focus.path), focus.source)

    assert len(findings) == example.expected_count


def test_flags_dict_str_any_return():
    src = """
from typing import Any

def build_payload(call) -> dict[str, Any]:
    return {"id": call.id}
"""
    diags = _check(src)
    assert len(diags) == 1
    assert "dict[str, Any]" in diags[0].message
    assert "TypedDict" in diags[0].message
    assert diags[0].code == "SARJ008"


def test_flags_dict_str_object_return():
    src = "def f() -> dict[str, object]:\n    return {'id': 1}\n"
    assert len(_check(src)) == 1


def test_flags_bare_dict_and_typing_dict():
    src = """
from typing import Dict

def f() -> dict:
    return {'id': 1}

def g() -> Dict:
    return {'id': 1}

def h() -> Dict[str, Any]:
    return {'id': 1}
"""
    assert len(_check(src)) == 3


def test_flags_list_of_untyped_dict():
    src = "def f() -> list[dict[str, Any]]:\n    return [{'id': 1}]\n"
    assert len(_check(src)) == 1


def test_flags_optional_untyped_dict():
    src = """
from typing import Any, Optional

def f() -> dict[str, Any] | None:
    return {"id": 1}

def g() -> Optional[dict[str, Any]]:
    return {"id": 1}
"""
    assert len(_check(src)) == 2


def test_flags_async_def():
    src = "async def f() -> dict[str, Any]:\n    return {'id': 1}\n"
    assert len(_check(src)) == 1


def test_flags_method_in_class():
    src = """
class CallService:
    def summarize(self) -> dict[str, Any]:
        return {'id': 1}
"""
    assert len(_check(src)) == 1


def test_skips_private_function():
    src = "def _build() -> dict[str, Any]:\n    return {'id': 1}\n"
    assert _check(src) == []


def test_skips_pydantic_validator_hooks():
    src = """
from typing import Any
from pydantic import model_validator, field_validator

class M:
    @model_validator(mode="before")
    @classmethod
    def normalize(cls, data) -> dict[str, Any]:
        return {"id": 1}

    @field_validator("x")
    def coerce(cls, v) -> dict[str, Any]:
        return {"id": 1}
"""
    assert _check(src) == []


def test_allows_concrete_dict_value_types():
    src = """
def f() -> dict[str, str]:
    return {'id': 1}

def g() -> dict[str, int]:
    return {'id': 1}

def h() -> dict[str, list[int]]:
    return {'id': 1}
"""
    assert _check(src) == []


def test_allows_typed_returns():
    src = """
def f() -> CallPayload: ...
def g() -> str: ...
def h() -> None: ...
def i() -> list[CallPayload]: ...
"""
    assert _check(src) == []


def test_allows_heterogeneous_tuple_return():
    src = "def stop_call() -> tuple[bool, str | None]:\n    return True, None\n"
    assert _check(src) == []


def test_allows_typing_tuple_heterogeneous():
    src = """
from typing import Tuple

def f() -> Tuple[int, str]:
    return 1, "x"
"""
    assert _check(src) == []


def test_allows_homogeneous_tuples():
    src = """
def f() -> tuple[int, ...]:
    return ()

def g() -> tuple[str, str]:
    return "a", "b"

def h() -> tuple[int]:
    return (1,)
"""
    assert _check(src) == []


def test_allows_private_function_returning_tuple():
    src = "def _split() -> tuple[bool, str | None]:\n    return True, None\n"
    assert _check(src) == []


def test_does_not_guess_fastapi_route_from_decorator_name():
    src = """
@router.get("/calls/{call_id}")
async def get_call(call_id: str):
    return {"id": call_id}
"""
    assert _check(src) == []


def test_unannotated_decorator_like_function_is_out_of_scope():
    src = """
@app.post("/calls")
def create_call(body: CreateCallRequest):
    return {"ok": True}
"""
    assert _check(src) == []


def test_flags_route_returning_untyped_dict():
    src = """
@router.get("/health")
async def health() -> dict[str, Any]:
    return {"status": "ok"}
"""
    assert len(_check(src)) == 1


def test_allows_route_with_pydantic_return_annotation():
    src = """
@router.get("/calls/{call_id}")
async def get_call(call_id: str) -> CallResponse:
    return {"id": call_id}
"""
    assert _check(src) == []


def test_allows_route_with_response_model_kwarg():
    src = """
@router.get("/calls/{call_id}", response_model=CallResponse)
async def get_call(call_id: str):
    return {"id": call_id}
"""
    assert _check(src) == []


def test_ignores_non_router_receivers():
    src = """
@client.get("/upstream")
def fetch_upstream():
    return {'id': 1}

@retry.post()
def push():
    return {'id': 1}
"""
    assert _check(src) == []


def test_named_router_receiver_is_not_inferred_without_provenance():
    src = """
@admin_router.delete("/orgs/{org_id}")
async def delete_org(org_id: str):
    return {"ok": True}
"""
    assert _check(src) == []


def test_skips_test_files():
    src = "def f() -> dict[str, Any]:\n    return {'id': 1}\n"
    assert _check(src, path="test_calls.py") == []
    assert _check(src, path="python/app/tests/helpers.py") == []


def test_skips_overload_stubs():
    src = """
from typing import overload, Any

@overload
def f(x: int) -> dict[str, Any]: ...

@typing.overload
def f(x: str) -> dict[str, Any]: ...

def f(x) -> Payload:
    return Payload()
"""
    assert _check(src) == []


def test_plain_function_without_annotation_not_flagged():
    src = "def helper(x):\n    return x\n"
    assert _check(src) == []


def test_syntax_error_returns_empty():
    assert _check("def f(:\n") == []


# ADDED COVERAGE


_FLAGGED_DICT_ANNOTATIONS = [
    "dict[str, Any]",
    "dict[str, object]",
    "dict[str, Any] | None",
    "None | dict[str, Any]",
    "Optional[dict[str, Any]]",
    "typing.Optional[dict[str, Any]]",
    "Union[dict[str, Any], None]",
    "Union[str, dict[str, Any]]",
    "Union[dict[str, Any]]",
    "typing.Union[dict[str, Any], None]",
    "dict",
    "Dict",
    "Dict[str, Any]",
    "typing.Dict",
    "typing.Dict[str, Any]",
    "typing.Dict[str, object]",
    "list[dict[str, Any]]",
    "list[dict[str, object]]",
    "List[dict[str, Any]]",
    "list[list[dict[str, Any]]]",
    "list[dict[str, Any]] | None",
    "Optional[list[dict[str, Any]]]",
    "dict[str, Any] | str | None",
    "dict[str, Any] | ErrorPayload",
]


@pytest.mark.parametrize("ann", _FLAGGED_DICT_ANNOTATIONS)
def test_flagged_dict_annotations(ann: str):
    diags = _check(f"import typing\ndef f() -> {ann}:\n    return {{'id': 1}}\n")
    assert len(diags) == 1, ann
    assert diags[0].code == "SARJ008"
    assert "Pydantic model" in diags[0].message


_ALLOWED_ANNOTATIONS = [
    "str",
    "int",
    "None",
    "bool",
    "CallPayload",
    "Any",  # bare `Any` in return position is not a dict
    "object",
    "dict[str, str]",
    "dict[str, int]",
    "dict[str, CallId]",
    "dict[str, list[int]]",
    "dict[CallId, Call]",
    # Non-str keys make a MAPPING (a data structure), not an unnamed record —
    # minimized from pydantic's `get_standard_typevars_map` / `deep_update`.
    "dict[int, Any]",
    "dict[TypeVar, Any]",
    "dict[KeyType, Any]",
    "dict[type, object]",
    "dict[str, dict[str, Any]]",  # inner Any-dict as VALUE is not detected
    "dict[str, Any | None]",  # union value is not `Any`/`object`
    "dict[str]",  # single subscript arg — not `dict[K, V]`
    "dict[str, Any, Any]",  # three args — not `dict[K, V]`
    "Mapping[str, Any]",  # not `dict`/`Dict`
    "MutableMapping[str, Any]",
    "list[str]",
    "list[CallPayload]",
    "list[dict[str, str]]",  # list of concrete dict is fine
    "set[dict[str, Any]]",  # only `list[...]` is unwrapped
    "frozenset[dict[str, Any]]",
    "tuple[bool, str | None]",
    "tuple[int, ...]",
    "tuple[dict[str, Any], int]",  # dict INSIDE a tuple is not flagged
    "Tuple[int, str]",
    "MyTypedDict",  # a named TypedDict is a real type, not raw dict
    "Optional[str]",
    "Union[str, int]",
    "make_type()",  # call expression in annotation position
]


@pytest.mark.parametrize("ann", _ALLOWED_ANNOTATIONS)
def test_allowed_annotations(ann: str):
    assert _check(f'def f() -> {ann}:\n    return {{"id": 1}}\n') == [], ann


def test_flags_string_forward_ref_dict():
    assert len(_check('def f() -> "dict[str, Any]":\n    return {"id": 1}\n')) == 1


def test_flags_string_forward_ref_nested_list_dict():
    assert len(_check('def f() -> "list[dict[str, Any]]":\n    return [{"id": 1}]\n')) == 1


def test_allows_string_forward_ref_concrete():
    assert _check('def f() -> "tuple[bool, str]":\n    return True, "x"\n') == []
    assert _check('def f() -> "CallPayload":\n    return {"id": 1}\n') == []


def test_string_forward_ref_with_syntax_error_not_flagged():
    assert _check('def f() -> "dict[":\n    return {"id": 1}\n') == []


_VALIDATOR_DECORATORS = [
    '@model_validator(mode="before")',
    "@model_validator",
    '@field_validator("x")',
    "@field_validator",
    '@validator("x")',
    "@root_validator",
    "@root_validator(pre=True)",
    '@pydantic.field_validator("x")',
    "@pydantic.model_validator(mode='after')",
]


@pytest.mark.parametrize("dec", _VALIDATOR_DECORATORS)
def test_validator_hooks_never_flagged(dec: str):
    src = (
        "import pydantic\n"
        "from pydantic import field_validator, model_validator, root_validator, validator\n"
        f"class M:\n    {dec}\n    def v(cls, value) -> dict[str, Any]:\n        return {{'id': 1}}\n"
    )
    assert _check(src) == [], dec


@pytest.mark.parametrize("dec", ["@overload", "@typing.overload", "@t.overload"])
def test_overload_variants_never_flagged(dec: str):
    src = f"{dec}\ndef f(x) -> dict[str, Any]: ...\n"
    assert _check(src) == [], dec


@pytest.mark.parametrize("method", ["get", "post", "put", "patch", "delete"])
@pytest.mark.parametrize("receiver", ["app", "router", "admin_router", "v1_router"])
def test_decorator_names_do_not_create_route_ownership(method: str, receiver: str):
    src = f'@{receiver}.{method}("/x")\ndef handler():\n    return {{"id": 1}}\n'
    assert _check(src) == [], (method, receiver)


@pytest.mark.parametrize("method", ["get", "post", "put", "patch", "delete"])
def test_route_methods_allowed_with_return_annotation(method: str):
    src = f'@router.{method}("/x")\ndef handler() -> CallResponse:\n    return {{"id": 1}}\n'
    assert _check(src) == [], method


def test_route_with_response_model_but_dict_annotation_still_flagged():
    src = """
@router.get("/x", response_model=X)
def f() -> dict[str, Any]:
    return {'id': 1}
"""
    diags = _check(src)
    assert len(diags) == 1
    assert "Pydantic model" in diags[0].message


def test_route_websocket_method_not_flagged():
    src = '@router.websocket("/ws")\ndef f():\n    return {"id": 1}\n'
    assert _check(src) == []


def test_route_decorator_must_be_a_call():
    src = "@router.get\ndef f():\n    return {'id': 1}\n"
    assert _check(src) == []


def test_bare_name_call_decorator_not_a_route():
    src = '@get("/x")\ndef f():\n    return {"id": 1}\n'
    assert _check(src) == []


def test_deeply_attributed_receiver_not_a_route():
    src = '@v1.router.get("/x")\ndef f():\n    return {"id": 1}\n'
    assert _check(src) == []


def test_private_route_handler_not_flagged():
    src = '@router.get("/x")\ndef _internal():\n    return {"id": 1}\n'
    assert _check(src) == []


def test_route_returning_none_annotation_not_flagged():
    src = '@router.post("/x")\ndef f() -> None:\n    return {"id": 1}\n'
    assert _check(src) == []


def test_plain_missing_annotation_not_flagged():
    src = "def f():\n    return {'id': 1}\n"
    assert _check(src) == []


def test_non_route_call_decorator_missing_annotation_not_flagged():
    src = "@lru_cache()\ndef f():\n    return {'id': 1}\n"
    assert _check(src) == []


def test_non_route_call_decorator_with_dict_still_flagged():
    src = "@lru_cache()\ndef f() -> dict[str, Any]:\n    return {'id': 1}\n"
    assert len(_check(src)) == 1


def test_property_returning_dict_flagged():
    src = "class C:\n    @property\n    def data(self) -> dict[str, Any]:\n        return {'id': 1}\n"
    assert len(_check(src)) == 1


def test_reports_line_and_col_for_top_level_function():
    src = "\n\ndef f() -> dict[str, Any]:\n    return {'id': 1}\n"
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].line == 3
    assert diags[0].col == 1


def test_reports_line_and_col_for_indented_method():
    src = "class C:\n    def m(self) -> dict[str, Any]:\n        return {'id': 1}\n"
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].line == 2
    assert diags[0].col == 5


def test_reports_decorated_function_line():
    src = '\n@cache\ndef handler() -> dict[str, Any]:\n    return {"id": 1}\n'
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].line == 3


def test_multiple_top_level_functions_in_source_order():
    src = """
def a() -> dict[str, Any]:
    return {'id': 1}

def b() -> dict[str, Any]:
    return {'id': 1}

def c() -> dict[str, Any]:
    return {'id': 1}
"""
    diags = _check(src)
    assert [d.line for d in diags] == [2, 5, 8]
    assert [d.message.split("`")[1] for d in diags] == ["a", "b", "c"]


def test_only_the_outer_function_is_flagged():
    src = """
def outer() -> dict[str, Any]:
    def inner() -> dict[str, Any]:
        return {'id': 1}
    return {'id': 1}
"""
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].message.split("`")[1] == "outer"


def test_public_nested_in_private_not_flagged():
    src = """
def _outer():
    def inner() -> dict[str, Any]:
        return {'id': 1}
    return inner
"""
    assert _check(src) == []


def test_findings_are_sorted_by_source_location():
    src = """
class C:
    def a(self) -> dict[str, Any]:
        return {'id': 1}

def b() -> dict[str, Any]:
    return {'id': 1}
"""
    diags = _check(src)
    assert [d.line for d in diags] == [3, 6]


def test_dict_message_includes_function_name_and_annotation():
    diags = _check("def build_payload() -> dict[str, Any]:\n    return {'id': 1}\n")
    assert len(diags) == 1
    msg = diags[0].message
    assert "build_payload" in msg
    assert "dict[str, Any]" in msg
    assert "Pydantic model" in msg


def test_message_leads_with_typed_dict_remediation():
    diags = _check('def get_call() -> dict[str, Any]:\n    return {"id": 1}\n')
    assert len(diags) == 1
    msg = diags[0].message
    assert "get_call" in msg
    assert "TypedDict" in msg


@pytest.mark.parametrize(
    "src",
    [
        "",
        "\n\n",
        "# just a comment\n",
        '"""module docstring only"""\n',
        "x = 1\n",
        "class C:\n    pass\n",
        "import os\n",
    ],
)
def test_sources_with_no_boundary_functions_return_empty(src: str):
    assert _check(src) == []


@pytest.mark.parametrize(
    "src",
    [
        "def f(:\n",
        "def f() ->\n",
        "class C\n    pass\n",
        "@\ndef f() -> dict[str, Any]:\n    return {'id': 1}\n",
        "def f() -> dict[str, Any]\n    return {'id': 1}\n",
    ],
)
def test_syntax_errors_return_empty(src: str):
    assert _check(src) == []


@pytest.mark.parametrize(
    "path",
    [
        "test_calls.py",
        "tests/test_calls.py",
        "python/app/tests/helpers.py",
        "a/tests/b/c.py",
        "tests/conftest.py",
        "service_test.py",
        "conftest.py",
    ],
)
def test_test_paths_are_skipped(path: str):
    src = "def f() -> dict[str, Any]:\n    return {'id': 1}\n"
    assert _check(src, path=path) == []


@pytest.mark.parametrize(
    "path",
    [
        "svc.py",
        "src/my_tests_helper.py",  # `tests` is a substring, not a path part
    ],
)
def test_non_test_paths_are_still_linted(path: str):
    src = "def f() -> dict[str, Any]:\n    return {'id': 1}\n"
    assert len(_check(src, path=path)) == 1, path


# ADVERSARIAL EDGE-CASE HUNT (new)


def test_flags_builtins_dict_subscript():
    src = "import builtins\ndef f() -> builtins.dict[str, Any]:\n    return {'id': 1}\n"
    assert len(_check(src)) == 1


def test_flags_builtins_dict_bare():
    src = "import builtins\ndef f() -> builtins.dict:\n    return {'id': 1}\n"
    assert len(_check(src)) == 1


def test_flags_list_of_bare_dict():
    assert len(_check("def f() -> list[dict]:\n    return [{'id': 1}]\n")) == 1


def test_flags_union_with_nested_optional_dict():
    src = """
from typing import Union, Optional, Any

def f() -> Union[str, Optional[dict[str, Any]]]:
    return {"id": 1}
"""
    assert len(_check(src)) == 1


def test_flags_forward_ref_with_leading_newline():
    assert len(_check('def f() -> "\\ndict[str, Any]":\n    return {"id": 1}\n')) == 1


def test_flags_implicitly_concatenated_string_annotation():
    assert len(_check('def f() -> "dict[str, " "Any]":\n    return {"id": 1}\n')) == 1


def test_allows_dict_with_bare_dict_value():
    assert _check("def f() -> dict[str, dict]:\n    return {'id': 1}\n") == []


def test_allows_sequence_of_untyped_dict():
    src = "from collections.abc import Sequence\ndef f() -> Sequence[dict[str, Any]]:\n    return [{'id': 1}]\n"
    assert _check(src) == []


def test_allows_kwargs_any_without_return_annotation():
    assert _check("def f(**kwargs: Any):\n    return {'id': 1}\n") == []


def test_allows_type_alias_return_pure_annotation_limitation():
    src = "type Payload = dict[str, Any]\ndef f() -> Payload:\n    return {'id': 1}\n"
    assert _check(src) == []


def test_annotated_dict_return_should_be_flagged():
    src = 'from typing import Annotated, Any\ndef f() -> Annotated[dict[str, Any], "meta"]:\n    return {"id": 1}\n'
    assert len(_check(src)) == 1


def test_forward_ref_with_leading_space_should_be_flagged():
    assert len(_check('def f() -> " dict[str, Any]":\n    return {"id": 1}\n')) == 1


def test_dict_with_string_forward_ref_any_value_should_be_flagged():
    assert len(_check('def f() -> dict[str, "Any"]:\n    return {"id": 1}\n')) == 1


def test_pytest_fixture_returning_dict_is_false_positive():
    src = "import pytest\n@pytest.fixture\ndef sample() -> dict[str, Any]:\n    return {'id': 1}\n"
    assert _check(src) == []


# CORPUS SWEEP: 413 findings over fastapi / pydantic / black / sqlmodel /
# rich / flask / httpx / requests / anyio (2,657 files).


_OPAQUE_MAPPING_BODIES = [
    # `black/src/black/files.py:130` (parse_pyproject_toml), `pydantic/mypy.py:1433`.
    "return tomllib.load(f)",
    # `fastapi/scripts/sponsors.py:92`, `pydantic/.github/.../people.py:358`.
    "return response.json()",
    # `sqlmodel/_compat.py:100`, `pydantic/_internal/_typing_extra.py:287`.
    "return getattr(obj, '__annotations__', {})",
    # `pydantic/_internal/_typing_extra.py:205` (parent_frame_namespace).
    "return frame.f_locals",
    # `pydantic/json_schema.py:2547`, `fastapi/openapi/utils.py:529`.
    "return generator.generate(schema)",
    # `pydantic/mypy.py:1272` (get_values_dict) — comprehension keys are dynamic.
    "return {k: v for k, v in self.__dict__.items()}",
    # `flask/src/flask/json/tag.py:87` (tag) — the key is a runtime value.
    "return {self.key: value}",
    # `flask/src/flask/config.py:323` (get_namespace) — `{}` then filled.
    "return {}",
    # A merge of mappings the function did not author.
    "return {**base, **overrides}",
    # A dynamic key means the returned mapping is not fixed-shape.
    "return {'id': ident, key: value}",
]


@pytest.mark.parametrize("body", _OPAQUE_MAPPING_BODIES)
def test_opaque_mapping_returns_are_not_records(body: str):
    assert _check(f"def f() -> dict[str, Any]:\n    {body}\n") == [], body


_RECORD_BODIES = [
    # `requests/src/requests/help.py:67` (info), `flask/examples/celery/.../views.py:22`.
    "return {'ready': ready, 'value': value}",
    "rv: dict[str, Any] = {'app': app}\n    return rv",
    # `list[dict[str, Any]]` shapes.
    "return [{'id': 1}]",
    "return [{'id': row.id} for row in rows]",
    # One opaque branch does not excuse the record branch.
    "if x:\n        return other.copy()\n    return {'id': 1}",
]


@pytest.mark.parametrize("body", _RECORD_BODIES)
def test_in_place_records_are_flagged(body: str):
    assert len(_check(f"def f() -> dict[str, Any]:\n    {body}\n")) == 1, body


@pytest.mark.parametrize(
    "body",
    [
        "entry = {'id': ident}\n    entry['service'] = service\n    return entry",
        "entry = {'id': ident}\n    entry.update(extra)\n    return entry",
        "entry = {'id': ident}\n    entry |= extra\n    return entry",
        "entry = {'id': ident}\n    entry = enrich(entry)\n    return entry",
    ],
)
def test_mutated_or_rebound_record_names_are_not_fixed_shapes(body: str) -> None:
    assert _check(f"def f() -> dict[str, Any]:\n    {body}\n") == []


def test_untouched_record_name_is_still_flagged() -> None:
    src = "def f() -> dict[str, Any]:\n    entry = {'id': ident}\n    return entry\n"
    assert len(_check(src)) == 1


def test_dynamic_returned_accumulator_makes_literal_fallback_open_shaped() -> None:
    src = """
def run_hook() -> dict[str, Any]:
    result = {"rc": 0}
    if remote:
        result[remote.key] = remote.value
    if failed:
        return {"rc": 1}
    return result
"""
    assert _check(src) == []


def test_stub_body_is_not_flagged_known_limitation():
    assert _check("def data(self) -> dict[str, Any]: ...\n") == []


def test_record_built_by_a_nested_function_does_not_count():
    src = """
def outer() -> dict[str, Any]:
    def make():
        return {"id": 1}
    return cache.load()
"""
    assert _check(src) == []


def test_record_assigned_but_not_returned_does_not_count():
    src = """
def f() -> dict[str, Any]:
    seed = {"id": 1}
    return transform(seed)
"""
    assert _check(src) == []


def test_closure_returning_record_not_flagged():
    src = """
class ASGITransport:
    async def handle(self):
        async def receive() -> dict[str, Any]:
            return {"type": "http.request", "more_body": False}
        return receive
"""
    assert _check(src) == []


def test_method_of_class_defined_inside_a_function_not_flagged():
    src = """
def factory():
    class Inner:
        def payload(self) -> dict[str, Any]:
            return {"id": 1}
    return Inner
"""
    assert _check(src) == []


def test_module_level_class_method_is_still_a_boundary():
    src = """
class Service:
    def payload(self) -> dict[str, Any]:
        return {"id": 1}
"""
    assert len(_check(src)) == 1


@pytest.mark.parametrize(
    "name",
    ["asdict", "as_dict", "dict", "model_dump", "to_data", "to_dict"],
)
def test_dict_conversion_methods_not_flagged(name: str):
    src = f"def {name}(self) -> dict[str, Any]:\n    return {{'id': self.id}}\n"
    assert _check(src) == [], name


def test_patterned_dict_conversion_method_not_flagged() -> None:
    src = "def to_import_dict(self) -> dict[str, Any]:\n    return {'id': self.id}\n"
    assert _check(src) == []


@pytest.mark.parametrize("name", ["to_dictionary", "build_dict", "dict_for", "as_dict_of"])
def test_names_merely_containing_dict_are_still_flagged(name: str):
    src = f"def {name}(self) -> dict[str, Any]:\n    return {{'id': self.id}}\n"
    assert len(_check(src)) == 1, name


_NON_RECORD_ROUTE_BODIES = [
    # 128 corpus findings: the route returns a model / ORM object.
    "return Item(id=1)",
    "return session.get(Hero, hero_id)",
    # 35: a list of models.
    "return session.exec(select(Hero)).all()",
    # 25: a Response subclass (`fastapi/docs_src/custom_response/*`).
    "return HTMLResponse(content=html)",
    "return StreamingResponse(iterfile())",
    "return templates.TemplateResponse('item.html', ctx)",
    # 11: no return at all (`status_code=204` style handlers).
    "pass",
]


@pytest.mark.parametrize("body", _NON_RECORD_ROUTE_BODIES)
def test_route_without_annotation_and_without_ad_hoc_dict_not_flagged(body: str):
    src = f'@router.get("/x")\ndef handler():\n    {body}\n'
    assert _check(src) == [], body


def test_unannotated_route_like_function_is_owned_elsewhere():
    src = '@router.get("/items/{item_id}")\ndef read_item(item_id: str):\n    return {"item_id": item_id}\n'
    assert _check(src) == []


def test_unannotated_route_like_list_is_owned_elsewhere():
    src = '@router.get("/items")\ndef read_items():\n    return [{"item_name": "Foo"}]\n'
    assert _check(src) == []


def test_payload_builder_under_test_support_directory_is_exempt() -> None:
    source = "def build_payload() -> dict[str, Any]:\n    return {'id': 1}\n"

    assert _check(source, path="python/common/testing/payloads.py") == []
    assert len(_check(source, path="python/common/payloads.py")) == 1


@pytest.mark.parametrize("path", ["docs_src/tutorial.py", "docs/examples/tutorial.py"])
def test_documentation_examples_are_exempt(path: str) -> None:
    source = "def payload() -> dict[str, object]:\n    return {'id': 1}\n"

    assert not _check(source, path)


def test_documentation_directory_name_does_not_hide_production_source() -> None:
    source = "def payload() -> dict[str, object]:\n    return {'id': 1}\n"

    assert _check(source, "src/documentation/payload.py")


def test_mapping_unpack_is_not_a_fixed_shape() -> None:
    source = "def payload(context) -> dict[str, object]:\n    return {**context, 'request': object()}\n"

    assert not _check(source)


@pytest.mark.parametrize(
    "body",
    [
        "enrich(payload)",
        "enrich(value=payload)",
    ],
)
def test_mapping_crossing_opaque_call_is_not_a_fixed_shape(body: str) -> None:
    source = f"def payload() -> dict[str, object]:\n    payload = {{'id': 1}}\n    {body}\n    return payload\n"

    assert not _check(source)


def test_private_class_method_is_not_a_public_api() -> None:
    source = "class _Internal:\n    def payload(self) -> dict[str, Any]:\n        return {'id': 1}\n"

    assert not _check(source)


@pytest.mark.parametrize("decorator", ["model_serializer", "field_serializer"])
def test_pydantic_serializer_protocol_is_exempt(decorator: str) -> None:
    source = (
        f"from pydantic import {decorator}\n"
        f"class Model:\n    @{decorator}\n    def serialize(self) -> dict[str, Any]:\n        return {{'id': 1}}\n"
    )

    assert not _check(source)


def test_foreign_any_annotation_is_not_treated_as_typing_any() -> None:
    source = "from vendor import Any\ndef payload() -> dict[str, Any]:\n    return {'id': 1}\n"

    assert not _check(source)


def test_shadowed_dict_annotation_is_not_treated_as_builtin_dict() -> None:
    source = "class dict: pass\ndef payload() -> dict[str, Any]:\n    return {'id': 1}\n"

    assert not _check(source)


def test_generated_source_is_exempt() -> None:
    source = "# Code generated by api-tool. DO NOT EDIT.\ndef payload() -> dict[str, Any]:\n    return {'id': 1}\n"

    assert not _check(source)


def test_inline_suppression_is_honored() -> None:
    source = "def payload() -> dict[str, Any]:  # sarj-noqa: SARJ008\n    return {'id': 1}\n"

    assert not _check(source)


def test_mutation_through_alias_makes_shape_open() -> None:
    source = (
        "def payload() -> dict[str, Any]:\n"
        "    record = {'id': 1}\n"
        "    alias = record\n"
        "    alias['name'] = 'Ada'\n"
        "    return record\n"
    )

    assert not _check(source)


def test_harmless_alias_preserves_fixed_record_evidence() -> None:
    source = "def payload() -> dict[str, Any]:\n    record = {'id': 1}\n    alias = record\n    return alias\n"

    assert len(_check(source)) == 1


def test_mixed_record_and_unknown_list_is_not_fixed() -> None:
    source = "def payload() -> list[dict[str, Any]]:\n    return [{'id': 1}, external]\n"

    assert not _check(source)


def test_unimported_typing_spellings_do_not_claim_provenance() -> None:
    source = "def payload() -> Dict[str, Any]:\n    return {'id': 1}\n"

    assert PydanticAtBoundaries().check(Path("service.py"), source) == []


def test_nested_bindings_do_not_shadow_module_annotation_names() -> None:
    source = """
from typing import Any

def helper(dict):
    Any = object
    return dict, Any

def payload() -> dict[str, Any]:
    return {"id": 1}
"""

    assert len(PydanticAtBoundaries().check(Path("service.py"), source)) == 1


def test_foreign_overload_decorator_does_not_exempt_record_return() -> None:
    source = """
from typing import Any
from vendor import overload

@overload
def payload() -> dict[str, Any]:
    return {"id": 1}
"""

    assert len(PydanticAtBoundaries().check(Path("service.py"), source)) == 1


def test_module_comprehension_targets_do_not_shadow_annotations() -> None:
    source = """
from typing import Any
consume([dict for dict in values])
[Any for Any in values]

def payload() -> dict[str, Any]:
    return {"id": 1}
"""

    assert len(PydanticAtBoundaries().check(Path("service.py"), source)) == 1


@pytest.mark.parametrize("name", ["Any", "dict"])
def test_module_comprehension_walrus_targets_do_shadow_annotations(name: str) -> None:
    source = """
from typing import Any
[(TARGET := value) for value in values]

def payload() -> dict[str, Any]:
    return {"id": 1}
""".replace("TARGET", name)

    assert PydanticAtBoundaries().check(Path("service.py"), source) == []


def test_type_checking_imports_have_annotation_provenance() -> None:
    source = """
from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any

def payload() -> dict[str, Any]:
    return {"id": 1}
"""

    assert len(PydanticAtBoundaries().check(Path("service.py"), source)) == 1


def test_annotated_harmless_alias_preserves_fixed_record_evidence() -> None:
    source = (
        "def payload() -> dict[str, Any]:\n"
        "    record = {'id': 1}\n"
        "    alias: dict[str, Any] = record\n"
        "    return alias\n"
    )

    assert len(_check(source)) == 1


def test_mutation_through_annotated_alias_makes_shape_open() -> None:
    source = (
        "def payload() -> dict[str, Any]:\n"
        "    record = {'id': 1}\n"
        "    alias: dict[str, Any] = record\n"
        "    alias['name'] = 'Ada'\n"
        "    return record\n"
    )

    assert not _check(source)
