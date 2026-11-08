from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from typing import TYPE_CHECKING, Final

import pytest

from sarj_standards.libs.adoption import lifecycle
from sarj_standards.libs.adoption.manifest import MANIFEST_NAME, ExclusionOverride, Manifest
from sarj_standards.libs.diagnostics import Completion, Diagnostic, Location, Severity, TrustMode, baseline
from sarj_standards.libs.linting import autofix, oxlint, oxlint_directives
from sarj_standards.libs.linting.external import UpstreamRules, analyze_external
from sarj_standards.libs.linting.policy import Policy
from sarj_standards.libs.linting.process import ProcessCapabilities, ProcessOutput, ToolResolution
from tests.oxlint_project import MODULES, environment, project


if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from pydantic import JsonValue

    from sarj_standards.libs.linting.process import ProcessRequest


_CAPABILITIES = frozenset({lifecycle.TYPESCRIPT_CAPABILITY})


class _Executor:
    def __init__(
        self,
        respond: Callable[[ProcessRequest], ProcessOutput],
        resolution: ToolResolution = ToolResolution.PROVIDED,
    ) -> None:
        self.respond = respond
        self.capabilities = ProcessCapabilities(resolution)
        self.requests: list[ProcessRequest] = []

    def run(self, request: ProcessRequest) -> ProcessOutput:
        self.requests.append(request)
        return self.respond(request)


def _tool(request: ProcessRequest) -> str:
    return next(Path(value).name for value in request.argv if Path(value).name in {"oxlint", "oxfmt"})


def _overlay(request: ProcessRequest) -> dict[str, JsonValue]:
    argv = list(request.argv)
    text = (request.cwd / argv[argv.index("-c") + 1]).read_text(encoding="utf-8")
    value: dict[str, JsonValue] = json.loads(text[text.index("(") + 1 : text.rindex(")")])  # pyright: ignore[reportAny] -- the overlay embeds its JSON request.
    return value


def _oxlint_output(request: ProcessRequest, *records: Mapping[str, JsonValue]) -> ProcessOutput:
    files = oxlint.command_files(lifecycle.Command("", request.argv, request.cwd))
    return ProcessOutput(1 if records else 0, json.dumps({"diagnostics": records, "number_of_files": len(files)}), "")


def _typescript_project(root: Path, *, oxfmt_config: str | None = ".oxfmtrc.json") -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "package.json").write_text('{"name":"fixture"}\n', encoding="utf-8")
    (root / "oxlint.config.mts").write_text("export default {};\n", encoding="utf-8")
    if oxfmt_config is not None:
        (root / oxfmt_config).write_text("{}\n", encoding="utf-8")
    binaries = root / "node_modules" / ".bin"
    binaries.mkdir(parents=True)
    for name in ("oxlint", "oxfmt", "tsrs-lint"):
        (binaries / name).touch()
    source = root / "src" / "app.ts"
    source.parent.mkdir()
    source.write_text("debugger;\n", encoding="utf-8")
    return root


_DEBUGGER: Final[Mapping[str, JsonValue]] = {
    "message": "`debugger` statement is not allowed",
    "code": "eslint(no-debugger)",
    "severity": "error",
    "filename": "src/app.ts",
    "labels": [{"span": {"offset": 0, "length": 9}}],
}
_STALE: Final[Mapping[str, JsonValue]] = {
    "message": "There are suppressions that do not occur anymore.",
    "severity": "error",
    "filename": "oxlint-suppressions.json",
}


def test_full_analysis_runs_one_type_checked_oxlint_and_one_oxfmt_per_project(tmp_path: Path) -> None:
    root = _typescript_project(tmp_path)

    def respond(request: ProcessRequest) -> ProcessOutput:
        if _tool(request) == "oxfmt":
            assert request.argv[-2:] == ("--", ".")
            return ProcessOutput(1, "src/app.ts\n", "")
        assert {"-f", "json", "--type-aware", "--type-check"} <= set(request.argv)
        assert request.environment["OXLINT_TSGOLINT_PATH"] == str(root / "node_modules/.bin/tsrs-lint")
        assert request.environment["NODE_OPTIONS"].startswith("--max-old-space-size=")
        assert _overlay(request)["rules"] is None
        return _oxlint_output(request, _DEBUGGER)

    executor = _Executor(respond)
    reports = analyze_external(
        [str(root)], root=root, trust=TrustMode.TRUSTED, runner=executor, capabilities=_CAPABILITIES
    )

    assert [(report.name, report.invocation_id, report.completion) for report in reports] == [
        ("oxlint", "oxlint:.", Completion.COMPLETE),
        ("oxfmt", "oxfmt:.", Completion.COMPLETE),
    ]
    assert [(item.rule_id, item.location.path) for report in reports for item in report.diagnostics] == [
        ("no-debugger", "src/app.ts"),
        ("format", "src/app.ts"),
    ]
    assert reports[0].file_count == 1
    assert reports[0].duration_ms is not None
    assert len(executor.requests) == 2


