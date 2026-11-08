import json
from typing import TYPE_CHECKING

import pytest

from sarj_standards.libs.adoption import doctor, typescript_migration
from sarj_standards.libs.json_boundary import parse_json
from tests.oxlint_project import commands, project, run_native


if TYPE_CHECKING:
    from pathlib import Path


# The entrypoint `setup` scaffolded before Oxlint.
_SCAFFOLDED_ESLINT_CONFIG = """// Flat config entrypoint. `eslint.strict.ts` next to this file is SYNCED --
// `code-standards setup` overwrites it.
import strict from "./eslint.strict.ts";

// Bun, Testing Library, and Playwright are opt-in because their global test
// syntax overlaps other runners. To enable them, replace the import above with:
//   import { createConfig } from "./eslint.strict.ts";

export default [
  ...strict,

  // --- repo-specific overrides -------------------------------------------
  // {
  //   files: ["src/routes/**/*.tsx"],
  //   rules: { "unicorn/filename-case": "off" },
  // },
] satisfies import("eslint").Linter.Config[];
"""
# A customized consumer entrypoint.
_CUSTOMIZED_ESLINT_CONFIG = """import tseslint from "typescript-eslint";

import strict from "./eslint.strict.mjs";

export default [
  ...strict,

  {
    rules: {
      // Iterator.concat is not available in the deployed Workers runtime yet.
      "unicorn/prefer-iterator-concat": "off",
      "unicorn/prefer-iterator-to-array": "off",
    },
  },
  {
    ignores: ["!packages/*/src/lib/**", "eslint.strict.mjs", "**/generated/**"],
  },
  {
    files: ["**/*.{jsx,tsx}"],
    settings: { "better-tailwindcss": { cwd: "./packages/app", entryPoint: "./src/app/globals.css" } },
  },
  {
    ...tseslint.configs.disableTypeChecked,
    files: ["**/*.config.{ts,mjs,js}", "**/scripts/**"],
  },
  {
    files: ['packages/app/src/app/**/*.{ts,tsx}'],
    rules: {
      "unicorn/filename-case": ["error", { cases: { kebabCase: true }, ignore: [String.raw`\\[[A-Za-z]+\\]`] }],
    },
  },
  {
    files: ["packages/app/src/app/**/route.ts"],
    rules: { "@typescript-eslint/naming-convention": "off", "regexp/no-missing-g-flag": "warn" },
  },
  {
    files: ["packages/app/src/app/**/error.tsx"],
    rules: { "@sarj/sole-export-matches-filename": "off", "react/no-unstable-nested-components": ["error", { allowAsProps: true }] },
  },
];
"""
_CUSTOM_ESLINT_CONFIG = """import { createConfig } from "./eslint.strict.mjs";

const STRICT = createConfig({ syntaxOnlyConfigFiles: [] });
const TYPED_FILES: readonly string[] = ["src/**/*.ts"];

export default [...STRICT, { files: [...TYPED_FILES], rules: { "no-undef": "off" } }];
"""


def _repository(root: Path, files: dict[str, str]) -> Path:
    for name, text in {"package.json": '{\n  "name": "consumer",\n  "private": true\n}\n', **files}.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


def _plan(root: Path) -> typescript_migration.Migration:
    return typescript_migration.plan(root, root, doctor.authored_files(root))


def _apply(migration: typescript_migration.Migration) -> None:
    for path, contents in migration.writes:
        path.write_text(contents, encoding="utf-8")
    for path in migration.deletes:
        path.unlink()


def _written(migration: typescript_migration.Migration, path: Path) -> str:
    return dict(migration.writes)[path]


def test_a_scaffolded_consumer_gets_the_default_entrypoint_and_loses_the_eslint_files(tmp_path: Path) -> None:
    root = _repository(
        tmp_path,
        {"eslint.config.ts": _SCAFFOLDED_ESLINT_CONFIG, "eslint.strict.ts": "export default [];\n"},
    )

    migration = _plan(root)

    assert _written(migration, root / "oxlint.config.mts") == typescript_migration.render_entrypoint()
    assert set(migration.deletes) == {root / "eslint.config.ts", root / "eslint.strict.ts"}
    assert not migration.keeps_eslint
    assert {"typescript-eslint", "@eslint/js", "@typescript/native"} <= migration.retired_dependencies
    assert "eslint" in migration.retired_dependencies


