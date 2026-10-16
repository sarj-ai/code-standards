from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Final

from repo_standards.pull_request import is_test_path

from sarj_standards.libs.rules import RuleEngine, RuleSelector

from .runner import group_paths


if TYPE_CHECKING:
    from collections.abc import Sequence


SELECTORS: Final = frozenset(
    RuleSelector.parse(selector)
    for selector in (
        "python:test-without-explicit-oracle",
        "python:no-raw-source-text-test-oracle",
        "python:iac-source-coupled-test",
        "python:no-repeated-test-body",
        "python:no-statically-truthy-assertion",
        "eslint:duplicate-test-body",
        "eslint:no-duplicate-test-case",
        "eslint:no-tautological-expect",
        "eslint:no-bare-return-from-test-catch",
    )
)
ESLINT_RULES: Final = frozenset({"vitest/expect-expect", "vitest/valid-expect-in-promise"}) | frozenset(
    selector.native_rule_id for selector in SELECTORS if selector.engine is RuleEngine.ESLINT
)


def select_test_paths(root: Path, paths: Sequence[str]) -> list[str]:
    grouped = group_paths(paths)
    selected: list[str] = []
    for path in (*grouped.python, *grouped.typescript):
        relative = Path(path).relative_to(root).as_posix()
        if is_test_path(relative) and {"lto", "e2e", "fixtures", "fakes", "__snapshots__"}.isdisjoint(
            Path(relative).parts
        ):
            selected.append(path)
    return sorted(selected)
