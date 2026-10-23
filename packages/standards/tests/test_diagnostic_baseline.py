from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
from typing import TYPE_CHECKING, Unpack

import pytest

from sarj_standards import api
from sarj_standards.cli.main import main as cli_main
from sarj_standards.libs.adoption.manifest import (
    ALL_CAPABILITIES,
    MANIFEST_NAME,
    Manifest,
    as_table,
    load as load_manifest,
)
from sarj_standards.libs.diagnostics import (
    AnalysisReport,
    Completion,
    Diagnostic,
    Location,
    Position,
    Region,
    Severity,
    ToolReport,
    baseline,
)
from sarj_standards.libs.diagnostics.serialize import to_github, to_sarif, to_text
from sarj_standards.libs.json_boundary import parse_unique_json
from sarj_standards.libs.linting import external
from sarj_standards.libs.linting.analysis import report_from_tools
from sarj_standards.libs.linting.policy import Policy


if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from tests.call_contracts import ExternalAnalyzeOptions, StandardsAnalyzeOptions


def _manifest(
    path: str | None = None,
    *,
    verify_paths: tuple[str, ...] = (".",),
) -> Manifest:
    return Manifest(
        version=api.__version__,
        configs=(),
        python_dest=".",
        typescript_dest=".",
        hook_manager="none",
        verify_paths=verify_paths,
        diagnostic_baseline=path,
    )


def _policy_baseline(diagnostics: tuple[Diagnostic, ...]) -> str:
    return baseline.render(
        diagnostics,
        bundle_version=api.__version__,
        consumer_base_sha="0" * 40,
        catalog_digest=baseline.bundled_catalog_digest(),
    )


@pytest.mark.parametrize("operation", ["merge", "remove"])
def test_baseline_updates_use_the_validated_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    path = tmp_path / "baseline.json"
    finding = Diagnostic("X", "existing", Severity.ERROR, "ruff", Location("app.py"), fingerprint="a" * 64)
    original = baseline.render((finding,))
    path.write_text(original, encoding="utf-8")
    invalid = original.replace('"count": 1', '"count": 0')

    def replace_after_parsing(text: str) -> object:
        document = parse_unique_json(text)
        path.write_text(invalid, encoding="utf-8")
        return document

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- replace the file between parsing and later reads to exercise the public update's snapshot contract.
        "sarj_standards.libs.diagnostics.baseline.parse_unique_json", replace_after_parsing
    )
    if operation == "merge":
        updated = baseline.merge_scoped(
            path,
            (),
            selectors=("eslint:other",),
            bundle_version=api.__version__,
            consumer_base_sha="b" * 40,
            catalog_digest="c" * 64,
        )
    else:
        removal = baseline.remove_rules(
            path,
            selectors=("eslint:other",),
            bundle_version=api.__version__,
            consumer_base_sha="b" * 40,
            catalog_digest="c" * 64,
        )
        assert removal.removed == 0
        updated = removal.contents
    path.write_text(updated, encoding="utf-8")

    assert baseline.load(path) == {"a" * 64: 1}


def test_baseline_read_remains_bounded_when_the_file_grows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "baseline.json"
    path.write_text('{"schemaVersion":1,"diagnostics":[]}', encoding="utf-8")
    limit = 128
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- intercept the internal limit to exercise the production read boundary with a small fixture.
        baseline, "_MAX_BYTES", limit
    )
    oversized = json.dumps({"schemaVersion": 1, "diagnostics": [], "padding": "x" * limit})
    original_stat = Path.stat
    checks = 0

    def grow_after_stat(candidate: Path, *, follow_symlinks: bool = True) -> os.stat_result:
        nonlocal checks
        metadata = original_stat(candidate, follow_symlinks=follow_symlinks)
        if candidate == path and follow_symlinks:
            checks += 1
            if checks == 1:
                path.write_text(oversized, encoding="utf-8")
        return metadata

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- grow the real file after its metadata check; injection would bypass the filesystem race under test.
        Path, "stat", grow_after_stat
    )
    with pytest.raises(ValueError, match="exceeds"):
        baseline.load(path)


def test_makefile_guard_cannot_be_captured_or_hidden_by_a_diagnostic_baseline(tmp_path: Path) -> None:
    guarded = Diagnostic(
        "repository/artifacts/makefile-growth",
        "Makefile grew",
        Severity.WARNING,
        "repo-standards",
        Location("Makefile"),
        rule_id="repository/artifacts/makefile-growth",
        fingerprint="a" * 64,
    )
    unrelated = replace(guarded, source="another-engine", fingerprint="b" * 64)
    rendered: dict[str, object] = json.loads(  # pyright: ignore[reportAny] -- stdlib JSON boundary.
        _policy_baseline((guarded, unrelated))
    )
    raw = report_from_tools(tmp_path, (ToolReport("repo-standards", Completion.COMPLETE, diagnostics=(guarded,)),))

    visible = api._without_baselined_diagnostics(  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage] -- exercise the internal _without_baselined_diagnostics contract directly with controlled fixture data.
        raw, {"a" * 64: 100}
    )

    assert not baseline.is_baselineable(guarded)
    assert baseline.is_baselineable(unrelated)
    assert rendered["diagnostics"] == [
        {
            "count": 1,
            "fingerprint": "b" * 64,
            "path": "Makefile",
            "ruleId": "repository/artifacts/makefile-growth",
            "source": "another-engine",
        }
    ]
    assert visible.diagnostics == (guarded,)
    assert visible.tools[0].baselined_count == 0


def test_policy_analysis_hides_only_exact_baselined_diagnostics(tmp_path: Path) -> None:
    selected = tmp_path / "selected.py"
    selected.write_text("logger.info('request', token=token)\n", encoding="utf-8")
    other = tmp_path / "other.py"
    other.write_text("logger.info('request', token=token)\n", encoding="utf-8")
    raw = api.Standards(tmp_path).analyze([str(selected)], mode=api.AnalysisMode.RAW)
    baseline_path = tmp_path / "diagnostic-baseline.json"
    baseline_path.write_text(_policy_baseline(raw.diagnostics), encoding="utf-8")
    (tmp_path / MANIFEST_NAME).write_text(_manifest(baseline_path.name).render(), encoding="utf-8")

    policy = api.Standards(tmp_path).analyze([str(selected), str(other)])
    raw_again = api.Standards(tmp_path).analyze([str(selected)], mode=api.AnalysisMode.RAW)

    assert [item.location.path for item in policy.diagnostics if item.code == "SARJ012"] == ["other.py"]
    assert [item.code for item in raw_again.diagnostics] == ["SARJ012"]
    assert sum(tool.baselined_count for tool in policy.tools) == 1
    assert sum(tool.baselined_count for tool in raw_again.tools) == 0
    assert any(tool.get("baselinedDiagnosticCount") == 1 for tool in policy.as_dict()["tools"])
    assert "1 existing finding(s) accepted by central diagnostic baseline" in to_text(policy)
    assert "1 existing finding(s) accepted by central diagnostic baseline" in to_github(policy)
    assert "baseline-notice" in to_sarif(policy)


def test_mocked_terraform_test_can_be_ratcheted_without_hiding_new_files(tmp_path: Path) -> None:
    test_source = """override_module {
  target = module.fixture
  outputs = { arn = "fixture-arn" }
}
run "routing" {
  assert {
    condition = module.fixture.arn == "fixture-arn"
    error_message = "ARN mismatch"
  }
}
"""
    source = tmp_path / "routing.tftest.hcl"
    source.write_text(test_source, encoding="utf-8")
    raw = api.Standards(tmp_path).analyze([str(source)], mode=api.AnalysisMode.RAW)
    baseline_path = tmp_path / "diagnostic-baseline.json"
    baseline_path.write_text(_policy_baseline(raw.diagnostics), encoding="utf-8")
    (tmp_path / MANIFEST_NAME).write_text(_manifest(baseline_path.name).render(), encoding="utf-8")

    new_source = tmp_path / "new-routing.tftest.hcl"
    new_source.write_text(test_source, encoding="utf-8")
    policy = api.Standards(tmp_path).analyze([str(source), str(new_source)])

    assert [item.location.path for item in policy.diagnostics] == ["new-routing.tftest.hcl"]


