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
    """Private/internal functions are not public boundaries — never flagged."""
    src = "def _build() -> dict[str, Any]:\n    return {'id': 1}\n"
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
    """`client.get(...)` etc. is not a FastAPI route decorator."""
    src = """
@client.get("/upstream")
def fetch_upstream():
    return {'id': 1}

@retry.post()
def push():
    return {'id': 1}
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
    diags = _check(f"def f() -> {ann}:\n    return {{'id': 1}}\n")
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
    assert _check(f'def f() -> {ann}:\n    return {{"id": 1}}\n') == [], ann


# --- Forward-reference string annotations -----------------------------------


def test_flags_string_forward_ref_dict():
    assert len(_check('def f() -> "dict[str, Any]":\n    return {"id": 1}\n')) == 1


def test_flags_string_forward_ref_nested_list_dict():
    assert len(_check('def f() -> "list[dict[str, Any]]":\n    return [{"id": 1}]\n')) == 1


def test_allows_string_forward_ref_concrete():
    assert _check('def f() -> "tuple[bool, str]":\n    return True, "x"\n') == []
    assert _check('def f() -> "CallPayload":\n    return {"id": 1}\n') == []


def test_string_forward_ref_with_syntax_error_not_flagged():
    """A malformed string annotation resolves to None → treated as unannotated."""
    assert _check('def f() -> "dict[":\n    return {"id": 1}\n') == []


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
    src = f"class M:\n    {dec}\n    def v(cls, value) -> dict[str, Any]:\n        return {{'id': 1}}\n"
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
    src = f'@{receiver}.{method}("/x")\ndef handler():\n    return {{"id": 1}}\n'
    diags = _check(src)
    assert len(diags) == 1, (method, receiver)
    assert "no return annotation" in diags[0].message


@pytest.mark.parametrize("method", ["get", "post", "put", "patch", "delete"])
def test_route_methods_allowed_with_return_annotation(method: str):
    src = f'@router.{method}("/x")\ndef handler() -> CallResponse:\n    return {{"id": 1}}\n'
    assert _check(src) == [], method


def test_route_with_response_model_but_dict_annotation_still_flagged():
    """`response_model=` only exempts the missing-annotation path, not a raw dict return."""
    src = """
@router.get("/x", response_model=X)
def f() -> dict[str, Any]:
    return {'id': 1}
"""
    diags = _check(src)
    assert len(diags) == 1
    assert "pydantic model" in diags[0].message


def test_route_websocket_method_not_flagged():
    """`websocket` is not an HTTP verb → not treated as a route boundary."""
    src = '@router.websocket("/ws")\ndef f():\n    return {"id": 1}\n'
    assert _check(src) == []


def test_route_decorator_must_be_a_call():
    """A bare `@router.get` (no parens) is not a route decorator Call."""
    src = "@router.get\ndef f():\n    return {'id': 1}\n"
    assert _check(src) == []


def test_bare_name_call_decorator_not_a_route():
    src = '@get("/x")\ndef f():\n    return {"id": 1}\n'
    assert _check(src) == []


def test_deeply_attributed_receiver_not_a_route():
    """`@v1.router.get(...)` — receiver is an Attribute, not a bare Name."""
    src = '@v1.router.get("/x")\ndef f():\n    return {"id": 1}\n'
    assert _check(src) == []


def test_private_route_handler_not_flagged():
    """Private-name guard runs before route detection."""
    src = '@router.get("/x")\ndef _internal():\n    return {"id": 1}\n'
    assert _check(src) == []


def test_route_returning_none_annotation_not_flagged():
    src = '@router.post("/x")\ndef f() -> None:\n    return {"id": 1}\n'
    assert _check(src) == []


# --- Non-route missing-annotation is NOT flagged ----------------------------


def test_plain_missing_annotation_not_flagged():
    """Only routes are flagged for a missing annotation — plain functions are not."""
    src = "def f():\n    return {'id': 1}\n"
    assert _check(src) == []


def test_non_route_call_decorator_missing_annotation_not_flagged():
    src = "@lru_cache()\ndef f():\n    return {'id': 1}\n"
    assert _check(src) == []


def test_non_route_call_decorator_with_dict_still_flagged():
    """A non-route decorator does not exempt a raw-dict return annotation."""
    src = "@lru_cache()\ndef f() -> dict[str, Any]:\n    return {'id': 1}\n"
    assert len(_check(src)) == 1


def test_property_returning_dict_flagged():
    src = "class C:\n    @property\n    def data(self) -> dict[str, Any]:\n        return {'id': 1}\n"
    assert len(_check(src)) == 1


# --- Line / column reporting ------------------------------------------------


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


def test_route_reports_decorated_function_line():
    src = '\n@router.get("/x")\ndef handler():\n    return {"id": 1}\n'
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].line == 3


# --- Multiple diagnostics / ordering ----------------------------------------


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
    """A closure is not importable — only the enclosing function is a boundary."""
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
    """A public name nested inside a private function is still a closure."""
    src = """
