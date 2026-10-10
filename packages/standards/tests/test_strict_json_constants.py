import math
from typing import TYPE_CHECKING

import pytest

from sarj_standards.libs.json_boundary import parse_json, parse_unique_json
from sarj_standards.libs.schema_boundary import validate_local_schema


if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
@pytest.mark.parametrize("template", ["{constant}", '{{"value": {constant}}}', "[{constant}]"])
def test_strict_json_rejects_native_invalid_nonfinite_literals(constant: str, template: str) -> None:
    with pytest.raises(ValueError, match="non-finite JSON constant"):
        parse_unique_json(template.format(constant=constant))


def test_strict_json_preserves_words_and_legal_numeric_grammar() -> None:
    assert parse_unique_json('{"NaN": 1, "words": ["Infinity", "-Infinity"]}') == {
        "NaN": 1,
        "words": ["Infinity", "-Infinity"],
    }
    assert parse_unique_json("1e999") == math.inf
    assert parse_unique_json("-1e999") == -math.inf


def test_permissive_json_contract_is_preserved() -> None:
    value = parse_json("NaN")
    assert isinstance(value, float)
    assert math.isnan(value)


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_local_schema_fails_before_native_invalid_json_can_pass(tmp_path: Path, constant: str) -> None:
    schema = tmp_path / "values.schema.json"
    schema.write_text('{"maximum": ' + constant + "}")
    with pytest.raises(ValueError, match="non-finite JSON constant"):
        validate_local_schema(1, schema, (schema,))
