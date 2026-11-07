from __future__ import annotations

import json
from pathlib import Path
import subprocess
from typing import Final

from sarj_standards.libs.adoption.configs import OXLINT_SUPPRESSIONS
from sarj_standards.libs.diagnostics import Completion, ToolReport
from sarj_standards.libs.linting import oxlint
from tests.oxlint_project import analyze, commands, environment, project


SELECTED_CONFIG: Final = Path(oxlint.__file__).parents[2] / "configs/oxlint-selected-config.mts"
_LOCAL_PLUGIN: Final = """
export default {
  meta: { name: "local" },
  rules: {
    "no-foo": {
      meta: { messages: { foo: "Rename foo." } },
      create(context) {
        return { Identifier(node) { if (node.name === "foo") context.report({ node, messageId: "foo" }); } };
      },
    },
  },
};
"""
# Relative plugin specifiers, own ignore patterns and overrides must survive
# the overlay; Oxlint drops the first two when a config is only extended.
_CONSUMER: Final = """
import { createConfig } from "./oxlint.strict.ts";
export default {
  extends: [createConfig()],
  jsPlugins: [{ name: "local", specifier: "./local-plugin.mjs" }],
  ignorePatterns: ["src/generated/**"],
  rules: { "local/no-foo": "error" },
  overrides: [{ files: ["src/legacy/**"], rules: { "no-console": "off" } }],
};
"""
_SOURCES: Final = {
    "local-plugin.mjs": _LOCAL_PLUGIN,
    "src/a.ts": (
        "// eslint-disable-next-line typescript/no-explicit-any -- the SDK payload is untyped\n"
        "export const foo: any = 1;\n"
        "debugger;\n"
        "console.log(foo);\n"
        "export const n: number = 'x';\n"
    ),
    "src/legacy/b.ts": "console.log(1);\nexport const b = 1;\n",
}


def _rules(report: ToolReport) -> set[tuple[str | None, str]]:
    return {(item.rule_id, item.location.path) for item in report.diagnostics}


def test_selected_run_keeps_the_consumer_config_but_only_selected_rules_and_the_floor(tmp_path: Path) -> None:
    root = project(tmp_path / "repo", _SOURCES, config=_CONSUMER)
    (root / OXLINT_SUPPRESSIONS).write_text(json.dumps({"src/a.ts": {"no-console": {"count": 1}}}), encoding="utf-8")

    full = analyze(root, oxlint.OxlintRequest(), "src")
    selected = analyze(root, oxlint.OxlintRequest(rules=frozenset({"no-debugger", "local/no-foo"})), "src")

    assert full.issues == ()
    assert {rule for rule, _path in _rules(full)} == {"no-debugger", "local/no-foo", "tsc/TS2322"}
    assert selected.completion is Completion.COMPLETE
    # The bulk entry for an unselected rule is not stale, and the directive for
    # an unselected rule is not reported unused.
    assert _rules(selected) == {("no-debugger", "src/a.ts"), ("local/no-foo", "src/a.ts")}
    assert selected.file_count == 2


def test_full_run_reports_unused_directives_and_stale_bulk_entries(tmp_path: Path) -> None:
    sources = {**_SOURCES, "src/a.ts": "// eslint-disable-next-line no-debugger -- nothing to hide here\nexport {};\n"}
    root = project(tmp_path / "repo", sources, config=_CONSUMER)
    (root / OXLINT_SUPPRESSIONS).write_text(json.dumps({"src/a.ts": {"no-debugger": {"count": 1}}}), encoding="utf-8")

    full = analyze(root, oxlint.OxlintRequest(), "src/a.ts")
    selected = analyze(root, oxlint.OxlintRequest(rules=frozenset({"no-debugger"})), "src/a.ts")

    assert _rules(full) == {
        (oxlint.UNUSED_DIRECTIVE, "src/a.ts"),
        (oxlint.UNUSED_SUPPRESSION, OXLINT_SUPPRESSIONS),
    }
    assert selected.issues == ()
    assert _rules(selected) == set()


def test_forced_rules_load_missing_native_and_js_plugins(tmp_path: Path) -> None:
    config = '{"plugins": ["eslint"], "categories": {"correctness": "off"}, "rules": {}}\n'
    root = project(
        tmp_path / "repo",
        {
            ".oxlintrc.json": config,
            "src/a.test.ts": 'import { it } from "vitest";\nit.only("x", () => {});\n// oxlint-disable-next-line no-console\nconsole.log(1);\n',
        },
        config="export default {};\n",
    )
    (root / "oxlint.config.ts").unlink()
    advisory = {"vitest/no-focused-tests": "error"}

    report = analyze(
        root,
        oxlint.OxlintRequest(rules=frozenset(), forced={**advisory, "@sarj/no-oxlint-directive": "error"}),
        "src",
    )

    assert report.issues == ()
    assert {rule for rule, _path in _rules(report)} == {"vitest/no-focused-tests", "@sarj/no-oxlint-directive"}


def test_overlay_forces_type_aware_rules_on(tmp_path: Path) -> None:
    config = tmp_path / ".oxlintrc.json"
    config.write_text('{"settings": {"sarj": {"typeAware": false, "kept": 1}, "other": 2}}', encoding="utf-8")
    request: dict[str, object] = {
        "config": str(config),
        "rules": None,
        "forced": {},
        "disabled": [],
        "jsPlugins": {},
        "aliases": {},
    }
    script = (
        f"import {{ createSelectedConfig }} from {json.dumps(SELECTED_CONFIG.as_uri())};\n"
        f"console.log(JSON.stringify((await createSelectedConfig({json.dumps(request)})).settings));\n"
    )

    settings = subprocess.run(
        ("node", "--input-type=module", "-e", script), capture_output=True, text=True, check=True
    ).stdout

    assert json.loads(settings) == {"sarj": {"typeAware": True, "kept": 1}, "other": 2}


def test_fix_overlay_turns_per_path_exclusions_off_for_js_rules(tmp_path: Path) -> None:
    sources = {
        "src/a.ts": "export function f() { return globalThis.Array; }\n",
        "src/legacy/b.ts": "export function g() { return globalThis.Array; }\n",
    }
    root = project(tmp_path / "repo", sources)
    request = oxlint.OxlintRequest(
        forced={}, disabled=((("src/legacy/**",), frozenset({"unicorn-js/no-unnecessary-global-this"})),)
    )

    for command in commands(root, "src", fix=True):
        with oxlint.selected_config(command, request) as configured:
            subprocess.run(
                configured.argv,
                cwd=configured.cwd,
                env={**environment(), **oxlint.oxlint_environment(configured.cwd, root)},
                capture_output=True,
                check=False,
            )

    assert (root / "src/a.ts").read_text(encoding="utf-8") == "export function f() { return Array; }\n"
    assert (root / "src/legacy/b.ts").read_text(encoding="utf-8") == sources["src/legacy/b.ts"]
