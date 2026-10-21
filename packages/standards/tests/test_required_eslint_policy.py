from __future__ import annotations

import json
from pathlib import Path
import shutil

import pytest

from sarj_standards import api
from sarj_standards.libs.adoption import manifest
from sarj_standards.libs.adoption.manifest import Manifest
from sarj_standards.libs.diagnostics import Completion, Severity, TrustMode, baseline
from sarj_standards.libs.linting.analysis import report_from_tools
from sarj_standards.libs.linting.external import analyze_external, run_process
from sarj_standards.libs.linting.policy import Policy
from sarj_standards.libs.rules import RuleEngine, RuleId, RuleSelector


_PREFIX = "@eslint-community/eslint-comments/"
_META_NAMES = (
    "require-description",
    "no-unlimited-disable",
    "no-use",
    "disable-enable-pair",
    "no-aggregating-enable",
    "no-duplicate-disable",
    "no-unused-enable",
    "no-restricted-disable",
)
_TURN_OFF_META = "/* eslint " + ", ".join(f'"{_PREFIX}{name}": "off"' for name in _META_NAMES) + " */\n"


@pytest.fixture
def eslint_project(tmp_path: Path) -> Path:
    typescript = Path(__file__).resolve().parents[2] / "typescript"
    modules = typescript / "node_modules"
    if shutil.which("node") is None or not (modules / "eslint/package.json").is_file():
        pytest.skip("requires the repository's locked TypeScript dependencies")
    dependencies = tmp_path / "node_modules"
    dependencies.mkdir()
    (dependencies / ".bin").symlink_to(modules / ".bin", target_is_directory=True)
    for name in ("eslint", "typescript-eslint", "@eslint-community/eslint-plugin-eslint-comments"):
        destination = dependencies / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.symlink_to(modules / name, target_is_directory=True)
    (dependencies / "@sarj").mkdir()
    (dependencies / "@sarj/eslint-plugin").symlink_to(typescript, target_is_directory=True)
    (tmp_path / "package.json").write_text('{"type":"module"}', encoding="utf-8")
    (tmp_path / "eslint.config.mjs").write_text(
        "import ts from 'typescript-eslint';\n"
        "import comments from '@eslint-community/eslint-plugin-eslint-comments';\n"
        "import sarj from '@sarj/eslint-plugin';\n"
        "export default [{files:['**/*.{js,jsx,mjs,cjs,ts,tsx,mts,cts}'],languageOptions:{parser:ts.parser},"
        "linterOptions:{reportUnusedDisableDirectives:'error',reportUnusedInlineConfigs:'error'},"
        "plugins:{'@eslint-community/eslint-comments':comments,'@sarj':sarj},rules:{"
        "'no-debugger':'error', '@sarj/no-vague-suppression-description':'error',"
        + ",".join(f"'{_PREFIX}{name}':'error'" for name in _META_NAMES)
        + "}}];\n",
        encoding="utf-8",
    )
    return tmp_path


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (_TURN_OFF_META + "/* eslint-disable */\ndebugger;\n", _PREFIX + "no-unlimited-disable"),
        ("/* eslint-disable no-debugger -- the adapter runs in a debugger */\ndebugger;\n", _PREFIX + "no-use"),
        ("// eslint-disable-next-line\ndebugger;\n", _PREFIX + "no-unlimited-disable"),
        ("// eslint-disable-next-line no-debugger\ndebugger;\n", _PREFIX + "require-description"),
        (
            (
                "// eslint-disable-next-line @eslint-community/eslint-comments/require-description -- adapter boundary\n"
                "// eslint-disable-next-line no-debugger\ndebugger;\n"
            ),
            _PREFIX + "no-restricted-disable",
        ),
        (
            "// @ts-ignore -- SDK declaration omits the runtime property\nconst item: string = 1;\n",
            "@typescript-eslint/ban-ts-comment",
        ),
        (
            "// @ts-nocheck -- SDK declaration omits the runtime property\nconst item: string = 1;\n",
            "@typescript-eslint/ban-ts-comment",
        ),
        ("// @ts-expect-error\nconst item: string = 1;\n", "@typescript-eslint/ban-ts-comment"),
        (
            "// @generated\n// @ts-expect-error -- needed\nconst item: string = 1;\n",
            "@sarj/no-vague-suppression-description",
        ),
        (
            (
                '/* eslint "@sarj/no-vague-suppression-description": "off" */\n'
                "// @ts-expect-error -- same\nconst item: string = 1;\n"
            ),
            "@sarj/no-vague-suppression-description",
        ),
    ],
    ids=(
        "inline-config-meta-disable",
        "range-disable",
        "blanket-local",
        "missing-reason",
        "self-disable",
        "ts-ignore",
        "ts-nocheck",
        "expect-error-description",
        "generated-marker",
        "inline-config-vague-disable",
    ),
)
def test_full_eslint_cannot_disable_its_suppression_policy(eslint_project: Path, source: str, expected: str) -> None:
    path = eslint_project / "sample.ts"
    path.write_text(source, encoding="utf-8")
    tools = analyze_external(
        [str(path)], root=eslint_project, trust=TrustMode.TRUSTED, capabilities=frozenset({"eslint"})
    )
    assert len(tools) == 1
    assert tools[0].completion is Completion.COMPLETE, tools[0].issues
    findings = [item for item in tools[0].diagnostics if item.rule_id == expected]
    assert findings
    assert all("required-source-policy" in item.tags for item in findings)
    assert all(not baseline.is_baselineable(item) for item in findings)


