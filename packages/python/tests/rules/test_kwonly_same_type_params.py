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
@app.get("/x")
def f(a: str, b: str) -> None: ...
"""
    assert len(_check(src)) == 1


# --------------------------------------------------------------------------- #
# Negative: signatures that already made the positional/keyword decision.      #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "params",
    [
        "a: str, *, b: str",
        "*, a: str, b: str",
        "a: str, b: str, *, c: int",
        "a: str, b: str, /",
        "a: str, /, b: str",
        "a: str, b: str, *args",
    ],
)
def test_allows_existing_markers(params: str):
    src = f"def f({params}) -> None: ...\n"
    assert _check(src) == []


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
