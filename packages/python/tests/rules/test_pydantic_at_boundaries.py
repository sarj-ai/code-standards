from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rules.pydantic_at_boundaries import PydanticAtBoundaries


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic


def _check(source: str, path: str = "svc.py") -> list[Diagnostic]:
    return PydanticAtBoundaries().check(Path(path), source)


# --- Trigger 1: untyped dict returns ---------------------------------------


def test_flags_dict_str_any_return():
    src = """
from typing import Any

def build_payload(call) -> dict[str, Any]:
    return {"id": call.id}
"""
    diags = _check(src)
    assert len(diags) == 1
    assert "dict[str, Any]" in diags[0].message
    assert diags[0].code == "SARJ008"


def test_flags_dict_str_object_return():
    src = "def f() -> dict[str, object]:\n    return {}\n"
    assert len(_check(src)) == 1


def test_flags_bare_dict_and_typing_dict():
    src = """
from typing import Dict

def f() -> dict:
    return {}

def g() -> Dict:
    return {}

def h() -> Dict[str, Any]:
    return {}
"""
    assert len(_check(src)) == 3


def test_flags_list_of_untyped_dict():
    src = "def f() -> list[dict[str, Any]]:\n    return []\n"
    assert len(_check(src)) == 1


def test_flags_optional_untyped_dict():
    src = """
from typing import Any, Optional

def f() -> dict[str, Any] | None:
    return None

def g() -> Optional[dict[str, Any]]:
    return None
"""
    assert len(_check(src)) == 2


def test_flags_async_def():
    src = "async def f() -> dict[str, Any]:\n    return {}\n"
    assert len(_check(src)) == 1


def test_flags_method_in_class():
    src = """
class CallService:
    def summarize(self) -> dict[str, Any]:
        return {}
"""
    assert len(_check(src)) == 1


def test_skips_private_function():
    """Private/internal functions are not public boundaries — never flagged."""
    src = "def _build() -> dict[str, Any]:\n    return {}\n"
    assert _check(src) == []


def test_skips_pydantic_validator_hooks():
    """@model_validator/@field_validator take and return raw dict/values by contract."""
    src = """
from typing import Any
from pydantic import model_validator, field_validator

class M:
    @model_validator(mode="before")
    @classmethod
    def normalize(cls, data) -> dict[str, Any]:
        return data

    @field_validator("x")
    def coerce(cls, v) -> dict[str, Any]:
        return v
"""
    assert _check(src) == []


def test_allows_concrete_dict_value_types():
    src = """
def f() -> dict[str, str]:
    return {}

def g() -> dict[str, int]:
    return {}

def h() -> dict[str, list[int]]:
    return {}
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


# --- tuple returns are NOT flagged (multiple return values are idiomatic) ----


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


# --- Trigger 2: FastAPI route handlers ---------------------------------------


def test_flags_router_get_without_return_annotation():
    src = """
@router.get("/calls/{call_id}")
async def get_call(call_id: str):
    return {"id": call_id}
"""
    diags = _check(src)
    assert len(diags) == 1
    assert "no return annotation" in diags[0].message


def test_flags_app_post_without_return_annotation():
    src = """
@app.post("/calls")
def create_call(body: CreateCallRequest):
    return {"ok": True}
"""
    assert len(_check(src)) == 1


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
    return CallResponse(id=call_id)
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
    """`client.get(...)` etc. is not a FastAPI route decorator."""
    src = """
@client.get("/upstream")
def fetch_upstream():
    return {}

@retry.post()
def push():
    return {}
"""
    assert _check(src) == []


def test_flags_named_router_receiver():
    src = """
@admin_router.delete("/orgs/{org_id}")
async def delete_org(org_id: str):
    return {"ok": True}
