from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
from typing import TYPE_CHECKING

import pytest

from sarj_standards.libs.diagnostics import (
    Completion,
    RuleExecution,
    RuleExecutionState,
    ToolReport,
    to_github,
    to_sarif,
    to_text,
)
from sarj_standards.libs.linting import external as external_module
from sarj_standards.libs.linting.analysis import report_from_tools
from sarj_standards.libs.linting.external import parse_eslint, parse_eslint_executions
from sarj_standards.libs.linting.process import ProcessOutput
from tests.process_fakes import FakeProcessExecutor


if TYPE_CHECKING:
    from collections.abc import Sequence

    from pydantic import JsonValue


def _payload(execution: str = "skipped", file_count: JsonValue = 2) -> str:
    return json.dumps(
        {
            "results": [
                {"filePath": "first.ts", "messages": []},
                {"filePath": "second.ts", "messages": []},
            ],
            "ruleExecutions": [
                {
                    "ruleId": "@sarj/no-known-value-widening",
                    "execution": execution,
                    "requiresTypeInformation": True,
                    "fileCount": file_count,
                    "reason": "missing-type-information",
                }
            ],
        }
    )


def test_legacy_eslint_arrays_have_unspecified_execution_coverage(tmp_path: Path) -> None:
    assert parse_eslint("[]", root=tmp_path) == ()
    assert parse_eslint_executions("[]") == ()


def test_clean_eslint_output_retains_a_skipped_semantic_check(tmp_path: Path) -> None:
    rows = parse_eslint_executions(_payload())
    assert parse_eslint(_payload(), root=tmp_path) == ()
    assert rows == (
        RuleExecution("@sarj/no-known-value-widening", RuleExecutionState.SKIPPED, 2, True, "missing-type-information"),
    )
    report = ToolReport("eslint", Completion.COMPLETE, rule_executions=rows)
    serialized = report.as_dict()
    assert "ruleExecutions" in serialized
    assert serialized["ruleExecutions"] == [
        {
            "ruleId": "@sarj/no-known-value-widening",
            "execution": "skipped",
            "requiresTypeInformation": True,
            "fileCount": 2,
            "reason": "missing-type-information",
        }
    ]


@pytest.mark.parametrize("count", [0, -1, True, "2"])
def test_execution_counts_reject_invalid_file_counts(count: JsonValue) -> None:
    with pytest.raises(ValueError, match="positive integer"):
        parse_eslint_executions(_payload(file_count=count))


def test_execution_counts_cannot_exceed_analyzed_coverage() -> None:
    with pytest.raises(ValueError, match="exceeds reported file coverage"):
        parse_eslint_executions(_payload(file_count=3))


def test_execution_counts_include_inputs_omitted_as_ignored() -> None:
    payload = json.dumps(
        {
            "results": [],
            "ruleExecutions": [
                {
                    "ruleId": "@sarj/probe",
                    "execution": "ignored",
                    "requiresTypeInformation": None,
                    "fileCount": 1,
                    "reason": "input-not-configured",
                }
            ],
        }
    )
    rows = parse_eslint_executions(payload, file_count=1)
    assert rows[0].execution is RuleExecutionState.IGNORED
    assert rows[0].file_count == 1


def test_duplicate_execution_groups_are_rejected() -> None:
    row = {
        "ruleId": "@sarj/probe",
        "execution": "skipped",
        "requiresTypeInformation": True,
        "fileCount": 1,
        "reason": "missing-type-information",
    }
    payload = json.dumps(
        {"results": [{"filePath": "first.ts"}, {"filePath": "second.ts"}], "ruleExecutions": [row, row]}
    )
    with pytest.raises(ValueError, match="duplicate groups"):
        parse_eslint_executions(payload)


def test_malformed_execution_metadata_preserves_native_diagnostics(tmp_path: Path) -> None:
    source = tmp_path / "input.ts"
    source.write_text("const value: unknown = { id: 'u1' };\n", encoding="utf-8")
    payload = json.dumps(
        {
            "results": [
                {
                    "filePath": str(source),
                    "messages": [
                        {
                            "ruleId": "@sarj/no-known-value-widening",
                            "severity": 1,
                            "message": "Retain the known contract.",
                            "line": 1,
                            "column": 1,
                        }
                    ],
                }
            ],
            "ruleExecutions": [
                {
                    "ruleId": "@sarj/no-known-value-widening",
                    "execution": "ran",
                    "requiresTypeInformation": True,
                    "fileCount": True,
                }
            ],
        }
    )

    def controlled(_argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        assert cwd == tmp_path
        return ProcessOutput(0, payload, "")

    report = external_module._invoke(  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage] -- Exercise the native invocation boundary with controlled wire data.
        "eslint",
        ("eslint",),
        cwd=tmp_path,
        root=tmp_path,
        runner=FakeProcessExecutor(controlled),
        parser=parse_eslint,
        execution_parser=parse_eslint_executions,
        file_count=1,
    )
    assert report.completion is Completion.FAILED
    assert len(report.diagnostics) == 1
    assert report.diagnostics[0].rule_id == "@sarj/no-known-value-widening"
    assert report.issues[0].kind == "protocol-mismatch"


