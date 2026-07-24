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
