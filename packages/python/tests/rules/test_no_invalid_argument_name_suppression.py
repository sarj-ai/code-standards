from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rules.no_invalid_argument_name_suppression import NoInvalidArgumentNameSuppression


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import RuleExample


@pytest.mark.parametrize(
    "example",
    NoInvalidArgumentNameSuppression.public_examples(),
    ids=[example.example_id for example in NoInvalidArgumentNameSuppression.public_examples()],
)
def test_public_examples_are_executable(example: RuleExample) -> None:
    assert (
        len(NoInvalidArgumentNameSuppression().check(Path(example.focus_file.path), example.focus_file.source))
        == example.expected_count
    )


@pytest.mark.parametrize(
    "comment",
    [
        "# ruff: ignore[invalid-argument-name]",
        "# noqa: N803 — vendor spelling",
        "# ruff: noqa: N803",
        "# ruff: ignore[boolean-default-value-positional-argument, invalid-argument-name]",
    ],
)
def test_flags_every_supported_suppression_spelling(comment: str) -> None:
    assert (
        len(NoInvalidArgumentNameSuppression().check(Path("app.py"), f"def f(badName: str):  {comment}\n    ...\n"))
        == 1
    )


def test_does_not_match_strings_or_unrelated_suppressions() -> None:
    source = 'TEXT = "# noqa: N803"\ndef f(value: str):  # noqa: ARG001\n    ...\n'
    assert NoInvalidArgumentNameSuppression().check(Path("app.py"), source) == []