def test_unknown_prerequisites_cannot_be_reported_as_ran() -> None:
    with pytest.raises(ValueError, match="must declare"):
        RuleExecution("@sarj/probe", RuleExecutionState.RAN, 1, None)


def test_skipped_checks_explain_their_reason() -> None:
    with pytest.raises(ValueError, match="explain"):
        RuleExecution("@sarj/probe", RuleExecutionState.SKIPPED, 1, True)


def test_completed_checks_cannot_claim_missing_prerequisites() -> None:
    with pytest.raises(ValueError, match="unevaluated reason"):
        RuleExecution("@sarj/probe", RuleExecutionState.RAN, 1, True, "missing-type-information")


@pytest.mark.parametrize("state", [RuleExecutionState.DISABLED, RuleExecutionState.UNTRACKED])
def test_missing_types_only_explain_a_skipped_check(state: RuleExecutionState) -> None:
    with pytest.raises(ValueError, match="skipped, explicitly typed"):
        RuleExecution("@sarj/probe", state, 1, True, "missing-type-information")


def test_failed_rule_execution_cannot_be_a_complete_tool() -> None:
    row = RuleExecution("@sarj/probe", RuleExecutionState.FAILED, 1, False, "rule-execution-failed")
    with pytest.raises(ValueError, match="failed rule executions"):
        ToolReport("eslint", Completion.COMPLETE, rule_executions=(row,))


_NODE_PROBE = r"""
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { writeFile } from 'node:fs/promises';
import { join } from 'node:path';
const [root, packageRoot, helperUrl] = process.argv.slice(1);
const require = createRequire(join(packageRoot, 'package.json'));
const { ESLint } = require('eslint');
const parser = require('@typescript-eslint/parser');
const loaded = require(join(packageRoot, 'dist/index.cjs'));
const plugin = loaded.default ?? loaded;
const { lintWithRuleExecutions } = await import(helperUrl);
const filename = join(root, 'input.ts');
await writeFile(filename, "const value: unknown = { id: 'u1' };\n");
const secondFile = join(root, 'second.ts');
await writeFile(secondFile, "const item = 1;\n");
const suppressedFile = join(root, 'suppressed.ts');
await writeFile(suppressedFile, "// eslint-disable-next-line @sarj/no-known-value-widening -- Opaque API fixture.\nconst value: unknown = { id: 'u1' };\n");
await writeFile(join(root, 'tsconfig.json'), JSON.stringify({
  compilerOptions: { target: 'es2022', module: 'esnext', strict: true, types: [] },
  include: ['*.ts'],
}));
function analyzer(level, typed = false) {
  return new ESLint({
    cwd: root, overrideConfigFile: true,
    overrideConfig: {
      files: ['**/*.ts'],
      languageOptions: { parser, parserOptions: typed
        ? { project: join(root, 'tsconfig.json'), tsconfigRootDir: root } : {} },
      plugins: { '@sarj': plugin },
      rules: { '@sarj/no-known-value-widening': level },
    },
  });
}
const request = { full: true, rules: new Set() };
const skipped = await lintWithRuleExecutions(analyzer('warn'), [filename], request);
assert.deepEqual(skipped.results[0].messages, []);
assert.equal(skipped.executions[0].execution, 'skipped');
assert.equal(skipped.executions[0].reason, 'missing-type-information');
const ran = await lintWithRuleExecutions(analyzer('warn', true), [filename], request);
assert.equal(ran.results[0].messages.length, 1);
assert.equal(ran.executions[0].execution, 'ran');
assert.equal(ran.executions[0].requiresTypeInformation, true);
const suppressed = await lintWithRuleExecutions(analyzer('warn', true), [suppressedFile], request);
assert.equal(suppressed.results[0].messages.length, 0);
assert.equal(suppressed.executions[0].execution, 'ran');
const disabled = await lintWithRuleExecutions(analyzer('off'), [filename, secondFile], request);
assert.equal(disabled.executions[0].execution, 'disabled');
assert.equal(disabled.executions[0].fileCount, 2);
const legacy = new ESLint({
  cwd: root, overrideConfigFile: true,
  overrideConfig: {
    files: ['**/*.ts'], languageOptions: { parser },
    plugins: { '@sarj': { rules: { legacy: {
      meta: { type: 'problem', schema: [] }, create() { return {}; },
    } } } },
    rules: { '@sarj/legacy': 'warn' },
  },
});
const untracked = await lintWithRuleExecutions(legacy, [filename, secondFile], request);
assert.equal(untracked.executions[0].execution, 'untracked');
assert.equal(untracked.executions[0].reason, 'requirements-not-declared');
assert.equal(untracked.executions[0].fileCount, 2);
const declaredLegacy = new ESLint({
  cwd: root, overrideConfigFile: true,
  overrideConfig: {
    files: ['**/*.ts'], languageOptions: { parser },
    plugins: { '@sarj': { rules: { legacy: {
      documentation: { requiresTypeInformation: true },
      meta: { type: 'problem', schema: [] }, create() { return {}; },
    } } } }, rules: { '@sarj/legacy': 'warn' },
  },
});
const unavailable = await lintWithRuleExecutions(declaredLegacy, [filename], request);
assert.equal(unavailable.executions[0].execution, 'untracked');
assert.equal(unavailable.executions[0].requiresTypeInformation, true);
assert.equal(unavailable.executions[0].reason, 'execution-reporting-unavailable');
const ignoredFile = join(root, 'ignored.txt');
await writeFile(ignoredFile, 'not configured');
const ignored = await lintWithRuleExecutions(analyzer('warn'), [ignoredFile], {
  full: false, rules: new Set(['@sarj/no-known-value-widening']),
});
assert.equal(ignored.executions[0].execution, 'ignored');
const executionFields = new Set(['ruleId', 'execution', 'requiresTypeInformation', 'fileCount', 'reason']);
for (const result of [skipped, ran, suppressed, disabled, untracked, unavailable, ignored]) {
  for (const row of result.executions) {
    assert.deepEqual(Object.keys(row).filter(field => !executionFields.has(field)), []);
  }
}
const preparation = analyzer('warn');
const calculate = preparation.calculateConfigForFile.bind(preparation);
let reads = 0;
preparation.calculateConfigForFile = async path => {
  if (++reads === 2) throw new Error('config failed');
  return calculate(path);
};
await assert.rejects(lintWithRuleExecutions(preparation, [filename, join(root, 'second.ts')], request), /config failed/);
assert.deepEqual(plugin.rules['no-known-value-widening'].trackExecution().finish(), []);
await assert.rejects(lintWithRuleExecutions(analyzer('warn'), [join(root, 'missing.ts')], request), /No files matching/);
assert.deepEqual(plugin.rules['no-known-value-widening'].trackExecution().finish(), []);
parser.clearCaches();
process.stdout.write(JSON.stringify({ results: skipped.results, ruleExecutions: skipped.executions }));
"""


