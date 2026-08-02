from pathlib import Path

import pytest

from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules.prefer_single_sentence_comment import PreferSingleSentenceComment


def test_two_sentences_warn_without_blocking() -> None:
    findings = PreferSingleSentenceComment().check(Path("app.py"), '"""First fact. Second fact."""\n')
    assert len(findings) == 1
    assert findings[0].severity is Severity.WARNING


def test_one_or_three_sentences_belong_elsewhere() -> None:
    rule = PreferSingleSentenceComment()
    assert rule.check(Path("app.py"), '"""One fact."""\n') == []
    assert rule.check(Path("app.py"), '"""One. Two. Three."""\n') == []


def test_wrapping_does_not_create_sentences() -> None:
    source = '"""One sentence that wraps\nonto another physical line."""\n'
    assert PreferSingleSentenceComment().check(Path("app.py"), source) == []


@pytest.mark.parametrize(
    "source",
    [
        '"""Supports e.g. compact mode."""\n',
        '"""Supports version 2.1."""\n',
        '"""See https://example.com/guide. Continue there"""\n',
        '"""Run `first. Second.` once."""\n',
    ],
)
def test_sentence_like_punctuation_inside_tokens_is_ignored(source: str) -> None:
    assert PreferSingleSentenceComment().check(Path("app.py"), source) == []


@pytest.mark.parametrize("path", [Path("generated/client.py"), Path("vendor/client.py")])
def test_generated_and_vendored_files_are_exempt(path: Path) -> None:
    assert PreferSingleSentenceComment().check(path, '"""First fact. Second fact."""\n') == []


@pytest.mark.parametrize(
    "source",
    [
        "# Copyright 2026 Example. Licensed under MIT.\nvalue = 1\n",
        "# noqa: First fact. Second fact.\nvalue = 1\n",
    ],
)
def test_licenses_and_directives_are_exempt(source: str) -> None:
    assert PreferSingleSentenceComment().check(Path("app.py"), source) == []


@pytest.mark.parametrize("decorator", ["function_tool", "app.route('/items')", "click.command()"])
def test_runtime_consumed_tool_route_and_cli_docs_are_exempt(decorator: str) -> None:
    source = f'''@{decorator}
def lookup(value: str) -> str:
    """First fact. Second fact."""
    return value
'''
    assert PreferSingleSentenceComment().check(Path("app.py"), source) == []


def test_two_unpunctuated_list_items_are_sentence_equivalents() -> None:
    source = '"""Constraints:\n- first item\n- second item\n"""\n'
    findings = PreferSingleSentenceComment().check(Path("app.py"), source)
    assert len(findings) == 1
