from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rules.kwonly_same_type_params import KwonlySameTypeParams


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic


def _check(source: str, path: str = "python/bulbul/bulbul/calls/service.py") -> list[Diagnostic]:
    return KwonlySameTypeParams().check(Path(path), source)


# --------------------------------------------------------------------------- #
# Positive: >=2 positional params sharing one primitive annotation.            #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("params", "primitive"),
    [
        ("source_id: str, target_id: str", "str"),
        ("a: int, b: int", "int"),
        ("x: float, y: float, z: float", "float"),
        ("dry_run: bool, force: bool", "bool"),
        ("name: str, org_id: int, label: str", "str"),
        ("a: str, b: str, c: int", "str"),
    ],
)
def test_flags_same_primitive_positionals(params: str, primitive: str):
    src = f"def f({params}) -> None: ...\n"
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].code == "SARJ034"
    assert f"`{primitive}`" in diags[0].message
    assert "`f`" in diags[0].message


def test_flags_async_def():
    src = "async def move(src_key: str, dst_key: str) -> None: ...\n"
    assert len(_check(src)) == 1


def test_flags_method_excluding_self():
    src = """
class Store:
    def link(self, parent_id: str, child_id: str) -> None: ...
"""
    assert len(_check(src)) == 1


def test_flags_classmethod_excluding_cls():
    src = """
class Store:
    @classmethod
    def build(cls, key: str, value: str) -> "Store": ...
"""
    assert len(_check(src)) == 1


def test_flags_with_defaults():
    src = "def f(a: str, b: str = 'x') -> None: ...\n"
    assert len(_check(src)) == 1


def test_one_diagnostic_per_function():
    src = "def f(a: str, b: str, c: int, d: int) -> None: ...\n"
    assert len(_check(src)) == 1


# --------------------------------------------------------------------------- #
# Negative: fewer than two shared primitives.                                  #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "params",
    [
        "a: str, b: int",
        "a: str",
        "a: str, b: bytes",
        "a: int, b: float",
        "",
        "a, b",
        "a: str, b",
    ],
)
def test_allows_distinct_or_missing_annotations(params: str):
    src = f"def f({params}) -> None: ...\n"
    assert _check(src) == []


def test_self_does_not_count():
    src = """
class T:
    def f(self, a: str) -> None: ...
"""
    assert _check(src) == []


# --------------------------------------------------------------------------- #
# Negative: non-primitive / non-bare-Name annotations never group.             #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "params",
    [
        "a: Money, b: Money",
        "a: UserId, b: UserId",
        "a: str | None, b: str | None",
        "a: Optional[str], b: Optional[str]",
        "a: list[str], b: list[str]",
        "a: Any, b: Any",
        'a: "str", b: "str"',
        "a: Literal['x'], b: Literal['x']",
    ],
)
def test_allows_non_primitive_annotations(params: str):
    src = f"def f({params}) -> None: ...\n"
    assert _check(src) == []


# --------------------------------------------------------------------------- #
# Negative: exempt names and decorators.                                       #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "name",
    ["__init__", "__eq__", "__setitem__", "visit_Call", "visit_node", "test_transfer"],
)
def test_allows_exempt_names(name: str):
    src = f"def {name}(a: str, b: str) -> None: ...\n"
    assert _check(src) == []


@pytest.mark.parametrize(
    "decorator",
    [
        "override",
        "typing.override",
        "overload",
        "typing.overload",
        "abstractmethod",
        "abc.abstractmethod",
    ],
)
def test_allows_exempt_decorators(decorator: str):
    src = f"""
class T:
    @{decorator}
    def f(self, a: str, b: str) -> None: ...
"""
    assert _check(src) == []


def test_non_exempt_decorator_still_fires():
    src = """
@retry(attempts=3)
def f(a: str, b: str) -> None: ...
"""
    assert len(_check(src)) == 1


# --------------------------------------------------------------------------- #
# Negative: HTTP route handlers — FastAPI binds params by name.                #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "decorator",
    [
        'app.get("/x")',
        'router.post("/calls/{call_id}")',
        'api.put("/x")',
        'router.patch("/x")',
        'app.delete("/x")',
        'router.head("/x")',
        'app.options("/x")',
        'router.websocket("/ws")',
        "router.get",
    ],
)
def test_allows_http_route_handlers(decorator: str):
    src = f"""
@{decorator}
async def handler(org_id: str, call_id: str) -> None: ...
"""
    assert _check(src) == []


@pytest.mark.parametrize(
    "decorator",
    [
        'get("/x")',  # bare Name, not <name>.<method>
        'self.router.get("/x")',  # receiver is an attribute chain, not a Name
        'app.route("/x")',  # not an HTTP-method attribute
    ],
)
def test_non_route_shaped_decorators_still_fire(decorator: str):
    src = f"""
@{decorator}
def f(a: str, b: str) -> None: ...
"""
    assert len(_check(src)) == 1


# --------------------------------------------------------------------------- #
# Negative: test files are exempt.                                             #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "path",
    [
        "tests/test_call_store.py",
        "test_helpers.py",
        "call_store_test.py",
        "python/bulbul/tests/helpers/fakes.py",
        "conftest.py",
    ],
)
def test_skips_test_paths(path: str):
    src = "def fake_transfer(source_id: str, target_id: str) -> None: ...\n"
    assert _check(src, path) == []


