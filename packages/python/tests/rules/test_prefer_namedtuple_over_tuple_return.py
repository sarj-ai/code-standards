from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rule_base import RuleExample, is_suppressed
from sarj_python_lint.rules.prefer_namedtuple_over_tuple_return import (
    PreferNamedtupleOverTupleReturn,
)


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic


def _check(source: str, path: str = "<t>.py") -> list[Diagnostic]:
    return PreferNamedtupleOverTupleReturn().check(Path(path), source)


_PUBLIC_EXAMPLES = PreferNamedtupleOverTupleReturn.public_examples()


@pytest.mark.parametrize("example", _PUBLIC_EXAMPLES, ids=tuple(e.example_id for e in _PUBLIC_EXAMPLES))
def test_public_documentation_examples_are_executable(example: RuleExample) -> None:
    focus = example.focus_file
    assert len(PreferNamedtupleOverTupleReturn().check(Path(focus.path), focus.source)) == example.expected_count


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


@pytest.mark.parametrize(
    "annotation",
    [
        "tuple[int, ...]",
        "tuple[str, ...]",
        "tuple[int]",
        "tuple[str]",
    ],
)
def test_does_not_fire_on_permitted_forms(annotation: str):
    diags = _check(f"def f() -> {annotation}: ...\n")
    assert diags == [], annotation


@pytest.mark.parametrize(
    "annotation",
    [
        "tuple[int, int]",
        "tuple[str, str]",
        "tuple[str, str, str]",
        "tuple[list[int], list[int]]",
        'tuple[Literal["a", "b"], int]',
        'tuple[Literal["both"], int, str]',
        "tuple[int, str] | None",
        "Optional[tuple[int, str]]",
        "Union[None, tuple[int, str]]",
        'Annotated[tuple[int, str], "pair"]',
        "Awaitable[tuple[int, str]]",
        "Coroutine[Any, Any, tuple[int, str]]",
    ],
)
def test_fires_on_every_fixed_tuple_return_shape(annotation: str):
    assert len(_check(f"def f() -> {annotation}: ...\n")) == 1


def test_does_not_fire_on_bare_tuple():
    assert _check("def f() -> tuple: ...\n") == []


@pytest.mark.parametrize(
    "annotation",
    [
        pytest.param("list[int]", id="list"),
        pytest.param("dict[str, int]", id="dict"),
        pytest.param("int", id="scalar"),
    ],
)
def test_does_not_fire_on_non_tuple_return(annotation: str) -> None:
    assert _check(f"def f() -> {annotation}: ...\n") == []


def test_does_not_fire_without_annotation():
    assert _check("def f(): ...\n") == []


def test_fires_on_inferred_tuple_literal_return():
    assert len(_check("def f():\n    return 1, 'a'\n")) == 1


def test_explicit_non_tuple_contract_wins_over_tuple_implementation():
    assert _check("def f() -> object:\n    return 1, 'a'\n") == []


def test_private_owning_class_is_not_a_public_boundary():
    assert _check("class _Internal:\n    def pair(self) -> tuple[int, str]: ...\n") == []


def test_does_not_fire_on_private_function():
    assert _check("def _helper() -> tuple[int, str]: ...\n") == []
    assert _check("def __dunder__() -> tuple[int, str]: ...\n") == []


def test_does_not_fire_on_private_async():
    assert _check("async def _helper() -> tuple[int, str]: ...\n") == []


def test_does_not_fire_on_private_method():
    src = "class C:\n    def _m(self) -> tuple[int, str]: ...\n"
    assert _check(src) == []


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


def test_multiple_sorted_by_line():
    src = "def a() -> tuple[int, str]: ...\ndef b() -> tuple[int, int]: ...\ndef c() -> tuple[bytes, str, None]: ...\n"
    diags = _check(src)
    assert [d.line for d in diags] == [1, 2, 3]


def test_empty_source():
    assert _check("") == []


def test_syntax_error_returns_empty():
    assert _check("def f( -> tuple[int, str]\n") == []


def test_nested_function_is_exempt():
    # A closure has no callers outside its enclosing frame, so its pair never
    # crosses the boundary this rule guards.
    src = "def outer():\n    def inner() -> tuple[int, str]: ...\n    return inner\n"
    assert _check(src) == []