def test_missing_diagnostic_baseline_is_an_execution_failure(tmp_path: Path) -> None:
    (tmp_path / MANIFEST_NAME).write_text(_manifest("missing.json").render(), encoding="utf-8")

    report = api.Standards(tmp_path).analyze()

    assert report.exit_code == 2
    assert report.issues[0].kind == "baseline-failure"


def test_diagnostic_baseline_exposes_fingerprint_count_growth(tmp_path: Path) -> None:
    source = tmp_path / "service.py"
    source.write_text("logger.info('request', token=token)\n", encoding="utf-8")
    raw = api.Standards(tmp_path).analyze([str(source)], mode=api.AnalysisMode.RAW)
    baseline_path = tmp_path / "diagnostic-baseline.json"
    baseline_path.write_text(_policy_baseline(raw.diagnostics), encoding="utf-8")
    (tmp_path / MANIFEST_NAME).write_text(_manifest(baseline_path.name).render(), encoding="utf-8")
    source.write_text(
        "logger.info('request', token=token)\nlogger.info('request', password=password)\n",
        encoding="utf-8",
    )

    policy = api.Standards(tmp_path).analyze([str(source)])

    assert [item.code for item in policy.diagnostics] == ["SARJ012"]


def _repeated_client_tests(count: int) -> str:
    return "from httpx import ASGITransport, AsyncClient\n\n" + "\n".join(
        f"async def test_response_{index}(app):\n"
        "    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:\n"
        f"        response = await client.get('/items/{index}')\n"
        "    assert response.status_code == 200\n"
        for index in range(count)
    )


def test_repeated_composition_baseline_does_not_absorb_another_test(tmp_path: Path) -> None:
    source = tmp_path / "test_endpoints.py"
    source.write_text(_repeated_client_tests(3), encoding="utf-8")
    standards = api.Standards(tmp_path)
    selectors = ["python:repeated-test-composition"]
    raw = standards.analyze([str(source)], rules=selectors, mode=api.AnalysisMode.RAW)
    assert raw.exit_code == 1
    assert len(raw.diagnostics) == 3
    baseline_path = tmp_path / "diagnostic-baseline.json"
    baseline_path.write_text(_policy_baseline(raw.diagnostics), encoding="utf-8")
    (tmp_path / MANIFEST_NAME).write_text(_manifest(baseline_path.name).render(), encoding="utf-8")

    unchanged = standards.analyze([str(source)], rules=selectors)
    assert unchanged.exit_code == 0
    assert unchanged.diagnostics == ()

    source.write_text(_repeated_client_tests(4), encoding="utf-8")
    changed = standards.analyze([str(source)], rules=selectors)
    assert changed.exit_code == 1
    assert [item.code for item in changed.diagnostics] == ["SARJ457"]


def test_manifest_round_trips_diagnostic_baseline(tmp_path: Path) -> None:
    (tmp_path / MANIFEST_NAME).write_text(_manifest("quality/diagnostics.json").render(), encoding="utf-8")

    adopted = load_manifest(tmp_path)

    assert adopted is not None
    assert adopted.diagnostic_baseline == "quality/diagnostics.json"


@pytest.mark.parametrize("path", ["../outside.json", "baseline.toml"])
def test_manifest_rejects_unsafe_diagnostic_baseline_paths(tmp_path: Path, path: str) -> None:
    rendered = _manifest().render() + f"\n[baseline]\ndiagnostics = {json.dumps(path)}\n"
    (tmp_path / MANIFEST_NAME).write_text(rendered, encoding="utf-8")

    with pytest.raises(ValueError, match=r"repository-relative JSON path|escapes"):
        load_manifest(tmp_path)


def test_diagnostic_baseline_rejects_duplicate_fingerprints(tmp_path: Path) -> None:
    fingerprint = "a" * 64
    entry = {"fingerprint": fingerprint, "source": "ruff", "ruleId": "E501", "path": "app.py", "count": 1}
    path = tmp_path / "baseline.json"
    path.write_text(json.dumps({"schemaVersion": 1, "diagnostics": [entry, entry]}), encoding="utf-8")

    with pytest.raises(ValueError, match="repeats fingerprint"):
        baseline.load(path)


@pytest.mark.parametrize(
    "version", [True, 1.0, 2.0, [], {}], ids=("boolean", "legacy-float", "current-float", "array", "object")
)
def test_diagnostic_baseline_schema_version_requires_an_integer(tmp_path: Path, version: object) -> None:
    path = tmp_path / "baseline.json"
    path.write_text(json.dumps({"schemaVersion": version, "diagnostics": []}), encoding="utf-8")

    with pytest.raises(ValueError, match="schemaVersion"):
        baseline.load(path)


@pytest.mark.parametrize(
    "contents",
    [
        '{"schemaVersion": 1, "schemaVersion": 1, "diagnostics": []}',
        '{"schemaVersion": 1, "diagnostics": [{"count": 2, "count": 1}]}',
        '{"schemaVersion": 1, "diagnostics": [], "extra": NaN}',
        '{"schemaVersion": 1, "diagnostics": [], "extra": Infinity}',
    ],
    ids=("schema-key", "nested-count-key", "nan", "infinity"),
)
def test_diagnostic_baseline_rejects_ambiguous_json(tmp_path: Path, contents: str) -> None:
    path = tmp_path / "baseline.json"
    path.write_text(contents, encoding="utf-8")

    with pytest.raises(ValueError, match="cannot read diagnostic baseline"):
        baseline.load(path)


def test_v2_baseline_records_and_validates_provenance(tmp_path: Path) -> None:
    rendered = baseline.render(
        (),
        bundle_version="9.0.0",
        consumer_base_sha="a" * 40,
        catalog_digest="b" * 64,
    )
    path = tmp_path / "baseline.json"
    path.write_text(rendered, encoding="utf-8")

    assert baseline.load(path) == {}
    assert json.loads(rendered)["provenance"] == {
        "bundleVersion": "9.0.0",
        "consumerBaseSha": "a" * 40,
        "catalogDigest": "b" * 64,
    }


def test_policy_mode_rejects_legacy_or_stale_baseline_provenance(tmp_path: Path) -> None:
    legacy = tmp_path / "legacy.json"
    legacy.write_text(baseline.render(()), encoding="utf-8")
    with pytest.raises(ValueError, match="schemaVersion 2"):
        baseline.load(legacy, require_v2=True)

    stale = tmp_path / "stale.json"
    stale.write_text(
        baseline.render((), bundle_version="0.0.0", consumer_base_sha="0" * 40, catalog_digest="f" * 64),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="bundle version"):
        baseline.load(stale, require_v2=True, expected_bundle_version=api.__version__)


def test_scoped_merge_preserves_unrelated_debt(tmp_path: Path) -> None:
    old = Diagnostic("OLD", "old", Severity.ERROR, "ruff", Location("old.py"), rule_id="OLD", fingerprint="a" * 64)
    promoted = Diagnostic("NEW", "new", Severity.ERROR, "ruff", Location("new.py"), rule_id="NEW", fingerprint="b" * 64)
    path = tmp_path / "baseline.json"
    path.write_text(baseline.render((old, promoted)), encoding="utf-8")
    replacement = Diagnostic(
        "NEW", "replacement", Severity.ERROR, "ruff", Location("next.py"), rule_id="NEW", fingerprint="c" * 64
    )

    merged = baseline.merge_scoped(
        path,
        (replacement,),
        selectors=("ruff:NEW",),
        bundle_version="9.0.0",
        consumer_base_sha="d" * 40,
        catalog_digest="e" * 64,
    )

    assert merged.count('"fingerprint":') == 2
    assert f'"fingerprint": "{"a" * 64}"' in merged
    assert f'"fingerprint": "{"c" * 64}"' in merged


def test_scoped_merge_preserves_existing_tab_indentation(tmp_path: Path) -> None:
    old = Diagnostic("OLD", "old", Severity.ERROR, "ruff", Location("old.py"), rule_id="OLD", fingerprint="a" * 64)
    replacement = Diagnostic(
        "OLD", "replacement", Severity.ERROR, "ruff", Location("next.py"), rule_id="OLD", fingerprint="b" * 64
    )
    path = tmp_path / "baseline.json"
    path.write_text(baseline.render((old,)).replace("  ", "\t"), encoding="utf-8")

    merged = baseline.merge_scoped(
        path,
        (replacement,),
        selectors=("ruff:OLD",),
        bundle_version="9.0.0",
        consumer_base_sha="d" * 40,
        catalog_digest="e" * 64,
    )

    assert '\n\t"schemaVersion"' in merged
    assert '\n  "schemaVersion"' not in merged
    assert json.loads(merged)["diagnostics"][0]["fingerprint"] == "b" * 64


