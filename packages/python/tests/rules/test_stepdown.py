import ast
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rules.stepdown import (
    Stepdown,
    _walk,  # pyright: ignore[reportPrivateUsage]  # sarj-noqa: SARJ048 — parity test for the rule's inlined AST walker vs ast.walk
)


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic, RuleExample


def _check(source: str, path: str = "svc.py") -> list[Diagnostic]:
    return Stepdown().check(Path(path), source)


@pytest.mark.parametrize("decorator", ["final", "override", "classmethod", "staticmethod"])
def test_shadowed_decorator_is_a_definition_order_barrier(decorator: str) -> None:
    source = f"""
def {decorator}(function):
    function()
    return function
def _helper():
    return 1
@{decorator}
def caller():
    return _helper()
"""
    assert _check(source) == []


def test_lambda_walrus_binding_does_not_reference_module_helper() -> None:
    assert _check("def _helper(): return 1\ndef caller(): return lambda: ((_helper := lambda: 2), _helper())\n") == []


_PUBLIC_EXAMPLES = Stepdown.public_examples()


@pytest.mark.parametrize("example", _PUBLIC_EXAMPLES, ids=tuple(e.example_id for e in _PUBLIC_EXAMPLES))
def test_public_documentation_examples_are_executable(example: RuleExample) -> None:
    focus = example.focus_file
    assert len(_check(focus.source, str(focus.path))) == example.expected_count


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


def test_cli_entrypoint_keeps_conventional_main_last() -> None:
    assert _check("def _parse(): return 1\ndef main(): return _parse()\n", "__main__.py") == []


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


def test_helper_used_as_value_reference_is_excluded():
    src = """
def _h() -> int:
    return 1

def caller():
    return _h
"""
    assert _check(src) == []


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


def test_module_lambda_reference_pins_helper():
    src = """
def _h() -> int:
    return 1

handler = lambda: _h()

def caller() -> int:
    return _h()
"""
    assert _check(src) == []


def test_lambda_parameter_shadow_does_not_pin_module_helper():
    src = """
handler = lambda _h: _h()

def _h() -> int:
    return 1

def caller() -> int:
    return _h()
"""
    diags = _check(src)
    assert len(diags) == 1
    assert "_h" in diags[0].message


def test_comprehension_target_only_does_not_create_a_helper_reference():
    src = """
def _h() -> int:
    return 1

def caller(functions) -> list[int]:
    return [_h() for _h in functions]
"""
    assert _check(src) == []


def test_nested_binding_does_not_hide_an_outer_helper_call():
    src = """
def _h() -> int:
    return 1

def caller() -> int:
    def nested() -> int:
        _h = 2
        return _h
    return _h() + nested()
"""
    diags = _check(src)
    assert len(diags) == 1
    assert "caller" in diags[0].message


def test_decorated_helper_and_caller_are_definition_order_barriers():
    decorated_helper = """
@register
def _h() -> int:
    return 1

def caller() -> int:
    return _h()
"""
    decorated_caller = """
def _h() -> int:
    return 1

@register
def caller() -> int:
    return _h()
"""
    assert _check(decorated_helper) == []
    assert _check(decorated_caller) == []


@pytest.mark.parametrize("path", ["service_test.py", "pkg/test/helpers.py"])
def test_shared_test_path_conventions_are_skipped(path: str):
    assert _check("def _h(): ...\n\ndef caller():\n    return _h()\n", path=path) == []


def test_extra_whitespace_before_a_private_name_does_not_disable_the_rule():
    diags = _check("def  _h(): ...\n\ndef caller():\n    return _h()\n")
    assert len(diags) == 1


def test_global_declaration_pins_a_mutable_helper_binding():
    src = """
def _h() -> int:
    return 1

def install() -> None:
    global _h
    _h = make_helper()

def caller() -> int:
    return _h()
"""
    assert _check(src) == []


def test_dynamic_attribute_reference_pins_a_method():
    src = """
class Service:
    def _load(self) -> int:
        return 1

    def run(self) -> int:
        return self._load()

    def dynamic(self) -> int:
        return getattr(self, "_load")()
"""
    assert _check(src) == []


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


def test_unknown_receiver_reference_pins_a_same_named_private_helper():
    src = """
class GraphNode:
    def _calculate_depth(self) -> int:
        return 1

    def evaluate_self(self) -> int:
        return self._calculate_depth()

    def evaluate_peer(self, peer: "GraphNode") -> int:
        return peer._calculate_depth()
"""
    assert _check(src) == []


def test_deep_unknown_receiver_reference_also_pins_helper():
    src = """
class Graph:
    def _load(self) -> int:
        return 1

    def load_self(self) -> int:
        return self._load()

    def load_child(self, node) -> int:
        return node.child._load()
"""
    assert _check(src) == []


def test_unknown_receiver_with_a_different_attribute_does_not_pin_helper():
    src = """
class Loader:
    def _load(self) -> int:
        return 1

    def run(self) -> int:
        return self._load()

    def inspect_peer(self, peer) -> int:
        return peer._save()
"""
    assert len(_check(src)) == 1


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