@pytest.mark.parametrize("bulk", [False, True])
def test_required_eslint_findings_survive_consumer_config_bulk_baseline_and_rule_exclusions(
    eslint_project: Path, *, bulk: bool
) -> None:
    rule_id = "@sarj/no-vague-suppression-description"
    path = eslint_project / "sample.ts"
    path.write_text("// @ts-expect-error -- needed\nconst value: string = 1;\n", encoding="utf-8")
    if bulk:
        (eslint_project / "eslint-suppressions.json").write_text(
            json.dumps({"sample.ts": {rule_id: {"count": 1}}}), encoding="utf-8"
        )
    else:
        (eslint_project / "eslint.config.mjs").write_text(
            "export default [{files:['**/*.ts'],rules:{}}];\n", encoding="utf-8"
        )
        path.write_text("// @ts-expect-error -- needed\nconst value = 1;\n", encoding="utf-8")
    tools = analyze_external(
        [str(path)], root=eslint_project, trust=TrustMode.TRUSTED, capabilities=frozenset({"eslint"})
    )
    assert tools[0].completion is Completion.COMPLETE, tools[0].issues
    report = report_from_tools(eslint_project, tools)
    finding = next(item for item in report.diagnostics if item.rule_id == rule_id)
    policy = Policy.from_manifest(
        eslint_project,
        Manifest(
            version=api.__version__,
            configs=("eslint",),
            python_dest=".",
            typescript_dest=".",
            excluded_rules=(f"eslint:{rule_id}",),
        ),
    )
    assert finding in policy.filter_diagnostics(report.diagnostics)
    assert finding.fingerprint is not None
    active = api._without_baselined_diagnostics(report, {finding.fingerprint: 100})  # ruff: ignore[private-member-access] -- exercise the canonical gate's existing-baseline boundary. # pyright: ignore[reportPrivateUsage]
    assert finding in active.diagnostics


def test_full_eslint_keeps_explained_local_exceptions(eslint_project: Path) -> None:
    path = eslint_project / "sample.ts"
    path.write_text(
        "// eslint-disable-next-line no-debugger -- browser protocol pauses at this injected breakpoint\ndebugger;\n// @ts-expect-error -- SDK declaration omits the runtime token field\nconst value = 1;\n",
        encoding="utf-8",
    )
    # The ordinary config permits named local exceptions; the mandatory floor
    # must not reinstate no-debugger or turn on unrelated style rules.
    (eslint_project / "eslint.config.mjs").write_text(
        "export default [{files:['**/*.ts'],rules:{'no-debugger':'error'}}];\n", encoding="utf-8"
    )
    tools = analyze_external(
        [str(path)], root=eslint_project, trust=TrustMode.TRUSTED, capabilities=frozenset({"eslint"})
    )
    assert tools[0].completion is Completion.COMPLETE, tools[0].issues
    assert tools[0].diagnostics == ()


