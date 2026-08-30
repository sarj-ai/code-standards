from __future__ import annotations

from pathlib import Path
from typing import cast  # ruff: ignore[banned-api] -- narrow PyYAML's untyped public return at one parser boundary.

from pydantic import TypeAdapter
import yaml


_CONFIGS = Path(__file__).resolve().parents[1] / "src/sarj_standards/configs"
_VERSIONS = {
    "detekt": "1.23.8",
    "ktlint": "1.8.0",
    "mint": "0.18.0",
    "mobsfscan": "1.0.0",
    "semgrep": "1.175.0",
    "swiftformat": "0.62.1",
    "swiftformat_commit": "2226e9d89bf05a604cc985bab3dccb44ff7c8ee3",
    "swiftlint": "0.65.1",
    "swiftlint_commit": "6aba03e3d8302b33f106e0f922210f35ca4b52cf",
}
_MAPPING_ADAPTER = TypeAdapter(dict[str, object])
_MAPPING_SEQUENCE_ADAPTER = TypeAdapter(list[dict[str, object]])
_STRING_MAPPING_ADAPTER = TypeAdapter(dict[str, str])
_STRING_SEQUENCE_ADAPTER = TypeAdapter(list[str])


def _yaml_mapping(name: str) -> dict[str, object]:
    loaded = _yaml_object((_CONFIGS / name).read_text(encoding="utf-8"))
    return _MAPPING_ADAPTER.validate_python(loaded)


def _yaml_object(source: str) -> object:
    return cast("object", yaml.safe_load(source))


def _table(parent: dict[str, object], key: str) -> dict[str, object]:
    return _MAPPING_ADAPTER.validate_python(parent[key])


def _strings(parent: dict[str, object], key: str) -> list[str]:
    return _STRING_SEQUENCE_ADAPTER.validate_python(parent[key])


def test_mobile_tool_versions_and_mint_pins_are_exact() -> None:
    versions = _STRING_MAPPING_ADAPTER.validate_json(
        (_CONFIGS / "mobile-tools.versions.json").read_text(encoding="utf-8")
    )
    assert versions == _VERSIONS

    mint_lines = (_CONFIGS / "Mintfile.mobile.strict").read_text(encoding="utf-8").splitlines()
    assert mint_lines == [
        f"realm/SwiftLint@{_VERSIONS['swiftlint_commit']}",
        f"nicklockwood/SwiftFormat@{_VERSIONS['swiftformat_commit']}",
    ]


def test_swiftlint_is_strict_and_keeps_formatter_ownership_disjoint() -> None:
    config = _yaml_mapping("swiftlint.strict.yml")
    assert config["strict"] is True
    assert config["allow_zero_lintable_files"] is False
    assert "analyzer_rules" not in config
    assert {
        "comma",
        "opening_brace",
        "sorted_imports",
        "trailing_comma",
        "trailing_whitespace",
        "vertical_whitespace",
    } <= set(_strings(config, "disabled_rules"))
    assert {
        "async_without_await",
        "discarded_notification_center_observer",
        "duplicate_conditions",
        "empty_xctest_method",
        "final_test_case",
        "force_unwrapping",
        "incompatible_concurrency_annotation",
        "optional_data_string_conversion",
        "prefer_condition_list",
        "redundant_sendable",
        "return_value_from_void_function",
        "test_case_accessibility",
        "unhandled_throwing_task",
        "unowned_variable_capture",
        "weak_delegate",
        "xct_specific_matcher",
    } <= set(_strings(config, "opt_in_rules"))
    assert "baseline" not in config
    assert "custom_rules" not in config
    assert "file_header" not in config


def test_swiftformat_is_pinned_to_supported_swift_syntax() -> None:
    lines = (_CONFIGS / "swiftformat.strict").read_text(encoding="utf-8").splitlines()
    assert not any(line.startswith("--swiftversion") for line in lines)
    assert not any(line.startswith("--language-mode") for line in lines)
    assert "--maxwidth 120" in lines
    assert {
        "--disable redundantRawValues",
        "--disable redundantSelf",
        "--disable trailingClosures",
    } <= set(lines)


def test_detekt_fails_closed_and_leaves_formatting_to_ktlint() -> None:
    config = _yaml_mapping("detekt.strict.yml")
    assert _table(config, "build")["maxIssues"] == 0
    assert _table(config, "config") == {
        "validation": True,
        "warningsAsErrors": True,
        "checkExhaustiveness": True,
        "excludes": "",
    }
    assert "formatting" not in config
    complexity = _table(config, "complexity")
    coroutines = _table(config, "coroutines")
    exceptions = _table(config, "exceptions")
    potential_bugs = _table(config, "potential-bugs")
    style = _table(config, "style")
    assert _table(complexity, "CognitiveComplexMethod") == {
        "active": True,
        "threshold": 12,
    }
    assert _table(complexity, "NestedScopeFunctions")["active"] is False
    assert _table(coroutines, "GlobalCoroutineUsage")["active"] is True
    assert _table(coroutines, "InjectDispatcher")["active"] is False
    assert _table(coroutines, "SleepInsteadOfDelay")["active"] is False
    assert _table(exceptions, "NotImplementedDeclaration")["active"] is True
    assert _table(exceptions, "ObjectExtendsThrowable")["active"] is False
    assert _table(exceptions, "SwallowedException")["active"] is True
    assert _table(potential_bugs, "ElseCaseInsteadOfExhaustiveWhen")["active"] is False
    assert _table(potential_bugs, "MissingPackageDeclaration")["active"] is True
    assert _table(potential_bugs, "NullCheckOnMutableProperty")["active"] is False
    assert _table(potential_bugs, "NullableToStringCall")["active"] is False
    assert _table(potential_bugs, "PropertyUsedBeforeDeclaration")["active"] is False
    assert _table(potential_bugs, "UnreachableCode")["active"] is False
    assert _table(style, "DataClassShouldBeImmutable")["active"] is True
    for duplicate in ("MaxLineLength", "NewLineAtEndOfFile", "TrailingWhitespace", "WildcardImport"):
        assert _table(style, duplicate)["active"] is False


def test_ktlint_uses_the_official_style_without_wildcard_imports() -> None:
    text = (_CONFIGS / "ktlint.strict.editorconfig").read_text(encoding="utf-8")
    assert "ktlint_code_style = ktlint_official" in text
    assert "ktlint_standard = enabled" in text
    assert "ktlint_standard_no-wildcard-imports = enabled" in text
    assert "max_line_length = 120" in text
    assert "ij_kotlin_name_count_to_use_star_import = 2147483647" in text


def test_mobsfscan_gates_actionable_findings_without_product_policy_noise() -> None:
    raw = _yaml_object((_CONFIGS / "mobsf.strict.yml").read_text(encoding="utf-8"))
    loaded = _MAPPING_SEQUENCE_ADAPTER.validate_python(raw)
    assert len(loaded) == 1
    config = loaded[0]
    assert config["ignore-rules"] == []
    assert config["severity-filter"] == ["WARNING", "ERROR"]
    assert config["severity-overrides"] == {}


def test_mobile_configs_are_public_and_well_formed() -> None:
    names = (
        "Mintfile.mobile.strict",
        "detekt.strict.yml",
        "ktlint.strict.editorconfig",
        "mobile-tools.versions.json",
        "mobsf.strict.yml",
        "swiftformat.strict",
        "swiftlint.strict.yml",
    )
    for name in names:
        text = (_CONFIGS / name).read_text(encoding="utf-8")
        assert text.endswith("\n")
        assert "/users/" not in text.casefold()
