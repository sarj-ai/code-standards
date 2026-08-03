import ast
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING

from sarj_python_lint.rules.stepdown import (
    Stepdown,
    _walk,  # pyright: ignore[reportPrivateUsage]  # sarj-noqa: SARJ048 — parity test for the rule's inlined AST walker vs ast.walk
)


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic


def _check(source: str, path: str = "svc.py") -> list[Diagnostic]:
    return Stepdown().check(Path(path), source)


def test_clean_stepdown_module():
    src = """
def handle_request(payload: dict) -> str:
    parsed = _parse(payload)
    return _render(parsed)

def _parse(payload: dict) -> dict:
    return _normalize(payload)

def _render(parsed: dict) -> str:
    return str(parsed)

def _normalize(payload: dict) -> dict:
    return payload
"""
    assert _check(src) == []


def test_private_above_caller_fires():
    src = """
def _parse(payload: dict) -> dict:
    return payload

def handle_request(payload: dict) -> str:
    return str(_parse(payload))
"""
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].line == 2
    assert "_parse" in diags[0].message
    assert "handle_request" in diags[0].message


def test_single_caller_below_is_clean():
    src = """
def handle_request(payload: dict) -> str:
    return str(_parse(payload))

def _parse(payload: dict) -> dict:
    return payload
"""
    assert _check(src) == []


def test_multi_caller_helper_between_callers_skipped():
    src = """
def first(x: int) -> int:
    return _shared(x)

def _shared(x: int) -> int:
    return x + 1

def second(x: int) -> int:
    return _shared(x)
"""
    assert _check(src) == []


def test_multi_caller_helper_above_all_callers_skipped():
    src = """
def _shared(x: int) -> int:
    return x + 1

def first(x: int) -> int:
    return _shared(x)

def second(x: int) -> int:
    return _shared(x)
"""
    assert _check(src) == []


def test_two_node_recursion_single_caller_each_skipped():
    src = """
def _ping(n: int) -> int:
    return _pong(n - 1)

def _pong(n: int) -> int:
    return _ping(n - 1)

def run(n: int) -> int:
    return _ping(n)
"""
    assert _check(src) == []


def test_class_method_multi_caller_above_skipped():
    src = """
class Handler:
    def _shared(self) -> int:
        return 1

    def a(self) -> int:
        return self._shared()

    def b(self) -> int:
        return self._shared()
"""
    assert _check(src) == []


def test_class_method_ordering_fires():
    src = """
class Handler:
    def _load(self) -> dict:
        return {}

    def handle(self) -> dict:
        return self._load()
"""
    diags = _check(src)
    assert len(diags) == 1
    assert "_load" in diags[0].message
    assert "handle" in diags[0].message


def test_class_clean_ordering():
    src = """
class Handler:
    def handle(self) -> dict:
        return self._load()

    def _load(self) -> dict:
        return {}
"""
    assert _check(src) == []


def test_mutual_recursion_skipped():
    src = """
def _even(n: int) -> bool:
    return True if n == 0 else _odd(n - 1)

def _odd(n: int) -> bool:
    return False if n == 0 else _even(n - 1)

def classify(n: int) -> bool:
    return _even(n)
"""
    assert _check(src) == []


def test_indirect_recursion_skipped():
    src = """
def _a(n: int) -> int:
    return _b(n)

def _b(n: int) -> int:
    return _c(n)

def _c(n: int) -> int:
    return _a(n)

def run(n: int) -> int:
    return _a(n)
"""
    assert _check(src) == []


def test_self_recursion_still_fires():
    src = """
def _countdown(n: int) -> int:
    return n if n == 0 else _countdown(n - 1)

def run(n: int) -> int:
    return _countdown(n)
"""
    diags = _check(src)
    assert len(diags) == 1
    assert "_countdown" in diags[0].message


def test_type_checking_only_usage_skipped():
    src = """
from typing import TYPE_CHECKING

def _make_client() -> object:
    return object()

if TYPE_CHECKING:
    _CLIENT_FACTORY = _make_client

def run() -> object:
    return _make_client()
"""
    assert _check(src) == []


