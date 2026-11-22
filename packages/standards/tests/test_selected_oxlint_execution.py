from __future__ import annotations

from importlib.resources import files
import json
from pathlib import Path
import subprocess
from typing import Final

import pytest

from sarj_standards.cli.main import main
from sarj_standards.libs.adoption.configs import OXLINT_SUPPRESSIONS
from sarj_standards.libs.adoption.manifest import as_table, list_field
from sarj_standards.libs.diagnostics import Completion, ToolReport
from sarj_standards.libs.json_boundary import parse_json
from sarj_standards.libs.linting import oxfmt, oxlint
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


@pytest.mark.parametrize("staged", [False, True], ids=("file-check", "staged-check"))
@pytest.mark.parametrize("suppressed", [False, True], ids=("new-finding", "accepted-baseline"))
@pytest.mark.parametrize(
    ("rule", "filename", "source"),
    [
        (
            "eslint-js/preserve-caught-error",
            "src/example.js",
            "export function example() { try { throw new Error('Original'); } catch (error) { throw new Error(`Operation failed: ${String(error)}`); } }\n",
        ),
        (
            "unicorn/no-lonely-if",
            "src/example.ts",
            "interface Condition { readonly enabled: boolean; readonly ready: boolean; } export function example(condition: Condition, publish: () => void): void { if (condition.enabled) { if (condition.ready) { publish(); } } }\n",
        ),
        (
            "unicorn-js/prefer-single-object-destructuring",
            "src/example.js",
            "export function example() { const source = {first: 1, second: 2}; const {first} = source; const {second} = source; return first + second; }\n",
        ),
    ],
)
def test_promoted_upstream_findings_block_core_file_and_staged_cli(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    *,
    rule: str,
    filename: str,
    source: str,
    staged: bool,
    suppressed: bool,
) -> None:
    root = project(
        tmp_path / "repo",
        {filename: source},
        config='import { createConfig } from "./oxlint.strict.ts"; export default createConfig();\n',
        git=staged,
    )
    (root / "oxlint.strict.ts").write_text(
        files("sarj_standards").joinpath("configs/oxlint.strict.mts").read_text(encoding="utf-8")
    )
    (root / "oxfmt.strict.mts").write_text(
        files("sarj_standards").joinpath("configs/oxfmt.strict.mts").read_text(encoding="utf-8")
    )
    (root / "oxfmt.config.mts").write_text(oxfmt.render_config(oxfmt.OxfmtSeed(None, {})), encoding="utf-8")
    formatter = oxfmt.write_command([filename], project=root, root=root)
    subprocess.run(formatter.argv, cwd=formatter.cwd, check=True, capture_output=True)
    if staged:
        subprocess.run(("git", "-C", str(root), "add", "--", filename), check=True, capture_output=True)
    if suppressed:
        (root / OXLINT_SUPPRESSIONS).write_text(
            json.dumps({filename: {oxlint.reported_rule_id(rule): {"count": 1}}}), encoding="utf-8"
        )
    paths = ["--staged"] if staged else [filename]

    status = main(
        [
            "--root",
            str(root),
            "check",
            "--format",
            "json",
            "--trust-repository-code",
            *paths,
        ]
    )

    report = as_table(parse_json(capsys.readouterr().out))
    assert status == (0 if suppressed else 1), report
    assert report["completion"] == "complete"
    assert report["issues"] == []
    assert [(as_table(item)["code"], as_table(item)["severity"]) for item in list_field(report, "diagnostics")] == (
        [] if suppressed else [(rule, "error")]
    )