def test_selected_rules_run_through_the_overlay_without_type_check_or_formatting(tmp_path: Path) -> None:
    root = _typescript_project(tmp_path)
    overlays: list[dict[str, JsonValue]] = []

    def respond(request: ProcessRequest) -> ProcessOutput:
        assert _tool(request) == "oxlint"
        assert "--type-check" not in request.argv
        overlays.append(_overlay(request))
        return _oxlint_output(request)

    reports = analyze_external(
        [str(root / "src/app.ts")],
        root=root,
        trust=TrustMode.TRUSTED,
        runner=_Executor(respond),
        capabilities=_CAPABILITIES,
        rule_ids=frozenset({"no-tautological-expect"}),
        upstream_rules=UpstreamRules(frozenset({"vitest/expect-expect"}), warning_only=True),
    )

    assert [report.name for report in reports] == ["oxlint"]
    (overlay,) = overlays
    assert overlay["rules"] == ["@sarj/no-tautological-expect", "vitest/expect-expect"]
    forced = overlay["forced"]
    assert isinstance(forced, dict)
    # Advisories run at error so bulk suppressions apply; the floor stays forced.
    assert forced["vitest/expect-expect"] == "error"
    assert set(oxlint.REQUIRED_RULES) <= set(forced)


def test_safe_trust_never_executes_oxlint_or_an_executable_oxfmt_config(tmp_path: Path) -> None:
    root = _typescript_project(tmp_path, oxfmt_config="oxfmt.config.mts")

    def forbidden(_request: ProcessRequest) -> ProcessOutput:
        pytest.fail("safe mode executed repository code")

    reports = analyze_external(
        [str(root)], root=root, trust="safe", runner=_Executor(forbidden), capabilities=_CAPABILITIES
    )

    assert [(report.name, report.issues[0].kind) for report in reports] == [
        ("oxlint", "trust-required"),
        ("oxfmt", "trust-required"),
    ]


def test_missing_local_oxlint_fails_before_execution(tmp_path: Path) -> None:
    root = _typescript_project(tmp_path)
    (root / "node_modules/.bin/oxlint").unlink()

    def respond(request: ProcessRequest) -> ProcessOutput:
        assert _tool(request) == "oxfmt", "oxlint ran without a local installation"
        return ProcessOutput(0, "", "")

    reports = analyze_external(
        [str(root)],
        root=root,
        trust=TrustMode.TRUSTED,
        runner=_Executor(respond, ToolResolution.LOCAL),
        capabilities=_CAPABILITIES,
    )

    assert reports[0].completion is Completion.FAILED
    assert reports[0].issues[0].kind == "missing-dependency"
    assert "node_modules/.bin/oxlint is missing" in reports[0].issues[0].message


@pytest.mark.parametrize("pass_on_unpruned", [False, True])
def test_full_runs_report_stale_bulk_suppressions_unless_a_scoped_update_passes_on_them(
    tmp_path: Path, *, pass_on_unpruned: bool
) -> None:
    root = _typescript_project(tmp_path, oxfmt_config=None)
    (root / ".oxfmtrc.json").write_text("{}\n", encoding="utf-8")

    def respond(request: ProcessRequest) -> ProcessOutput:
        return _oxlint_output(request, _STALE) if _tool(request) == "oxlint" else ProcessOutput(0, "", "")

    reports = analyze_external(
        [str(root)],
        root=root,
        trust=TrustMode.TRUSTED,
        runner=_Executor(respond),
        capabilities=_CAPABILITIES,
        pass_on_unpruned_suppressions=pass_on_unpruned,
    )

    stale = [item.rule_id for item in reports[0].diagnostics]
    assert stale == ([] if pass_on_unpruned else [oxlint.UNUSED_SUPPRESSION])


