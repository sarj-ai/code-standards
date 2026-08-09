"""Tests for strict cross-language rule catalog generation."""

from __future__ import annotations

import pytest

from sarj_standards.libs.repository import rule_catalog_artifact


def _typescript_rule() -> dict[str, object]:
    return {
        "engine": "eslint",
        "ruleId": "sample-rule",
        "code": None,
        "summary": "Report a representative problem.",
        "rationale": "The problem makes maintenance harder.",
        "remediation": "Use the supported construct.",
        "category": "maintainability",
        "languages": ["typescript"],
        "autofix": "none",
        "aliases": [],
        "limitations": [],
        "filePatterns": ["**/*.ts"],
        "references": [],
        "since": None,
        "messageIds": ["problem"],
        "optionsSchema": None,
        "examples": [
            {
                "id": "rejected",
                "scenarioId": "primary",
                "title": "Rejected source",
                "outcome": "match",
                "files": [{"path": "src/input.ts", "source": "let value = 1;\n"}],
                "fixedFiles": [],
                "focusPath": "src/input.ts",
                "expectedCount": 1,
            },
            {
                "id": "accepted",
                "scenarioId": "primary",
                "title": "Accepted source",
                "outcome": "no-match",
                "files": [{"path": "src/input.ts", "source": "const value = 1;\n"}],
                "fixedFiles": [],
                "focusPath": "src/input.ts",
                "expectedCount": 0,
            },
        ],
    }


def _object_table(value: object) -> dict[str, object]:
    assert isinstance(value, dict)
    assert all(isinstance(key, str) for key in value)  # pyright: ignore[reportUnknownVariableType]
    return value  # pyright: ignore[reportUnknownVariableType]


def _object_list(value: object) -> list[object]:
    assert isinstance(value, list)
    return value  # pyright: ignore[reportUnknownVariableType]


def test_typescript_projection_accepts_the_closed_public_shape() -> None:
    (spec,) = rule_catalog_artifact.parse_typescript_projection([_typescript_rule()])

    assert spec.key == "eslint:sample-rule"
    assert tuple(example.example_id for example in spec.examples) == (
        "rejected",
        "accepted",
    )


def test_typescript_projection_rejects_unknown_rule_fields() -> None:
    payload = _typescript_rule()
    payload["privateExamples"] = []

    with pytest.raises(ValueError, match="unexpected or missing fields"):
        rule_catalog_artifact.parse_typescript_projection([payload])


def test_typescript_projection_rejects_unknown_example_fields() -> None:
    payload = _typescript_rule()
    first = _object_table(_object_list(payload["examples"])[0])
    first["private"] = True

    with pytest.raises(ValueError, match="unexpected or missing fields"):
        rule_catalog_artifact.parse_typescript_projection([payload])


def test_typescript_projection_rejects_unknown_file_fields() -> None:
    payload = _typescript_rule()
    first = _object_table(_object_list(payload["examples"])[0])
    first_file = _object_table(_object_list(first["files"])[0])
    first_file["fixtureOrigin"] = "internal"

    with pytest.raises(ValueError, match="unexpected or missing fields"):
        rule_catalog_artifact.parse_typescript_projection([payload])


def test_typescript_projection_rejects_boolean_diagnostic_counts() -> None:
    payload = _typescript_rule()
    first = _object_table(_object_list(payload["examples"])[0])
    first["expectedCount"] = True

    with pytest.raises(TypeError, match="expectedCount must be an integer"):
        rule_catalog_artifact.parse_typescript_projection([payload])


def test_typescript_projection_rejects_forged_engine_identity() -> None:
    payload = _typescript_rule()
    payload["engine"] = "python"

    with pytest.raises(ValueError, match="invalid engine or code"):
        rule_catalog_artifact.parse_typescript_projection([payload])