def test_native_engine_events_reach_the_analysis_protocol(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[3]
    package = root / "packages" / "typescript"
    helper = root / "packages" / "standards" / "src" / "sarj_standards" / "configs" / "eslint-rule-execution.mts"
    node = shutil.which("node")
    assert node is not None
    result = subprocess.run(
        (node, "--input-type=module", "--eval", _NODE_PROBE, str(tmp_path), str(package), helper.as_uri()),
        cwd=package,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert parse_eslint(result.stdout, root=tmp_path) == ()
    rows = parse_eslint_executions(result.stdout)
    assert len(rows) == 1
    assert rows[0].execution is RuleExecutionState.SKIPPED
    assert rows[0].file_count == 1


def test_skipped_semantic_checks_are_visible_without_new_source_diagnostics(tmp_path: Path) -> None:
    row = RuleExecution(
        "@sarj/no-known-value-widening", RuleExecutionState.SKIPPED, 1, True, "missing-type-information"
    )
    report = report_from_tools(tmp_path, (ToolReport("eslint", Completion.COMPLETE, rule_executions=(row,)),))
    assert report.exit_code == 0
    assert report.diagnostics == ()
    for rendered in (to_text(report), to_github(report), to_sarif(report)):
        assert "missing-type-information" in rendered
        assert "@sarj/no-known-value-widening skipped on 1 file(s)" in rendered
    assert "0 error(s), 0 warning(s), 0 notice(s), 0 execution issue(s)" in to_text(report)


def test_legacy_unknown_requirements_render_as_one_group(tmp_path: Path) -> None:
    rows = tuple(
        RuleExecution(rule, RuleExecutionState.UNTRACKED, 1, None, "requirements-not-declared")
        for rule in ("@sarj/first", "@sarj/second")
    )
    report = report_from_tools(tmp_path, (ToolReport("eslint", Completion.COMPLETE, rule_executions=rows),))
    rendered = to_text(report)
    assert rendered.count("code-standards execution:") == 1
    assert "2 rule(s) untracked: requirements-not-declared" in rendered
    assert report.exit_code == 0