"""
    assert len(_check(src)) == 1


# --- Exclusions ---------------------------------------------------------------


def test_skips_test_files():
    src = "def f() -> dict[str, Any]:\n    return {}\n"
    assert _check(src, path="test_calls.py") == []
    assert _check(src, path="python/bulbul/tests/helpers.py") == []


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


# ===========================================================================
# ADDED COVERAGE
# ===========================================================================

# --- Flagged dict shapes (parametrized) ------------------------------------

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
    diags = _check(f"def f() -> {ann}:\n    return {{}}\n")
    assert len(diags) == 1, ann
    assert diags[0].code == "SARJ008"
    assert "pydantic model" in diags[0].message


# --- NOT-flagged shapes / false-positive guards (parametrized) --------------

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
    assert _check(f"def f() -> {ann}:\n    return x\n") == [], ann


# --- Forward-reference string annotations -----------------------------------


def test_flags_string_forward_ref_dict():
    assert len(_check('def f() -> "dict[str, Any]":\n    return {}\n')) == 1


def test_flags_string_forward_ref_nested_list_dict():
    assert len(_check('def f() -> "list[dict[str, Any]]":\n    return []\n')) == 1


def test_allows_string_forward_ref_concrete():
    assert _check('def f() -> "tuple[bool, str]":\n    return True, "x"\n') == []
    assert _check('def f() -> "CallPayload":\n    return c\n') == []


def test_string_forward_ref_with_syntax_error_not_flagged():
    """A malformed string annotation resolves to None → treated as unannotated."""
    assert _check('def f() -> "dict[":\n    return {}\n') == []


# --- Validator hook variants (parametrized) ---------------------------------

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
    src = f"class M:\n    {dec}\n    def v(cls, value) -> dict[str, Any]:\n        return value\n"
    assert _check(src) == [], dec


# --- Overload stub variants -------------------------------------------------


@pytest.mark.parametrize("dec", ["@overload", "@typing.overload", "@t.overload"])
def test_overload_variants_never_flagged(dec: str):
    src = f"{dec}\ndef f(x) -> dict[str, Any]: ...\n"
    assert _check(src) == [], dec


# --- Route method / receiver matrix -----------------------------------------


@pytest.mark.parametrize("method", ["get", "post", "put", "patch", "delete"])
@pytest.mark.parametrize("receiver", ["app", "router", "admin_router", "v1_router"])
def test_route_methods_and_receivers_flagged_without_annotation(method: str, receiver: str):
    src = f'@{receiver}.{method}("/x")\ndef handler():\n    return {{}}\n'
    diags = _check(src)
    assert len(diags) == 1, (method, receiver)
    assert "no return annotation" in diags[0].message


@pytest.mark.parametrize("method", ["get", "post", "put", "patch", "delete"])
def test_route_methods_allowed_with_return_annotation(method: str):
    src = f'@router.{method}("/x")\ndef handler() -> CallResponse:\n    return c\n'
    assert _check(src) == [], method


def test_route_with_response_model_but_dict_annotation_still_flagged():
    """`response_model=` only exempts the missing-annotation path, not a raw dict return."""
    src = """
@router.get("/x", response_model=X)
def f() -> dict[str, Any]:
    return {}