def test_suppression_recognized():
    src = "def f() -> tuple[int, str]:  # sarj-noqa: SARJ026 — deliberate\n    ...\n"
    diags = _check(src)
    assert len(diags) == 1
    assert is_suppressed(src.splitlines(), diags[0].line, diags[0].code)


def test_test_file_is_exempt():
    # Minimized from trio's test helpers: an ad-hoc pair from a test fixture is
    # local scaffolding, not a public boundary.
    src = "async def make_pipe() -> tuple[PipeSendStream, PipeReceiveStream]:\n    return a, b\n"
    assert _check(src, path="src/trio/_tests/test_windows_pipes.py") == []


@pytest.mark.parametrize("path", ["docs_src/tutorial.py", "docs/examples/tutorial.py"])
def test_documentation_examples_are_exempt(path: str) -> None:
    assert not _check("def pair() -> tuple[int, str]: ...", path)


def test_documentation_directory_name_does_not_hide_production_source() -> None:
    assert _check("def pair() -> tuple[int, str]: ...", "src/documentation/pair.py")


def test_not_implemented_stub_still_bans_a_new_tuple_contract():
    # Minimized from trio's SocketType.accept: the tuple shape mirrors stdlib
    # socket.accept and is not this module's to change.
    src = """
class SocketType:
    async def accept(self) -> tuple[SocketType, AddressFormat]:
        raise NotImplementedError
"""
    assert len(_check(src)) == 1


def test_not_implemented_stub_with_docstring_still_bans_a_new_tuple_contract():
    src = """
class SocketType:
    async def accept(self) -> tuple[SocketType, AddressFormat]:
        \"\"\"Mirror of stdlib accept.\"\"\"
        raise NotImplementedError("subclass me")
"""
    assert len(_check(src)) == 1


def test_not_implemented_stub_with_other_statements_still_fires():
    src = """
class SocketType:
    async def accept(self) -> tuple[SocketType, AddressFormat]:
        log.warning("not implemented")
        raise NotImplementedError
"""
    assert len(_check(src)) == 1


def test_overload_only_tuple_contract_fires_once():
    src = """
@overload
def pair(x: int) -> tuple[int, str]: ...
"""
    assert len(_check(src)) == 1


def test_qualified_overload_only_tuple_contract_fires_once():
    src = """
@typing.overload
def pair(x: int) -> tuple[int, str]: ...
"""
    assert len(_check(src)) == 1


def test_ellipsis_body_still_fires():
    # `...` is also the shorthand for an ordinary unwritten function — only a
    # NotImplementedError body marks an interface stub.
    src = "def download() -> tuple[bytes, str]: ...\n"
    assert len(_check(src)) == 1


def test_implemented_function_still_fires():
    src = "def run_black(file, source) -> tuple[bool, str]:\n    return True, source\n"
    assert len(_check(src)) == 1


def test_sort_key_closure_is_exempt():
    # Minimized from rich/rich/scope.py:45 and rich/rich/_inspect.py:128 — a
    # `sorted(key=...)` function MUST return a tuple.
    src = """
def render_scope(scope):
    def sort_items(item: tuple[str, Any]) -> tuple[bool, str]:
        key, _value = item
        return (not key.startswith("__"), key.lower())

    return sorted(scope.items(), key=sort_items)
"""
    assert _check(src) == []


def test_method_nested_in_a_function_is_exempt():
    src = """
def build():
    class Inner:
        def pair(self) -> tuple[int, str]: ...
    return Inner
"""
    assert _check(src) == []


def test_module_level_function_still_fires_after_a_nested_one():
    # The closure skip must not swallow the functions that follow it.
    src = """
def outer():
    def inner() -> tuple[int, str]: ...
    return inner


def public() -> tuple[bytes, str]: ...
"""
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].line == 7


def test_override_decorated_method_is_exempt():
    src = """
class APIRoute(Route):
    @override
    def matches(self, scope: Scope) -> tuple[Match, Scope]: ...
"""
    assert _check(src) == []


def test_typing_qualified_override_decorator_is_exempt():
    src = """
class APIRoute(Route):
    @typing.override
    def matches(self, scope: Scope) -> tuple[Match, Scope]: ...
"""
    assert _check(src) == []


def test_super_delegating_method_is_exempt():
    # Minimized from fastapi/fastapi/routing.py:825 — starlette's BaseRoute
    # pins the shape of `matches`.
    src = """
class APIWebSocketRoute(routing.WebSocketRoute):
    def matches(self, scope: Scope) -> tuple[Match, Scope]:
        match, child_scope = super().matches(scope)
        return match, child_scope
"""
    assert _check(src) == []