def test_class_execution_is_a_definition_order_barrier():
    src = """
def _load() -> dict:
    return {}

class Unrelated:
    pass

def run() -> dict:
    return _load()
"""
    assert _check(src) == []


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


def test_overload_decorators_remain_definition_order_barriers():
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
    assert _check(src) == []


def test_a_singledispatch_registration_is_never_a_stepdown_target():
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
    assert _check(f"# Code generated by openapi-generator. DO NOT EDIT.\n{_ABOVE_ITS_ONLY_CALLER}") == []


def test_a_banner_less_generated_tree_is_skipped_by_path():
    assert _check(_ABOVE_ITS_ONLY_CALLER, "src/generated/models.py") == []


def test_a_codegen_root_makes_the_subtree_generated(tmp_path: Path):
    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True)
    sdk = root / "sdk"
    sdk.mkdir()
    (sdk / ".openapi-generator-ignore").write_text("")
    package = sdk / "client"
    package.mkdir()
    target = package / "api.py"
    target.write_text(_ABOVE_ITS_ONLY_CALLER)
    assert Stepdown().check(target, _ABOVE_ITS_ONLY_CALLER) == []


def test_a_hand_written_path_still_reports():
    assert len(_check(_ABOVE_ITS_ONLY_CALLER, "src/app/service.py")) == 1


@pytest.mark.parametrize("use", ["return _helper", "register(_helper)", "yield _helper"])
def test_escaped_callable_is_not_a_sole_caller(use: str) -> None:
    assert _check(f"def _helper(): return 1\ndef caller():\n    {use}\n") == []


def test_local_callable_alias_with_only_calls_establishes_caller() -> None:
    source = "def _helper(): return 1\ndef caller():\n    invoke = _helper\n    return invoke()\n"
    assert len(_check(source)) == 1


@pytest.mark.parametrize("use", ["return invoke", "register(invoke)", "invoke = replacement\n    return invoke()"])
def test_escaping_or_reassigned_callable_alias_pins_helper(use: str) -> None:
    source = f"def _helper(): return 1\ndef caller():\n    invoke = _helper\n    {use}\n"
    assert _check(source) == []


@pytest.mark.parametrize("between", ["run_startup()", "state = 2", "if enabled:\n    run_startup()"])
def test_executable_statement_is_a_movement_barrier(between: str) -> None:
    source = f"def _helper(value=state): return value\n{between}\ndef caller(): return _helper()\n"
    assert _check(source) == []


@pytest.mark.parametrize("signature", ["value=initialize()", "value: initialize()", "*, value=initialize()"])
def test_definition_time_execution_is_a_movement_barrier(signature: str) -> None:
    source = f"def _helper(): return 1\ndef unrelated({signature}): pass\ndef caller(): return _helper()\n"
    assert _check(source) == []


def test_redefining_a_captured_default_is_a_movement_barrier() -> None:
    source = "def capture(): pass\ndef _helper(value=capture): return value()\ndef capture(): pass\ndef caller(): return _helper()\n"
    assert _check(source) == []


def test_comprehension_walrus_binds_the_containing_function() -> None:
    source = "def _helper(): return 1\ndef caller(values):\n    [(_helper := value) for value in values]\n    return _helper()\n"
    assert _check(source) == []


def test_comprehension_walrus_inside_lambda_does_not_bind_outer_function() -> None:
    source = "def _helper(): return 1\ndef caller():\n    nested = lambda values: [(_helper := value) for value in values]\n    return _helper()\n"
    assert len(_check(source)) == 1


def test_nested_sibling_helpers_in_a_declaration_region_are_checked() -> None:
    source = "def outer():\n    def _helper(): return 1\n    def caller(): return _helper()\n    return caller()\n"
    assert len(_check(source)) == 1


def test_nested_sibling_helper_cannot_cross_eager_use() -> None:
    source = "def outer():\n    def _helper(): return 1\n    value = _helper()\n    def caller(): return _helper()\n    return caller() + value\n"
    assert _check(source) == []


def test_nested_class_reference_pins_module_helper() -> None:
    source = "def _helper(): return 1\ndef caller():\n    return _helper()\ndef other():\n    class Nested:\n        def run(this): return _helper()\n    return Nested\n"
    assert _check(source) == []


@pytest.mark.parametrize("receiver", ["this", "instance", "klass"])
def test_actual_receiver_parameter_establishes_method_caller(receiver: str) -> None:
    source = f"class Service:\n    def _helper({receiver}): return 1\n    def caller({receiver}): return {receiver}._helper()\n"
    assert len(_check(source)) == 1


def test_stable_receiver_alias_establishes_method_caller() -> None:
    source = "class Service:\n    def _helper(this): return 1\n    def caller(this):\n        receiver = this\n        return receiver._helper()\n"
    assert len(_check(source)) == 1