def test_later_projects_fail_once_the_aggregate_deadline_passes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    for name in ("alpha", "beta"):
        _typescript_project(tmp_path / name)
    (tmp_path / "package.json").write_text('{"name":"workspace"}\n', encoding="utf-8")
    elapsed = 0.0
    monkeypatch.setattr(time, "monotonic", lambda: elapsed)  # sarj-noqa: SARJ445 -- controls the aggregate deadline.
    timeouts: list[float] = []

    def respond(request: ProcessRequest) -> ProcessOutput:
        nonlocal elapsed
        if _tool(request) == "oxfmt":
            return ProcessOutput(0, "", "")
        timeouts.append(request.timeout_seconds)
        elapsed = 301.0
        return _oxlint_output(request)

    reports = analyze_external(
        [str(tmp_path)], root=tmp_path, trust=TrustMode.TRUSTED, runner=_Executor(respond), capabilities=_CAPABILITIES
    )

    oxlint_reports = [report for report in reports if report.name == "oxlint"]
    assert timeouts == [300.0]
    assert [report.completion for report in oxlint_reports] == [Completion.COMPLETE, Completion.FAILED]
    assert oxlint_reports[1].issues[0].kind == "aggregate-timeout"


def test_oxfmt_covers_selected_directories_once_and_requires_a_config_per_project(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{"name":"workspace"}\n', encoding="utf-8")
    web = _typescript_project(tmp_path / "apps/web")
    _typescript_project(tmp_path / "apps/api", oxfmt_config=None)
    nested = web / "packages/ui"
    (nested / "src").mkdir(parents=True)
    (nested / ".oxfmtrc.json").write_text("{}\n", encoding="utf-8")
    (nested / "src/button.ts").write_text("export {};\n", encoding="utf-8")
    calls: list[tuple[Path, tuple[str, ...]]] = []

    def respond(request: ProcessRequest) -> ProcessOutput:
        if _tool(request) == "oxlint":
            return _oxlint_output(request)
        calls.append((request.cwd, tuple(request.argv[request.argv.index("--") + 1 :])))
        return ProcessOutput(0, "", "")

    reports = analyze_external(
        [str(tmp_path / "apps")],
        root=tmp_path,
        trust=TrustMode.TRUSTED,
        runner=_Executor(respond),
        capabilities=_CAPABILITIES,
    )

    # One run at the web project formats the nested project through oxfmt's own nested-config lookup.
    assert calls == [(web, (".",))]
    failures = [(report.invocation_id, report.issues[0].kind) for report in reports if report.issues]
    assert failures == [("oxfmt:apps/api", "configuration-failure")]


def test_disabled_capability_runs_no_typescript_tool_but_react_doctor_selection_follows_it(tmp_path: Path) -> None:
    root = _typescript_project(tmp_path)

    def forbidden(_request: ProcessRequest) -> ProcessOutput:
        pytest.fail("a disabled capability executed")

    assert (
        analyze_external(
            [str(root)], root=root, trust=TrustMode.TRUSTED, runner=_Executor(forbidden), capabilities=frozenset()
        )
        == ()
    )
    assert (
        analyze_external(
            [str(root)],
            root=root,
            trust=TrustMode.TRUSTED,
            runner=_Executor(forbidden),
            capabilities=_CAPABILITIES,
            typescript=False,
        )
        == ()
    )


def test_fix_commands_turn_excluded_rules_off_with_literal_route_globs(tmp_path: Path) -> None:
    root = _typescript_project(tmp_path)
    route = root / "src/app/[id]/page.tsx"
    route.parent.mkdir(parents=True)
    route.write_text("export default function Page() { return null; }\n", encoding="utf-8")
    (root / "src/app.ts").write_text("export {};\n", encoding="utf-8")
    override = ExclusionOverride(("src/app/**",), ("oxlint:typescript/no-explicit-any",), "generated routes")
    policy = Policy.from_manifest(
        root, Manifest("8.0.0", (lifecycle.TYPESCRIPT_CAPABILITY,), ".", ".", exclusion_overrides=(override,))
    )

    fix, directives = lifecycle.oxlint_fix_commands(root, [str(route), str(root / "src/app.ts")], policy)

    assert fix.argv[-4:] == ("--fix", "--", "src/app.ts", "src/app/[id]/page.tsx")
    assert "--report-unused-disable-directives-severity=off" in fix.argv
    assert dict(fix.environment) == {
        "OXLINT_TSGOLINT_PATH": str(root / "node_modules/.bin/tsrs-lint"),
        "SARJ_TYPE_AWARE": "1",
    }
    assert fix.prepare is not None
    with fix.prepare(fix) as prepared:
        text = Path(prepared.argv[prepared.argv.index("-c") + 1]).read_text(encoding="utf-8")
    request = json.loads(text[text.index("(") + 1 : text.rindex(")")])  # pyright: ignore[reportAny] -- overlay JSON.
    assert request["forced"] == {}
    assert request["disabled"] == [{"files": ["src/app/[[]id[]]/page.tsx"], "rules": ["typescript/no-explicit-any"]}]
    assert directives.label == "Oxlint unused directives"
    assert directives.argv[1:4] == ("-m", "sarj_standards.libs.linting.oxlint_directives", "--root")


def test_fix_sources_removes_unused_directives_oxlint_reports(tmp_path: Path) -> None:
    source = (
        "// eslint-disable-next-line no-debugger -- nothing to hide here\n"
        "export const value = 1;\n"
        "// eslint-disable-next-line no-console -- logging is the contract\n"
        "console.log(value);\n"
    )
    root = project(tmp_path / "repo", {"src/a.ts": source, "src/clean.ts": "export {};\n"})

    assert oxlint_directives.fix_sources(root, ["src/a.ts", "src/clean.ts", "README.md"]) == 0

    assert (root / "src/a.ts").read_text(encoding="utf-8") == source.split("\n", 1)[1]
    assert (root / "src/clean.ts").read_text(encoding="utf-8") == "export {};\n"


def test_fix_pipeline_fixes_cleans_directives_and_formats(tmp_path: Path) -> None:
    source = (
        "// eslint-disable-next-line no-debugger -- nothing to hide here\n"
        "export function f() { return globalThis.Array }\n"
    )
    root = project(tmp_path / "repo", {"src/a.ts": source})
    (root / ".oxfmtrc.json").write_text('{"semi": true}\n', encoding="utf-8")
    commands = lifecycle.selected_format_commands(root, [str(root / "src/a.ts")], trusted=True)
    assert [command.label for command in commands if not command.label.startswith(("Ruff", "Shell"))] == [
        "Oxlint (selected: .)",
        "Oxlint unused directives",
        "oxfmt",
    ]

    result = autofix.run(root, ["src/a.ts"], trusted=True)

    assert result.status == 0
    assert result.changed == (root / "src/a.ts",)
    assert (root / "src/a.ts").read_text(encoding="utf-8") == "export function f() {\n  return Array;\n}\n"


def test_oxfmt_project_analysis_reports_unformatted_files_with_the_real_binary(tmp_path: Path) -> None:
    root = project(tmp_path / "repo", {"src/a.ts": "export const a = 1\n", "src/b.ts": "export const b = 1;\n"})
    (root / ".oxfmtrc.json").write_text('{"semi": true}\n', encoding="utf-8")

    reports = analyze_external([str(root / "src")], root=root, trust=TrustMode.TRUSTED, capabilities=_CAPABILITIES)

    formatted = next(report for report in reports if report.name == "oxfmt")
    assert formatted.completion is Completion.COMPLETE
    assert [(item.location.path, item.severity) for item in formatted.diagnostics] == [("src/a.ts", Severity.ERROR)]
    assert all(report.completion is Completion.COMPLETE for report in reports), [report.issues for report in reports]


@pytest.mark.parametrize("formatted", [True, False], ids=("formatted", "formatter-debt"))
def test_directive_plan_formats_postimages_with_the_projects_oxfmt(tmp_path: Path, *, formatted: bool) -> None:
    body = "export const value = 1;\n" if formatted else "export const value = 1\n"
    source = f"// eslint-disable-next-line no-debugger -- nothing to hide here\n{body}"
    root = project(tmp_path / "repo", {"src/a.ts": source})
    # The bridge proves a regular, pinned, repository-local oxfmt install.
    (root / "node_modules/oxfmt").unlink()
    shutil.copytree(MODULES / "oxfmt", root / "node_modules/oxfmt", symlinks=True)
    (root / "package.json").write_text(
        '{"type":"module","private":true,"devDependencies":{"oxfmt":"0.76.0"}}\n', encoding="utf-8"
    )
    (root / "package-lock.json").write_text('{"lockfileVersion":3}\n', encoding="utf-8")
    (root / ".oxfmtrc.json").write_text('{"semi": true}\n', encoding="utf-8")
    (root / ".gitignore").write_text("node_modules\n", encoding="utf-8")
    for argv in (("init", "-q"), ("add", "--all")):
        subprocess.run(("git", "-C", str(root), *argv), check=True, capture_output=True)

    def run(command: lifecycle.Command) -> subprocess.CompletedProcess[str]:
        # The byte bridge keeps its private payload under the parent's temporary directory.
        return subprocess.run(
            command.argv,
            cwd=command.cwd,
            env={**environment(), "TMPDIR": tempfile.gettempdir()},
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )

    expected = oxlint_directives.plan(root, ("src/a.ts",), run=run)

    # Formatter debt stays for the rollout's own oxfmt commit; the cleanup removes only the directive.
    assert expected["src/a.ts"].after.decode("utf-8") == body


@pytest.mark.parametrize("count", [120, 129])
def test_large_project_selection_remains_bounded_and_complete(tmp_path: Path, count: int) -> None:
    for index in range(count):
        _typescript_project(tmp_path / f"project-{index:03}", oxfmt_config=None)
    (tmp_path / "unowned.ts").write_text("export {};\n")
    executor = _Executor(_oxlint_output)
    reports = analyze_external(
        [str(tmp_path)],
        root=tmp_path,
        trust=TrustMode.TRUSTED,
        runner=executor,
        capabilities=_CAPABILITIES,
        rule_ids=frozenset({"no-tautological-expect"}),
    )
    assert reports[0].issues[0].kind == "coverage-missing"
    if count == 120:
        assert len(executor.requests) == len(reports) - 1 == 120
        assert all(report.completion is Completion.COMPLETE and report.file_count == 1 for report in reports[1:])
        assert {request.cwd for request in executor.requests} == {
            tmp_path / f"project-{index:03}" for index in range(count)
        }
    else:
        assert not executor.requests
        assert reports[1].issues[0].kind == "project-limit"


@pytest.mark.parametrize("metadata", ["baseline", "nested-ledger"])
def test_historical_autofix_preserves_sources_and_reports_new_findings(tmp_path: Path, metadata: str) -> None:
    historical = "// eslint-disable-next-line no-debugger -- retain authored explanation\nexport const value = globalThis.Array;\n"
    root = project(
        tmp_path / "repo",
        {"src/history.ts": historical.replace(" = ", "="), "src/clean.ts": "export const clean = globalThis.Array;\n"},
    )
    (root / ".oxfmtrc.json").write_text("{}\n")
    owner = root
    if metadata == "baseline":
        path = root / "baseline.json"
        path.write_text(
            baseline.render(
                (
                    Diagnostic(
                        "HISTORY",
                        "existing",
                        Severity.ERROR,
                        "oxlint",
                        Location("src/history.ts"),
                        rule_id="unicorn-js/no-unnecessary-global-this",
                        fingerprint="a" * 64,
                    ),
                )
            )
        )
        adopted = Manifest("8.0.0", (lifecycle.TYPESCRIPT_CAPABILITY,), ".", ".", diagnostic_baseline=path.name)
        (root / MANIFEST_NAME).write_text(adopted.render())
    else:
        owner = root / "src"
        (owner / "oxlint.config.ts").write_text('import config from "../oxlint.config.ts";\nexport default config;\n')
        (owner / "oxlint-suppressions.json").write_text(
            json.dumps({"history.ts": {"unicorn-js/no-unnecessary-global-this": {"count": 1}}}, indent=2)
        )
    ledger = owner / "oxlint-suppressions.json"
    ledger_before = ledger.read_bytes() if ledger.exists() else None

    result = autofix.run(root, ["src/history.ts", "src/clean.ts"], trusted=True)

    assert result.status == 0
    assert (root / "src/history.ts").read_text() == historical
    assert (root / "src/clean.ts").read_text() == "export const clean = Array;\n"
    assert (ledger.read_bytes() if ledger.exists() else None) == ledger_before
    (root / "src/history.ts").write_text(f"{historical}debugger;\n")
    reports = analyze_external(
        [str(root / "src/history.ts")], root=root, trust=TrustMode.TRUSTED, capabilities=_CAPABILITIES
    )
    assert all(report.completion is Completion.COMPLETE and not report.issues for report in reports)
    assert any(diagnostic.rule_id == "no-debugger" for report in reports for diagnostic in report.diagnostics)


@pytest.mark.parametrize("metadata", ["baseline", "ledger"])
def test_invalid_historical_metadata_fails_before_any_source_write(tmp_path: Path, metadata: str) -> None:
    original = "export const value = globalThis.Array;\n"
    root = project(tmp_path / "repo", {"src/history.ts": original})
    if metadata == "baseline":
        (root / "baseline.json").write_text('{"schemaVersion":1,"diagnostics":[{"path":"../escape.ts"}]}')
        adopted = Manifest("8.0.0", (lifecycle.TYPESCRIPT_CAPABILITY,), ".", ".", diagnostic_baseline="baseline.json")
        (root / MANIFEST_NAME).write_text(adopted.render())
    else:
        (root / "oxlint-suppressions.json").write_text('{"src/history.ts":{"no-debugger":{"count":0}}}')

    with pytest.raises(ValueError, match=r"invalid fingerprint|greater than or equal to 1"):
        autofix.run(root, ["src/history.ts"], trusted=True)

    assert (root / "src/history.ts").read_text() == original