def _outer():
    def inner() -> dict[str, Any]:
        return {'id': 1}
    return inner
"""
    assert _check(src) == []


def test_walk_order_is_breadth_first_not_line_sorted():
    """Locks emission order: `ast.walk` BFS, so a method follows its top-level sibling."""
    src = """
class C:
    def a(self) -> dict[str, Any]:
        return {'id': 1}

def b() -> dict[str, Any]:
    return {'id': 1}
"""
    diags = _check(src)
    assert [d.line for d in diags] == [6, 3]


# --- Message content --------------------------------------------------------


def test_dict_message_includes_function_name_and_annotation():
    diags = _check("def build_payload() -> dict[str, Any]:\n    return {'id': 1}\n")
    assert len(diags) == 1
    msg = diags[0].message
    assert "build_payload" in msg
    assert "dict[str, Any]" in msg
    assert "pydantic model" in msg


def test_route_message_includes_route_name():
    diags = _check('@router.get("/x")\ndef get_call():\n    return {"id": 1}\n')
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
        "@\ndef f() -> dict[str, Any]:\n    return {'id': 1}\n",
        "def f() -> dict[str, Any]\n    return {'id': 1}\n",
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
        "python/app/tests/helpers.py",
        "a/tests/b/c.py",
        "tests/conftest.py",
    ],
)
def test_test_paths_are_skipped(path: str):
    src = "def f() -> dict[str, Any]:\n    return {'id': 1}\n"
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
    src = "def f() -> dict[str, Any]:\n    return {'id': 1}\n"
    assert len(_check(src, path=path)) == 1, path


# ===========================================================================
# ADVERSARIAL EDGE-CASE HUNT (new)
# ===========================================================================

# --- Additional flagged shapes (passing regressions) ------------------------


def test_flags_builtins_dict_subscript():
    """`builtins.dict[str, Any]` — attribute receiver still resolves to `dict`."""
    src = "import builtins\ndef f() -> builtins.dict[str, Any]:\n    return {'id': 1}\n"
    assert len(_check(src)) == 1


def test_flags_builtins_dict_bare():
    src = "import builtins\ndef f() -> builtins.dict:\n    return {'id': 1}\n"
    assert len(_check(src)) == 1


def test_flags_list_of_bare_dict():
    """`list[dict]` — the inner bare `dict` classifies as untyped."""
    assert len(_check("def f() -> list[dict]:\n    return [{'id': 1}]\n")) == 1


def test_flags_union_with_nested_optional_dict():
    src = """
from typing import Union, Optional, Any

def f() -> Union[str, Optional[dict[str, Any]]]:
    return {"id": 1}
