from __future__ import annotations

import pytest

from sarj_sql_lint.rule_base import SourceLocation, source_location


@pytest.mark.parametrize("source", ["", "one line", "\n", "first\nsecond\n", "\r\n\té漢字🙂\r\nlast", "\n\n\n"])
def test_source_locations_preserve_existing_codepoint_coordinates(source: str) -> None:
    for offset in range(len(source) + 1):
        expected = SourceLocation(source.count("\n", 0, offset) + 1, offset - source.rfind("\n", 0, offset))
        assert source_location(source, offset) == expected


def test_source_location_refreshes_when_content_changes() -> None:
    assert source_location("first\nsecond", 8) == SourceLocation(2, 3)
    assert source_location("first second", 8) == SourceLocation(1, 9)
    assert source_location("first\nsecond", 8) == SourceLocation(2, 3)
