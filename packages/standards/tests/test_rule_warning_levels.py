from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from sarj_standards.libs.rules import RuleEngine, RuleId, RuleSelector, warning_levels


if TYPE_CHECKING:
    from pathlib import Path


def test_warning_levels_load_mixed_engines_and_render_canonically(tmp_path: Path) -> None:
    path = tmp_path / "rule-warning-levels.v1.json"
    path.write_text(
        '{\n  "schemaVersion": 1,\n  "rules": ["python:second", "eslint:first"]\n}\n',
        encoding="utf-8",
    )

    selectors = warning_levels.load(path)

    assert selectors == (
        RuleSelector(RuleEngine.PYTHON, RuleId("second")),
        RuleSelector(RuleEngine.ESLINT, RuleId("first")),
    )
    assert warning_levels.render(selectors) == ('{"rules":["eslint:first","python:second"],"schemaVersion":1}\n')


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"schemaVersion": 1, "rules": [], "extra": True}, "exactly schemaVersion and rules"),
        ({"schemaVersion": 2, "rules": []}, "schemaVersion 1"),
        ({"schemaVersion": 1, "rules": "python:first"}, "rules array"),
        ({"schemaVersion": 1, "rules": [""]}, "unique non-empty canonical selectors"),
        ({"schemaVersion": 1, "rules": ["python:first", "python:first"]}, "unique non-empty canonical selectors"),
        ({"schemaVersion": 1, "rules": ["ruff:first"]}, "unknown custom-rule engine"),
        ({"schemaVersion": 1, "rules": ["python:First"]}, "lowercase kebab-case"),
    ],
)
def test_warning_levels_reject_malformed_documents(payload: object, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        _ = warning_levels.validate(payload)


def test_warning_levels_render_rejects_duplicates() -> None:
    selector = RuleSelector(RuleEngine.TEXT, RuleId("first"))

    with pytest.raises(ValueError, match="duplicate selectors"):
        _ = warning_levels.render((selector, selector))
