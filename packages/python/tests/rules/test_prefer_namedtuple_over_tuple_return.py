from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rule_base import is_suppressed
from sarj_python_lint.rules.prefer_namedtuple_over_tuple_return import (
    PreferNamedtupleOverTupleReturn,
)


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic, RuleExample


SOURCE_PATH = "python/app/profile.py"


def _check(source: str, path: str = SOURCE_PATH) -> list[Diagnostic]:
    return PreferNamedtupleOverTupleReturn().check(Path(path), source)


_PUBLIC_EXAMPLES = PreferNamedtupleOverTupleReturn.public_examples()


@pytest.mark.parametrize("example", _PUBLIC_EXAMPLES, ids=tuple(example.example_id for example in _PUBLIC_EXAMPLES))
def test_public_documentation_examples_are_executable(example: RuleExample) -> None:
    focus = example.focus_file
    assert len(_check(focus.source, str(focus.path))) == example.expected_count


def test_rule_identity_and_summary_match_narrow_boundary() -> None:
    rule = PreferNamedtupleOverTupleReturn()

    assert rule.code == "SARJ026"
    assert rule.id == "prefer-namedtuple-over-tuple-return"
    assert "Public top-level" in rule.description


@pytest.mark.parametrize(
    "source",
    [
        "def profile() -> tuple[str, int, bool]: ...\n",
        "async def profile() -> tuple[str, int, bool]: ...\n",
        "from typing import Tuple\n\ndef profile() -> Tuple[str, int, bool]: ...\n",
        "import typing\n\ndef profile() -> typing.Tuple[str, int, bool]: ...\n",
        "from typing import Tuple as RecordTuple\n\ndef profile() -> RecordTuple[str, int, bool]: ...\n",
        "import typing as t\n\ndef profile() -> t.Tuple[str, int, bool]: ...\n",
        "import builtins\n\ndef profile() -> builtins.tuple[str, int, bool]: ...\n",
        "from builtins import tuple as record_tuple\n\ndef profile() -> record_tuple[str, int, bool]: ...\n",
        "def profile() -> tuple[list[int], str, bool]: ...\n",
    ],
)
def test_flags_proven_public_heterogeneous_record(source: str) -> None:
    diagnostics = _check(source)

    assert len(diagnostics) == 1
    assert diagnostics[0].code == "SARJ026"
    assert diagnostics[0].severity.value == "warning"
    assert "typing.NamedTuple" in diagnostics[0].message


def test_reports_source_location_and_sort_order() -> None:
    source = (
        "\n"
        "def first() -> tuple[str, int, bool]: ...\n"
        "def second() -> tuple[bytes, float, None]: ...\n"
    )

    diagnostics = _check(source)
    assert [(diagnostic.line, diagnostic.col) for diagnostic in diagnostics] == [(2, 1), (3, 1)]


@pytest.mark.parametrize(
    "annotation",
    [
        "tuple[int, str]",
        "tuple[int]",
        "tuple[int, int, int]",
        "tuple[str, str, str, str]",
        "tuple[int, ...]",
        "tuple[int, str, *Ts]",
        "tuple[int, str, Unpack[Ts]]",
        "tuple[int, str, typing.Unpack[Ts]]",
        "list[tuple[int, str, bool]]",
        "Sequence[tuple[int, str, bool]]",
        "tuple[int, str, bool] | None",
        "Optional[tuple[int, str, bool]]",
        "Annotated[tuple[int, str, bool], 'record']",
        "Awaitable[tuple[int, str, bool]]",
        "Coroutine[Any, Any, tuple[int, str, bool]]",
        "tuple",
        "object",
    ],
)
def test_allows_small_homogeneous_variadic_wrapped_or_nested_tuple(annotation: str) -> None:
    assert _check(f"def profile() -> {annotation}: ...\n") == []