def test_required_eslint_covers_sibling_tooling_outside_project_cwd(eslint_project: Path) -> None:
    paths = (eslint_project / "sample.ts", eslint_project.parent / "sibling.ts")
    for path in paths:
        path.write_text("// @ts-nocheck\nconst value = 1;\n", encoding="utf-8")
    script = (
        "const {requiredSuppressionResults}=await import(process.argv[1]);"
        "const results=await requiredSuppressionResults(process.argv.slice(2));"
        "console.log(JSON.stringify(Object.fromEntries(results.map(r=>[r.filePath,r.messages.map(m=>m.ruleId)]))));"
    )
    result = run_process(
        (
            "node",
            "--input-type=module",
            "--eval",
            script,
            manifest.PEERS_JSON.with_name("eslint-required-policy.mts").as_uri(),
            *(str(path) for path in paths),
        ),
        cwd=eslint_project,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {str(path): ["@typescript-eslint/ban-ts-comment"] for path in paths}


@pytest.mark.parametrize("fail_on_warnings", [False, True])
def test_full_console_driver_preserves_the_provider_warning_gate(
    eslint_project: Path, *, fail_on_warnings: bool
) -> None:
    (eslint_project / "sample.ts").write_text("debugger;\n", encoding="utf-8")
    (eslint_project / "eslint.config.mjs").write_text(
        "export default [{files:['**/*.ts'],rules:{'no-debugger':'warn'}}];\n", encoding="utf-8"
    )
    request = json.dumps(
        {"full": True, "config": None, "rules": [], "consoleOutput": True, "failOnWarnings": fail_on_warnings}
    )
    result = run_process(
        ("node", str(manifest.PEERS_JSON.with_name("eslint-selected-rules.mts")), request, "--", "sample.ts"),
        cwd=eslint_project,
    )
    assert result.returncode == int(fail_on_warnings), result.stderr
    assert "warning" in result.stdout
    assert "no-debugger" in result.stdout


def test_canonical_warning_staging_cannot_demote_the_required_floor(eslint_project: Path) -> None:
    path = eslint_project / "sample.ts"
    path.write_text("// @ts-expect-error -- needed\nconst value = 1;\n", encoding="utf-8")
    tools = analyze_external(
        [str(path)], root=eslint_project, trust=TrustMode.TRUSTED, capabilities=frozenset({"eslint"})
    )
    report = report_from_tools(eslint_project, tools)
    selector = RuleSelector(RuleEngine.ESLINT, RuleId("no-vague-suppression-description"))
    active = api._with_warning_severity(report, frozenset({selector}))  # ruff: ignore[private-member-access] -- exercise the canonical warning-stage boundary with an explicitly selected advisory. # pyright: ignore[reportPrivateUsage]
    findings = [item for item in active.diagnostics if item.rule_id == "@sarj/no-vague-suppression-description"]
    assert len(findings) == 1
    assert findings[0].severity is Severity.ERROR
    assert active.exit_code == 1


def test_full_facade_keeps_required_hygiene_blocking(eslint_project: Path) -> None:
    (eslint_project / ".sarj-standards.toml").write_text(
        Manifest(version=api.__version__, configs=("eslint",), python_dest=".", typescript_dest=".").render(),
        encoding="utf-8",
    )
    path = eslint_project / "sample.ts"
    path.write_text("// @ts-expect-error -- needed\nconst value = 1;\n", encoding="utf-8")
    report = api.Standards(eslint_project).analyze(
        [str(path)], external=True, trust=TrustMode.TRUSTED, include_react_doctor=False
    )
    finding = next(item for item in report.diagnostics if item.rule_id == "@sarj/no-vague-suppression-description")
    assert finding.severity is Severity.ERROR
    assert "required-source-policy" in finding.tags
    assert report.exit_code == 1
