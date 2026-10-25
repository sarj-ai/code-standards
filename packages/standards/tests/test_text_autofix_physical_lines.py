from __future__ import annotations

import tomllib
from typing import TYPE_CHECKING

import pytest

from sarj_standards.libs.linting.textlint import check_paths, fix_source
from sarj_standards.libs.yaml_boundary import parse_yaml_documents


if TYPE_CHECKING:
    from pathlib import Path


_SEPARATORS = ["\u2028", "\x85", "\f", "\u2029"]
_MARKDOWN_RULES = frozenset({"hidden-markdown-heading"})


@pytest.mark.parametrize("separator", _SEPARATORS)
@pytest.mark.parametrize("ending", ["\n", "\r\n", "\r"])
def test_unicode_virtual_fence_cannot_expose_hidden_heading_in_code(
    tmp_path: Path, separator: str, ending: str
) -> None:
    source = ending.join(
        ("```", f'literal = "before{separator}```{separator}<!--', "# Hidden", "-->", 'after"', "```", "")
    )
    path = tmp_path / "guide.md"
    path.write_bytes(source.encode())

    assert check_paths([str(path)], root=tmp_path, rule_ids=_MARKDOWN_RULES) == []
    assert fix_source(path, source, root=tmp_path, rule_ids=tuple(_MARKDOWN_RULES)) == source


@pytest.mark.parametrize("separator", _SEPARATORS)
@pytest.mark.parametrize("ending", ["\n", "\r\n", "\r"])
def test_real_hidden_heading_after_unicode_prose_is_removed_and_converges(
    tmp_path: Path, separator: str, ending: str
) -> None:
    prefix = f"Visible before{separator}visible after{ending}"
    source = prefix + ending.join(("<!--", "# Hidden", "-->", "# Current", ""))
    expected = prefix + ending * 3 + "# Current" + ending
    path = tmp_path / "guide.md"
    path.write_bytes(source.encode())
    findings = check_paths([str(path)], root=tmp_path, rule_ids=_MARKDOWN_RULES)
    assert len(findings) == 1
    assert findings[0].line == 2

    fixed = fix_source(path, source, root=tmp_path, rule_ids=tuple(_MARKDOWN_RULES))

    assert fixed == expected
    path.write_bytes(fixed.encode())
    assert check_paths([str(path)], root=tmp_path, rule_ids=_MARKDOWN_RULES) == []
    assert fix_source(path, fixed, root=tmp_path, rule_ids=tuple(_MARKDOWN_RULES)) == fixed


@pytest.mark.parametrize("separator", _SEPARATORS)
def test_markdown_suppression_uses_same_physical_lines_as_writer(tmp_path: Path, separator: str) -> None:
    source = f"Visible{separator}text\n<!-- sarj-noqa: SARJ305 -->\n<!--\n# Hidden\n-->\n"
    path = tmp_path / "guide.md"
    path.write_bytes(source.encode())
    assert check_paths([str(path)], root=tmp_path, rule_ids=_MARKDOWN_RULES) == []
    assert fix_source(path, source, root=tmp_path, rule_ids=tuple(_MARKDOWN_RULES)) == source


@pytest.mark.parametrize("separator", ["\u2028", "\x85", "\u2029"])
@pytest.mark.parametrize("ending", ["\n", "\r\n"])
def test_toml_comment_fix_preserves_parsed_unicode_multiline_string(
    tmp_path: Path, separator: str, ending: str
) -> None:
    prefix = f'payload = """before{separator}# retries is 3{separator}after"""{ending}'
    source = prefix + "# retries is 3" + ending + "retries = 3" + ending
    path = tmp_path / "config.toml"
    rule_ids = ("exact-config-comment-restatement",)

    fixed = fix_source(path, source, root=tmp_path, rule_ids=rule_ids)

    assert fixed == prefix + ending + "retries = 3" + ending
    assert tomllib.loads(source) == tomllib.loads(fixed)
    assert fix_source(path, fixed, root=tmp_path, rule_ids=rule_ids) == fixed


@pytest.mark.parametrize("separator", ["\x85", "\u2028", "\u2029"])
def test_yaml_keeps_its_native_unicode_line_break_convention(tmp_path: Path, separator: str) -> None:
    source = f"# retries is 3{separator}retries: 3{separator}"
    path = tmp_path / "config.yaml"
    rule_ids = ("exact-config-comment-restatement",)

    fixed = fix_source(path, source, root=tmp_path, rule_ids=rule_ids)

    assert fixed != source
    assert "# retries is 3" not in fixed
    assert parse_yaml_documents(source) == parse_yaml_documents(fixed)
    assert fix_source(path, fixed, root=tmp_path, rule_ids=rule_ids) == fixed
