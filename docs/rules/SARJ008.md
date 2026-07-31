# SARJ008 `pydantic-at-boundaries` — evidence

Behaviour is specified by [the tests](../../packages/python/tests/rules/test_pydantic_at_boundaries.py); every guard below
has a named test asserting it. This file holds what a test cannot carry: the
measurements that chose each threshold, and the false-positive family each
guard exists to stop.

The anti-pattern:

    def build_payload(call: Call) -> dict[str, Any]:
        return {"id": call.id, "status": call.status}

    @router.get("/calls/{call_id}")
    async def get_call(call_id: str):   # no return annotation at all
        return {"id": call_id}

A record built inline and typed as raw ``dict[str, Any]`` /
``dict[str, object]`` / bare ``dict`` hides its shape from both the type
checker and the reader. Define a pydantic model (or frozen dataclass) instead
— Python analogue of ``@sarj/prefer-schema-for-api-payload``:

    class CallPayload(BaseModel):
        id: CallId
        status: CallStatus

    def build_payload(call: Call) -> CallPayload: ...

Annotation-driven, checked on function definitions (sync + async). A function
is flagged only when BOTH hold:

1. Shape — either a return annotation that is ``dict[str, Any]`` /
   ``dict[str, object]`` / bare ``dict`` / ``Dict`` (or ``list[...]`` of one),
   or a FastAPI route handler (``@router.get(...)`` / ``@app.post(...)`` etc.)
   with no return annotation and no ``response_model=`` in the decorator.
2. Evidence — the body visibly builds the record in place: a
   ``return {"k": ..., ...}`` with at least one literal string key (or a
   ``return name`` whose ``name = {"k": ...}`` is assigned in the same
   function; ``list`` literals and list comprehensions of such dicts count).

Requirement 2 is what separates "an unnamed record that wants to be a model"
from "an opaque mapping": a function that parses, forwards, merges or
reflects over a mapping it did not author has no record shape to declare.

Deliberately NOT flagged (kept high-precision for real boundaries):

* private / ``_``-prefixed functions — internal, not a public contract;
* nested functions (closures) — not importable, so not a boundary at all.
  Corpus: ``httpx/_transports/asgi.py:134`` (``receive``), an inner ASGI
  callable whose ``{"type": "http.request", ...}`` messages are fixed by the
  ASGI spec;
* dict-conversion protocol methods (``model_dump`` / ``dict`` / ``asdict`` /
  ``as_dict`` / ``to_dict`` / ``to_data``) — returning a dict IS their
  declared contract, and for pydantic's own the signature is inherited.
  Corpus (6): ``pydantic/main.py:469`` + ``sqlmodel/main.py:890``
  (``model_dump``), ``pydantic/main.py:1385`` + ``sqlmodel/main.py:938``
  (``dict``), ``fastapi/_compat/v2.py:100`` (``asdict``),
  ``pydantic/mypy.py:284`` (``to_data``);
* opaque mappings the function did not author — no in-place record literal.
  Corpus (56 of the 67 raw-dict findings across fastapi/pydantic/black/
  flask/rich/sqlmodel), e.g. parsed documents ``black/src/black/files.py:130``
  (``parse_pyproject_toml`` → ``tomllib.load``), ``pydantic/mypy.py:1433``
  (``parse_toml``); symbol tables ``pydantic/_internal/_typing_extra.py:359``
  (``get_cls_type_hints``), ``sqlmodel/_compat.py:100`` (``get_annotations``);
  generated JSON Schema / OpenAPI documents ``pydantic/json_schema.py:2547``
  (``model_json_schema``), ``fastapi/openapi/utils.py:529`` (``get_openapi``);
  caller-owned metadata ``rich/style.py:473`` (``meta``), and namespace
  mappings ``flask/config.py:323`` (``get_namespace``);
* pydantic ``@model_validator`` / ``@field_validator`` hooks (raw dict in/out
  is their API), ``@pytest.fixture`` scaffolding, ``tuple[...]`` returns
  (multiple return values are idiomatic Python), fully-concrete dict value
  types (``dict[str, str]``), ``@overload`` stubs, and test files.

Known limitation (accepted, precision over recall): a stub or abstract
declaration such as ``def data(self) -> dict[str, Any]: ...`` builds no record
in place, so it is not flagged — corpus
``pydantic-core/python/pydantic_core/core_schema.py:234``.

References:
- https://docs.pydantic.dev/latest/concepts/models/
- https://fastapi.tiangolo.com/tutorial/response-model/

## Implementation notes

### `_is_untyped_dict_args`

Only a str-keyed dict is a record shape a pydantic model can replace. A dict
keyed by anything else (`dict[TypeVar, Any]`, `dict[type, Any]`) is a
mapping — a data structure, not an unnamed record (pydantic's own
`typevars_map` helpers were the sweep case).

### `_is_validator`

Its dict/value in-and-out is a required contract, so the rule exempts it.

### `_builds_record_literal`

Either `return {"k": ...}` directly, or `return name` where `name` was
assigned such a literal in the same function. Nested function / lambda /
class bodies are not inspected — their returns belong to them.

### `_is_record_literal`

A dict display with at least one literal string key is a record — the shape
a pydantic model would name. A dict comprehension, a `{**a, **b}` merge or
an empty `{}` carries no such shape. `list` displays and list
comprehensions are unwrapped so `list[dict[str, Any]]` returns count too.

### `_local_function_ids`

Such a function is a closure: it cannot be imported, so its return shape is
an implementation detail rather than a boundary contract.
