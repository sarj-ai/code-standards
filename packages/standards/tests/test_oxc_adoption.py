from __future__ import annotations

import json
from pathlib import Path

import pytest

from sarj_standards.libs.adoption import doctor, formatting, lifecycle, manifest, scaffold
from sarj_standards.libs.json_boundary import parse_json
from sarj_standards.libs.typed_containers import is_object_list


def test_setup_preserves_existing_policy_filename_and_overrides(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{"name":"fixture"}\n', encoding="utf-8")
    policy = tmp_path / "oxlint.config.js"
    source = (
        'import strict from "./oxlint.strict.mjs";\n'
        'export default { ...strict, rules: { ...strict.rules, "no-console": "off" } };\n'
    )
    policy.write_text(source, encoding="utf-8")
    plan = scaffold.build_plan(tmp_path, force=False, configs=("oxlint",), hook_manager="none")
    assert not plan.errors
    assert policy not in dict(plan.writes)
    assert not any(path.name == "oxlint.plugin.mjs" for path, _ in plan.writes)
    assert policy.read_text(encoding="utf-8") == source


def test_oxlint_config_owns_nested_project_without_legacy_entrypoint(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text("{}\n", encoding="utf-8")
    nested = tmp_path / "src" / "widget"
    nested.mkdir(parents=True)
    (nested / "oxlint.config.mts").write_text("export default {};\n", encoding="utf-8")
    source = nested / "view.ts"
    source.write_text("export const value = 1;\n", encoding="utf-8")

    selection = lifecycle.select_oxlint_commands(tmp_path, [str(source)])

    assert selection.unowned_count == 0
    assert selection.commands[0].cwd == nested
    assert selection.commands[0].argv[-1] == "view.ts"
    assert "--type-aware" in selection.commands[0].argv


def test_formatter_migration_preserves_width_quotes_tailwind_and_override(tmp_path: Path) -> None:
    (tmp_path / ".prettierrc.json").write_text(
        json.dumps(
            {
                "printWidth": 117,
                "singleQuote": True,
                "plugins": ["prettier-plugin-tailwindcss"],
                "tailwindStylesheet": "./src/styles.css",
                "tailwindFunctions": ["cn", "cva"],
                "overrides": [{"files": "*.md", "options": {"proseWrap": "always"}}],
            }
        ),
        encoding="utf-8",
    )

    migrated = formatting.oxfmt_policy(tmp_path)

    assert migrated["printWidth"] == 117
    assert migrated["singleQuote"] is True
    assert migrated["sortImports"] is False
    assert migrated["sortPackageJson"] is False
    assert migrated["sortTailwindcss"] == {"stylesheet": "./src/styles.css", "functions": ["cn", "cva"]}
    assert migrated["overrides"] == [{"files": "*.md", "options": {"proseWrap": "always"}}]
    ignores = migrated["ignorePatterns"]
    assert is_object_list(ignores)
    assert "**/*.generated.*" in ignores


def test_formatter_does_not_silently_drop_unsupported_plugins(tmp_path: Path) -> None:
    (tmp_path / ".prettierrc.json").write_text('{"plugins":["prettier-plugin-custom"]}\n', encoding="utf-8")

    with pytest.raises(ValueError, match="unsupported Prettier plugins"):
        formatting.oxfmt_policy(tmp_path)


@pytest.mark.parametrize(
    ("source", "message"),
    [
        pytest.param('{"overrides":{}}', "Prettier overrides must be an array", id="non-array"),
        pytest.param('{"overrides":[1]}', "each Prettier override must be an object", id="non-object-entry"),
        pytest.param(
            '{"overrides":[{"files":"*.md","options":[]}]}',
            "Prettier override options must be an object",
            id="non-object-options",
        ),
        pytest.param(
            '{"overrides":[{"files":"*.md","options":{"plugins":["prettier-plugin-custom"]}}]}',
            "unsupported Prettier plugins",
            id="unsupported-scoped-plugin",
        ),
    ],
)
def test_formatter_rejects_override_policies_it_cannot_preserve(tmp_path: Path, source: str, message: str) -> None:
    (tmp_path / ".prettierrc.json").write_text(source, encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        formatting.oxfmt_policy(tmp_path)


def test_formatter_preserves_package_json_policy(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{"prettier":{"semi":false,"useTabs":true}}\n', encoding="utf-8")

    migrated = formatting.oxfmt_policy(tmp_path)

    assert migrated["semi"] is False
    assert migrated["useTabs"] is True
    assert migrated["printWidth"] == 80


def test_published_policy_pins_all_oxc_engines() -> None:
    pins = manifest.oxlint_peers()

    assert pins["oxlint"] == "1.86.0"
    assert pins["oxlint-tsgolint"] == "7.0.2003"
    assert pins["oxfmt"] == "0.71.0"


@pytest.mark.parametrize("consumer_authors_plugins", [False, True], ids=("shared-policy", "consumer-plugin"))
def test_doctor_accepts_plugin_api_owned_by_its_actual_importer(
    tmp_path: Path, *, consumer_authors_plugins: bool
) -> None:
    provider_path = Path(__file__).resolve().parents[3] / "packages/typescript/package.json"
    provider = manifest.as_table(parse_json(provider_path.read_text(encoding="utf-8")))
    api_version = manifest.table_field(provider, "dependencies")["@oxlint/plugins"]
    assert api_version == manifest.oxlint_peers()["oxlint"]
    dependencies = {"@oxlint/plugins": api_version} if consumer_authors_plugins else {}
    (tmp_path / "package.json").write_text(
        json.dumps({"name": "fixture", "private": True, "devDependencies": dependencies}), encoding="utf-8"
    )
    if consumer_authors_plugins:
        (tmp_path / "native-plugin.mjs").write_text(
            'import { definePlugin } from "@oxlint/plugins";\n'
            'export default definePlugin({meta:{name:"fixture"},rules:{debugger:{create(context){'
            'return {DebuggerStatement(node){context.report({node,message:"Remove debugger."});}};'
            "}}}});\n",
            encoding="utf-8",
        )
    plan = scaffold.build_plan(tmp_path, force=False, configs=("oxlint",), hook_manager="none")
    assert not plan.errors
    scaffold.apply(plan)
    package = manifest.as_table(parse_json((tmp_path / "package.json").read_text(encoding="utf-8")))
    declared = manifest.table_field(package, "devDependencies")
    findings = doctor.diagnose_adoption_health(tmp_path)

    assert not [finding for finding in findings if finding.id == "doctor.oxlint.peer"]
    assert ("@oxlint/plugins" in declared) is consumer_authors_plugins
    assert "@sarj/oxlint-plugin" in declared


def test_selected_fix_keeps_formatting_when_lint_fix_is_excluded(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{"name":"fixture"}\n', encoding="utf-8")
    (tmp_path / ".oxfmtrc.json").write_text("{}\n", encoding="utf-8")
    (tmp_path / "view.ts").write_text("export const value=1;\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("#Document\n", encoding="utf-8")

    commands = lifecycle.selected_format_commands(tmp_path, ["view.ts", "README.md"], lint_paths=[])

    assert [command.label for command in commands] == ["Oxfmt"]
    assert tuple((commands[0].cwd / name).resolve() for name in commands[0].argv[-2:]) == (
        tmp_path / "README.md",
        tmp_path / "view.ts",
    )
    assert "--write" in commands[0].argv


def test_full_fix_formats_only_explicit_maintained_scope(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{"name":"fixture"}\n', encoding="utf-8")
    (tmp_path / ".oxfmtrc.json").write_text("{}\n", encoding="utf-8")
    (tmp_path / "view.ts").write_text("export const value=1;\n", encoding="utf-8")
    (tmp_path / "generated.ts").write_text("export const value=2;\n", encoding="utf-8")
    ecosystems = scaffold.detect(tmp_path)

    commands = lifecycle.format_commands(ecosystems, lint_paths=(), format_paths=("view.ts",), root=tmp_path)

    assert [command.label for command in commands] == ["Oxfmt"]
    assert commands[0].argv[-2] == "--"
    assert (commands[0].cwd / commands[0].argv[-1]).resolve() == tmp_path / "view.ts"
    assert lifecycle.format_commands(ecosystems, lint_paths=(), format_paths=(), root=tmp_path) == []


def test_selected_formatter_scope_can_exclude_a_selected_generated_file(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{"name":"fixture"}\n', encoding="utf-8")
    (tmp_path / ".oxfmtrc.json").write_text("{}\n", encoding="utf-8")
    for name in ("view.ts", "generated.ts"):
        (tmp_path / name).write_text("export const value=1;\n", encoding="utf-8")

    commands = lifecycle.selected_format_commands(
        tmp_path, ("view.ts", "generated.ts"), lint_paths=(), format_paths=("view.ts",)
    )

    assert [command.label for command in commands] == ["Oxfmt"]
    assert commands[0].argv[-2] == "--"
    assert (commands[0].cwd / commands[0].argv[-1]).resolve() == tmp_path / "view.ts"


def test_prettier_ignore_patterns_travel_with_migrated_formatter_policy(tmp_path: Path) -> None:
    (tmp_path / ".prettierignore").write_text("# generated SDK\nclient/**\n!client/README.md\n", encoding="utf-8")

    migrated = formatting.oxfmt_policy(tmp_path)

    ignores = migrated["ignorePatterns"]
    assert is_object_list(ignores)
    assert "client/**" in ignores
    assert "!client/README.md" in ignores


def test_biome_policy_is_not_silently_replaced_when_migrator_is_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PATH", str(tmp_path))
    (tmp_path / "biome.json").write_text('{"formatter":{"lineWidth":120}}\n', encoding="utf-8")

    with pytest.raises(ValueError, match="pinned Oxfmt dependency"):
        formatting.oxfmt_policy(tmp_path)