@pytest.mark.parametrize(
    ("rule", "source"),
    [
        (
            "eslint-js/preserve-caught-error",
            "export function run(operation) { try { return operation(); } catch (error) { throw new Error('failed', {cause: error}); } }\n",
        ),
        (
            "eslint-js/preserve-caught-error",
            "export function run(operation) { class Error {} try { return operation(); } catch (error) { throw new Error(); } }\n",
        ),
        (
            "unicorn/no-lonely-if",
            "export function run(first, second) { if (first) { if (second) { return 1; } else { return 2; } } }\n",
        ),
        (
            "unicorn-js/prefer-single-object-destructuring",
            "export function run() { const source = {first: 1, second: 2}; const {first = 0} = source; const {second} = source; return first + second; }\n",
        ),
        (
            "unicorn-js/prefer-single-object-destructuring",
            "export function run() { const source = {value: 1}; const {value: first} = source; const {value: second} = source; return first + second; }\n",
        ),
        (
            "eslint-js/preserve-caught-error",
            (
                "export function run(operation) { try { return operation(); } catch (error) {\n"
                "// eslint-disable-next-line eslint-js/preserve-caught-error -- The public boundary deliberately hides private upstream causes.\n"
                "throw new Error('failed');\n} }\n"
            ),
        ),
        (
            "unicorn/no-lonely-if",
            (
                "export function run(first, second) {\n"
                "// eslint-disable-next-line unicorn/no-lonely-if -- Preserve the branching shape required by the external diagnostic contract.\n"
                "if (first) { if (second) { return 1; } }\n}\n"
            ),
        ),
        (
            "unicorn-js/prefer-single-object-destructuring",
            (
                "export function run() { const source = {first: 1, second: 2}; const {first} = source;\n"
                "// eslint-disable-next-line unicorn-js/prefer-single-object-destructuring -- Keep the separate observations required by the external adapter contract.\n"
                "const {second} = source; return first + second; }\n"
            ),
        ),
    ],
)
def test_promoted_upstream_boundaries_and_exact_suppressions_remain_valid(
    tmp_path: Path, rule: str, source: str
) -> None:
    root = project(tmp_path / "repo", {"src/example.js": source})
    (root / "oxlint.strict.ts").write_text(
        files("sarj_standards").joinpath("configs/oxlint.strict.mts").read_text(encoding="utf-8")
    )

    report = analyze(root, oxlint.OxlintRequest(rules=frozenset({rule})), "src/example.js")

    assert report.completion is Completion.COMPLETE
    assert report.issues == ()
    assert report.diagnostics == ()


@pytest.mark.parametrize(
    ("filename", "ignored"),
    [
        ("src/generated/example.js", True),
        ("dist/example.js", True),
        ("vendor/example.js", False),
        ("tests/fixtures/example.js", False),
    ],
)
def test_upstream_promotions_preserve_managed_source_boundaries(
    tmp_path: Path, filename: str, *, ignored: bool
) -> None:
    rules = frozenset(
        {"eslint-js/preserve-caught-error", "unicorn/no-lonely-if", "unicorn-js/prefer-single-object-destructuring"}
    )
    source = (
        "export function example(first, second) {\n"
        "if (first) { if (second) { throw new Error('failed'); } }\n"
        "const source = {first: 1, second: 2}; const {first: left} = source; const {second: right} = source;\n"
        "try { return left + right; } catch (error) { throw new Error(String(error)); }\n"
        "}\n"
    )
    root = project(
        tmp_path / "repo",
        {filename: source},
        config='import { createConfig } from "./oxlint.strict.ts"; export default createConfig();\n',
    )
    (root / "oxlint.strict.ts").write_text(
        files("sarj_standards").joinpath("configs/oxlint.strict.mts").read_text(encoding="utf-8")
    )
    if ignored:
        assert commands(root, filename) == ()
        return

    report = analyze(root, oxlint.OxlintRequest(rules=rules), filename)

    assert report.completion is Completion.COMPLETE
    assert report.issues == ()
    assert {(item.rule_id, str(item.severity)) for item in report.diagnostics} == {(rule, "error") for rule in rules}


def test_vitest_type_assertions_keep_the_native_assertion_owner(tmp_path: Path) -> None:
    source = (
        "import {test, expectTypeOf, assertType} from 'vitest';\n"
        "test('matching types', () => { expectTypeOf<number>().toEqualTypeOf<number>(); });\n"
        "test('assignable value', () => { assertType<number>(1); });\n"
        "test('empty test', () => {});\n"
    )
    root = project(tmp_path / "repo", {"src/assertions.test.ts": source})
    (root / "oxlint.strict.ts").write_text(
        files("sarj_standards").joinpath("configs/oxlint.strict.mts").read_text(encoding="utf-8")
    )

    report = analyze(root, oxlint.OxlintRequest(rules=frozenset({"vitest/expect-expect"})), "src/assertions.test.ts")

    assert report.completion is Completion.COMPLETE
    assert report.issues == ()
    assert [(item.rule_id, str(item.severity)) for item in report.diagnostics] == [("vitest/expect-expect", "warning")]


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
