from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
from typing import TYPE_CHECKING, Final

from pydantic import BaseModel
import pytest

from sarj_standards.libs.adoption.configs import OXLINT_SUPPRESSIONS
from sarj_standards.libs.adoption.lifecycle import Command
from sarj_standards.libs.adoption.manifest import ALL_CAPABILITIES
from sarj_standards.libs.diagnostics import Completion, Severity
from sarj_standards.libs.linting import oxlint
from sarj_standards.libs.linting.external import DEFAULT_EXECUTOR
from sarj_standards.libs.linting.process import ProcessOutput, ProcessRequest
from tests.oxlint_project import OXLINT, analyze, environment, local, project
from tests.process_fakes import FakeProcessExecutor


if TYPE_CHECKING:
    from collections.abc import Sequence


class _Case(BaseModel):
    files: dict[str, str]
    returncode: int
    stdout: str


class _Recording(BaseModel):
    oxlint: str
    cases: dict[str, _Case]


# Real Oxlint 1.91.0 output for the listed sources, with the fixture root as `<root>`.
_RECORDED: Final = _Recording.model_validate_json(
    (Path(__file__).parent / "fixtures" / "oxlint" / "recorded-1.91.0.json").read_bytes()
).cases


def _recorded(name: str, root: Path) -> ProcessOutput:
    case = _RECORDED[name]
    for relative, text in case.files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return ProcessOutput(case.returncode, case.stdout.replace("<root>", str(root)), "")