"""
    assert len(_check(src)) == 1


def test_flags_forward_ref_with_leading_newline():
    """A leading newline inside an eval-mode string forward-ref parses fine."""
    assert len(_check('def f() -> "\\ndict[str, Any]":\n    return {"id": 1}\n')) == 1


def test_flags_implicitly_concatenated_string_annotation():
    """Adjacent string literals fold into one Constant at parse time → resolvable."""
    assert len(_check('def f() -> "dict[str, " "Any]":\n    return {"id": 1}\n')) == 1


# --- Additional allowed shapes / documented limitations (passing) -----------


def test_allows_dict_with_bare_dict_value():
    """Bare `dict` in VALUE position is not inspected (mirrors `dict[str, dict[str, Any]]`)."""
    assert _check("def f() -> dict[str, dict]:\n    return {'id': 1}\n") == []


def test_allows_sequence_of_untyped_dict():
    """Only `list`/`List` are unwrapped — `Sequence[...]` is not."""
    src = "from collections.abc import Sequence\ndef f() -> Sequence[dict[str, Any]]:\n    return [{'id': 1}]\n"
    assert _check(src) == []


def test_allows_kwargs_any_without_return_annotation():
    """`**kwargs: Any` is a param annotation; a non-route missing return is not flagged."""
    assert _check("def f(**kwargs: Any):\n    return {'id': 1}\n") == []


def test_allows_type_alias_return_pure_annotation_limitation():
    """Pure-annotation rule does not resolve `type X = dict[...]` aliases (by design)."""
    src = "type Payload = dict[str, Any]\ndef f() -> Payload:\n    return {'id': 1}\n"
    assert _check(src) == []


# --- Previously-genuine defects (now fixed) ---------------------------------


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


# ===========================================================================
# CORPUS SWEEP: 413 findings over fastapi / pydantic / black / sqlmodel /
# rich / flask / httpx / requests / anyio (2,657 files).
# ===========================================================================

# --- Guard: the record must be built in place -------------------------------

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
]


@pytest.mark.parametrize("body", _OPAQUE_MAPPING_BODIES)
def test_opaque_mapping_returns_are_not_records(body: str):
    """A mapping the function parses/forwards/reflects over has no shape to declare."""
    assert _check(f"def f() -> dict[str, Any]:\n    {body}\n") == [], body


_RECORD_BODIES = [
    # `requests/src/requests/help.py:67` (info), `flask/examples/celery/.../views.py:22`.
    "return {'ready': ready, 'value': value}",
    # A record assigned to a local, then mutated before return (`app.py:620`).
    "rv = {'app': app}\n    rv.update(extra)\n    return rv",
    "rv: dict[str, Any] = {'app': app}\n    return rv",
    # `list[dict[str, Any]]` shapes.
    "return [{'id': 1}]",
    "return [{'id': row.id} for row in rows]",
    # One opaque branch does not excuse the record branch.
    "if x:\n        return other.copy()\n    return {'id': 1}",
    # A single literal string key is enough evidence.
    "return {'id': ident, key: value}",
]


@pytest.mark.parametrize("body", _RECORD_BODIES)
def test_in_place_records_are_flagged(body: str):
    assert len(_check(f"def f() -> dict[str, Any]:\n    {body}\n")) == 1, body


def test_stub_body_is_not_flagged_known_limitation():
    """`pydantic_core/core_schema.py:234` — a `...` stub builds no record in place."""
    assert _check("def data(self) -> dict[str, Any]: ...\n") == []


def test_record_built_by_a_nested_function_does_not_count():
    """The outer function forwards an opaque mapping; the inner record is not its return."""
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


# --- Guard: closures are not boundaries -------------------------------------


def test_closure_returning_record_not_flagged():
    """`httpx/_transports/asgi.py:134` — an inner ASGI callable is not importable."""
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
    """Opposite case: the closure guard must not swallow ordinary methods."""
    src = """
class Service:
    def payload(self) -> dict[str, Any]:
        return {"id": 1}
"""
    assert len(_check(src)) == 1


# --- Guard: dict-conversion protocol methods --------------------------------


@pytest.mark.parametrize(
    "name",
    ["asdict", "as_dict", "dict", "model_dump", "to_data", "to_dict"],
)
def test_dict_conversion_methods_not_flagged(name: str):
    """`pydantic/main.py:469`, `sqlmodel/main.py:890`, `fastapi/_compat/v2.py:100`."""
    src = f"def {name}(self) -> dict[str, Any]:\n    return {{'id': self.id}}\n"
    assert _check(src) == [], name


@pytest.mark.parametrize("name", ["to_dictionary", "build_dict", "dict_for", "as_dict_of"])
def test_names_merely_containing_dict_are_still_flagged(name: str):
    """Opposite case: the exemption is an exact-name allowlist, not a substring match."""
    src = f"def {name}(self) -> dict[str, Any]:\n    return {{'id': self.id}}\n"
    assert len(_check(src)) == 1, name


# --- Routes: the missing-annotation trigger needs an ad-hoc dict too --------


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


def test_route_without_annotation_returning_ad_hoc_dict_still_flagged():
    """Opposite case: 130 corpus findings are exactly this (`return {"item_id": ...}`)."""
    src = '@router.get("/items/{item_id}")\ndef read_item(item_id: str):\n    return {"item_id": item_id}\n'
    diags = _check(src)
    assert len(diags) == 1
    assert "ad-hoc dict" in diags[0].message


def test_route_without_annotation_returning_list_of_records_flagged():
    src = '@router.get("/items")\ndef read_items():\n    return [{"item_name": "Foo"}]\n'
    assert len(_check(src)) == 1
