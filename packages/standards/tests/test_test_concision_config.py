from __future__ import annotations

import json
from pathlib import Path
import re

import pytest


CONFIG_DIRECTORY = Path(__file__).parents[1] / "src/sarj_standards/configs"
PROFILES = ("eslint.strict.mjs", "eslint.application.mjs")
EXPECTED_RULES = {
    "jest": {
        "prefer-to-be",
    },
    "node-test": {
        "no-assert-throws-multiple-statements",
        "no-unneeded-async-rejects-callback",
        "no-useless-assertion",
    },
    "playwright": {
        "no-unnecessary-assertions",
    },
    "testing-library": {
        "no-unnecessary-act",
        "prefer-screen-queries",
    },
    "vitest": {
        "prefer-to-be",
    },
}
EXPECTED_PEERS = {
    "@vitest/eslint-plugin": "1.6.27",
    "eslint-node-test": "0.4.0",
    "eslint-plugin-jest": "29.16.6",
    "eslint-plugin-playwright": "2.11.0",
    "eslint-plugin-testing-library": "7.16.2",
}


def _rules(source: str, plugin: str) -> set[str]:
    rules = set(re.findall(rf'"{re.escape(plugin)}/([a-z0-9-]+)"\s*:', source))
    if plugin == "testing-library":
        rules -= {"custom-queries", "custom-renders", "utils-module"}
    return rules


@pytest.mark.parametrize("profile", PROFILES)
def test_profiles_enable_only_the_reviewed_dense_test_rules(profile: str) -> None:
    source = (CONFIG_DIRECTORY / profile).read_text(encoding="utf-8")
    for plugin, expected in EXPECTED_RULES.items():
        assert _rules(source, plugin) == expected


@pytest.mark.parametrize("profile", PROFILES)
def test_framework_rules_are_explicit_and_isolated(profile: str) -> None:
    source = (CONFIG_DIRECTORY / profile).read_text(encoding="utf-8")
    assert 'options.testFrameworks ?? ["vitest", "node"]' in source
    assert "Unsupported test framework" in source
    assert "files: BUN_TEST_FILES" in source
    assert "files: PLAYWRIGHT_TEST_FILES" in source
    assert "Object.keys(vitest.rules).map" in source
    assert "Object.keys(jest.rules).map" in source
    assert '["error", { isStrict: false }]' in source
    for setting in ("custom-queries", "custom-renders", "utils-module"):
        assert f'"testing-library/{setting}": "off"' in source


def test_all_imported_test_plugins_have_exact_consumer_pins() -> None:
    raw: object = json.loads(  # pyright: ignore[reportAny] -- narrowed immediately below
        (CONFIG_DIRECTORY / "eslint.peers.json").read_text(encoding="utf-8")
    )
    assert isinstance(raw, dict)
    manifest_items: list[tuple[object, object]] = list(raw.items())  # pyright: ignore[reportUnknownArgumentType]
    manifest = {key: value for key, value in manifest_items if isinstance(key, str)}
    peers = manifest["peers"]
    assert isinstance(peers, dict)
    peer_items: list[tuple[object, object]] = list(peers.items())  # pyright: ignore[reportUnknownArgumentType]
    peer_map = {key: value for key, value in peer_items if isinstance(key, str) and isinstance(value, str)}
    assert {package: peer_map.get(package) for package in EXPECTED_PEERS} == EXPECTED_PEERS