def test_the_default_entrypoint_extends_the_managed_preset_and_spreads_its_ignores() -> None:
    rendered = typescript_migration.render_entrypoint()

    assert 'import { createConfig, ignorePatterns } from "./oxlint.strict.mts";' in rendered
    assert "const managed = createConfig();\n" in rendered
    assert "  extends: [managed],\n" in rendered
    assert "  settings: managed.settings,\n  ignorePatterns: [\n    ...ignorePatterns,\n  ]," in rendered


def test_a_customized_config_translates_through_the_rule_map(tmp_path: Path) -> None:
    root = _repository(
        tmp_path, {"eslint.config.mjs": _CUSTOMIZED_ESLINT_CONFIG, "eslint.strict.mjs": "export default [];\n"}
    )

    migration = _plan(root)

    rendered = _written(migration, root / "oxlint.config.mts")
    overrides_block = rendered[rendered.index("  overrides: [\n") + len("  overrides: [\n") : rendered.rindex("  ],")]
    overrides = parse_json(f"[{overrides_block.rstrip().removesuffix(',')}]")
    assert overrides == [
        {"files": ["**/*"], "rules": {"unicorn-js/prefer-iterator-to-array": "off"}},
        {
            "files": ["packages/app/src/app/**/*.{ts,tsx}"],
            "rules": {"unicorn/filename-case": ["error", {"cases": {"kebabCase": True}, "ignore": [r"\[[A-Za-z]+\]"]}]},
        },
        {
            "files": ["packages/app/src/app/**/route.ts"],
            "rules": {"oxc/bad-replace-all-arg": "warn", "oxc/bad-match-all-arg": "warn"},
        },
        {
            "files": ["packages/app/src/app/**/error.tsx"],
            "rules": {
                "@sarj/sole-export-matches-filename": "off",
                "react/no-unstable-nested-components": ["error", {"allowAsProps": True}],
            },
        },
    ]
    assert '    ...ignorePatterns,\n    "!packages/*/src/lib/**",\n    "**/generated/**",\n  ],' in rendered
    assert set(migration.deletes) == {root / "eslint.config.mjs", root / "eslint.strict.mjs"}
    notes = "\n".join(migration.notes)
    assert "dropped typescript-eslint configs.disableTypeChecked" in notes
    assert "dropped settings.better-tailwindcss" in notes
    assert "kept react/no-unstable-nested-components as written" in notes
    assert "unicorn/prefer-iterator-concat" not in notes  # Turning off a rule Oxlint does not run needs no note.


def test_create_config_options_carry_over_when_oxlint_supports_them(tmp_path: Path) -> None:
    config = (
        'import { createConfig } from "./eslint.strict.mjs";\n\n'
        'export default [...createConfig({ testFrameworks: ["vitest", "playwright"], tsconfigRootDir: "." })];\n'
    )
    root = _repository(tmp_path, {"eslint.config.mjs": config})

    migration = _plan(root)

    rendered = _written(migration, root / "oxlint.config.mts")
    assert (
        'const managed = createConfig({\n    "testFrameworks": [\n      "vitest",\n      "playwright"\n    ]\n  });'
        in rendered
    )
    assert any("tsconfigRootDir" in note for note in migration.notes)


def test_a_custom_config_stays_and_keeps_its_preset_and_dependencies(tmp_path: Path) -> None:
    root = _repository(
        tmp_path,
        {
            "eslint.config.ts": _CUSTOM_ESLINT_CONFIG,
            "eslint.strict.mjs": 'import js from "@eslint/js";\n\nexport default [js.configs.recommended];\n',
            "eslint.strict.d.mts": "export default [];\n",
        },
    )

    migration = _plan(root)
    assert migration.errors
    assert migration.writes == ()
    assert migration.deletes == ()


def test_several_eslint_configs_are_an_error(tmp_path: Path) -> None:
    root = _repository(
        tmp_path, {"eslint.config.mjs": "export default [];\n", "eslint.config.ts": "export default [];\n"}
    )

    migration = _plan(root)

    assert migration.errors == (
        f"multiple ESLint flat configs in {root}: eslint.config.mjs, eslint.config.ts; keep one before running update",
    )
    assert migration.writes == ()