def test_decorator_reference_pins_helper():
    src = """
def _traced(fn):
    return fn

@_traced
def handle() -> None: ...

def rewrap(fn):
    return _traced(fn)
"""
    assert _check(src) == []


def test_default_arg_reference_pins_helper():
    src = """
def _default_limit() -> int:
    return 10

def fetch(limit: int = _default_limit()) -> int:
    return limit

def refetch() -> int:
    return fetch(_default_limit())
"""
    assert _check(src) == []


def test_annotation_reference_pins_helper():
    src = """
def _sentinel() -> object:
    return object()

def apply(fn: _sentinel) -> None: ...

def run() -> None:
    _sentinel()
"""
    assert _check(src) == []


def test_dunder_first_is_clean():
    src = """
class Service:
    def __init__(self) -> None:
        self.state = self._initial_state()

    def run(self) -> None:
        self._step()

    def _initial_state(self) -> dict:
        return {}

    def _step(self) -> None: ...
"""
    assert _check(src) == []


def test_dunder_never_flagged():
    src = """
class Service:
    def __call__(self) -> None: ...

    def run(self) -> None:
        self.__call__()
"""
    assert _check(src) == []


def test_unused_private_def_not_flagged():
    src = """
def _orphan() -> None: ...

def run() -> None: ...
"""
    assert _check(src) == []


def test_module_level_reference_pins_helper():
    src = """
def _build_registry() -> dict:
    return {}

REGISTRY = _build_registry()

def lookup(key: str) -> object:
    return _build_registry()[key]
"""
    assert _check(src) == []


def test_class_body_attribute_reference_pins_method():
    src = """
def _handler() -> None: ...

class Dispatcher:
    default = staticmethod(_handler)

    def run(self) -> None:
        _handler()
"""
    assert _check(src) == []


def test_property_and_abstractmethod_exempt():
    src = """
from abc import abstractmethod
from functools import cached_property

class Base:
    @property
    def _conn(self) -> object:
        return object()

    @cached_property
    def _pool(self) -> object:
        return object()

    @abstractmethod
    def _hook(self) -> None: ...

    def run(self) -> None:
        self._hook()
        print(self._conn, self._pool)
"""
    assert _check(src) == []


def test_overload_style_duplicate_defs_skipped():
    src = """
class Model:
    @property
    def _value(self) -> int:
        return 1

    @_value.setter
    def _value(self, v: int) -> None: ...

    def bump(self) -> None:
        self._value = self._value + 1
"""
    assert _check(src) == []


def test_shadowing_local_binding_skipped():
    src = """
def _config() -> dict:
    return {}

def run() -> dict:
    _config = {"a": 1}
    return _config()
"""
    assert _check(src) == []


def test_self_attribute_store_shadows_method_name():
    src = """
class Service:
    def _factory(self) -> object:
        return object()

    def __init__(self) -> None:
        self._factory = object

    def run(self) -> object:
        return self._factory()
"""
    assert _check(src) == []


def test_class_calling_module_helper_below_is_clean():
    src = """
class Runner:
    def run(self) -> dict:
        return _load()

def _load() -> dict:
    return {}
"""
    assert _check(src) == []


def test_module_helper_whose_only_caller_is_a_class_is_not_flagged():
    # A class is a scope, not a call site: no module-level position sits
    # "directly below" the method that actually calls the helper.
    src = """
def _load() -> dict:
    return {}

class Runner:
    def run(self) -> dict:
        return _load()
"""
    assert _check(src) == []


def test_private_class_not_flagged():
    src = """
class _State:
    pass

def run() -> _State:
    return _State()
"""
    assert _check(src) == []


def test_syntax_error_returns_empty():
    assert _check("def broken(:\n") == []


def test_test_paths_skipped():
    src = """
def _helper() -> int: ...

def test_x():
    _helper()
"""
    assert _check(src, path="test_things.py") == []
    assert _check(src, path="pkg/tests/helpers.py") == []


def test_async_helper_above_caller_fires():
    src = """
async def _fetch() -> int:
    return 1

async def run() -> int:
    return await _fetch()
"""
    diags = _check(src)
    assert len(diags) == 1
    assert "_fetch" in diags[0].message
    assert "run" in diags[0].message