@pytest.fixture
def git_root(tmp_path: Path) -> Path:
    subprocess.run(("git", "init", "-q"), cwd=tmp_path, check=True)
    subprocess.run(("git", "config", "user.name", "Standards Test"), cwd=tmp_path, check=True)
    subprocess.run(("git", "config", "user.email", "standards@example.com"), cwd=tmp_path, check=True)
    return tmp_path


def test_staged_changed_lines_cannot_consume_baseline_allowance(git_root: Path) -> None:
    source = git_root / "app.py"
    source.write_text("old\n", encoding="utf-8")
    subprocess.run(("git", "add", "app.py"), cwd=git_root, check=True)
    subprocess.run(("git", "commit", "-qm", "base"), cwd=git_root, check=True)
    source.write_text("old\nnew\n", encoding="utf-8")
    subprocess.run(("git", "add", "app.py"), cwd=git_root, check=True)

    scope = baseline.changed_line_scope(git_root, staged=True)
    old = Diagnostic("X", "old", Severity.ERROR, "ruff", Location("app.py", position=Position(0, 0, 0)))
    new = Diagnostic("X", "new", Severity.ERROR, "ruff", Location("app.py", position=Position(1, 0, 4)))

    assert not baseline.touches_changed_lines(old, scope)
    assert baseline.touches_changed_lines(new, scope)


@pytest.mark.parametrize("mode", list(api.AnalysisMode))
def test_analysis_without_a_baseline_skips_changed_line_queries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: api.AnalysisMode
) -> None:
    source = tmp_path / "app.py"
    source.write_text("logger.info('request', token=token)\n", encoding="utf-8")

    def unexpected_scope(_root: Path, *, staged: bool, paths: Iterable[str] | None = None) -> None:
        pytest.fail(f"analysis without baseline consumers must not query Git diffs: staged={staged}, paths={paths}")

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- prove public analysis skips the Git-diff boundary when no consumer needs it.
        baseline, "changed_line_scope", unexpected_scope
    )

    report = api.Standards(tmp_path).analyze(["app.py"], staged=True, mode=mode, rules=["python:no-secret-in-log"])

    assert [item.code for item in report.diagnostics] == ["SARJ012"]
    assert report.issues == ()


def test_policy_analysis_keeps_a_changed_baselined_finding_active(git_root: Path) -> None:
    source = git_root / "app.py"
    source.write_text("logger.info('request', token=token)\n", encoding="utf-8")
    standards = api.Standards(git_root)
    selectors = ["python:no-secret-in-log"]
    raw = standards.analyze(["app.py"], mode=api.AnalysisMode.RAW, rules=selectors)
    baseline_path = git_root / "diagnostic-baseline.json"
    baseline_path.write_text(_policy_baseline(raw.diagnostics), encoding="utf-8")
    (git_root / MANIFEST_NAME).write_text(_manifest(baseline_path.name).render(), encoding="utf-8")
    subprocess.run(("git", "add", "."), cwd=git_root, check=True)
    subprocess.run(("git", "commit", "-qm", "base"), cwd=git_root, check=True)
    unchanged = standards.analyze(["app.py"], staged=True, rules=selectors)
    source.write_text("logger.info('changed', token=token)\n", encoding="utf-8")
    subprocess.run(("git", "add", "app.py"), cwd=git_root, check=True)

    changed = standards.analyze(["app.py"], staged=True, rules=selectors)

    assert unchanged.diagnostics == ()
    assert [item.code for item in changed.diagnostics] == ["SARJ012"]
    assert changed.diagnostics[0].fingerprint == raw.diagnostics[0].fingerprint


