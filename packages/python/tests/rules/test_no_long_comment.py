from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules.no_long_comment import NoLongComment


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import RuleExample


EIGHT_SENTENCES = "One fact. Two facts. Three facts. Four facts. Five facts. Six facts. Seven facts. Eight facts."

_PUBLIC_EXAMPLES = NoLongComment.public_examples()


@pytest.mark.parametrize("example", _PUBLIC_EXAMPLES, ids=tuple(e.example_id for e in _PUBLIC_EXAMPLES))
def test_public_documentation_examples_are_executable(example: RuleExample) -> None:
    focus = example.focus_file
    assert len(NoLongComment().check(Path(focus.path), focus.source)) == example.expected_count


def test_plain_eight_sentence_module_docstring_is_a_prose_wall() -> None:
    findings = NoLongComment().check(Path("app.py"), f'"""{EIGHT_SENTENCES}"""\n')
    assert len(findings) == 1
    assert findings[0].severity is Severity.WARNING


def test_untyped_function_docstring_can_be_a_prose_wall() -> None:
    source = f'''def explain(value):
    """{EIGHT_SENTENCES}"""
    return value
'''
    assert len(NoLongComment().check(Path("app.py"), source)) == 1


def test_seven_sentences_stay_below_the_high_precision_threshold() -> None:
    source = '"""One. Two. Three. Four. Five. Six. Seven."""\n'
    assert NoLongComment().check(Path("app.py"), source) == []


def test_line_comment_rationale_is_owned_by_semantic_comment_rules() -> None:
    source = "\n".join(f"# Trace invariant fact {index}." for index in range(10)) + "\nvalue = 1\n"
    assert NoLongComment().check(Path("app.py"), source) == []


def test_multiple_paragraphs_are_deliberately_structured_documentation() -> None:
    source = '''"""One fact. Two facts. Three facts. Four facts.

Five facts. Six facts. Seven facts. Eight facts.
"""
'''
    assert NoLongComment().check(Path("app.py"), source) == []


def test_list_items_are_deliberately_structured_documentation() -> None:
    source = f'''"""{EIGHT_SENTENCES}

- fast path
- safe path
"""
'''
    assert NoLongComment().check(Path("app.py"), source) == []


def test_inline_code_is_a_technical_anchor() -> None:
    source = f'"""{EIGHT_SENTENCES} The `traceparent` value is forwarded."""\n'
    assert NoLongComment().check(Path("app.py"), source) == []


def test_phase_four_style_module_contract_is_preserved() -> None:
    source = '''"""Feasibility revenue slice.

Reads clean/funnel.parquet and writes revenue rollups.

Ground truth: `contract_value` is total lease revenue. It scales with duration.
Realized annual value divides by duration. Projection uses cohort baselines.
The result stays deterministic. Missing cohorts remain out of scope.

  realized rollups -> revenue.csv
  projection       -> model.json
"""
'''
    assert NoLongComment().check(Path("phase4.py"), source) == []


def test_fully_typed_public_function_is_api_documentation() -> None:
    source = f'''def decode(value: str) -> str:
    """{EIGHT_SENTENCES}"""
    return value
'''
    assert NoLongComment().check(Path("codec.py"), source) == []


def test_public_class_docstring_is_api_documentation() -> None:
    source = f'''class Decoder:
    """{EIGHT_SENTENCES}"""
'''
    assert NoLongComment().check(Path("codec.py"), source) == []


def test_runtime_consumed_tool_prompt_is_exempt() -> None:
    source = f'''@function_tool
def lookup(value: str) -> str:
    """{EIGHT_SENTENCES}"""
    return value
'''
    assert NoLongComment().check(Path("app.py"), source) == []


def test_generated_source_is_exempt() -> None:
    assert NoLongComment().check(Path("generated/client.py"), f'"""{EIGHT_SENTENCES}"""\n') == []


def test_schema_class_docstring_is_runtime_consumed() -> None:
    source = f'''class Payload(pydantic.BaseModel):
    """{EIGHT_SENTENCES}"""
'''
    assert NoLongComment().check(Path("models.py"), source) == []


def test_typed_sections_are_preserved() -> None:
    source = f'''def decode(value: str) -> str:
    """{EIGHT_SENTENCES}

    Args:
        value: The encoded value.

    Returns:
        The decoded value.
    """
    return value
'''
    assert NoLongComment().check(Path("codec.py"), source) == []


def test_abbreviations_urls_and_decimals_do_not_split() -> None:
    source = '"""Supports e.g. version 2.1 from https://example.com/a. One constraint."""\n'
    assert NoLongComment().check(Path("app.py"), source) == []


def test_arbitrary_count_does_not_exempt_a_prose_wall() -> None:
    source = '"""One fact. Two facts. Three facts. Four facts. Five facts. Six facts. Seven facts. It covers 3 record types."""\n'
    assert len(NoLongComment().check(Path("app.py"), source)) == 1


def test_numeric_unit_remains_a_technical_anchor() -> None:
    source = '"""One fact. Two facts. Three facts. Four facts. Five facts. Six facts. Seven facts. The deadline is 10 ms."""\n'
    assert NoLongComment().check(Path("app.py"), source) == []