def test_call_from_nested_function_counts_as_caller():
    src = """
def _h() -> int:
    return 1

def caller() -> int:
    def inner() -> int:
        return _h()
    return inner()
"""
    diags = _check(src)
    assert len(diags) == 1
    assert "_h" in diags[0].message
    assert "caller" in diags[0].message


def test_call_inside_comprehension_fires():
    src = """
def _h(x: int) -> int:
    return x

def caller(xs: list[int]) -> list[int]:
    return [_h(x) for x in xs]
"""
    diags = _check(src)
    assert len(diags) == 1
    assert "_h" in diags[0].message


def test_call_inside_match_case_fires():
    src = """
def _h(x: int) -> int:
    return x

def caller(x: int) -> int:
    match x:
        case 0:
            return _h(x)
        case _:
            return x
"""
    diags = _check(src)
    assert len(diags) == 1
    assert "_h" in diags[0].message


def test_call_inside_except_star_fires():
    src = """
def _h() -> int:
    return 1

def caller() -> int:
    try:
        return _h()
    except* ValueError:
        return 0
"""
    diags = _check(src)
    assert len(diags) == 1
    assert "_h" in diags[0].message


def test_pep695_type_param_caller_fires():
    src = """
def _bound() -> int:
    return 1

def caller[T]() -> int:
    return _bound()
"""
    diags = _check(src)
    assert len(diags) == 1
    assert "_bound" in diags[0].message


def test_classmethod_cls_reference_ordering_fires():
    src = """
class H:
    @classmethod
    def _load(cls) -> int:
        return 1

    @classmethod
    def run(cls) -> int:
        return cls._load()
"""
    diags = _check(src)
    assert len(diags) == 1
    assert "_load" in diags[0].message


def test_helper_used_as_value_reference_fires():
    src = """
def _h() -> int:
    return 1

def caller():
    return _h
"""
    diags = _check(src)
    assert len(diags) == 1
    assert "_h" in diags[0].message


def test_nested_def_default_reference_fires():
    src = """
def _h() -> int:
    return 1

def caller():
    def inner(x=_h()):
        return x
    return inner()
"""
    diags = _check(src)
    assert len(diags) == 1
    assert "_h" in diags[0].message


def test_call_inside_lambda_body_fires():
    src = """
def _h() -> int:
    return 1

def caller():
    f = lambda: _h()
    return f()
"""
    diags = _check(src)
    assert len(diags) == 1
    assert "_h" in diags[0].message


def test_walrus_binding_in_caller_shadows_helper():
    src = """
def _cfg() -> dict:
    return {}

def caller() -> dict:
    if (_cfg := {"a": 1}):
        return _cfg
    return _cfg()
"""
    assert _check(src) == []


def test_type_checking_only_reference_in_body_not_a_call():
    src = """
from typing import TYPE_CHECKING

def _h() -> int:
    return 1

def caller() -> int:
    if TYPE_CHECKING:
        x = _h()
    return 2
"""
    assert _check(src) == []


def test_annotation_only_local_in_body_not_a_call():
    src = """
def _t() -> int:
    return 1

def caller() -> None:
    x: _t
    return None

def other() -> int:
    return _t()
"""
    diags = _check(src)
    assert len(diags) == 1
    assert "_t" in diags[0].message
    assert "other" in diags[0].message


def test_walk_matches_ast_walk_multiset():
    src = """
match command.split():
    case [action]:
        pass
    case [action, obj, *rest]:
        pass
    case {"key": value, **others}:
        pass
    case Point(x=0, y=0) | Line(a=1):
        pass
    case _ as fallback:
        pass

try:
    run()
except* ValueError as e:
    handle(e)
except* (TypeError, KeyError):
    pass

def gen[T, *Ts, **P](a, /, b=1, *args, kw=2, **kw2) -> T:
    total = [y := f(x) for x in data if (z := g(x))]
    return total

class K[T](Base, metaclass=Meta):
    attr: int = 5

type Alias[T] = list[T]
"""
    tree = ast.parse(src)
    expected = Counter(type(n).__name__ for n in ast.walk(tree))
    actual = Counter(type(n).__name__ for n in _walk(tree))
    assert actual == expected