def test_full_external_scan_requires_only_changed_shell_formatting(
    git_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("changed.sh", "legacy.sh"):
        (git_root / name).write_text("#!/bin/bash\nif true; then\necho ok\nfi\n", encoding="utf-8")
    adopted = replace(_manifest(), disabled_capabilities=tuple(name for name in ALL_CAPABILITIES if name != "shfmt"))
    (git_root / MANIFEST_NAME).write_text(adopted.render(), encoding="utf-8")
    subprocess.run(("git", "add", "."), cwd=git_root, check=True)
    subprocess.run(("git", "commit", "-qm", "base"), cwd=git_root, check=True)
    base = subprocess.check_output(("git", "rev-parse", "HEAD"), cwd=git_root, text=True).strip()
    with (git_root / "changed.sh").open("a", encoding="utf-8") as source:
        source.write("# changed\n")
    subprocess.run(("git", "add", "."), cwd=git_root, check=True)
    subprocess.run(("git", "commit", "-qm", "head"), cwd=git_root, check=True)
    monkeypatch.setenv("SARJ_STANDARDS_BASE", base)

    standards = api.Standards(git_root)
    full = standards.analyze(external=True)
    staged = standards.analyze(["legacy.sh"], external=True, staged=True)

    assert {item.location.path: item.severity for item in full.diagnostics if item.source == "shfmt"} == {
        "changed.sh": Severity.ERROR,
        "legacy.sh": Severity.WARNING,
    }
    assert [item.severity for item in staged.diagnostics if item.source == "shfmt"] == [Severity.ERROR]


@pytest.mark.parametrize("staged", [True, False], ids=("staged", "committed"))
@pytest.mark.parametrize("oversized", [False, True], ids=("scoped", "argv-fallback"))
def test_changed_line_query_handles_literal_paths_and_oversized_scope(
    git_root: Path, monkeypatch: pytest.MonkeyPatch, *, staged: bool, oversized: bool
) -> None:
    filename = "app[1].py"
    for name in (filename, "app1.py", "unrelated.txt"):
        (git_root / name).write_text("old\nkeep\n", encoding="utf-8")
    subprocess.run(("git", "add", "."), cwd=git_root, check=True)
    subprocess.run(("git", "commit", "-qm", "base"), cwd=git_root, check=True)
    base = subprocess.check_output(("git", "rev-parse", "HEAD"), cwd=git_root, text=True).strip()
    for name in (filename, "app1.py", "unrelated.txt"):
        (git_root / name).write_text("old\nchanged\n", encoding="utf-8")
    subprocess.run(("git", "add", "."), cwd=git_root, check=True)
    if not staged:
        subprocess.run(("git", "commit", "-qm", "head"), cwd=git_root, check=True)
        monkeypatch.setenv("SARJ_STANDARDS_BASE", base)

    paths = (filename, *(f"missing/{index:04d}/" + "x" * 100 for index in range(700))) if oversized else (filename,)
    scope = baseline.changed_line_scope(git_root, staged=staged, paths=paths)

    assert scope is not None
    expected = frozenset({filename, "app1.py", "unrelated.txt"}) if oversized else frozenset({filename})
    assert scope.paths == expected
    assert scope.lines == dict.fromkeys(expected, frozenset({2}))


@pytest.mark.parametrize("staged", [True, False], ids=("staged", "committed"))
def test_scoped_changed_lines_preserve_distant_baselines_after_a_rename(
    git_root: Path, monkeypatch: pytest.MonkeyPatch, *, staged: bool
) -> None:
    lines = [f"value{index} = {index}\n" for index in range(100)]
    (git_root / "old.py").write_text("".join(lines), encoding="utf-8")
    subprocess.run(("git", "add", "."), cwd=git_root, check=True)
    subprocess.run(("git", "commit", "-qm", "base"), cwd=git_root, check=True)
    base = subprocess.check_output(("git", "rev-parse", "HEAD"), cwd=git_root, text=True).strip()
    subprocess.run(("git", "mv", "old.py", "new.py"), cwd=git_root, check=True)
    lines[90] = "value90 = 100\n"
    (git_root / "new.py").write_text("".join(lines), encoding="utf-8")
    subprocess.run(("git", "add", "."), cwd=git_root, check=True)
    if not staged:
        subprocess.run(("git", "commit", "-qm", "head"), cwd=git_root, check=True)
        monkeypatch.setenv("SARJ_STANDARDS_BASE", base)

    scope = baseline.changed_line_scope(git_root, staged=staged, paths=("new.py",))
    distant = Diagnostic("X", "old", Severity.ERROR, "ruff", Location("new.py", position=Position(1, 0, 10)))
    edited = replace(distant, location=Location("new.py", position=Position(90, 0, 1000)))

    assert scope is not None
    assert scope.lines == {"new.py": frozenset({91})}
    assert not baseline.touches_changed_lines(distant, scope)
    assert baseline.touches_changed_lines(edited, scope)


def test_changed_line_timeout_keeps_findings_active(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def expire(arguments: Sequence[str], *, cwd: Path, check: bool, capture_output: bool, timeout: float) -> None:
        assert cwd == tmp_path
        assert not check
        assert capture_output
        raise subprocess.TimeoutExpired(arguments, timeout)

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- force a process timeout that fixture data cannot produce reliably.
        subprocess, "run", expire
    )

    scope = baseline.changed_line_scope(tmp_path, staged=True, paths=("app.py",))
    finding = Diagnostic("X", "new", Severity.ERROR, "ruff", Location("app.py"))

    assert scope is not None
    assert scope.failed
    assert baseline.touches_changed_lines(finding, scope)


@pytest.mark.parametrize("staged", [True, False], ids=("staged", "committed"))
@pytest.mark.parametrize(
    "filename",
    [
        "plain.py",
        "space name.py",
        "caf\u00e9.py",
        "emoji-\U0001f30d.py",
        pytest.param("trailing.py ", marks=pytest.mark.skipif(os.name == "nt", reason="Windows filename grammar")),
        pytest.param('quoted"name.py', marks=pytest.mark.skipif(os.name == "nt", reason="Windows filename grammar")),
        pytest.param("tab\tname.py", marks=pytest.mark.skipif(os.name == "nt", reason="Windows filename grammar")),
        pytest.param("line\nname.py", marks=pytest.mark.skipif(os.name == "nt", reason="Windows filename grammar")),
    ],
)
def test_changed_line_paths_preserve_baselines_with_custom_git_configuration(
    git_root: Path, monkeypatch: pytest.MonkeyPatch, filename: str, *, staged: bool
) -> None:
    source = git_root / filename
    source.write_text("old\nkeep\n", encoding="utf-8")
    subprocess.run(("git", "add", "."), cwd=git_root, check=True)
    subprocess.run(("git", "commit", "-qm", "base"), cwd=git_root, check=True)
    base = subprocess.check_output(("git", "rev-parse", "HEAD"), cwd=git_root, text=True).strip()
    subprocess.run(("git", "config", "core.quotePath", "false"), cwd=git_root, check=True)
    subprocess.run(("git", "config", "diff.noprefix", "true"), cwd=git_root, check=True)
    source.write_text("old\nchanged\n", encoding="utf-8")
    subprocess.run(("git", "add", "."), cwd=git_root, check=True)
    if not staged:
        subprocess.run(("git", "commit", "-qm", "head"), cwd=git_root, check=True)
        monkeypatch.setenv("SARJ_STANDARDS_BASE", base)

    scope = baseline.changed_line_scope(git_root, staged=staged)
    old = Diagnostic("X", "old", Severity.ERROR, "ruff", Location(filename, position=Position(0, 0, 0)))
    changed = replace(old, location=Location(filename, position=Position(1, 0, 4)))

    assert scope is not None
    assert scope.lines == {filename: frozenset({2})}
    assert not baseline.touches_changed_lines(old, scope)
    assert baseline.touches_changed_lines(changed, scope)


def test_non_utf8_git_paths_preserve_byte_identity(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    filename = "raw-\udcff.py"

    def git_diff(
        arguments: Sequence[str], *, cwd: Path, check: bool, capture_output: bool, timeout: float
    ) -> subprocess.CompletedProcess[bytes]:
        assert cwd == tmp_path
        assert not check
        assert capture_output
        assert timeout == 30
        output = (
            b"M\0raw-\xff.py\0"
            if "--name-status" in arguments
            else b'diff --git "a/raw-\\377.py" "b/raw-\\377.py"\n'
            b'--- "a/raw-\\377.py"\n+++ "b/raw-\\377.py"\n@@ -2 +2 @@\n-old\n+changed\n'
        )
        return subprocess.CompletedProcess(arguments, 0, stdout=output, stderr=b"")

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- supply Git byte-protocol output unsupported by this filesystem.
        subprocess, "run", git_diff
    )

    scope = baseline.changed_line_scope(tmp_path, staged=True)

    assert scope is not None
    assert scope.paths == frozenset({filename})
    assert scope.lines == {filename: frozenset({2})}


@pytest.mark.parametrize("staged", [True, False], ids=("staged", "committed"))
def test_changed_lines_are_relative_to_the_analysis_root(
    git_root: Path, monkeypatch: pytest.MonkeyPatch, *, staged: bool
) -> None:
    project = git_root / "project"
    project.mkdir()
    source = project / "app.py"
    source.write_text("old\nkeep\n", encoding="utf-8")
    subprocess.run(("git", "add", "."), cwd=git_root, check=True)
    subprocess.run(("git", "commit", "-qm", "base"), cwd=git_root, check=True)
    base = subprocess.check_output(("git", "rev-parse", "HEAD"), cwd=git_root, text=True).strip()
    source.write_text("old\nchanged\n", encoding="utf-8")
    subprocess.run(("git", "add", "."), cwd=git_root, check=True)
    if not staged:
        subprocess.run(("git", "commit", "-qm", "head"), cwd=git_root, check=True)
        monkeypatch.setenv("SARJ_STANDARDS_BASE", base)

    scope = baseline.changed_line_scope(project, staged=staged)
    old = Diagnostic("X", "old", Severity.ERROR, "ruff", Location("app.py", position=Position(0, 0, 0)))
    changed = replace(old, location=Location("app.py", position=Position(1, 0, 4)))

    assert scope is not None
    assert scope.paths == frozenset({"app.py"})
    assert not baseline.touches_changed_lines(old, scope)
    assert baseline.touches_changed_lines(changed, scope)


@pytest.mark.parametrize(
    "source_line",
    [
        "++ b/decoy;\n",
        "value;\r+++ b/decoy;\n",
        "value;\u2028diff --git a/decoy b/decoy\u2028+++ b/decoy;\n",
    ],
    ids=("added-header", "carriage-return", "unicode-line-separator"),
)
def test_patch_like_source_cannot_hide_a_later_changed_hunk(git_root: Path, source_line: str) -> None:
    source = git_root / "app.ts"
    lines = [f"value{index};\n" for index in range(12)]
    source.write_text("".join(lines), encoding="utf-8")
    subprocess.run(("git", "add", "."), cwd=git_root, check=True)
    subprocess.run(("git", "commit", "-qm", "base"), cwd=git_root, check=True)
    lines[1] = source_line
    lines[10] = "changed;\n"
    source.write_text("".join(lines), encoding="utf-8")
    subprocess.run(("git", "add", "."), cwd=git_root, check=True)

    scope = baseline.changed_line_scope(git_root, staged=True)
    changed = Diagnostic("X", "new", Severity.ERROR, "eslint", Location("app.ts", position=Position(10, 0, 100)))

    assert baseline.touches_changed_lines(changed, scope)


def test_changed_line_analysis_does_not_execute_text_converters(git_root: Path) -> None:
    source = git_root / "app.py"
    source.write_text("old\nkeep\n", encoding="utf-8")
    (git_root / ".gitattributes").write_text("app.py diff=fixture\n", encoding="utf-8")
    subprocess.run(("git", "add", "."), cwd=git_root, check=True)
    subprocess.run(("git", "commit", "-qm", "base"), cwd=git_root, check=True)
    converter = git_root / "converter.py"
    converter.write_text(
        'from pathlib import Path\nPath(__file__).with_suffix(".ran").touch()\nprint("converted")\n',
        encoding="utf-8",
    )
    subprocess.run(
        ("git", "config", "diff.fixture.textconv", shlex.join((sys.executable, str(converter)))),
        cwd=git_root,
        check=True,
    )
    source.write_text("old\nchanged\n", encoding="utf-8")
    subprocess.run(("git", "add", "app.py"), cwd=git_root, check=True)

    scope = baseline.changed_line_scope(git_root, staged=True)

    assert not converter.with_suffix(".ran").exists()
    assert scope is not None
    assert scope.lines["app.py"] == frozenset({2})


@pytest.mark.parametrize(
    ("before", "after", "boundaries"),
    [
        ("first\nsecond\nremove\nfourth\nfifth\n", "first\nsecond\nfourth\nfifth\n", {2, 3}),
        ("remove\nsecond\nthird\nfourth\n", "second\nthird\nfourth\n", {1}),
        ("first\nsecond\nthird\nremove\n", "first\nsecond\nthird\n", {3, 4}),
        (
            "first\nremove-one\nsecond\nthird\nfourth\nremove-two\nfifth\n",
            "first\nsecond\nthird\nfourth\nfifth\n",
            {1, 2, 4, 5},
        ),
    ],
    ids=("middle", "start", "end", "multiple"),
)
def test_deletion_hunks_preserve_baselines_away_from_surviving_boundaries(
    before: str, after: str, boundaries: set[int], tmp_path: Path
) -> None:
    subprocess.run(("git", "init", "-q"), cwd=tmp_path, check=True)
    subprocess.run(("git", "config", "user.name", "Standards Test"), cwd=tmp_path, check=True)
    subprocess.run(("git", "config", "user.email", "standards@example.com"), cwd=tmp_path, check=True)
    source = tmp_path / "app.py"
    source.write_text(before, encoding="utf-8")
    subprocess.run(("git", "add", "app.py"), cwd=tmp_path, check=True)
    subprocess.run(("git", "commit", "-qm", "base"), cwd=tmp_path, check=True)
    source.write_text(after, encoding="utf-8")
    subprocess.run(("git", "add", "app.py"), cwd=tmp_path, check=True)

    scope = baseline.changed_line_scope(tmp_path, staged=True)
    findings = tuple(
        Diagnostic(
            "X",
            "existing",
            Severity.ERROR,
            "ruff",
            Location("app.py", position=Position(index, 0, index)),
            fingerprint=f"{index:064x}",
        )
        for index in range(len(after.splitlines()))
    )
    report = report_from_tools(tmp_path, (ToolReport("ruff", Completion.COMPLETE, findings),))
    visible = api._without_baselined_diagnostics(  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage] -- exercise the internal _without_baselined_diagnostics contract directly with controlled fixture data.
        report,
        {finding.fingerprint: 1 for finding in findings if finding.fingerprint is not None},
        changed_scope=scope,
    )

    assert scope is not None
    assert scope.lines == {"app.py": frozenset(boundaries)}
    assert tuple(
        finding.location.position.line + 1 for finding in visible.diagnostics if finding.location.position
    ) == tuple(line for line in range(1, len(after.splitlines()) + 1) if line in boundaries)