def test_a_pnpm_workspace_keeps_a_nested_config_and_rewrites_package_directives(tmp_path: Path) -> None:
    root = _repository(
        tmp_path,
        {
            "pnpm-workspace.yaml": "packages:\n  - packages/*\n",
            "eslint.config.ts": _SCAFFOLDED_ESLINT_CONFIG,
            "eslint.strict.ts": "export default [];\n",
            "packages/web/eslint.config.mjs": (
                'import sarjStrict from "../../eslint.strict.ts";\n\nexport default [...sarjStrict];\n'
            ),
            "packages/web/src/page.ts": "// eslint-disable-next-line @typescript-eslint/no-explicit-any -- legacy\n",
        },
    )

    migration = _plan(root)
    assert migration.errors
    assert migration.writes == ()
    assert migration.deletes == ()


def test_yarn_plug_and_play_artifacts_are_left_alone(tmp_path: Path) -> None:
    root = _repository(
        tmp_path,
        {
            ".yarnrc.yml": "nodeLinker: pnp\n",
            ".pnp.cjs": '// eslint-plugin-unicorn resolution table\nconst packages = ["eslint-plugin-unicorn"];\n',
            "eslint.config.ts": _SCAFFOLDED_ESLINT_CONFIG,
            "eslint.strict.ts": "export default [];\n",
        },
    )

    migration = _plan(root)

    assert {path.name for path, _contents in migration.writes} == {"oxlint.config.mts"}


def test_directives_follow_the_rule_map(tmp_path: Path) -> None:
    source = (
        "// eslint-disable-next-line unicorn/no-exports-in-scripts -- testable entrypoint\n"
        "export const run = 1;\n"
        "throw new Error(); // eslint-disable-line preserve-caught-error -- private cause\n"
        "  // eslint-disable-next-line unicorn/prefer-iterator-concat -- runtime lacks Iterator.concat\n"
        "const joined = 1;\n"
        "/* eslint-disable regexp/no-missing-g-flag, @sarj/no-test-comments */\n"
        "/* eslint-disable */\n"
        "// oxlint-disable-next-line no-restricted-syntax -- reviewed\n"
        "// react-doctor-disable-next-line react-doctor/no-array-index-key -- stable list\n"
    )
    root = _repository(tmp_path, {"scripts/run.mts": source})

    migration = _plan(root)

    assert _written(migration, root / "scripts/run.mts") == (
        "// eslint-disable-next-line unicorn-js/no-exports-in-scripts -- testable entrypoint\n"
        "export const run = 1;\n"
        "throw new Error(); // eslint-disable-line eslint-js/preserve-caught-error -- private cause\n"
        "const joined = 1;\n"
        "/* eslint-disable oxc/bad-replace-all-arg, oxc/bad-match-all-arg, @sarj/no-test-comments */\n"
        "/* eslint-disable */\n"
        "// oxlint-disable-next-line eslint-js/no-restricted-syntax -- reviewed\n"
        "// react-doctor-disable-next-line react-doctor/no-array-index-key -- stable list\n"
    )


def test_jsx_wrapped_directives_follow_the_rule_map(tmp_path: Path) -> None:
    source = (
        "export const Row = () => (\n"
        "  <div>\n"
        "    {/* eslint-disable-next-line react/no-danger, preserve-caught-error -- trusted markup */}\n"
        "    <span dangerouslySetInnerHTML={{ __html: html }} />\n"
        "    {/* eslint-disable-next-line unicorn/prefer-iterator-concat -- runtime lacks Iterator.concat */}\n"
        "    <Joined />\n"
        "    <p>{/* eslint-disable-line unicorn/prefer-iterator-concat */}</p>\n"
        "  </div>\n"
        ");\n"
    )
    root = _repository(tmp_path, {"src/row.tsx": source})

    migration = _plan(root)

    # A wrapped comment for a dropped rule goes with its braces when it fills the line.
    assert _written(migration, root / "src/row.tsx") == (
        "export const Row = () => (\n"
        "  <div>\n"
        "    {/* eslint-disable-next-line react/no-danger, eslint-js/preserve-caught-error -- trusted markup */}\n"
        "    <span dangerouslySetInnerHTML={{ __html: html }} />\n"
        "    <Joined />\n"
        "    <p>{/* eslint-disable-line unicorn/prefer-iterator-concat */}</p>\n"
        "  </div>\n"
        ");\n"
    )