def test_fires_in_non_test_paths():
    src = "def transfer(source_id: str, target_id: str) -> None: ...\n"
    assert len(_check(src, "python/bulbul/bulbul/calls/service.py")) == 1


# --------------------------------------------------------------------------- #
# Marker position: `*` / `/` exempt exactly the params they protect.           #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "params",
    [
        "a: str, *, b: str",  # only one swappable str
        "*, a: str, b: str",  # both keyword-only
        "a: str, b: str, /",  # both positional-only: deliberate API
        "a: str, /, b: str",  # one posonly + one swappable str
    ],
)
def test_allows_params_protected_by_markers(params: str):
    src = f"def f({params}) -> None: ...\n"
    assert _check(src) == []


@pytest.mark.parametrize(
    "params",
    [
        # The same-type pair sits BEFORE the marker and stays swap-prone.
        "a: str, b: str, *, c: int",
        "a: str, b: str, *args",
        "x: int, /, a: str, b: str",
    ],
)
def test_flags_same_type_pair_before_marker(params: str):
    src = f"def f({params}) -> None: ...\n"
    assert len(_check(src)) == 1


def test_kwargs_alone_is_not_a_marker():
    # **kwargs does not protect the positional params from swapping.
    src = "def f(a: str, b: str, **kwargs) -> None: ...\n"
    assert len(_check(src)) == 1


def test_lambda_never_flagged():
    assert _check("f = lambda a, b: a + b\n") == []


# --------------------------------------------------------------------------- #
# Ordering, edge cases.                                                        #
# --------------------------------------------------------------------------- #


def test_multiple_functions_sorted():
    src = """
def f(a: str, b: str) -> None: ...

def g(x: int, y: int) -> None: ...
"""
    diags = _check(src)
    assert len(diags) == 2
    assert [(d.line, d.col) for d in diags] == sorted((d.line, d.col) for d in diags)


def test_line_col_point_at_def():
    diags = _check("def f(a: str, b: str) -> None: ...\n")
    assert (diags[0].line, diags[0].col) == (1, 1)


@pytest.mark.parametrize("source", ["", "  ", "# comment\n"])
def test_empty_or_trivial_source(source: str):
    assert _check(source) == []


def test_syntax_error_returns_empty():
    assert _check("def f(:\n    pass") == []


# --------------------------------------------------------------------------- #
# FP-hardening (famous-repo sweep): callback values, overload impls,           #
# generated files, symmetric numbering.                                        #
# --------------------------------------------------------------------------- #


def test_function_referenced_as_value_is_exempt():
    # Minimized from attrs' fmt_setter family: the function is returned as a
    # value, so its signature is a callback protocol shared with other
    # implementations and cannot go keyword-only unilaterally.
    src = """
def _assign(attr_name: str, value: str, has_on_setattr: bool) -> str:
    return f"self.{attr_name} = {value}"

def _determine_setters(frozen: bool):
    return (), _assign
"""
    diags = _check(src)
    assert all("_assign" not in d.message for d in diags)


def test_function_registered_as_handler_is_exempt():
    # Minimized from trio's sphinx conf.py: the signature is pinned by the
    # framework that calls the handler.
    src = """
def autodoc_process_docstring(app, what: str, name: str, obj, options, lines) -> None:
    ...

def setup(app):
    app.connect("autodoc-process-docstring", autodoc_process_docstring)
"""
    assert _check(src) == []


def test_function_only_called_still_fires():
    src = """
def transfer(source_id: str, target_id: str) -> None: ...

def run():
    transfer("a", "b")
"""
    assert len(_check(src)) == 1


def test_overload_implementation_is_exempt():
    # Minimized from trio's _fake_net.getsockopt: the impl's positional shape
    # is pinned by its @overload stubs.
    src = """
from typing import overload

class Sock:
    @overload
    def getsockopt(self, level: int, optname: int) -> int: ...
    @overload
    def getsockopt(self, level: int, optname: int, buflen: int) -> bytes: ...
    def getsockopt(self, level: int, optname: int, buflen: int | None = None) -> int | bytes:
        raise OSError
"""
    assert _check(src) == []


def test_generated_file_is_exempt():
    # Minimized from trio's _generated_io_kqueue.py.
    src = (
        "# ******* WARNING: AUTOGENERATED! ALL EDITS WILL BE LOST ******\n"
        "def monitor_kevent(ident: int, filter: int) -> None: ...\n"
    )
    assert _check(src) == []


def test_symmetric_numeric_suffix_params_are_exempt():
    # Minimized from pydantic's almost_equal_floats: value_1/value_2 declare a
    # symmetric comparison — order genuinely does not matter.
    src = "def almost_equal_floats(value_1: float, value_2: float, *, delta: float = 1e-8) -> bool: ...\n"
    assert _check(src) == []


def test_symmetric_suffix_without_underscore_is_exempt():
    src = "def midpoint(x1: float, x2: float) -> float: ...\n"
    assert _check(src) == []


def test_distinct_stems_with_numbers_still_fire():
    src = "def link(node1_id: str, parent2_key: str) -> None: ...\n"
    assert len(_check(src)) == 1


def test_positive_distilled_from_trio_set_result():
    # Distilled TP from trio's _raises_group.ResultHolder.set_result: two
    # same-typed index parameters that are genuinely swap-prone.
    src = """
class ResultHolder:
    def set_result(self, expected: int, actual: int, result: str | None) -> None:
        self.results[actual][expected] = result
"""
    assert len(_check(src)) == 1
