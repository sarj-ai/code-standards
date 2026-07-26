from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rule_base import is_suppressed
from sarj_python_lint.rules.prefer_namedtuple_over_tuple_return import (
    PreferNamedtupleOverTupleReturn,
)


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic


def _check(source: str, path: str = "<t>.py") -> list[Diagnostic]:
    return PreferNamedtupleOverTupleReturn().check(Path(path), source)


# --- Metadata ----------------------------------------------------------------


def test_rule_identity():
    rule = PreferNamedtupleOverTupleReturn()
    assert rule.code == "SARJ026"
    assert rule.id == "prefer-namedtuple-over-tuple-return"
    assert rule.description


def test_diag_carries_code_and_message():
    diags = _check("def f() -> tuple[int, str]: ...\n")
    assert len(diags) == 1
    assert diags[0].code == "SARJ026"
    assert "NamedTuple" in diags[0].message


# --- Positive: heterogeneous positional tuple returns ------------------------


@pytest.mark.parametrize(
    "annotation",
    [
        "tuple[int, str]",
        "tuple[int, str, float]",
        "tuple[int, str, float, bytes]",
        "Tuple[int, str]",
        "typing.Tuple[int, str]",
        "tuple[list[int], int]",
        "tuple[bytes, dict[str, str], str | None]",
        "tuple[list[Snapshot], int]",
        "tuple[str, int | None]",
        "tuple[int, str, float, bytes, bool]",
    ],
)
def test_fires_on_heterogeneous_positional_tuple(annotation: str):
    diags = _check(f"def f() -> {annotation}: ...\n")
    assert len(diags) == 1, annotation
    assert diags[0].code == "SARJ026"


def test_fires_on_async_function():
    diags = _check("async def f() -> tuple[int, str]: ...\n")
    assert len(diags) == 1


def test_fires_on_str_none_element():
    diags = _check("def download() -> tuple[bytes, dict[str, str], str | None]: ...\n")
    assert len(diags) == 1


def test_fires_on_method():
    src = "class C:\n    def m(self) -> tuple[int, str]: ...\n"
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].line == 2


# --- Negative: the three permitted tuple forms + non-boundary ----------------


@pytest.mark.parametrize(
    "annotation",
    [
        "tuple[int, ...]",
        "tuple[str, ...]",
        "tuple[int, int]",
        "tuple[str, str]",
        "tuple[str, str, str]",
        "tuple[list[int], list[int]]",
        'tuple[Literal["a", "b"], int]',
        'tuple[Literal["both"], int, str]',
        "tuple[int]",
        "tuple[str]",
    ],
)
def test_does_not_fire_on_permitted_forms(annotation: str):
    diags = _check(f"def f() -> {annotation}: ...\n")
    assert diags == [], annotation


def test_does_not_fire_on_bare_tuple():
    assert _check("def f() -> tuple: ...\n") == []


def test_does_not_fire_on_non_tuple_return():
    assert _check("def f() -> list[int]: ...\n") == []
    assert _check("def f() -> dict[str, int]: ...\n") == []
    assert _check("def f() -> int: ...\n") == []


def test_does_not_fire_without_annotation():
    assert _check("def f(): ...\n") == []


def test_does_not_fire_on_private_function():
    assert _check("def _helper() -> tuple[int, str]: ...\n") == []
    assert _check("def __dunder__() -> tuple[int, str]: ...\n") == []


def test_does_not_fire_on_private_async():
    assert _check("async def _helper() -> tuple[int, str]: ...\n") == []


def test_does_not_fire_on_private_method():
    src = "class C:\n    def _m(self) -> tuple[int, str]: ...\n"
    assert _check(src) == []


# --- Line / column reporting -------------------------------------------------


def test_reports_at_function_def_line_and_col():
    src = "\n\ndef f() -> tuple[int, str]:\n    return (1, 'a')\n"
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].line == 3
    assert diags[0].col == 1


def test_reports_indented_col():
    src = "class C:\n    def m(self) -> tuple[int, str]: ...\n"
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].line == 2
    assert diags[0].col == 5


# --- Multiple, sorted --------------------------------------------------------


def test_multiple_sorted_by_line():
    src = "def a() -> tuple[int, str]: ...\ndef b() -> tuple[int, int]: ...\ndef c() -> tuple[bytes, str, None]: ...\n"
    diags = _check(src)
    assert [d.line for d in diags] == [1, 3]


# --- Edge cases --------------------------------------------------------------


def test_empty_source():
    assert _check("") == []


def test_syntax_error_returns_empty():
    assert _check("def f( -> tuple[int, str]\n") == []


def test_nested_function_fires():
    src = "def outer():\n    def inner() -> tuple[int, str]: ...\n    return inner\n"
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].line == 2


# --- Suppression -------------------------------------------------------------


def test_suppression_recognized():
    src = "def f() -> tuple[int, str]:  # sarj-noqa: SARJ026 — deliberate\n    ...\n"
    diags = _check(src)
    assert len(diags) == 1
    assert is_suppressed(src.splitlines(), diags[0].line, diags[0].code)


# --- FP-hardening (famous-repo sweep) ----------------------------------------


def test_test_file_is_exempt():
    # Minimized from trio's test helpers: an ad-hoc pair from a test fixture is
    # local scaffolding, not a public boundary.
    src = "async def make_pipe() -> tuple[PipeSendStream, PipeReceiveStream]:\n    return a, b\n"
    assert _check(src, path="src/trio/_tests/test_windows_pipes.py") == []


def test_not_implemented_stub_is_exempt():
    # Minimized from trio's SocketType.accept: the tuple shape mirrors stdlib
    # socket.accept and is not this module's to change.
    src = """
class SocketType:
    async def accept(self) -> tuple[SocketType, AddressFormat]:
        raise NotImplementedError
"""
    assert _check(src) == []


def test_not_implemented_stub_with_docstring_is_exempt():
    src = """
class SocketType:
    async def accept(self) -> tuple[SocketType, AddressFormat]:
        \"\"\"Mirror of stdlib accept.\"\"\"
        raise NotImplementedError("subclass me")
"""
    assert _check(src) == []


def test_overload_stub_is_exempt():
    src = """
@overload
def pair(x: int) -> tuple[int, str]: ...
"""
    assert _check(src) == []


def test_ellipsis_body_still_fires():
    # `...` is also the shorthand for an ordinary unwritten function — only a
    # NotImplementedError body marks an interface stub.
    src = "def download() -> tuple[bytes, str]: ...\n"
    assert len(_check(src)) == 1


def test_implemented_function_still_fires():
    src = "def run_black(file, source) -> tuple[bool, str]:\n    return True, source\n"
    assert len(_check(src)) == 1