def test_eslint_comments_directives_and_package_move_to_the_sarj_ports(tmp_path: Path) -> None:
    source = (
        "/* eslint-disable @eslint-community/eslint-comments/no-use -- generated */\n"
        "// eslint-disable-next-line @eslint-community/eslint-comments/require-description\n"
        "export const a = 1;\n"
    )
    package = '{"name": "consumer", "devDependencies": {"@eslint-community/eslint-plugin-eslint-comments": "4.8.1"}}\n'
    root = _repository(tmp_path, {"package.json": package, "src/a.ts": source})

    migration = _plan(root)

    assert _written(migration, root / "src/a.ts") == (
        "/* eslint-disable @sarj/directive-no-use -- generated */\n"
        "// eslint-disable-next-line @sarj/directive-require-description\n"
        "export const a = 1;\n"
    )
    assert "@eslint-community/eslint-plugin-eslint-comments" in migration.retired_dependencies


def test_eslint_suppressions_convert_and_merge_into_oxlint_suppressions(tmp_path: Path) -> None:
    eslint = {
        "src/a.ts": {
            "@typescript-eslint/no-explicit-any": {"count": 2},
            "@typescript-eslint/naming-convention": {"count": 4},
            "no-irregular-whitespace": {"count": 1},
            "unicorn/prefer-escaped-irregular-whitespace": {"count": 2},
        },
        "src/b.ts": {"regexp/no-missing-g-flag": {"count": 1}},
        "src/c.ts": {"@typescript-eslint/naming-convention": {"count": 3}},
    }
    oxlint = {"src/a.ts": {"typescript/no-explicit-any": {"count": 1}}}
    root = _repository(
        tmp_path,
        {"eslint-suppressions.json": json.dumps(eslint), "oxlint-suppressions.json": json.dumps(oxlint)},
    )

    migration = _plan(root)

    assert json.loads(_written(migration, root / "oxlint-suppressions.json")) == {
        "src/a.ts": {"typescript/no-explicit-any": {"count": 3}, "no-irregular-whitespace": {"count": 3}},
        "src/b.ts": {"oxc/bad-replace-all-arg": {"count": 1}, "oxc/bad-match-all-arg": {"count": 1}},
    }
    assert root / "eslint-suppressions.json" in migration.deletes


def test_a_kept_config_keeps_its_suppressions_and_converts_them_once(tmp_path: Path) -> None:
    root = _repository(
        tmp_path,
        {
            "eslint.config.ts": _CUSTOM_ESLINT_CONFIG,
            "eslint-suppressions.json": json.dumps({"src/a.ts": {"no-undef": {"count": 1}}}),
        },
    )

    migration = _plan(root)
    assert migration.errors
    assert migration.writes == ()
    assert migration.deletes == ()


def test_unreferenced_tsconfig_projects_join_the_root_references(tmp_path: Path) -> None:
    root = _repository(
        tmp_path,
        {
            "tsconfig.json": '{\n  "files": [],\n  "references": [\n    {\n      "path": "apps/web"\n    }\n  ]\n}\n',
            "tsconfig.base.json": '{ "compilerOptions": { "strict": true } }\n',
            "tsconfig.tooling.json": (
                '{\n  // Tool scripts outside every package.\n  "extends": "./tsconfig.base.json",\n'
                '  "include": [".github/scripts/**/*.mts"],\n}\n'
            ),
            "tsconfig.eslint.json": '{ "extends": "./tsconfig.base.json", "include": ["**/*.ts"] }\n',
            "apps/web/tsconfig.json": '{ "extends": "../../tsconfig.base.json", "include": ["src"] }\n',
            "apps/web/tsconfig.build.json": '{ "extends": "./tsconfig.json", "include": ["src"] }\n',
        },
    )

    migration = _plan(root)

    assert json.loads(_written(migration, root / "tsconfig.json")) == {
        "files": [],
        "references": [{"path": "apps/web"}, {"path": "./tsconfig.tooling.json"}],
    }
    assert [path for path, _contents in migration.writes if path.name.startswith("tsconfig")] == [
        root / "tsconfig.json"
    ]
    assert any("tsconfig.eslint.json only served ESLint" in note for note in migration.notes)


