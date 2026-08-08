from pathlib import Path

import pytest

from sarj_python_lint.rules import _prose_budget  # sarj-noqa: SARJ048 — white-box helper test
from sarj_python_lint.rules._prose_budget import groups, sentence_units


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("See https://example.com/a. Continue there", 1),
        ("Run `first. Second.` once.", 1),
        ("Version 2.1 is stable.", 1),
        ("Use e.g. compact mode.", 1),
        ("Compare i.e. normalized values.", 1),
        ("Current vs. legacy behavior.", 1),
        ("Supports retries etc. by default.", 1),
        ("First fact. Second fact?", 2),
    ],
)
def test_sentence_units_protects_tokens_and_finds_real_boundaries(text: str, expected: int) -> None:
    assert sentence_units(text) == expected


def test_sentence_units_counts_unpunctuated_list_items() -> None:
    assert sentence_units("Modes:\n- fast path\n- safe path") == 2


def test_groups_combines_only_adjacent_aligned_comments() -> None:
    source = "# First.\n# Second.\n\n  # Third.\nvalue = 1\n"
    found = groups(Path("app.py"), source)
    assert [(group.line, group.text) for group in found] == [
        (1, "First.\nSecond."),
        (4, "Third."),
    ]


def test_groups_excludes_directives_licenses_and_inline_comments() -> None:
    source = "# noqa: One. Two. Three.\n# Copyright 2026 Example. Licensed under MIT.\nvalue = 1  # One. Two. Three.\n"
    assert groups(Path("app.py"), source) == []


@pytest.mark.parametrize(
    "path",
    [Path("generated/client.py"), Path("vendor/client.py")],
    ids=["generated", "vendor"],
)
def test_groups_excludes_generated_and_vendored_files(path: Path) -> None:
    assert groups(path, '"""One. Two. Three."""\n') == []


def test_groups_extracts_once_for_adjacent_rules(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    def extract(_path: Path, _source: str) -> list[_prose_budget.ProseGroup]:
        nonlocal calls
        calls += 1
        return [_prose_budget.ProseGroup(1, 1, "Fact.", "comment")]

    monkeypatch.setattr(_prose_budget, "_last_groups", None)
    monkeypatch.setattr(_prose_budget, "_extract_groups", extract)
    source = "# Fact.\n"

    first = groups(Path("app.py"), source)
    first.clear()

    assert len(groups(Path("app.py"), source)) == 1
    assert calls == 1
