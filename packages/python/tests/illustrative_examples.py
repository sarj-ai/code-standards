"""Execute the exact illustrative examples published by a rule."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

import pytest


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Rule, RuleExample


type ExampleTest = Callable[[RuleExample], object]


def illustrative_examples(rule: type[Rule]) -> Callable[[ExampleTest], ExampleTest]:
    """Parametrize a test with every reviewed public example owned by ``rule``."""
    examples = rule.public_examples()
    if not examples:
        msg = f"{rule.id}: illustrative example test requires at least one public example"
        raise ValueError(msg)

    def decorate(test: ExampleTest) -> ExampleTest:
        return pytest.mark.parametrize(
            "example",
            examples,
            ids=tuple(example.example_id for example in examples),
        )(pytest.mark.illustrative(test))

    return decorate