def test_stable_bound_method_alias_establishes_method_caller() -> None:
    source = "class Service:\n    def _helper(this): return 1\n    def caller(this):\n        invoke = this._helper\n        return invoke()\n"
    assert len(_check(source)) == 1


def test_rebound_receiver_does_not_establish_method_caller() -> None:
    source = "class Service:\n    def _helper(self): return 1\n    def caller(self):\n        self = another\n        return self._helper()\n"
    assert _check(source) == []


def test_staticmethod_parameter_named_self_is_not_a_receiver() -> None:
    source = "class Service:\n    def _helper(self): return 1\n    @staticmethod\n    def caller(self): return self._helper()\n"
    assert _check(source) == []


def test_method_reference_hidden_in_nested_class_pins_helper() -> None:
    source = "class Service:\n    def _helper(self): return 1\n    def caller(self): return self._helper()\n    def other(self):\n        class Nested:\n            def run(inner): return self._helper()\n        return Nested\n"
    assert _check(source) == []


@pytest.mark.parametrize(
    ("preamble", "decorator"),
    [("import builtins as b", "b.classmethod"), ("from builtins import classmethod as cm", "cm")],
)
def test_qualified_builtin_decorator_and_actual_class_receiver(preamble: str, decorator: str) -> None:
    source = f"{preamble}\nclass Service:\n    @{decorator}\n    def _helper(klass): return 1\n    @{decorator}\n    def caller(klass): return klass._helper()\n"
    assert len(_check(source)) == 1


def test_unrelated_local_builtin_shadow_does_not_hide_classmethod() -> None:
    source = "def unrelated(classmethod): return classmethod\nclass Service:\n    @classmethod\n    def _helper(klass): return 1\n    @classmethod\n    def caller(klass): return klass._helper()\n"
    assert len(_check(source)) == 1


def test_class_scope_builtin_shadow_is_not_transparent() -> None:
    source = "class Service:\n    classmethod = register\n    @classmethod\n    def _helper(klass): return 1\n    @classmethod\n    def caller(klass): return klass._helper()\n"
    assert _check(source) == []


def test_actual_receiver_in_subclass_prevents_sole_caller_claim() -> None:
    source = "class Base:\n    def _helper(this): return 1\n    def caller(this): return this._helper()\nclass Child(Base):\n    def other(instance): return instance._helper()\n"
    assert _check(source) == []


def test_nonlocal_rebinding_pins_nested_helper() -> None:
    source = "def outer():\n    def _helper(): return 1\n    def mutate():\n        nonlocal _helper\n        _helper = replacement\n    def caller(): return _helper()\n    return caller()\n"
    assert _check(source) == []


def test_nonlocal_rebinding_pins_method_receiver() -> None:
    source = "class Service:\n    def _helper(this): return 1\n    def caller(this):\n        def mutate():\n            nonlocal this\n            this = replacement\n        mutate()\n        return this._helper()\n"
    assert _check(source) == []


def test_walrus_in_nested_default_binds_the_containing_function() -> None:
    source = "def _helper(): return 1\ndef caller():\n    def nested(value=(_helper := replacement)): pass\n    return _helper()\n"
    assert _check(source) == []


def test_walrus_in_nested_default_rebinds_method_receiver() -> None:
    source = "class Service:\n    def _helper(this): return 1\n    def caller(this):\n        def nested(value=(this := replacement)): pass\n        return this._helper()\n"
    assert _check(source) == []


def test_dynamic_attribute_name_prevents_a_sole_method_caller_claim() -> None:
    source = "class Service:\n    def _helper(self): return 1\n    def caller(self): return self._helper()\n    def other(self, key): return getattr(self, key)()\n"
    assert _check(source) == []


def test_rebound_class_name_prevents_a_sole_method_caller_claim() -> None:
    source = "class Service:\n    @staticmethod\n    def _helper(): return 1\n    @staticmethod\n    def caller(): return Service._helper()\nService = Other\n"
    assert _check(source) == []


def test_late_class_import_cannot_prove_an_earlier_decorator_builtin() -> None:
    source = "sm = custom\nclass Service:\n    @sm\n    def _helper(): return 1\n    @staticmethod\n    def caller(): return Service._helper()\n    from builtins import staticmethod as sm\n"
    assert _check(source) == []


@pytest.mark.parametrize(
    "body",
    ["return lambda: _helper()", "def nested(): return _helper()\n    return nested", "register(lambda: _helper())"],
)
def test_escaping_closure_does_not_establish_a_sole_caller(body: str) -> None:
    assert _check(f"def _helper(): return 1\ndef caller():\n    {body}\n") == []


def test_immediately_called_lambda_establishes_a_sole_caller() -> None:
    assert len(_check("def _helper(): return 1\ndef caller(): return (lambda: _helper())()\n")) == 1


def test_helper_returning_itself_is_an_escaped_callable() -> None:
    assert _check("def _helper(): return _helper\ndef caller(): return _helper()\n") == []
