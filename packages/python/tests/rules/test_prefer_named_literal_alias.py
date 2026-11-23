from pathlib import Path

import pytest
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze
from sarj_python_lint.rules.prefer_named_literal_alias import PreferNamedLiteralAlias


def _lines(source: str) -> list[int]:
    return [item.line for item in PreferNamedLiteralAlias().check(Path("app/case.py"), source)]


def test_documented_examples() -> None:
    verify_native_rule(PreferNamedLiteralAlias, analyze)


@pytest.mark.parametrize(
    "source",
    [
        'from typing import Literal\ndef f() -> Literal["a", "b"] | None: ...\n',
        'import typing\ndef f(x: list[typing.Literal["a", "b"]]) -> None: ...\n',
        "from typing_extensions import Literal as L\nasync def f(*args: L[1, 2]) -> None: ...\n",
        'from typing import Literal\nstatus: Literal["played", "skipped"]\n',
    ],
    ids=["nullable-return", "nested-parameter", "aliased-import-vararg", "variable"],
)
def test_reports_inline_multi_member_literal(source: str) -> None:
    assert _lines(source) == [2]


@pytest.mark.parametrize(
    "source",
    [
        'from typing import Literal\ntype Kind = Literal["a", "b"]\ndef f(kind: Kind) -> None: ...\n',
        'from typing import Literal\nclass Event:\n    event: Literal["played"] = "played"\n',
        'from typing import Literal, cast\nvalue = cast(Literal["a", "b"], "a")\n',
        'from typing import Literal\nKind = Literal["a", "b"]\n',
        'from somewhere import Literal\ndef f(x: Literal["a", "b"]) -> None: ...\n',
        (
            'from typing import Literal\ndef f(x: Literal["a", "b"]) -> None: ...  '
            "# sarj-noqa: SARJ586 -- Wire contract mirrors an external schema.\n"
        ),
    ],
    ids=["type-alias", "single-member-tag", "runtime-cast", "assigned-alias", "foreign-literal", "suppressed"],
)
def test_accepts_named_or_single_member_literal(source: str) -> None:
    assert _lines(source) == []