def test_a_jsonc_root_tsconfig_without_references_is_reported(tmp_path: Path) -> None:
    root = _repository(
        tmp_path,
        {
            "tsconfig.json": '{\n  // Application project.\n  "include": ["src"]\n}\n',
            "tsconfig.tooling.json": '{ "include": ["scripts"] }\n',
        },
    )

    migration = _plan(root)

    assert root / "tsconfig.json" not in dict(migration.writes)
    assert any("reference tsconfig.tooling.json from tsconfig.json" in note for note in migration.notes)


def test_planning_a_migrated_repository_changes_nothing(tmp_path: Path) -> None:
    root = _repository(
        tmp_path,
        {
            "eslint.config.mjs": _CUSTOMIZED_ESLINT_CONFIG,
            "eslint.strict.mjs": "export default [];\n",
            "eslint-suppressions.json": json.dumps({"src/a.ts": {"@typescript-eslint/no-explicit-any": {"count": 1}}}),
            "src/a.ts": "// eslint-disable-next-line @typescript-eslint/no-explicit-any -- boundary\nexport const a = 1;\n",
            "tsconfig.json": '{ "files": [] }\n',
            "tsconfig.tooling.json": '{ "include": ["scripts"] }\n',
        },
    )
    _apply(_plan(root))

    second = _plan(root)

    assert (second.writes, second.deletes, second.errors) == ((), (), ())


def test_retired_dependencies_stay_while_a_source_imports_them(tmp_path: Path) -> None:
    root = _repository(
        tmp_path,
        {
            "eslint.config.ts": _SCAFFOLDED_ESLINT_CONFIG,
            "scripts/lint.mts": 'import js from "@eslint/js";\nimport { parse } from "typescript-eslint/parser";\n',
            "packages/tool/package.json": '{ "scripts": { "types": "node node_modules/@typescript/native/bin/tsc -b" } }\n',
        },
    )

    retired = _plan(root).retired_dependencies

    assert {"@eslint/js", "typescript-eslint", "@typescript/native"}.isdisjoint(retired)
    assert "eslint-plugin-jest" in retired


def test_workspace_type_checks_move_to_tsrs_and_retire_the_native_compiler(tmp_path: Path) -> None:
    package = '{\n  "name": "app",\n  "scripts": {\n    "typecheck": "tsc --noEmit",\n    "build": "tsc -b"\n  }\n}\n'
    root = _repository(tmp_path, {"packages/app/package.json": package})

    migration = _plan(root)

    assert _written(migration, root / "packages/app/package.json") == package.replace(
        '"tsc --noEmit"', '"tsrs --noEmit"'
    )
    # `tsc -b` still builds with the compiler, so the package that provides it stays.
    assert "@typescript/native" not in migration.retired_dependencies
    _apply(migration)
    assert not _plan(root).writes


@pytest.mark.parametrize(
    ("scripts", "replace_eslint", "expected"),
    [
        ({}, True, {"lint": "LINT", "format": "oxfmt", "format:check": "oxfmt --check"}),
        (
            {"lint": "eslint . --max-warnings 0", "format": "prettier --write .", "format:check": "biome format ."},
            True,
            {"lint": "LINT", "format": "oxfmt", "format:check": "oxfmt --check"},
        ),
        ({"lint": "eslint ."}, False, {"lint": "eslint .", "format": "oxfmt", "format:check": "oxfmt --check"}),
        (
            {"lint": "eslint --max-warnings=0", "lint:fix": "pnpm exec eslint . --fix", "format": "prettier --check ."},
            True,
            {"lint": "LINT", "lint:fix": "LINT --fix", "format": "oxfmt --check", "format:check": "oxfmt --check"},
        ),
        (
            {
                "lint:ci": "eslint --format json -o report.json .",
                "lint:src": "eslint src",
                "format": "prettier --write src",
                "format:check": "prettier .",
            },
            True,
            {
                "lint:ci": "eslint --format json -o report.json .",
                "lint:src": "LINT src",
                "lint": "LINT",
                "format": "oxfmt src",
                "format:check": "oxfmt --check",
            },
        ),
        (
            {"lint": "pnpm lint:eslint && biome check .", "format": "turbo run format", "format:check": "x"},
            True,
            {"lint": "pnpm lint:eslint && biome check .", "format": "turbo run format", "format:check": "x"},
        ),
        (
            {
                "typecheck": "tsc --noEmit -p tsconfig.json && pnpm exec tsc6 --noEmit",
                "tooling": "node node_modules/@typescript/native/bin/tsc --project tools --noEmit",
                "build": "tsc -b && tsc -p tsconfig.build.json",
                "lint": "x",
                "format": "x",
                "format:check": "x",
            },
            True,
            {
                "typecheck": "tsrs --noEmit -p tsconfig.json && pnpm exec tsrs --noEmit",
                "tooling": "tsrs --project tools --noEmit",
                "build": "tsc -b && tsc -p tsconfig.build.json",
                "lint": "x",
                "format": "x",
                "format:check": "x",
            },
        ),
    ],
)
def test_migrated_scripts(scripts: dict[str, str], replace_eslint: bool, expected: dict[str, str]) -> None:
    assert typescript_migration.migrated_scripts(scripts, lint="LINT", replace_eslint=replace_eslint) == expected