def test_comprehension_target_wrongly_shadows_helper():
    src = """
def _x() -> int:
    return 1

def caller(xs) -> int:
    total = _x()
    doubled = [_x for _x in xs]
    return total + len(doubled)
"""
    diags = _check(src)
    assert len(diags) == 1
    assert "_x" in diags[0].message


def test_unrelated_local_binding_suppresses_violation():
    src = """
def _item() -> int:
    return 1

def unrelated() -> int:
    _item = 5
    return _item

def other() -> int:
    return _item()
"""
    diags = _check(src)
    assert len(diags) == 1
    assert "_item" in diags[0].message
    assert "other" in diags[0].message


def test_module_lambda_reference_over_pins_helper():
    src = """
def _h() -> int:
    return 1

handler = lambda: _h()

def caller() -> int:
    return _h()
"""
    diags = _check(src)
    assert len(diags) == 1
    assert "_h" in diags[0].message
    assert "caller" in diags[0].message


def test_same_class_call_via_class_name_missed():
    src = """
class H:
    @staticmethod
    def _load() -> int:
        return 1

    def run(self) -> int:
        return H._load()
"""
    diags = _check(src)
    assert len(diags) == 1
    assert "_load" in diags[0].message


def test_inherited_method_called_from_subclass_not_falsely_single_caller():
    src = """
class Base:
    def _code_str(self) -> str:
        return "x"

    def __str__(self) -> str:
        return self._code_str()

class Child(Base):
    def render(self) -> str:
        return self._code_str()
"""
    assert _check(src) == []


def test_super_call_from_subclass_suppresses_base_only_caller():
    src = """
class Base:
    def _hook(self) -> int:
        return 1

    def run(self) -> int:
        return self._hook()

class Child(Base):
    def _hook(self) -> int:
        return super()._hook() + 1
"""
    assert _check(src) == []


def test_sibling_classes_same_named_method_still_flagged():
    src = """
class Base:
    pass

class Left(Base):
    def _fit(self) -> int:
        return 1

    def run(self) -> int:
        return self._fit()

class Right(Base):
    def _fit(self) -> int:
        return 2

    def go(self) -> int:
        return self._fit()
"""
    diags = _check(src)
    assert len(diags) == 2
    assert all("_fit" in d.message for d in diags)


def test_message_reports_reference_line_not_caller_def_line():
    src = """
def _worker(x: int) -> int:
    return x

def run(xs: list[int]) -> list[int]:
    total = 0
    return [_worker(x) for x in xs]
"""
    diags = _check(src)
    assert len(diags) == 1
    assert "_worker" in diags[0].message
    assert "run" in diags[0].message
    # Line 7 is the reference; `run` itself is defined on line 5.
    assert "referenced at line 7" in diags[0].message


# FP-hardening (famous-repo sweep): a class is never the stepdown target.      #


def test_class_caller_referencing_helper_from_several_methods_is_not_flagged():
    # Distilled from pydantic `_internal/_generate_schema.py:286`, where `_extract_json_schema_info_from_field_info` is referenced by three different `GenerateSchema` methods yet collapsed into one "caller".
    src = """
def _norm(k: str) -> str:
    return k

class Big:
    def a(self) -> str:
        return _norm("a")

    def b(self) -> str:
        return _norm("b")
"""
    assert _check(src) == []


def test_class_still_counts_as_a_caller_for_multi_caller_suppression():
    # The class does not become invisible: a helper shared by a class and a
    # function has two callers and stays out of scope.
    src = """
def _shared() -> int:
    return 1

def run() -> int:
    return _shared()

class Runner:
    def go(self) -> int:
        return _shared()
"""
    assert _check(src) == []


def test_function_caller_defined_below_a_class_still_fires():
    # The class-caller guard is about the *flagged* caller only — a genuine
    # single function caller is reported even when classes sit in between.
    src = """
def _load() -> dict:
    return {}

class Unrelated:
    pass

def run() -> dict:
    return _load()
"""
    diags = _check(src)
    assert len(diags) == 1
    assert "_load" in diags[0].message
    assert "run" in diags[0].message