def _unreachable(_argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
    raise AssertionError(cwd)


def test_recorded_lint_maps_codes_byte_spans_and_codeless_records(tmp_path: Path) -> None:
    result = oxlint.read_oxlint(_recorded("lint", tmp_path), root=tmp_path, cwd=tmp_path, selected=False)

    assert result.file_count == 3
    by_rule = {item.rule_id: item for item in result.diagnostics}
    assert set(by_rule) >= {
        "no-debugger",
        "typescript/no-explicit-any",
        "unicorn/no-null",
        "@sarj/no-vague-suppression-description",
        "unicorn-js/no-useless-undefined",
        "react/immutability",
        "react/rules-of-hooks",
        "nextjs/no-img-element",
        "tsc/TS2322",
        "tsc/TS1134",
        "typescript/no-floating-promises",
        oxlint.UNUSED_DIRECTIVE,
    }
    explicit_any = by_rule["typescript/no-explicit-any"]
    assert explicit_any.source == "oxlint"
    assert explicit_any.location.path == "src/a.ts"
    region = explicit_any.location.region
    assert region is not None
    # Oxlint spans are UTF-8 byte offsets; the line before holds multibyte text.
    assert (region.start.line, region.start.character, region.start.byte_offset) == (1, 16, 58)
    assert by_rule["nextjs/no-img-element"].severity is Severity.WARNING
    assert by_rule["react/immutability"].notes
    assert [item.label for item in by_rule["react/rules-of-hooks"].related] == [
        "This Hook call is not reachable on every render path.",
        "When this condition is false, this Hook is skipped.",
    ]
    assert by_rule["typescript/no-explicit-any"].help_url == (
        "https://oxc.rs/docs/guide/usage/linter/rules/typescript/no-explicit-any.html"
    )
    unused = [item for item in result.diagnostics if item.rule_id == oxlint.UNUSED_DIRECTIVE]
    assert len(unused) == 2
    assert by_rule["@sarj/no-vague-suppression-description"].tags == oxlint.REQUIRED_TAGS
    assert by_rule["no-debugger"].tags == ()
    # A syntax error has no code; ESLint treated the same input as a fatal failure.
    assert [(issue.kind, issue.message) for issue in result.issues] == [
        ("tool-failure", "Oxlint could not parse src/broken.ts: Unexpected token")
    ]


def test_js_plugin_crash_is_a_tool_failure_not_a_clean_file(tmp_path: Path) -> None:
    result = oxlint.read_oxlint(_recorded("crash", tmp_path), root=tmp_path, cwd=tmp_path, selected=False)

    assert result.diagnostics == ()
    (issue,) = result.issues
    assert issue.kind == "tool-failure"
    assert issue.message == (
        "Oxlint JS plugin failed on src/generated.ts: RangeError: Line/column pair translates to an out of range offset"
    )


@pytest.mark.parametrize("selected", [False, True])
def test_stale_bulk_suppressions_fail_only_full_runs(tmp_path: Path, *, selected: bool) -> None:
    result = oxlint.read_oxlint(_recorded("stale", tmp_path), root=tmp_path, cwd=tmp_path, selected=selected)

    assert result.issues == ()
    if selected:
        assert result.diagnostics == ()
        return
    (stale,) = result.diagnostics
    assert (stale.rule_id, stale.location.path, stale.severity) == (
        oxlint.UNUSED_SUPPRESSION,
        OXLINT_SUPPRESSIONS,
        Severity.ERROR,
    )
    # Its fingerprint never changes, so a baselined entry would hide every later stale count.
    assert "non-baselineable" in stale.tags


def test_typed_rules_falling_back_to_untyped_fail_the_run(tmp_path: Path) -> None:
    output = ProcessOutput(
        0,
        '{"diagnostics": [], "number_of_files": 1}',
        f"{oxlint.TSRS_FAILURE}, type-aware rules take their untyped path for the rest of the run: boom\n",
    )

    result = oxlint.read_oxlint(output, root=tmp_path, cwd=tmp_path, selected=False)

    (issue,) = result.issues
    assert issue.kind == "tool-failure"
    assert issue.message.startswith(oxlint.TSRS_FAILURE)


def test_configuration_failure_text_is_classified(tmp_path: Path) -> None:
    result = oxlint.read_oxlint(_recorded("configuration", tmp_path), root=tmp_path, cwd=tmp_path, selected=False)

    assert result.diagnostics == ()
    assert [issue.kind for issue in result.issues] == ["configuration-failure"]
    assert result.issues[0].message.startswith("Failed to parse oxlint configuration file.")


def test_tsconfig_errors_are_type_check_findings_that_cannot_be_baselined(tmp_path: Path) -> None:
    result = oxlint.read_oxlint(_recorded("tsconfig", tmp_path), root=tmp_path, cwd=tmp_path, selected=False)

    assert result.issues == ()
    (finding,) = result.diagnostics
    assert (finding.rule_id, finding.location.path, finding.location.region) == (
        oxlint.TSCONFIG_ERROR,
        "tsconfig.json",
        None,
    )
    assert finding.message == "Cannot find type definition file for 'missing-types-package'."
    assert "non-baselineable" in finding.tags


def test_text_before_the_json_report_is_tolerated(tmp_path: Path) -> None:
    result = oxlint.read_oxlint(_recorded("no-files", tmp_path), root=tmp_path, cwd=tmp_path, selected=False)

    assert (result.diagnostics, result.issues, result.file_count) == ((), (), 0)


@pytest.mark.parametrize(
    ("output", "kind"),
    [
        (ProcessOutput(1, "Failed to find tsgolint executable. You may need to add it\n", ""), "missing-dependency"),
        (ProcessOutput(2, "", "thread panicked"), "tool-failure"),
        (ProcessOutput(1, "unexpected banner\n", ""), "protocol-mismatch"),
        (ProcessOutput(1, '{"diagnostics": [], "number_of_files": 2}', ""), "protocol-mismatch"),
    ],
)
def test_unstructured_or_inconsistent_output_fails(tmp_path: Path, output: ProcessOutput, kind: str) -> None:
    result = oxlint.read_oxlint(output, root=tmp_path, cwd=tmp_path, selected=False)

    assert [issue.kind for issue in result.issues] == [kind]


def test_paths_outside_the_repository_are_rejected(tmp_path: Path) -> None:
    payload: dict[str, object] = {
        "diagnostics": [
            {"message": "m", "code": "eslint(no-debugger)", "severity": "error", "filename": "../x.ts", "labels": []}
        ],
        "number_of_files": 1,
    }
    with pytest.raises(ValueError, match="outside the repository"):
        oxlint.read_oxlint(ProcessOutput(1, json.dumps(payload), ""), root=tmp_path, cwd=tmp_path, selected=False)


def _touch(root: Path, *names: str) -> None:
    for name in names:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("export {};\n", encoding="utf-8")


def _files(command: Command) -> Sequence[str]:
    argv = tuple(command.argv)
    return argv[max(index for index, value in enumerate(argv) if value == "--") + 1 :]


def test_selection_groups_by_nearest_config_and_runs_beside_the_suppressions(tmp_path: Path) -> None:
    _touch(
        tmp_path,
        "oxlint.config.ts",
        "package.json",
        "oxlint-suppressions.json",
        "src/a.ts",
        "apps/web/oxlint.config.ts",
        "apps/web/src/b.tsx",
        "apps/web/src/c.md",
        "apps/web/node_modules/pkg/index.ts",
        "syncpack.strict.mts",
    )

    selection = oxlint.select_oxlint_commands(tmp_path, [str(tmp_path)], label="analysis")

    assert selection.unowned_count == 0
    assert [(command.label, command.cwd, tuple(command.argv[:6])) for command in selection.commands] == [
        ("Oxlint (analysis: .)", tmp_path, ("npm", "exec", "--offline", "--", "oxlint", "-c")),
        ("Oxlint (analysis: apps/web)", tmp_path, ("npm", "exec", "--offline", "--", "oxlint", "-c")),
    ]
    root_command, web_command = selection.commands
    assert root_command.argv[6] == "oxlint.config.ts"
    assert web_command.argv[6] == "apps/web/oxlint.config.ts"
    assert _files(root_command) == ("src/a.ts",)
    assert _files(web_command) == ("apps/web/src/b.tsx",)
    assert oxlint.command_files(web_command) == frozenset({tmp_path / "apps/web/src/b.tsx"})


def test_selection_without_a_root_ledger_runs_in_the_project(tmp_path: Path) -> None:
    _touch(tmp_path, "package.json", "web/oxlint.config.ts", "web/src/a.ts")

    (command,) = oxlint.select_oxlint_commands(tmp_path, ["web/src/a.ts"], fix=True).commands

    assert command.cwd == tmp_path / "web"
    assert tuple(command.argv[4:]) == ("oxlint", "-c", "oxlint.config.ts", "--fix", "--", "src/a.ts")


def test_projects_without_an_install_run_the_adopted_projects_tools(tmp_path: Path) -> None:
    (tmp_path / ".sarj-standards.toml").write_text(
        'schema = 4\nbundle = "9.0.0"\n[dest]\npython = "."\ntypescript = "web"\n', encoding="utf-8"
    )
    _touch(
        tmp_path,
        "web/package.json",
        "web/oxlint.config.mts",
        "web/node_modules/.bin/oxlint",
        "web/node_modules/.bin/tsrs-lint",
        "tools/oxlint.config.mts",
        "tools/fix.ts",
    )
    binaries = tmp_path / "web/node_modules/.bin"

    (tools,) = oxlint.select_oxlint_commands(tmp_path, ["tools/fix.ts"], fix=True).commands
    (web,) = oxlint.select_oxlint_commands(tmp_path, ["web/oxlint.config.mts"], include_config_sources=True).commands

    assert tools.cwd == tmp_path / "tools"
    assert tuple(tools.argv) == (str(binaries / "oxlint"), "-c", "oxlint.config.mts", "--fix", "--", "fix.ts")
    # Standards runs force type-aware rules on; `SARJ_TYPE_AWARE=0` only opts editors out.
    assert oxlint.oxlint_environment(tools.cwd, tmp_path) == {
        "OXLINT_TSGOLINT_PATH": str(binaries / "tsrs-lint"),
        "SARJ_TYPE_AWARE": "1",
    }
    # A project with its own install keeps the package manager's resolution.
    assert tuple(web.argv[:5]) == ("npm", "exec", "--offline", "--", "oxlint")


@pytest.mark.parametrize("own_package", [False, True])
def test_forced_plugins_load_from_the_install_that_runs_oxlint(tmp_path: Path, *, own_package: bool) -> None:
    # A project without an install cannot resolve the floor's plugin from its own config.
    install = tmp_path / "web"
    plugin = install if own_package else install / "node_modules/@sarj/eslint-plugin"
    _touch(tmp_path, "web/node_modules/.bin/oxlint", "tools/oxlint.config.mts")
    plugin.mkdir(parents=True, exist_ok=True)
    (plugin / "package.json").write_text('{"name": "@sarj/eslint-plugin", "main": "dist/index.js"}', encoding="utf-8")
    argv = (str(install / "node_modules/.bin/oxlint"), "-c", "oxlint.config.mts", "--", "a.ts")

    with oxlint.selected_config(Command("x", argv, tmp_path / "tools"), oxlint.OxlintRequest()) as configured:
        overlay = Path(configured.argv[2]).read_text(encoding="utf-8")

    assert json.dumps({"@sarj": str(plugin / "dist/index.js")}) in overlay


def test_tsrs_lint_is_required_for_typed_analysis(tmp_path: Path) -> None:
    _touch(tmp_path, "oxlint.config.ts", "src/a.ts")
    command = Command("Oxlint", ("oxlint", "-c", "oxlint.config.ts", "--", "src/a.ts"), tmp_path)
    executor = FakeProcessExecutor(_unreachable)

    report = oxlint.run_oxlint(command, root=tmp_path, runner=executor, environment={}, request=oxlint.OxlintRequest())

    assert report.completion is Completion.FAILED
    assert [issue.kind for issue in report.issues] == ["missing-dependency"]
    assert "node_modules/.bin/tsrs-lint is missing" in report.issues[0].message
    assert executor.requests == []


def test_full_run_type_checks_and_reports_files_the_config_excludes(tmp_path: Path) -> None:
    config = (
        'import { createConfig } from "./oxlint.strict.ts";\n'
        'export default { extends: [createConfig()], ignorePatterns: ["src/legacy/**"] };\n'
    )
    root = project(
        tmp_path / "repo",
        {
            "src/a.ts": "export const n: number = 'x';\ndebugger;\n",
            "src/legacy/b.ts": "export const b = 1;\n",
        },
        config=config,
    )

    report = analyze(root, oxlint.OxlintRequest(), "src")

    assert report.completion is Completion.COMPLETE
    assert {item.rule_id for item in report.diagnostics} == {"tsc/TS2322", "no-debugger"}
    assert not report.issues
    assert report.file_count == 1
    (scope,) = report.rule_executions
    assert scope.execution.value == "skipped"
    assert scope.file_count == 1
    assert scope.reason == "skipped-scope: native Oxlint ignore policy excludes src/legacy/b.ts"
    assert not list(root.glob(".sarj-oxlint-*"))


def test_full_run_type_checks_project_files_outside_the_lint_selection(tmp_path: Path) -> None:
    root = project(
        tmp_path / "repo",
        {
            "src/selected.ts": "export const selected = 1;\n",
            "src/sibling.ts": "export const n: number = 'x';\n",
        },
    )

    report = analyze(root, oxlint.OxlintRequest(), "src/selected.ts")

    assert report.issues == ()
    assert {(item.rule_id, item.location.path) for item in report.diagnostics} == {("tsc/TS2322", "src/sibling.ts")}


def test_explicit_config_disables_nested_config_lookup(tmp_path: Path) -> None:
    root = project(
        tmp_path / "repo",
        {"src/nested/a.ts": "debugger;\n", "src/nested/.oxlintrc.json": '{"rules": {"no-debugger": "off"}}\n'},
    )
    # Native discovery applies the nested config; `-c` alone would not.
    for argv, expected in (((), set[str]()), (("-c", "oxlint.config.ts"), {"no-debugger"})):
        output = DEFAULT_EXECUTOR.run(ProcessRequest((str(OXLINT), *argv, "-f", "json", "src"), root, environment()))
        result = oxlint.read_oxlint(output, root=root, cwd=root, selected=False)
        assert {item.rule_id for item in result.diagnostics} == expected

    # Standards groups by nearest config, so the nested config owns its file.
    (command,) = oxlint.select_oxlint_commands(root, ["src/nested/a.ts"]).commands
    assert command.cwd == root / "src/nested"
    assert command.argv[command.argv.index("-c") + 1] == ".oxlintrc.json"
    report = oxlint.run_oxlint(
        local(command),
        root=root,
        runner=DEFAULT_EXECUTOR,
        environment=environment(),
        request=oxlint.OxlintRequest(forced={}),
    )
    assert report.issues == ()
    assert report.diagnostics == ()


def test_selection_skips_skill_payloads_links_generated_trees_and_lint_configs(tmp_path: Path) -> None:
    _touch(
        tmp_path,
        "oxlint.config.mts",
        "package.json",
        "src/a.ts",
        ".agents/tools/helper.ts",
        ".agents/skills/x/payload.ts",
        ".claude/skills/x/payload.ts",
        "packages/app/.claude/skills/x/payload.ts",
        "build/out.js",
        "eslint.config.mjs",
        "oxlint.strict.mts",
    )
    (tmp_path / "src/link.ts").symlink_to(tmp_path / "src/a.ts")

    for paths in (["."], ["src/a.ts", "src/link.ts", ".agents/tools/helper.ts", ".claude/skills/x/payload.ts"]):
        (command,) = oxlint.select_oxlint_commands(tmp_path, paths).commands
        assert oxlint.command_files(command) == frozenset({tmp_path / "src/a.ts", tmp_path / ".agents/tools/helper.ts"})


def test_ignored_selected_source_completes_check_and_baseline_init(tmp_path: Path) -> None:
    config = 'import { createConfig } from "./oxlint.strict.ts"; export default {extends:[createConfig()],ignorePatterns:["scripts/**"]};'
    root = project(tmp_path / "repo", {"scripts/lib.mjs": "debugger;\n", "adjacent.mjs": "debugger;\n"}, config=config)
    (root / "oxfmt.config.mts").write_text("export default {printWidth:80};\n")
    disabled = json.dumps([name for name in ALL_CAPABILITIES if name != "typescript"])
    (root / ".sarj-standards.toml").write_text(f'schema=4\nbundle="9.4.5"\n[capabilities]\ndisable={disabled}\n')
    commands = (
        ("check", "scripts/lib.mjs", "--trust-repository-code", "--format", "json"),
        ("baseline", "init", "scripts/lib.mjs", "--trust-repository-code", "--output", str(root / "baseline.json")),
    )
    for arguments in commands:
        result = subprocess.run(
            (sys.executable, "-m", "sarj_standards", "--root", str(root), *arguments),
            cwd=root,
            capture_output=True,
            text=True,
            timeout=90,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
    result = subprocess.run(
        (
            sys.executable,
            "-m",
            "sarj_standards",
            "--root",
            str(root),
            "check",
            "adjacent.mjs",
            "--trust-repository-code",
            "--format",
            "json",
        ),
        cwd=root,
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert '"ruleId": "no-debugger"' in result.stdout


def test_native_discovery_cannot_explain_a_missing_file(tmp_path: Path) -> None:
    root = project(tmp_path / "repo", {"source.ts": "export const n = 1;\n"})
    outputs = iter(
        (
            ProcessOutput(0, '{"diagnostics":[],"number_of_files":0}', ""),
            ProcessOutput(0, "", ""),
            ProcessOutput(0, "", ""),
        )
    )

    def discovery(_argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        assert cwd == root
        return next(outputs)

    executor = FakeProcessExecutor(discovery)
    command = local(oxlint.select_oxlint_commands(root, ("source.ts",)).commands[0])
    report = oxlint.run_oxlint(
        command, root=root, runner=executor, environment=environment(), request=oxlint.OxlintRequest()
    )
    assert report.completion is Completion.FAILED
    assert report.issues[0].kind == "coverage-missing"
    assert not report.rule_executions


def test_actual_plugin_crash_remains_execution_failure(tmp_path: Path) -> None:
    config = (
        'export default {jsPlugins:[{name:"scope-crash",specifier:"./scope-crash.mjs"}],'
        'rules:{"scope-crash/explode":"error"}};'
    )
    root = project(tmp_path / "repo", {"source.mjs": "export const value = 1;\n"}, config=config)
    (root / "scope-crash.mjs").write_text(
        'export default {meta:{name:"scope-crash"},rules:{explode:{create(){throw new Error("scope crash control")}}}};'
    )
    report = analyze(root, oxlint.OxlintRequest(), "source.mjs")
    assert report.completion is Completion.FAILED
    assert report.issues
    assert not report.rule_executions


def test_actual_parser_failure_is_not_a_scope_exclusion(tmp_path: Path) -> None:
    root = project(tmp_path / "repo", {"source.mjs": "const value = ;\n"})
    report = analyze(root, oxlint.OxlintRequest(), "source.mjs")
    assert report.completion is Completion.FAILED
    assert report.issues
    assert not report.rule_executions


def test_unowned_source_is_not_a_scope_exclusion(tmp_path: Path) -> None:
    source = tmp_path / "source.mjs"
    source.write_text("debugger;\n")
    selection = oxlint.select_oxlint_commands(tmp_path, (str(source),))
    assert selection.unowned_count == 1
    assert not selection.commands