@pytest.mark.parametrize(
    ("root_config", "tooling_options"),
    [
        ('{ "compilerOptions": { "strict": true }, "include": ["src"] }\n', {}),
        ('{ "compilerOptions": { "strict": true }, "include": ["src"] }\n', {"composite": True, "noEmit": True}),
        ('{ "compilerOptions": { "strict": true } }\n', {"composite": True, "noEmit": True}),
    ],
)
def test_a_project_root_tsconfig_references_only_composite_projects_that_emit(
    tmp_path: Path, root_config: str, tooling_options: dict[str, bool]
) -> None:
    # tsc and tsrs reject the reference with TS6306 or TS6310, which Oxlint reports as tsc/tsconfig-error.
    tooling = json.dumps({"compilerOptions": tooling_options, "include": ["scripts"]})
    root = _repository(tmp_path, {"tsconfig.json": root_config, "tsconfig.tooling.json": tooling})

    migration = _plan(root)

    assert root / "tsconfig.json" not in dict(migration.writes)
    assert any(
        "reference tsconfig.tooling.json from tsconfig.json" in note and "composite: true" in note
        for note in migration.notes
    )


def test_a_project_root_tsconfig_references_a_composite_project(tmp_path: Path) -> None:
    tooling = '{ "compilerOptions": { "composite": true }, "include": ["scripts"] }\n'
    root = _repository(
        tmp_path,
        {"tsconfig.json": '{ "include": ["src"] }\n', "tsconfig.tooling.json": tooling},
    )

    migration = _plan(root)

    assert json.loads(_written(migration, root / "tsconfig.json")) == {
        "include": ["src"],
        "references": [{"path": "./tsconfig.tooling.json"}],
    }


def test_suppressions_use_the_namespace_oxlint_reports(tmp_path: Path) -> None:
    eslint = {
        "src/a.tsx": {
            "react-hooks/exhaustive-deps": {"count": 1},
            "react-hooks/rules-of-hooks": {"count": 1},
            "@next/next/no-img-element": {"count": 1},
            "@typescript-eslint/no-explicit-any": {"count": 1},
        }
    }
    root = _repository(tmp_path, {"eslint-suppressions.json": json.dumps(eslint)})

    migration = _plan(root)

    assert json.loads(_written(migration, root / "oxlint-suppressions.json")) == {
        "src/a.tsx": {
            "react-hooks/exhaustive-deps": {"count": 1},
            "react-hooks/rules-of-hooks": {"count": 1},
            "next/no-img-element": {"count": 1},
            "typescript/no-explicit-any": {"count": 1},
        }
    }