def test_super_call_to_a_different_method_still_fires():
    src = """
class C(Base):
    def matches(self, scope: Scope) -> tuple[Match, Scope]:
        super().__init__()
        return Match.NONE, {}
"""
    assert len(_check(src)) == 1


def test_class_reimplementing_its_same_named_base_is_exempt():
    # Minimized from anyio/src/anyio/_backends/_trio.py:617 —
    # `class UDPSocket(_TrioSocketMixin, abc.UDPSocket)` implements its own ABC.
    src = """
class UDPSocket(_TrioSocketMixin, abc.UDPSocket):
    async def receive(self) -> tuple[bytes, IPSockAddrType]: ...
"""
    assert _check(src) == []


def test_shared_method_name_across_classes_with_foreign_bases_is_exempt():
    # Minimized from fastapi/fastapi/routing.py: six classes declare
    # `matches(scope) -> tuple[Match, Scope]`, starlette's BaseRoute contract.
    src = """
class _FrontendRoute(BaseRoute):
    def matches(self, scope: Scope) -> tuple[Match, Scope]: ...


class _IncludedRouter(BaseRoute):
    def matches(self, scope: Scope) -> tuple[Match, Scope]: ...
"""
    assert _check(src) == []


def test_shared_method_name_on_locally_defined_bases_still_fires():
    # You own the base, so you own the shape.
    src = """
class Base:
    pass


class A(Base):
    def pair(self) -> tuple[int, str]: ...


class B(Base):
    def pair(self) -> tuple[int, str]: ...
"""
    assert len(_check(src)) == 2


def test_single_class_with_a_foreign_base_still_fires():
    src = """
class Handler(BaseRoute):
    def matches(self, scope: Scope) -> tuple[Match, Scope]: ...
"""
    assert len(_check(src)) == 1


@pytest.mark.parametrize("base", ["BaseModel", "Protocol", "Generic[T]", "NamedTuple", "Enum", "str"])
def test_structural_bases_do_not_mark_a_method_as_an_override(base: str):
    src = f"""
class A({base}):
    def pair(self) -> tuple[int, str]: ...


class B({base}):
    def pair(self) -> tuple[int, str]: ...
"""
    assert len(_check(src)) == 2


@pytest.mark.parametrize("body", ["pass", "...", '"""Interface declaration."""'])
def test_abstract_declaration_still_bans_a_new_tuple_contract(body: str):
    src = f"""
class UNIXSocketStream(SocketStream):
    @abstractmethod
    async def receive_fds(self, msglen: int, maxfds: int) -> tuple[bytes, list[int]]:
        {body}
"""
    assert len(_check(src)) == 1


def test_abstract_method_with_a_real_body_still_fires():
    src = """
class C(ABC):
    @abstractmethod
    def pair(self) -> tuple[int, str]:
        return 1, "a"
"""
    assert len(_check(src)) == 1


def test_undecorated_ellipsis_body_in_a_class_still_fires():
    src = "class C:\n    def pair(self) -> tuple[int, str]: ...\n"
    assert len(_check(src)) == 1


_GENERATED_PROBE = """
def f() -> tuple[str, int]:
    return "a", 1
"""


@pytest.mark.parametrize(
    "header",
    [
        '"""Code generated by Speakeasy (https://speakeasy.com). DO NOT EDIT."""',
        "# Auto-generated file, do not edit.",
        "# This file was automatically generated.",
    ],
)
def test_generated_source_is_exempt(header: str):
    assert _check(f"{header}\n{_GENERATED_PROBE}") == []


def test_the_same_body_without_a_generated_header_still_fires():
    assert len(_check(_GENERATED_PROBE)) >= 1


def test_stringized_fixed_tuple_return_still_fires():
    src = """
def pair() -> "tuple[str, int]":
    return "a", 1
"""
    assert len(_check(src)) == 1


@pytest.mark.parametrize(
    "declaration",
    [
        "Pair = tuple[str, int]",
        "Pair: TypeAlias = tuple[str, int]",
        "type Pair = tuple[str, int]",
    ],
)
def test_local_fixed_tuple_alias_still_fires(declaration: str):
    src = f"{declaration}\n\ndef pair() -> Pair:\n    return 'a', 1\n"
    assert len(_check(src)) == 1