def test_deletion_boundaries_affect_spanning_regions_and_file_level_findings() -> None:
    scope = baseline.ChangedLineScope(frozenset({"app.py"}), {"app.py": frozenset({3, 4})})
    distant = Diagnostic(
        "X", "old", Severity.ERROR, "ruff", Location("app.py", region=Region(Position(0, 0, 0), Position(1, 0, 1)))
    )
    spanning = replace(distant, location=Location("app.py", region=Region(Position(0, 0, 0), Position(4, 0, 4))))
    whole_file = replace(distant, location=Location("app.py"))

    assert not baseline.touches_changed_lines(distant, scope)
    assert baseline.touches_changed_lines(spanning, scope)
    assert baseline.touches_changed_lines(whole_file, scope)


@pytest.mark.parametrize(
    ("start", "end", "changed", "touches"),
    [
        (Position(0, 0, 0), Position(1, 0, 3), 2, False),
        (Position(0, 0, 0), Position(1, 1, 4), 2, True),
        (Position(0, 0, 0), Position(1, 0, 3), 1, True),
        (Position(1, 0, 3), Position(1, 0, 3), 2, True),
        (Position(1, 0, 3), Position(1, 2, 5), 1, False),
    ],
)
def test_changed_lines_use_exclusive_range_ends(start: Position, end: Position, changed: int, touches: bool) -> None:
    finding = Diagnostic("X", "existing", Severity.ERROR, "ruff", Location("app.py", region=Region(start, end)))
    scope = baseline.ChangedLineScope(frozenset({"app.py"}), {"app.py": frozenset({changed})})

    assert baseline.touches_changed_lines(finding, scope) is touches


@pytest.mark.parametrize(
    "scope",
    [
        baseline.ChangedLineScope(frozenset(), {}, failed=True),
        baseline.ChangedLineScope(frozenset({"app.py"}), {}),
        baseline.ChangedLineScope(frozenset({"app.py"}), {"app.py": frozenset()}),
    ],
    ids=("failed-diff", "missing-hunks", "empty-hunks"),
)
def test_missing_or_failed_diff_information_stays_conservative(scope: baseline.ChangedLineScope) -> None:
    finding = Diagnostic("X", "existing", Severity.ERROR, "ruff", Location("app.py", position=Position(100, 0, 100)))

    assert baseline.touches_changed_lines(finding, scope)


def test_react_doctor_findings_are_baselineable_by_fingerprint() -> None:
    finding = Diagnostic(
        "react-doctor/no-array-index-as-key",
        "Do not use an array index as a key.",
        Severity.WARNING,
        "react-doctor",
        Location("app.tsx"),
        rule_id="react-doctor/no-array-index-as-key",
        fingerprint="a" * 64,
    )

    rendered: dict[str, object] = json.loads(  # pyright: ignore[reportAny] -- untyped stdlib boundary
        baseline.render((finding,))
    )
    assert rendered["diagnostics"] == [
        {
            "count": 1,
            "fingerprint": "a" * 64,
            "path": "app.tsx",
            "ruleId": "react-doctor/no-array-index-as-key",
            "source": "react-doctor",
        }
    ]


def test_existing_baseline_fingerprint_hides_only_matching_react_doctor_debt(tmp_path: Path) -> None:
    finding = Diagnostic(
        "react-doctor/no-array-index-as-key",
        "Do not use an array index as a key.",
        Severity.WARNING,
        "react-doctor",
        Location("app.tsx"),
        rule_id="react-doctor/no-array-index-as-key",
        fingerprint="a" * 64,
    )
    new_finding = replace(finding, fingerprint="b" * 64)
    report = report_from_tools(
        tmp_path,
        (ToolReport("react-doctor", Completion.COMPLETE, (finding, new_finding)),),
    )

    visible = api._without_baselined_diagnostics(  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage] -- exercise the internal _without_baselined_diagnostics contract directly with controlled fixture data.
        report, {"a" * 64: 1}
    )

    assert visible.diagnostics == (new_finding,)
    assert visible.tools[0].baselined_count == 1


def _configure_authored_engine_baseline_fixture(root: Path, path: str | None = None) -> None:
    # These fixtures exercise authored-engine debt, without initialized native providers.
    adopted = replace(_manifest(path), disabled_capabilities=("terraform", "tflint", "jscpd"))
    (root / MANIFEST_NAME).write_text(adopted.render(), encoding="utf-8")


@pytest.fixture
def checkov_process(monkeypatch: pytest.MonkeyPatch) -> None:
    original = external._run_process  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage] -- exercise the internal _run_process contract directly with controlled fixture data.
    payload = json.dumps(
        {"passed": 0, "failed": 0, "skipped": 0, "parsing_errors": 0, "resource_count": 0, "checkov_version": "3.3.30"}
    )

    def run(
        argv: Sequence[str], *, cwd: Path, environment: dict[str, str], timeout_seconds: float = 900
    ) -> external.ProcessOutput:
        if "checkov==3.3.30" in argv:
            assert "--offline" in argv
            assert "--skip-download" in argv
            return external.ProcessOutput(0, payload, "")
        return original(argv, cwd=cwd, environment=environment, timeout_seconds=timeout_seconds)

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- replaces only Checkov's process response; CLI, parser, and baseline behavior run normally without a provisioned scanner cache.
        external, "_run_process", run
    )


