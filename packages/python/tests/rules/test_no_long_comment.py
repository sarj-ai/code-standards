from pathlib import Path

from sarj_python_lint.rules.no_long_comment import NoLongComment


def test_three_sentences_are_an_error() -> None:
    findings = NoLongComment().check(Path("app.py"), '"""One fact. Two facts. Three facts."""\n')
    assert len(findings) == 1
    assert findings[0].code == "SARJ091"


def test_contiguous_line_comments_are_one_group() -> None:
    source = "# First fact.\n# Second fact.\n# Third fact.\nvalue = 1\n"
    assert len(NoLongComment().check(Path("app.py"), source)) == 1


def test_three_unpunctuated_list_items_are_sentence_equivalents() -> None:
    source = '"""Supported modes:\n\n- fast path\n- safe path\n- legacy path\n"""\n'
    assert len(NoLongComment().check(Path("app.py"), source)) == 1


def test_abbreviations_urls_and_decimals_do_not_split() -> None:
    source = "# Supports e.g. version 2.1 from https://example.com/a. One constraint.\nvalue = 1\n"
    assert NoLongComment().check(Path("app.py"), source) == []


def test_runtime_consumed_tool_prompt_is_exempt() -> None:
    source = '@function_tool\ndef lookup(value: str) -> str:\n    """One. Two. Three."""\n    return value\n'
    assert NoLongComment().check(Path("app.py"), source) == []


def test_generated_source_is_exempt() -> None:
    source = '"""One. Two. Three."""\n'
    assert NoLongComment().check(Path("generated/client.py"), source) == []


def test_pr_4213_module_wall_is_an_error() -> None:
    source = '''"""Codec for structured webhook configuration carried on the URL.

The service stores configuration in query params. There is no local record of it.
Structured configuration is compressed. The payloads are highly repetitive.
Compression keeps the URL inside its length budget.
"""
'''
    assert len(NoLongComment().check(Path("query_param_codec.py"), source)) == 1


def test_schema_class_docstring_is_runtime_consumed() -> None:
    source = '''class Payload(pydantic.BaseModel):
    """One. Two. Three."""
'''
    assert NoLongComment().check(Path("models.py"), source) == []


def test_typed_sections_are_left_to_sarj092() -> None:
    source = '''def decode(value: str) -> str:
    """Decode a value.

    Args:
        value: The encoded value.

    Returns:
        The decoded value.
    """
    return value
'''
    assert NoLongComment().check(Path("codec.py"), source) == []


def test_directives_and_licenses_are_not_prose_groups() -> None:
    source = "# noqa: One. Two. Three.\n# SPDX-License-Identifier: One. Two. Three.\nvalue = 1\n"
    assert NoLongComment().check(Path("app.py"), source) == []