def test_class_scope_method_helper_still_fires():
    # In class scope every caller is a method, so the guard changes nothing.
    src = """
class Runner:
    def _load(self) -> dict:
        return {}

    def run(self) -> dict:
        return self._load()
"""
    diags = _check(src)
    assert len(diags) == 1
    assert "_load" in diags[0].message


# A duplicate-named def is not flaggable, but it IS a caller.                  #


def test_a_caller_fronted_by_overloads_counts_as_a_caller():
    """An `@overload` group used to be invisible to the caller graph."""
    src = """
from typing import overload

def _init_core_attrs(x: object) -> object:
    return x

@overload
def build(x: int) -> int: ...
@overload
def build(x: str) -> str: ...
def build(x: object) -> object:
    return _init_core_attrs(x)

def rebuild(x: object) -> object:
    return _init_core_attrs(x)
"""
    assert _check(src) == []


def test_a_caller_that_is_a_property_setter_pair_counts_as_a_caller():
    """The class-scope spelling of the same bug."""
    src = """
class Band:
    def _flush(self) -> None:
        self._dirty = False

    @property
    def nodata_value(self) -> int:
        self._flush()
        return 1

    @nodata_value.setter
    def nodata_value(self, value: int) -> None:
        self._flush()

    def data(self) -> int:
        self._flush()
        return 2
"""
    assert _check(src) == []


def test_a_helper_whose_only_caller_is_overloaded_now_fires():
    """The boundary, and the recall GAIN half of the same fix."""
    src = """
from typing import overload

def _get_pandas_df(sql: str) -> object:
    return sql

@overload
def get_df(sql: str, kind: int) -> object: ...
@overload
def get_df(sql: str, kind: str) -> object: ...
def get_df(sql: str, kind: object) -> object:
    return _get_pandas_df(sql)
"""
    diags = _check(src)
    assert len(diags) == 1
    assert "_get_pandas_df" in diags[0].message
    assert "get_df" in diags[0].message


def test_a_singledispatch_registration_is_never_a_stepdown_target():
    """`_` can suppress, but "move it below `_`" names no location."""
    src = """
import functools

class Evaluator:
    def _resolve_asset_ref(self, o: object) -> object:
        return o

    @functools.singledispatchmethod
    def run(self, o: object) -> bool:
        raise NotImplementedError

    @run.register
    def _(self, o: int) -> bool:
        return bool(self._resolve_asset_ref(o))

    @run.register
    def _(self, o: str) -> bool:
        return bool(o)
"""
    assert _check(src) == []


_ABOVE_ITS_ONLY_CALLER = """
def _parse(payload: dict) -> dict:
    return payload

def handle_request(payload: dict) -> str:
    return str(_parse(payload))
"""


def test_a_generated_file_is_skipped_by_its_header():
    """Generated code mirrors whatever its generator emits, so ordering is not ours to fix."""
    assert _check("# Code generated by openapi-generator. DO NOT EDIT.\n" + _ABOVE_ITS_ONLY_CALLER) == []


def test_a_banner_less_generated_tree_is_skipped_by_path():
    """The header half of the predicate is not enough on its own."""
    assert _check(_ABOVE_ITS_ONLY_CALLER, "src/generated/models.py") == []


def test_a_codegen_root_makes_the_subtree_generated(tmp_path: Path):
    """The other non-header signal: an ancestor holding a generator's own config."""
    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True)
    sdk = root / "sdk"
    sdk.mkdir()
    _ = (sdk / ".openapi-generator-ignore").write_text("")
    package = sdk / "client"
    package.mkdir()
    target = package / "api.py"
    _ = target.write_text(_ABOVE_ITS_ONLY_CALLER)
    assert Stepdown().check(target, _ABOVE_ITS_ONLY_CALLER) == []


def test_a_hand_written_path_still_reports():
    """Pins the surviving true positives, so widening the guard cannot go unnoticed."""
    assert len(_check(_ABOVE_ITS_ONLY_CALLER, "src/app/service.py")) == 1