@pytest.mark.usefixtures("checkov_process")
def test_baseline_init_records_todays_findings_for_every_authored_engine(tmp_path: Path) -> None:
    _configure_authored_engine_baseline_fixture(tmp_path)
    (tmp_path / "service.py").write_text("logger.info('request', token=token)\n", encoding="utf-8")
    (tmp_path / "main.tf").write_text(
        'resource "google_storage_bucket" "a" {\n  count = var.environment == "prod" ? 1 : 0\n}\n',
        encoding="utf-8",
    )

    assert cli_main(["--root", str(tmp_path), "baseline", "init"]) == 0

    raw = api.Standards(tmp_path).analyze(external=True, mode=api.AnalysisMode.CORPUS)
    recorded = baseline.load(tmp_path / "diagnostic-baseline.json")

    # One command has to cover every engine, or a consumer needs one baseline per tool.
    assert {"SARJ012", "SARJ204"} <= {item.code for item in raw.diagnostics}
    assert sum(recorded.values()) == len(raw.diagnostics)


@pytest.mark.usefixtures("checkov_process")
def test_baselined_findings_stop_failing_but_a_new_one_still_does(tmp_path: Path) -> None:
    _configure_authored_engine_baseline_fixture(tmp_path)
    source = tmp_path / "main.tf"
    source.write_text(
        'resource "google_storage_bucket" "a" {\n  count = var.environment == "prod" ? 1 : 0\n}\n',
        encoding="utf-8",
    )
    assert cli_main(["--root", str(tmp_path), "baseline", "init"]) == 0
    _configure_authored_engine_baseline_fixture(tmp_path, "diagnostic-baseline.json")

    settled = api.Standards(tmp_path).analyze()
    assert [item.code for item in settled.diagnostics] == []

    source.write_text(
        source.read_text(encoding="utf-8")
        + '\nresource "google_storage_bucket" "b" {\n  count = var.environment == "dev" ? 1 : 0\n}\n',
        encoding="utf-8",
    )

    grown = api.Standards(tmp_path).analyze()
    assert "SARJ204" in [item.code for item in grown.diagnostics]


@pytest.mark.usefixtures("checkov_process")
def test_baseline_init_refuses_to_overwrite_and_update_replaces(tmp_path: Path) -> None:
    _configure_authored_engine_baseline_fixture(tmp_path)
    (tmp_path / "main.tf").write_text(
        'resource "google_storage_bucket" "a" {\n  count = var.environment == "prod" ? 1 : 0\n}\n',
        encoding="utf-8",
    )
    assert cli_main(["--root", str(tmp_path), "baseline", "init"]) == 0

    assert cli_main(["--root", str(tmp_path), "baseline", "init"]) == 2
    assert cli_main(["--root", str(tmp_path), "baseline", "update"]) == 0


@pytest.mark.parametrize(
    ("selector", "expected"),
    [
        ("eslint:@sarj/prefer-ecmascript-private-members", "eslint:prefer-ecmascript-private-members"),
        ("eslint:prefer-ecmascript-private-members", "eslint:prefer-ecmascript-private-members"),
        ("sarj-iac-lint:no-restated-comment", "iac:no-restated-comment"),
        ("iac:no-restated-comment", "iac:no-restated-comment"),
        ("sarj-python-lint:no-unnecessary-docstring", "python:no-unnecessary-docstring"),
        ("python:no-unnecessary-docstring", "python:no-unnecessary-docstring"),
        ("sarj-sql-lint:no-create-trigger", "sql:no-create-trigger"),
        ("sql:no-create-trigger", "sql:no-create-trigger"),
        ("sarj-text-lint:hidden-markdown-heading", "text:hidden-markdown-heading"),
        ("text:hidden-markdown-heading", "text:hidden-markdown-heading"),
    ],
)
def test_scoped_baseline_update_normalizes_native_sarj_rule_source(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    selector: str,
    expected: str,
) -> None:
    baseline_path = tmp_path / "diagnostic-baseline.json"
    baseline_path.write_text(
        baseline.render(
            (),
            bundle_version=api.__version__,
            consumer_base_sha="0" * 40,
            catalog_digest=baseline.bundled_catalog_digest(),
        ),
        encoding="utf-8",
    )
    captured: list[tuple[object, object, object]] = []

    def analyze(
        _self: api.Standards,
        paths: object = None,  # ruff: ignore[unused-function-argument] -- Standards.analyze fixes this keyword.
        **kwargs: Unpack[StandardsAnalyzeOptions],
    ) -> AnalysisReport:
        captured.append(
            (
                kwargs.get("rules"),
                kwargs.get("include_react_doctor"),
                kwargs.get("pass_on_unpruned_eslint_suppressions"),
            )
        )
        return report_from_tools(tmp_path, ())

    monkeypatch.setattr(api.Standards, "analyze", analyze)  # sarj-noqa: SARJ445 -- intercepts baseline analyzer routing

    assert (
        cli_main(
            [
                "--root",
                str(tmp_path),
                "baseline",
                "update",
                "--output",
                str(baseline_path),
                "--rule",
                selector,
            ]
        )
        == 0
    )
    assert captured == [([expected], False, True)]


def test_scoped_baseline_update_runs_only_shellcheck_for_native_selector(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    baseline_path = tmp_path / "diagnostic-baseline.json"
    baseline_path.write_text(
        baseline.render(
            (),
            bundle_version=api.__version__,
            consumer_base_sha="0" * 40,
            catalog_digest=baseline.bundled_catalog_digest(),
        ),
        encoding="utf-8",
    )
    source = tmp_path / "release.sh"
    source.write_text("echo $name\n", encoding="utf-8")
    finding = Diagnostic(
        "SC2086",
        "quote expansion",
        Severity.WARNING,
        "shellcheck",
        Location("release.sh"),
        rule_id="SC2086",
        fingerprint="e" * 64,
    )
    calls: list[object] = []

    def analyze_shellcheck(files: object, **kwargs: Unpack[ExternalAnalyzeOptions]) -> tuple[ToolReport, ...]:
        calls.append((files, kwargs.get("capabilities"), kwargs.get("include_react_doctor")))
        return (ToolReport("shellcheck", Completion.COMPLETE, (finding,)),)

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- intercepts baseline analyzer routing
        external, "analyze_external", analyze_shellcheck
    )

    status = cli_main(
        [
            "--root",
            str(tmp_path),
            "baseline",
            "update",
            "--output",
            str(baseline_path),
            "--rule",
            "shellcheck:SC2086",
            str(source),
        ]
    )

    assert status == 0
    assert calls == [([str(source)], frozenset({"shellcheck"}), False)]
    rendered: object = json.loads(baseline_path.read_text(encoding="utf-8"))  # pyright: ignore[reportAny] -- inspect the stdlib decoder's untyped JSON payload before asserting the serialized contract.
    diagnostics = as_table(rendered).get("diagnostics")
    assert isinstance(diagnostics, list)
    assert diagnostics == [
        {
            "fingerprint": "e" * 64,
            "source": "shellcheck",
            "ruleId": "SC2086",
            "path": "release.sh",
            "count": 1,
        }
    ]


