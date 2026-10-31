from pathlib import Path

import pytest
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze
from sarj_python_lint.rules.no_shared_mutable_default import NoSharedMutableDefault


def _lines(source: str) -> list[int]:
    return [finding.line for finding in NoSharedMutableDefault().check(Path("service/batch.py"), source)]


def test_documented_examples() -> None:
    verify_native_rule(NoSharedMutableDefault, analyze)


@pytest.mark.parametrize(
    "annotation",
    [
        "Sequence[int]",
        "Mapping[str, int]",
        "Set[int]",
        "Iterable[int]",
        "Collection[int]",
        "Container[int]",
        "Reversible[int]",
        "Sized",
    ],
)
@pytest.mark.parametrize(
    "default", ["[]", "{}", "{1}", "list()", "dict()", "set()", "bytearray()", "[value for value in values]"]
)
def test_rejects_mutable_defaults_with_readonly_annotations(annotation: str, default: str) -> None:
    assert _lines(
        f"from collections.abc import Sequence, Mapping, Set, Iterable, Collection, Container, Reversible, Sized\ndef batch(values: {annotation} = {default}):\n    return values\n"
    ) == [2]


@pytest.mark.parametrize(
    "annotation",
    [
        "T.Optional[T.Sequence[int]]",
        "T.Sequence[int] | None",
        "T.Annotated[T.Sequence[int], 'readonly']",
        "T.Literal['value']",
        "object",
        "tuple[int, ...]",
        "str",
        "None",
    ],
)
def test_handles_native_readonly_annotation_forms(annotation: str) -> None:
    assert _lines(f"import typing as T\ndef batch(values: {annotation} = []):\n    return values\n") == [2]


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("DEFAULT = []\ndef batch(values=DEFAULT):\n    return values\n", [2]),
        ("DEFAULT = {}\nALIAS = DEFAULT\ndef batch(values=ALIAS):\n    return values\n", [3]),
        ("def outer():\n    cache = {}\n    def batch(values=cache):\n        return values\n    return batch\n", [3]),
        (
            "from collections.abc import Sequence\nasync def batch(*, values: Sequence[int]=[]):\n    return values\n",
            [2],
        ),
        ("batch = lambda values=[]: values\n", [1]),
        ("batch = lambda *, values={}: values\n", [1]),
        ("def batch(values=bytearray()):\n    return values\n", [1]),
        ("make_values = list\ndef batch(values=make_values()):\n    return values\n", [2]),
        (
            "import collections\ncontainers = collections\ndef batch(values=containers.deque()):\n    return values\n",
            [3],
        ),
        ("def batch(values=[] if condition else []):\n    return values\n", [1]),
        ("def batch(values=[] + []):\n    return values\n", [1]),
        ("def batch(values=[1] * 2):\n    return values\n", [1]),
        ("def batch(values=2 * [1]):\n    return values\n", [1]),
        ("def batch(values: object=(cache := [])):\n    return values\n", [1]),
        ("batch = lambda values=(cache := []): values\n", [1]),
        ("def batch(values: object=list[int]()):\n    return values\n", [1]),
        ("import collections\ndef batch(values: object=collections.UserList()):\n    return values\n", [2]),
        ("import collections\ndef batch(values: object=collections.UserDict()):\n    return values\n", [2]),
        (
            "import collections as containers\nfrom collections.abc import Mapping\ndef batch(values: Mapping=containers.defaultdict(list)):\n    return values\n",
            [3],
        ),
        (
            "from collections.abc import Sequence\nmake_values = list\ndef batch(values: Sequence=make_values()):\n    return values\n",
            [3],
        ),
    ],
)
def test_rejects_aliases_lambda_and_keyword_only_defaults(source: str, expected: list[int]) -> None:
    assert _lines(source) == expected


@pytest.mark.parametrize(
    "source",
    [
        "def batch(values=[]):\n    return values\n",
        "def batch(values: list[int]=[]):\n    return values\n",
        "def batch(values=(cache := [])):\n    return values\n",
        "def batch(values: 'Sequence[int]'=[]):\n    return values\n",
        "from collections.abc import Iterator\ndef batch(values: Iterator[int]=[]):\n    return values\n",
        "def batch(values=list[int]()):\n    return values\n",
        "from collections import deque as make_values\ndef batch(values=make_values()):\n    return values\n",
        "import collections\ndef batch(values=collections.UserList()):\n    return values\n",
        "import collections\ndef batch(values=collections.UserDict()):\n    return values\n",
        "from typing import Sequence\nReadonly = Sequence\ndef batch(values: Readonly=[]):\n    return values\n",
        "import typing\nannotations = typing\ndef batch(values: annotations.Sequence[int]=[]):\n    return values\n",
        "Opaque = object\ndef batch(values: Opaque=[]):\n    return values\n",
    ],
)
def test_keeps_the_native_b006_owner(source: str) -> None:
    assert _lines(source) == []


@pytest.mark.parametrize(
    "source",
    [
        "from collections.abc import Sequence\ndef batch(values: Sequence[int]=()):\n    return values\n",
        "from collections.abc import Mapping\nfrom types import MappingProxyType\ndef batch(values: Mapping[str,int]=MappingProxyType({})):\n    return values\n",
        "def batch(values=None):\n    return [] if values is None else values\n",
        "DEFAULT = ()\ndef batch(values=DEFAULT):\n    return values\n",
        "class Model:\n    values: list[int] = []\n",
        "from collections.abc import Sequence\ndef list():\n    return ()\ndef batch(values: Sequence[int]=list()):\n    return values\n",
        "from application import Sequence\ndef batch(values: Sequence=[]):\n    return values\n",
        "text = 'def batch(values=[]): pass'\n",
        "def batch(values=\n",
    ],
)
def test_accepts_immutable_defaults_unknown_types_and_malformed_source(source: str) -> None:
    assert _lines(source) == []