"""
    diags = _check(src)
    assert len(diags) == 1
    assert "pydantic model" in diags[0].message


def test_route_websocket_method_not_flagged():
    """`websocket` is not an HTTP verb → not treated as a route boundary."""
    src = '@router.websocket("/ws")\ndef f():\n    return {}\n'
    assert _check(src) == []


def test_route_decorator_must_be_a_call():
    """A bare `@router.get` (no parens) is not a route decorator Call."""
    src = "@router.get\ndef f():\n    return {}\n"
    assert _check(src) == []


def test_bare_name_call_decorator_not_a_route():
    src = '@get("/x")\ndef f():\n    return {}\n'
    assert _check(src) == []


def test_deeply_attributed_receiver_not_a_route():
    """`@v1.router.get(...)` — receiver is an Attribute, not a bare Name."""
    src = '@v1.router.get("/x")\ndef f():\n    return {}\n'
    assert _check(src) == []


def test_private_route_handler_not_flagged():
    """Private-name guard runs before route detection."""
    src = '@router.get("/x")\ndef _internal():\n    return {}\n'
    assert _check(src) == []


def test_route_returning_none_annotation_not_flagged():
    src = '@router.post("/x")\ndef f() -> None:\n    return None\n'
    assert _check(src) == []


# --- Non-route missing-annotation is NOT flagged ----------------------------


def test_plain_missing_annotation_not_flagged():
    """Only routes are flagged for a missing annotation — plain functions are not."""
    src = "def f():\n    return {}\n"
    assert _check(src) == []


def test_non_route_call_decorator_missing_annotation_not_flagged():
    src = "@lru_cache()\ndef f():\n    return {}\n"
    assert _check(src) == []


def test_non_route_call_decorator_with_dict_still_flagged():
    """A non-route decorator does not exempt a raw-dict return annotation."""
    src = "@lru_cache()\ndef f() -> dict[str, Any]:\n    return {}\n"
    assert len(_check(src)) == 1


def test_property_returning_dict_flagged():
    src = "class C:\n    @property\n    def data(self) -> dict[str, Any]:\n        return {}\n"
    assert len(_check(src)) == 1


# --- Line / column reporting ------------------------------------------------


def test_reports_line_and_col_for_top_level_function():
    src = "\n\ndef f() -> dict[str, Any]:\n    return {}\n"
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].line == 3
    assert diags[0].col == 1


def test_reports_line_and_col_for_indented_method():
    src = "class C:\n    def m(self) -> dict[str, Any]:\n        return {}\n"
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].line == 2
    assert diags[0].col == 5


def test_route_reports_decorated_function_line():
    src = '\n@router.get("/x")\ndef handler():\n    return {}\n'
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].line == 3


# --- Multiple diagnostics / ordering ----------------------------------------


def test_multiple_top_level_functions_in_source_order():
    src = """
def a() -> dict[str, Any]:
    return {}

def b() -> dict[str, Any]:
    return {}

def c() -> dict[str, Any]:
    return {}
"""
    diags = _check(src)
    assert [d.line for d in diags] == [2, 5, 8]
    assert [d.message.split("`")[1] for d in diags] == ["a", "b", "c"]


def test_nested_functions_both_flagged():
    src = """
def outer() -> dict[str, Any]:
    def inner() -> dict[str, Any]:
        return {}
    return {}
"""
    diags = _check(src)
    assert len(diags) == 2
    assert {d.message.split("`")[1] for d in diags} == {"outer", "inner"}


def test_public_nested_in_private_still_flagged():
    """The private-name guard is per-function; a public inner function is a boundary."""
    src = """
def _outer():
    def inner() -> dict[str, Any]:
        return {}
    return inner
"""
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].message.split("`")[1] == "inner"


def test_walk_order_is_breadth_first_not_line_sorted():
    """Locks current emission order: siblings before nested children (ast.walk BFS)."""
    src = """
def a() -> dict[str, Any]:
    def b() -> dict[str, Any]:
        return {}
    return {}

def c() -> dict[str, Any]:
    return {}