@pytest.mark.parametrize(
    "source",
    [
        "def profile():\n    return 'Ada', 42, True\n",
        "def profile() -> object:\n    return 'Ada', 42, True\n",
        "def _profile() -> tuple[str, int, bool]: ...\n",
        "def __profile__() -> tuple[str, int, bool]: ...\n",
        "def outer():\n    def profile() -> tuple[str, int, bool]: ...\n    return profile\n",
        "class Service:\n    def profile(self) -> tuple[str, int, bool]: ...\n",
        "@app.route('/')\ndef profile() -> tuple[dict, int, dict]: ...\n",
        "def rank() -> tuple[int, str, bool]: ...\nitems.sort(key=rank)\n",
        "def rank() -> tuple[int, str, bool]: ...\nranked = sorted(items, key=rank)\n",
        "def profile() -> 'tuple[str, int, bool]': ...\n",
        "type Profile = tuple[str, int, bool]\n\ndef profile() -> Profile: ...\n",
        "Profile = tuple[str, int, bool]\n\ndef profile() -> Profile: ...\n",
    ],
)
def test_allows_inferred_private_nested_method_stringized_or_aliased_returns(source: str) -> None:
    assert _check(source) == []


def test_reports_overloaded_public_api_once_at_implementation() -> None:
    source = (
        "from typing import overload\n\n"
        "@overload\n"
        "def profile(value: str) -> tuple[str, int, bool]: ...\n"
        "@overload\n"
        "def profile(value: bytes) -> tuple[bytes, int, bool]: ...\n"
        "def profile(value: str | bytes) -> tuple[str | bytes, int, bool]: ...\n"
    )

    diagnostics = _check(source)

    assert [(diagnostic.line, diagnostic.col) for diagnostic in diagnostics] == [(7, 1)]


@pytest.mark.parametrize(
    "source",
    [
        "import builtins\n\ndef profile() -> tuple[int, builtins.int, int]: ...\n",
        "from builtins import int as Integer\n\ndef profile() -> tuple[int, Integer, int]: ...\n",
    ],
)
def test_allows_semantically_homogeneous_builtin_annotations(source: str) -> None:
    assert _check(source) == []


@pytest.mark.parametrize(
    "source",
    [
        "class tuple:\n    pass\n\ndef profile() -> tuple[str, int, bool]: ...\n",
        "from fake import tuple\n\ndef profile() -> tuple[str, int, bool]: ...\n",
        "import fake as typing\n\ndef profile() -> typing.Tuple[str, int, bool]: ...\n",
        "from fake import Tuple\n\ndef profile() -> Tuple[str, int, bool]: ...\n",
        "from fake import *\n\ndef profile() -> tuple[str, int, bool]: ...\n",
    ],
)
def test_allows_unproven_tuple_bindings(source: str) -> None:
    assert _check(source) == []


@pytest.mark.parametrize(
    "path",
    [
        "tests/test_profile.py",
        "python/common/testing/builders.py",
        "python/app/fakes/profile.py",
        "docs/example.py",
        "docs_src/example.py",
    ],
)
def test_skips_nonproduction_paths(path: str) -> None:
    assert _check("def profile() -> tuple[str, int, bool]: ...\n", path) == []


@pytest.mark.parametrize(
    "header",
    [
        "# Generated by protoc. Do not edit.\n",
        '"""Code generated by Speakeasy. DO NOT EDIT."""\n',
    ],
)
def test_skips_generated_source(header: str) -> None:
    assert _check(header + "def profile() -> tuple[str, int, bool]: ...\n") == []


def test_documentation_named_directory_does_not_hide_production_source() -> None:
    assert len(_check("def profile() -> tuple[str, int, bool]: ...\n", "src/documentation/profile.py")) == 1


def test_opaque_key_alias_cycle_does_not_crash() -> None:
    source = (
        "def _key() -> tuple[int, str]: ...\n"
        "value = _key()\n"
        "value = value\n"
    )

    assert _check(source) == []


def test_suppression_is_recognized() -> None:
    source = "def profile() -> tuple[str, int, bool]:  # sarj-noqa: SARJ026 — wire compatibility\n    ...\n"
    diagnostic = _check(source)[0]

    assert is_suppressed(source.splitlines(), diagnostic.line, diagnostic.code)


@pytest.mark.parametrize("source", ["", "# comment\n", "def broken( -> tuple[str, int, bool]:\n"])
def test_allows_empty_or_invalid_source(source: str) -> None:
    assert _check(source) == []
