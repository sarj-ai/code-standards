from __future__ import annotations

from pathlib import Path

import pytest

from sarj_python_lint.__main__ import check_source
from sarj_python_lint.autofix import fix_source
from sarj_python_lint.rules import REGISTRY


_PATH = Path("app/source_lines.py")
_SEPARATORS = (
    pytest.param("\v", id="vertical-tab"),
    pytest.param("\f", id="form-feed"),
    pytest.param("\x1c", id="file-separator"),
    pytest.param("\x1d", id="group-separator"),
    pytest.param("\x1e", id="record-separator"),
    pytest.param("\x85", id="next-line"),
    pytest.param("\u2028", id="unicode-line-separator"),
    pytest.param("\u2029", id="unicode-paragraph-separator"),
)


@pytest.mark.parametrize("separator", _SEPARATORS)
@pytest.mark.parametrize("container", [pytest.param("literal", id="literal"), pytest.param("comment", id="comment")])
@pytest.mark.parametrize(
    "rule_ids", [pytest.param(["no-comment-cruft"], id="selected"), pytest.param(None, id="default")]
)
def test_nonphysical_separators_cannot_apply_a_diagnostic_to_different_source(
    separator: str, container: str, rule_ids: list[str] | None
) -> None:
    if container == "literal":
        source = f'DATA = """x{separator}y{separator}z\npreserve\n"""\n# --------------------\n'
    else:
        source = f"# x{separator}y{separator}z\nDATA = 'preserve'\n# --------------------\n"
    assert check_source([REGISTRY["no-comment-cruft"]()], _PATH, source)
    assert fix_source(_PATH, source, rule_ids=rule_ids) == source


@pytest.mark.parametrize("ending", [pytest.param("\n", id="lf"), pytest.param("\r\n", id="crlf")])
@pytest.mark.parametrize(
    "rule_ids", [pytest.param(["no-comment-cruft"], id="selected"), pytest.param(None, id="default")]
)
def test_ordinary_unicode_and_supported_line_endings_keep_safe_fixes(ending: str, rule_ids: list[str] | None) -> None:
    source = f"DATA = 'préservé 日本語'{ending}# --------------------{ending}"
    assert fix_source(_PATH, source, rule_ids=rule_ids) == f"DATA = 'préservé 日本語'{ending}{ending}"


@pytest.mark.parametrize(
    "rule_ids", [pytest.param(["no-comment-cruft"], id="selected"), pytest.param(None, id="default")]
)
def test_bare_carriage_returns_are_left_unchanged_until_shared_tokenizers_agree(rule_ids: list[str] | None) -> None:
    source = "DATA = 'preserve'\r# --------------------\r"
    assert fix_source(_PATH, source, rule_ids=rule_ids) == source


@pytest.mark.parametrize("separator", [*_SEPARATORS, pytest.param("\r", id="bare-carriage-return")])
def test_line_safety_refusal_keeps_existing_unknown_rule_validation(separator: str) -> None:
    source = f'DATA = """before{separator}after"""\n'
    with pytest.raises(KeyError):
        fix_source(_PATH, source, rule_ids=["missing-rule-id"])
