from pathlib import Path

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