"""
    diags = _check(src)
    assert [d.line for d in diags] == [2, 7, 3]


# --- Message content --------------------------------------------------------


def test_dict_message_includes_function_name_and_annotation():
    diags = _check("def build_payload() -> dict[str, Any]:\n    return {}\n")
    assert len(diags) == 1
    msg = diags[0].message
    assert "build_payload" in msg
    assert "dict[str, Any]" in msg
    assert "pydantic model" in msg


def test_route_message_includes_route_name():
    diags = _check('@router.get("/x")\ndef get_call():\n    return {}\n')
    assert len(diags) == 1
    msg = diags[0].message
    assert "get_call" in msg
    assert "response_model" in msg


# --- Empty / trivial / malformed sources ------------------------------------


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
        "@\ndef f() -> dict[str, Any]:\n    return {}\n",
        "def f() -> dict[str, Any]\n    return {}\n",
    ],
)
def test_syntax_errors_return_empty(src: str):
    assert _check(src) == []


# --- Test-path exclusion variants -------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "test_calls.py",
        "tests/test_calls.py",
        "python/bulbul/tests/helpers.py",
        "a/tests/b/c.py",
        "tests/conftest.py",
    ],
)
def test_test_paths_are_skipped(path: str):
    src = "def f() -> dict[str, Any]:\n    return {}\n"
    assert _check(src, path=path) == []


@pytest.mark.parametrize(
    "path",
    [
        "svc.py",
        "service_test.py",  # trailing `_test`, not a `test_` prefix
        "src/testing.py",  # `testing`, not a `tests` path part
        "src/my_tests_helper.py",  # `tests` is a substring, not a path part
        "conftest.py",  # not under a tests dir, no test_ prefix
    ],
)
def test_non_test_paths_are_still_linted(path: str):
    src = "def f() -> dict[str, Any]:\n    return {}\n"
    assert len(_check(src, path=path)) == 1, path


# ===========================================================================
# ADVERSARIAL EDGE-CASE HUNT (new)
# ===========================================================================

# --- Additional flagged shapes (passing regressions) ------------------------


def test_flags_builtins_dict_subscript():
    """`builtins.dict[str, Any]` — attribute receiver still resolves to `dict`."""
    src = "import builtins\ndef f() -> builtins.dict[str, Any]:\n    return {}\n"
    assert len(_check(src)) == 1


def test_flags_builtins_dict_bare():
    src = "import builtins\ndef f() -> builtins.dict:\n    return {}\n"
    assert len(_check(src)) == 1


def test_flags_list_of_bare_dict():
    """`list[dict]` — the inner bare `dict` classifies as untyped."""
    assert len(_check("def f() -> list[dict]:\n    return []\n")) == 1


def test_flags_union_with_nested_optional_dict():
    src = """
from typing import Union, Optional, Any

def f() -> Union[str, Optional[dict[str, Any]]]:
    return None
"""
    assert len(_check(src)) == 1


def test_flags_forward_ref_with_leading_newline():
    """A leading newline inside an eval-mode string forward-ref parses fine."""
    assert len(_check('def f() -> "\\ndict[str, Any]":\n    return {}\n')) == 1


def test_flags_implicitly_concatenated_string_annotation():
    """Adjacent string literals fold into one Constant at parse time → resolvable."""
    assert len(_check('def f() -> "dict[str, " "Any]":\n    return {}\n')) == 1


# --- Additional allowed shapes / documented limitations (passing) -----------


def test_allows_dict_with_bare_dict_value():
    """Bare `dict` in VALUE position is not inspected (mirrors `dict[str, dict[str, Any]]`)."""
    assert _check("def f() -> dict[str, dict]:\n    return {}\n") == []


def test_allows_sequence_of_untyped_dict():
    """Only `list`/`List` are unwrapped — `Sequence[...]` is not."""
    src = "from collections.abc import Sequence\ndef f() -> Sequence[dict[str, Any]]:\n    return []\n"
    assert _check(src) == []


def test_allows_kwargs_any_without_return_annotation():
    """`**kwargs: Any` is a param annotation; a non-route missing return is not flagged."""
    assert _check("def f(**kwargs: Any):\n    return {}\n") == []


def test_allows_type_alias_return_pure_annotation_limitation():
    """Pure-annotation rule does not resolve `type X = dict[...]` aliases (by design)."""
    src = "type Payload = dict[str, Any]\ndef f() -> Payload:\n    return {}\n"
    assert _check(src) == []


# --- Previously-genuine defects (now fixed) ---------------------------------


def test_annotated_dict_return_should_be_flagged():
    src = 'from typing import Annotated, Any\ndef f() -> Annotated[dict[str, Any], "meta"]:\n    return {}\n'
    assert len(_check(src)) == 1


def test_forward_ref_with_leading_space_should_be_flagged():
    assert len(_check('def f() -> " dict[str, Any]":\n    return {}\n')) == 1


def test_dict_with_string_forward_ref_any_value_should_be_flagged():
    assert len(_check('def f() -> dict[str, "Any"]:\n    return {}\n')) == 1


def test_pytest_fixture_returning_dict_is_false_positive():
    src = "import pytest\n@pytest.fixture\ndef sample() -> dict[str, Any]:\n    return {}\n"
    assert _check(src) == []