def test_converted_suppressions_cover_what_oxlint_reports(tmp_path: Path) -> None:
    source = (
        'import { useEffect } from "react";\n'
        "export function A({ x }: { x: number }) {\n"
        "  useEffect(() => {\n    void x;\n  }, []);\n"
        '  return <img src="a.png" alt="" />;\n'
        "}\n"
    )
    eslint = {"a.tsx": {"react-hooks/exhaustive-deps": {"count": 1}, "@next/next/no-img-element": {"count": 1}}}
    config = (
        'export default { plugins: ["react", "nextjs"], '
        'rules: { "react/exhaustive-deps": "error", "nextjs/no-img-element": "error" } };\n'
    )
    root = project(tmp_path / "repo", {"a.tsx": source, "eslint-suppressions.json": json.dumps(eslint)}, config=config)
    _apply(typescript_migration.plan(root, root, [root / "eslint-suppressions.json"]))
    (command,) = commands(root)

    completed = run_native(command)

    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_an_entry_on_a_dropped_spread_keeps_its_own_rules(tmp_path: Path) -> None:
    config = (
        'import tseslint from "typescript-eslint";\n'
        'import strict from "./eslint.strict.mjs";\n'
        "export default [\n"
        "  ...strict,\n"
        '  { ...tseslint.configs.disableTypeChecked, files: ["**/*.js"], rules: { "no-console": "off" } },\n'
        "];\n"
    )
    root = _repository(tmp_path, {"eslint.config.mjs": config})

    rendered = _written(_plan(root), root / "oxlint.config.mts")

    assert '"files": [\n        "**/*.js"\n      ],\n      "rules": {\n        "no-console": "off"' in rendered


@pytest.mark.parametrize("name", ["App.vue", "Page.svelte", "index.astro"])
def test_a_dependency_imported_only_from_a_component_file_stays(tmp_path: Path, name: str) -> None:
    source = '<script lang="ts">\nimport { z } from "zod";\n</script>\n'
    root = _repository(tmp_path, {"eslint.config.ts": _SCAFFOLDED_ESLINT_CONFIG, f"src/{name}": source})

    assert "zod" not in _plan(root).retired_dependencies


def test_a_script_that_still_runs_eslint_is_reported(tmp_path: Path) -> None:
    package = json.dumps({"name": "consumer", "scripts": {"lint:ci": "eslint -o report.json ."}})
    root = _repository(tmp_path, {"package.json": package, "eslint.config.ts": _SCAFFOLDED_ESLINT_CONFIG})

    errors = _plan(root).errors

    assert any("script lint:ci" in error and "package.json" in error for error in errors)


def test_workspace_legacy_commands_forward_to_root_and_retire_tools(tmp_path: Path) -> None:
    root = _repository(
        tmp_path,
        {
            "package.json": json.dumps({"name": "consumer", "packageManager": "pnpm@10.0.0"}),
            "packages/app/package.json": json.dumps(
                {
                    "name": "app",
                    "scripts": {
                        "lint": "biome check --config-path=../../biome.json ./src",
                        "format": "prettier --write ./src",
                    },
                    "devDependencies": {
                        "@biomejs/biome": "1",
                        "prettier": "1",
                        "eslint-config-next": "1",
                        "eslint-config-expo": "1",
                        "eslint-config-prettier": "1",
                    },
                }
            ),
        },
    )
    migration = _plan(root)
    assert not migration.errors
    document = parse_json(_written(migration, root / "packages/app/package.json"))
    assert isinstance(document, dict)
    assert document["scripts"] == {"lint": "pnpm -w run lint packages/app", "format": "pnpm -w run format packages/app"}
    assert document["devDependencies"] == {}


def test_supported_typescript_aliases_preserve_source_across_repeated_migration(tmp_path: Path) -> None:
    source = (
        "// eslint-disable-next-line @typescript-eslint/no-deprecated -- legacy API boundary\n"
        "export const value = legacy();\n"
        "// eslint-disable-next-line @typescript-eslint/no-unnecessary-type-parameters -- public signature\n"
        "export function identity<T extends string>(value: T): T { return value; }\n"
    )
    root = _repository(tmp_path, {"src/legacy.ts": source})
    for _ in range(2):
        migration = _plan(root)
        assert all(path != root / "src/legacy.ts" for path, _contents in migration.writes)
        for path, contents in migration.writes:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(contents)
        for path in migration.deletes:
            path.unlink(missing_ok=True)
        assert (root / "src/legacy.ts").read_text() == source


def test_preserving_supported_aliases_still_migrates_other_directives(tmp_path: Path) -> None:
    source = (
        "// eslint-disable-next-line @typescript-eslint/no-deprecated -- legacy API boundary\n"
        "export const value = legacy();\n"
        "// eslint-disable-next-line unicorn/no-exports-in-scripts -- testable entrypoint\n"
        "export const run = value;\n"
    )
    root = _repository(tmp_path, {"src/legacy.ts": source})
    assert _written(_plan(root), root / "src/legacy.ts") == source.replace(
        "unicorn/no-exports-in-scripts", "unicorn-js/no-exports-in-scripts"
    )
