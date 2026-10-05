from __future__ import annotations

from sarj_standards.libs.adoption import manifest
from tests._oxlint_config import native_policy


EXPECTED_RULES = {
    "sarj-bun": {
        "prefer-to-be",
    },
    "node-test": {
        "no-assert-throws-async",
        "no-assert-throws-multiple-statements",
        "no-unneeded-async-rejects-callback",
        "no-useless-assertion",
    },
    "sarj-playwright": {
        "missing-playwright-await",
        "no-unnecessary-assertions",
    },
    "sarj-testing-library": {
        "await-async-events",
        "await-async-queries",
        "await-async-utils",
        "no-unnecessary-act",
        "prefer-screen-queries",
    },
    "vitest": {
        "prefer-called-once",
        "prefer-expect-resolves",
        "prefer-to-be",
    },
}


def test_reviewed_test_checks_are_enabled_in_native_plugins() -> None:
    policy = native_policy(all_frameworks=True)
    configurations = [manifest.table_field(policy, "rules")]
    configurations.extend(
        manifest.table_field(manifest.as_table(override), "rules")
        for override in manifest.list_field(policy, "overrides")
    )
    for plugin, names in EXPECTED_RULES.items():
        for name in names:
            rule_id = f"{plugin}/{name}"
            levels = [_rule_level(configured, rule_id) for configured in configurations]
            assert any(isinstance(level, str) and level in {"error", "warn"} for level in levels), rule_id


def _rule_level(configured: dict[str, object], rule_id: str) -> object:
    options = manifest.list_field(configured, rule_id)
    return options[0] if options else configured.get(rule_id)


def test_dense_test_checks_have_file_scopes() -> None:
    policy = native_policy(all_frameworks=True)
    scopes = [manifest.as_table(value) for value in manifest.list_field(policy, "overrides")]
    test_scope = next(scope for scope in scopes if "vitest/prefer-to-be" in manifest.table_field(scope, "rules"))
    patterns = manifest.list_field(test_scope, "files")
    assert any(isinstance(pattern, str) and "{test,spec,e2e}" in pattern for pattern in patterns)
    assert any(isinstance(pattern, str) and "/tests/" in pattern for pattern in patterns)
    assert "vitest/prefer-to-be" not in manifest.table_field(policy, "rules")


def test_test_frameworks_register_native_source_plugins_without_an_eslint_engine() -> None:
    peers = manifest.oxlint_peers()
    assert peers["oxlint"] == "1.86.0"
    assert peers["oxlint-tsgolint"] == "7.0.2003"
    assert not any("eslint" in name for name in peers)
    plugins = manifest.list_field(native_policy(all_frameworks=True), "plugins")
    assert "vitest" in plugins
    assert "jest" in plugins
    js_plugins = manifest.list_field(native_policy(all_frameworks=True), "jsPlugins")
    specifiers = {manifest.text_field(manifest.as_table(plugin), "specifier") for plugin in js_plugins}
    aliases = {manifest.text_field(manifest.as_table(plugin), "name") for plugin in js_plugins}
    assert {"@sarj", "sarj-bun", "sarj-playwright", "sarj-testing-library"} <= aliases
    assert None not in specifiers
    assert all(
        isinstance(name, str) and "eslint-plugin-playwright" not in name and "eslint-plugin-testing-library" not in name
        for name in specifiers
    )


def test_bun_and_vitest_scopes_choose_one_assertion_namespace() -> None:
    scopes = [
        manifest.as_table(value) for value in manifest.list_field(native_policy(all_frameworks=True), "overrides")
    ]
    bun_scope = next(
        scope
        for scope in scopes
        if any(isinstance(pattern, str) and ".bun." in pattern for pattern in manifest.list_field(scope, "files"))
    )
    bun_rules = manifest.table_field(bun_scope, "rules")
    assert bun_rules["sarj-bun/prefer-to-be"] == "error"
    assert bun_rules["vitest/prefer-to-be"] == "off"
    vitest_scope = next(scope for scope in scopes if "vitest/prefer-to-be" in manifest.table_field(scope, "rules"))
    vitest_rules = manifest.table_field(vitest_scope, "rules")
    assert vitest_rules["vitest/prefer-to-be"] == "error"
    assert vitest_rules["jest/prefer-to-be"] == "off"
    assert scopes.index(bun_scope) > scopes.index(vitest_scope)