def test_scoped_baseline_update_keeps_retired_iac_alias_invalid(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    baseline_path = tmp_path / "diagnostic-baseline.json"
    baseline_path.write_text(
        baseline.render(
            (),
            bundle_version=api.__version__,
            consumer_base_sha="0" * 40,
            catalog_digest=baseline.bundled_catalog_digest(),
        ),
        encoding="utf-8",
    )
    (tmp_path / "main.tf").write_text("terraform {}\n", encoding="utf-8")

    status = cli_main(
        [
            "--root",
            str(tmp_path),
            "baseline",
            "update",
            "--output",
            str(baseline_path),
            "--rule",
            "iac:no-terraform-test-file",
        ]
    )

    assert status == 2
    assert "unknown or invalid rule selector: iac:no-terraform-test-file" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("source", "rule_id", "selector"),
    [
        ("eslint", "@sarj/prefer-ecmascript-private-members", "eslint:prefer-ecmascript-private-members"),
        ("sarj-iac-lint", "no-restated-comment", "iac:no-restated-comment"),
        ("sarj-python-lint", "no-unnecessary-docstring", "python:no-unnecessary-docstring"),
        ("sarj-sql-lint", "no-create-trigger", "sql:no-create-trigger"),
        ("sarj-text-lint", "hidden-markdown-heading", "text:hidden-markdown-heading"),
    ],
)
def test_scoped_baseline_update_replaces_native_debt_for_canonical_selector(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    source: str,
    rule_id: str,
    selector: str,
) -> None:
    baseline_path = tmp_path / "diagnostic-baseline.json"
    old = Diagnostic(
        "OLD",
        "old",
        Severity.ERROR,
        source,
        Location("old.txt"),
        rule_id=rule_id,
        fingerprint="a" * 64,
    )
    baseline_path.write_text(
        baseline.render(
            (old,),
            bundle_version=api.__version__,
            consumer_base_sha="0" * 40,
            catalog_digest=baseline.bundled_catalog_digest(),
        ),
        encoding="utf-8",
    )
    replacement = Diagnostic(
        "NEW",
        "replacement",
        Severity.ERROR,
        source,
        Location("new.txt"),
        rule_id=rule_id,
        fingerprint="b" * 64,
    )

    def analyze(
        _self: api.Standards,
        paths: object = None,  # ruff: ignore[unused-function-argument] -- Standards.analyze fixes this keyword.
        **_kwargs: Unpack[StandardsAnalyzeOptions],
    ) -> AnalysisReport:
        return report_from_tools(tmp_path, (ToolReport(source, Completion.COMPLETE, (replacement,)),))

    monkeypatch.setattr(api.Standards, "analyze", analyze)  # sarj-noqa: SARJ445 -- intercepts baseline analyzer routing

    assert (
        cli_main(
            [
                "--root",
                str(tmp_path),
                "baseline",
                "update",
                "--output",
                str(baseline_path),
                "--rule",
                selector,
            ]
        )
        == 0
    )
    updated = baseline.load(baseline_path)
    assert "a" * 64 not in updated
    assert updated == {"b" * 64: 1}


def test_scoped_baseline_update_replaces_debt_recorded_under_a_catalogued_alias(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    baseline_path = tmp_path / "diagnostic-baseline.json"
    old = Diagnostic(
        "OLD",
        "old",
        Severity.ERROR,
        "sarj-iac-lint",
        Location("old.tf"),
        rule_id="no-terraform-test-file",
        fingerprint="a" * 64,
    )
    baseline_path.write_text(
        baseline.render(
            (old,),
            bundle_version=api.__version__,
            consumer_base_sha="0" * 40,
            catalog_digest=baseline.bundled_catalog_digest(),
        ),
        encoding="utf-8",
    )
    replacement = Diagnostic(
        "NEW",
        "replacement",
        Severity.ERROR,
        "sarj-iac-lint",
        Location("new.tf"),
        rule_id="no-mocked-terraform-test-oracle",
        fingerprint="b" * 64,
    )

    def analyze(
        _self: api.Standards,
        paths: object = None,  # ruff: ignore[unused-function-argument] -- Standards.analyze fixes this keyword.
        **_kwargs: Unpack[StandardsAnalyzeOptions],
    ) -> AnalysisReport:
        return report_from_tools(tmp_path, (ToolReport("sarj-iac-lint", Completion.COMPLETE, (replacement,)),))

    monkeypatch.setattr(api.Standards, "analyze", analyze)  # sarj-noqa: SARJ445 -- intercepts baseline analyzer routing

    assert (
        cli_main(
            [
                "--root",
                str(tmp_path),
                "baseline",
                "update",
                "--output",
                str(baseline_path),
                "--rule",
                "iac:no-mocked-terraform-test-oracle",
            ]
        )
        == 0
    )
    assert baseline.load(baseline_path) == {"b" * 64: 1}


def test_scoped_baseline_update_replaces_plugin_qualified_eslint_alias_debt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    baseline_path = tmp_path / "diagnostic-baseline.json"
    old = Diagnostic(
        "OLD",
        "old",
        Severity.ERROR,
        "eslint",
        Location("old.ts"),
        rule_id="@sarj/zod-naming-convention",
        fingerprint="a" * 64,
    )
    baseline_path.write_text(
        baseline.render(
            (old,),
            bundle_version=api.__version__,
            consumer_base_sha="0" * 40,
            catalog_digest=baseline.bundled_catalog_digest(),
        ),
        encoding="utf-8",
    )
    replacement = Diagnostic(
        "NEW",
        "replacement",
        Severity.ERROR,
        "eslint",
        Location("new.ts"),
        rule_id="@sarj/require-pascal-case-zod-schema-name",
        fingerprint="b" * 64,
    )

    def analyze(
        _self: api.Standards,
        paths: object = None,  # ruff: ignore[unused-function-argument] -- Standards.analyze fixes this keyword.
        **_kwargs: Unpack[StandardsAnalyzeOptions],
    ) -> AnalysisReport:
        return report_from_tools(
            tmp_path,
            (ToolReport("eslint", Completion.COMPLETE, (replacement,)),),
        )

    monkeypatch.setattr(api.Standards, "analyze", analyze)  # sarj-noqa: SARJ445 -- intercepts baseline analyzer routing

    assert (
        cli_main(
            [
                "--root",
                str(tmp_path),
                "baseline",
                "update",
                "--output",
                str(baseline_path),
                "--rule",
                "eslint:require-pascal-case-zod-schema-name",
            ]
        )
        == 0
    )
    assert baseline.load(baseline_path) == {"b" * 64: 1}


@pytest.mark.parametrize(
    ("selector", "source", "rule_id"),
    [
        ("react-doctor:react-doctor/no-array-index-as-key", "react-doctor", "react-doctor/no-array-index-as-key"),
        ("react-doctor:no-array-index-as-key", "react-doctor", "react-doctor/no-array-index-as-key"),
        ("eslint:react-doctor/no-array-index-as-key", "react-doctor", "react-doctor/no-array-index-as-key"),
        ("eslint:react-doctor/no-array-index-as-key", "react-doctor", "no-array-index-as-key"),
        (
            "react-doctor:react-hooks-js/no-useless-custom-hooks",
            "react-doctor",
            "react-hooks-js/no-useless-custom-hooks",
        ),
        ("eslint:react-hooks-js/no-useless-custom-hooks", "react-doctor", "react-hooks-js/no-useless-custom-hooks"),
        ("eslint:react-hooks-js/no-useless-custom-hooks", "react-hooks-js", "no-useless-custom-hooks"),
        ("react-hooks-js:no-useless-custom-hooks", "react-doctor", "react-hooks-js/no-useless-custom-hooks"),
        ("react-hooks-js:no-useless-custom-hooks", "react-hooks-js", "no-useless-custom-hooks"),
    ],
)
def test_scoped_baseline_update_captures_react_doctor_and_preserves_unrelated_debt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    selector: str,
    source: str,
    rule_id: str,
) -> None:
    baseline_path = tmp_path / "diagnostic-baseline.json"
    old = Diagnostic(
        rule_id,
        "old selected debt",
        Severity.ERROR,
        source,
        Location("old.tsx"),
        rule_id=rule_id,
        fingerprint="a" * 64,
    )
    unrelated = Diagnostic(
        "react-doctor/button-has-type",
        "unrelated debt",
        Severity.ERROR,
        source,
        Location("button.tsx"),
        rule_id="react-doctor/button-has-type",
        fingerprint="c" * 64,
    )
    baseline_path.write_text(
        baseline.render(
            (old, unrelated),
            bundle_version=api.__version__,
            consumer_base_sha="0" * 40,
            catalog_digest=baseline.bundled_catalog_digest(),
        ),
        encoding="utf-8",
    )
    replacement = replace(old, message="replacement debt", location=Location("new.tsx"), fingerprint="b" * 64)
    calls: list[tuple[object, object, object, object]] = []

    def analyze_react_doctor(files: object, **kwargs: Unpack[ExternalAnalyzeOptions]) -> tuple[ToolReport, ...]:
        calls.append(
            (
                files,
                kwargs.get("capabilities"),
                (kwargs.get("include_react_doctor"), kwargs.get("force_react_doctor")),
                kwargs.get("react_doctor_full_scan"),
            )
        )
        return (ToolReport("react-doctor", Completion.COMPLETE, (replacement, unrelated)),)

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- intercepts baseline analyzer routing
        external, "analyze_external", analyze_react_doctor
    )

    assert (
        cli_main(
            [
                "--root",
                str(tmp_path),
                "baseline",
                "update",
                "--output",
                str(baseline_path),
                "--rule",
                selector,
            ]
        )
        == 0
    )
    assert calls == [
        ([str(tmp_path)], frozenset({"react-doctor"}), (True, True), True),
    ]
    assert baseline.load(baseline_path) == {"b" * 64: 1, "c" * 64: 1}


def test_scoped_react_doctor_wildcard_replaces_every_react_doctor_rule(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    baseline_path = tmp_path / "diagnostic-baseline.json"
    old_react = Diagnostic(
        "react-doctor/old",
        "old React debt",
        Severity.ERROR,
        "react-doctor",
        Location("old.tsx"),
        rule_id="react-doctor/old",
        fingerprint="a" * 64,
    )
    unrelated = Diagnostic(
        "F401",
        "unrelated Python debt",
        Severity.ERROR,
        "ruff",
        Location("old.py"),
        rule_id="F401",
        fingerprint="c" * 64,
    )
    baseline_path.write_text(
        baseline.render(
            (old_react, unrelated),
            bundle_version=api.__version__,
            consumer_base_sha="0" * 40,
            catalog_digest=baseline.bundled_catalog_digest(),
        ),
        encoding="utf-8",
    )
    replacement = replace(
        old_react,
        code="react-doctor/new",
        rule_id="react-doctor/new",
        message="current React debt",
        fingerprint="b" * 64,
    )

    def analyze_react_doctor(files: object, **kwargs: Unpack[ExternalAnalyzeOptions]) -> tuple[ToolReport, ...]:
        assert files == [str(tmp_path)]
        assert kwargs.get("react_doctor_full_scan") is True
        return (ToolReport("react-doctor", Completion.COMPLETE, (replacement,)),)

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- intercepts baseline analyzer routing
        external, "analyze_external", analyze_react_doctor
    )

    assert (
        cli_main(
            [
                "--root",
                str(tmp_path),
                "baseline",
                "update",
                "--output",
                str(baseline_path),
                "--rule",
                "react-doctor:*",
            ]
        )
        == 0
    )
    assert baseline.load(baseline_path) == {"b" * 64: 1, "c" * 64: 1}


def test_scoped_baseline_update_uses_manifest_verification_paths(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    baseline_path = tmp_path / "diagnostic-baseline.json"
    baseline_path.write_text(
        baseline.render(
            (),
            bundle_version=api.__version__,
            consumer_base_sha="0" * 40,
            catalog_digest=baseline.bundled_catalog_digest(),
        ),
        encoding="utf-8",
    )
    adopted = _manifest(baseline_path.name, verify_paths=("src", "test"))
    (tmp_path / MANIFEST_NAME).write_text(adopted.render(), encoding="utf-8")
    captured: list[object] = []

    def analyze_eslint(files: object, **_kwargs: Unpack[ExternalAnalyzeOptions]) -> tuple[ToolReport, ...]:
        captured.append(files)
        return ()

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- intercepts baseline analyzer routing
        external, "analyze_external", analyze_eslint
    )

    assert (
        cli_main(
            [
                "--root",
                str(tmp_path),
                "baseline",
                "update",
                "--output",
                str(baseline_path),
                "--rule",
                "eslint:unicorn/prefer-iterator-helpers",
            ]
        )
        == 0
    )
    assert captured == [[str(tmp_path / "src"), str(tmp_path / "test")]]


def test_scoped_baseline_update_includes_tracked_terraform_tests_outside_verification_paths(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "iac" / "bootstrap.tftest.hcl"
    source.parent.mkdir()
    source.write_text('mock_provider "aws" {}\n', encoding="utf-8")
    (tmp_path / "src").mkdir()
    subprocess.run(("git", "init", "-q"), cwd=tmp_path, check=True)
    subprocess.run(("git", "add", "iac/bootstrap.tftest.hcl"), cwd=tmp_path, check=True)
    baseline_path = tmp_path / "diagnostic-baseline.json"
    baseline_path.write_text(
        baseline.render(
            (),
            bundle_version=api.__version__,
            consumer_base_sha="0" * 40,
            catalog_digest=baseline.bundled_catalog_digest(),
        ),
        encoding="utf-8",
    )
    adopted = _manifest(baseline_path.name, verify_paths=("src",))
    (tmp_path / MANIFEST_NAME).write_text(adopted.render(), encoding="utf-8")
    finding = Diagnostic(
        "SARJ206",
        "Terraform mock provider oracle",
        Severity.WARNING,
        "sarj-iac-lint",
        Location("iac/bootstrap.tftest.hcl"),
        rule_id="no-mocked-terraform-test-oracle",
        fingerprint="d" * 64,
    )
    captured: list[object] = []

    def analyze(
        _self: api.Standards, paths: object = None, **_kwargs: Unpack[StandardsAnalyzeOptions]
    ) -> AnalysisReport:
        captured.append(paths)
        diagnostics = (finding,) if isinstance(paths, list) and str(source) in paths else ()
        return report_from_tools(tmp_path, (ToolReport("sarj-iac-lint", Completion.COMPLETE, diagnostics),))

    monkeypatch.setattr(api.Standards, "analyze", analyze)  # sarj-noqa: SARJ445 -- intercepts baseline analyzer routing

    assert (
        cli_main(
            [
                "--root",
                str(tmp_path),
                "baseline",
                "update",
                "--output",
                str(baseline_path),
                "--rule",
                "sarj-iac-lint:no-mocked-terraform-test-oracle",
            ]
        )
        == 0
    )
    assert captured == [[str(tmp_path / "src"), str(source)]]
    assert baseline.load(baseline_path) == {"d" * 64: 1}


@pytest.mark.parametrize(
    "selector",
    ["eslint:@typescript-eslint/naming-convention", "eslint:unicorn/prefer-iterator-helpers"],
)
def test_scoped_baseline_update_runs_only_eslint_for_upstream_selector(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    selector: str,
) -> None:
    baseline_path = tmp_path / "diagnostic-baseline.json"
    baseline_path.write_text(
        baseline.render(
            (),
            bundle_version=api.__version__,
            consumer_base_sha="0" * 40,
            catalog_digest=baseline.bundled_catalog_digest(),
        ),
        encoding="utf-8",
    )
    adopted = replace(_manifest(baseline_path.name), excluded_paths=("generated/**",))
    (tmp_path / MANIFEST_NAME).write_text(adopted.render(), encoding="utf-8")
    captured: list[tuple[object, object]] = []

    def analyze(
        _self: api.Standards, paths: object = None, **kwargs: Unpack[StandardsAnalyzeOptions]
    ) -> AnalysisReport:
        captured.append((paths, kwargs.get("rules")))
        return report_from_tools(tmp_path, ())

    monkeypatch.setattr(api.Standards, "analyze", analyze)  # sarj-noqa: SARJ445 -- intercepts baseline analyzer routing

    external_calls: list[object] = []

    def analyze_eslint(files: object, **kwargs: Unpack[ExternalAnalyzeOptions]) -> tuple[ToolReport, ...]:
        policy = kwargs.get("policy")
        assert isinstance(policy, Policy)
        external_calls.append(
            (
                files,
                kwargs.get("capabilities"),
                kwargs.get("include_react_doctor"),
                kwargs.get("pass_on_unpruned_eslint_suppressions"),
                policy.allows_path(tmp_path / "generated" / "client.ts"),
            )
        )
        return ()

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- intercepts baseline analyzer routing
        external, "analyze_external", analyze_eslint
    )

    assert (
        cli_main(
            [
                "--root",
                str(tmp_path),
                "baseline",
                "update",
                "--output",
                str(baseline_path),
                "--rule",
                selector,
            ]
        )
        == 0
    )
    assert captured == []
    assert external_calls == [([str(tmp_path)], frozenset({"eslint"}), False, True, False)]


def test_baseline_rejects_a_path_outside_the_repository(tmp_path: Path) -> None:
    (tmp_path / "main.tf").write_text('resource "x" "y" {}\n', encoding="utf-8")

    assert cli_main(["--root", str(tmp_path), "baseline", "init", "/etc/hosts"]) == 2
