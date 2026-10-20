from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from sarj_standards import api
from sarj_standards.libs.adoption.manifest import ExclusionOverride, Manifest
from sarj_standards.libs.diagnostics import Completion, Conclusion, TrustMode, baseline
from sarj_standards.libs.linting.analysis import analyze, report_from_tools
from sarj_standards.libs.linting.external import analyze_external
from sarj_standards.libs.linting.policy import Policy


if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize(
    "source",
    [
        "value = 1 # noqa\n",
        "# ruff: noqa\nvalue = 1\n",
        "value = 1 # type: ignore\n",
        "value = 1 # noqa # ruff: ignore[blanket-noqa]\n",
        "# ruff: file-ignore[blanket-noqa]\nvalue = 1 # noqa\n",
        "value = 1 # type: ignore # ruff: ignore[blanket-type-ignore]\n",
    ],
)
def test_upstream_blanket_checks_are_required_despite_source_and_consumer_config(tmp_path: Path, source: str) -> None:
    path = tmp_path / "service.py"
    path.write_text(source, encoding="utf-8")
    (tmp_path / "ruff.toml").write_text("[lint]\nselect = []\n", encoding="utf-8")

    reports = analyze_external([str(path)], root=tmp_path, trust=TrustMode.TRUSTED, capabilities=frozenset({"ruff"}))

    assert all(report.completion is Completion.COMPLETE for report in reports)
    findings = [item for report in reports for item in report.diagnostics if "required-source-policy" in item.tags]
    assert len(findings) == 1
    assert not baseline.is_baselineable(findings[0])


@pytest.mark.parametrize(
    ("source", "code", "rule_id"),
    [
        ("value = vendor.value # sarj-noqa\n", "SARJ523", "no-blanket-suppression"),
        (
            "# ruff: file-ignore[banned-api] # sarj-noqa: SARJ054 -- dependency boundary\n",
            "SARJ054",
            "no-file-level-escape-hatch-suppression",
        ),
        (
            "value = vendor.value # pyright: ignore[reportAny] -- false positive\n",
            "SARJ419",
            "no-vague-suppression-description",
        ),
    ],
)
@pytest.mark.parametrize("scoped", [False, True])
def test_native_suppression_policy_cannot_be_excluded_or_baselined(
    tmp_path: Path, source: str, code: str, rule_id: str, *, scoped: bool
) -> None:
    path = tmp_path / "service.py"
    path.write_text(source, encoding="utf-8")
    selectors = (f"python:{code}", f"python:{rule_id}")
    manifest = Manifest(
        version=api.__version__,
        configs=(),
        python_dest=".",
        typescript_dest=".",
        excluded_rules=() if scoped else selectors,
        exclusion_overrides=(
            ExclusionOverride(paths=("service.py",), rules=selectors, reason="exercise waiver boundary"),
        )
        if scoped
        else (),
    )
    report = analyze([str(path)], root=tmp_path, policy=Policy.from_manifest(tmp_path, manifest))
    findings = [item for item in report.diagnostics if item.code == code]
    assert len(findings) == 1
    finding = findings[0]
    assert "required-source-policy" in finding.tags
    assert not baseline.is_baselineable(finding)
    assert finding.fingerprint is not None
    active = api._without_baselined_diagnostics(report, {finding.fingerprint: 100})  # ruff: ignore[private-member-access] -- exercise the full gate's existing-baseline filter.  # pyright: ignore[reportPrivateUsage]
    assert any(item.code == code for item in active.diagnostics)


def test_upstream_suppression_policy_cannot_be_excluded_or_baselined(tmp_path: Path) -> None:
    path = tmp_path / "service.py"
    path.write_text("value = 1 # noqa\n", encoding="utf-8")
    (tmp_path / "ruff.toml").write_text("[lint]\nselect = []\n", encoding="utf-8")
    tools = analyze_external([str(path)], root=tmp_path, trust=TrustMode.TRUSTED, capabilities=frozenset({"ruff"}))
    manifest = Manifest(
        version=api.__version__,
        configs=(),
        python_dest=".",
        typescript_dest=".",
        excluded_rules=("ruff:PGH004", "ruff:blanket-noqa"),
    )
    policy = Policy.from_manifest(tmp_path, manifest)
    report = report_from_tools(tmp_path, tools)
    findings = policy.filter_diagnostics(report.diagnostics)
    assert len(findings) == 1
    finding = findings[0]
    assert finding.fingerprint is not None
    active = api._without_baselined_diagnostics(report, {finding.fingerprint: 100})  # ruff: ignore[private-member-access] -- exercise the full gate's existing-baseline filter.  # pyright: ignore[reportPrivateUsage]
    assert len(active.diagnostics) == 1


def test_explicit_whole_path_exclusion_remains_a_boundary(tmp_path: Path) -> None:
    path = tmp_path / "vendor/service.py"
    path.parent.mkdir()
    path.write_text("value = 1 # sarj-noqa\n", encoding="utf-8")
    manifest = Manifest(
        version=api.__version__, configs=(), python_dest=".", typescript_dest=".", excluded_paths=("vendor/**",)
    )
    report = analyze([str(path)], root=tmp_path, policy=Policy.from_manifest(tmp_path, manifest))
    assert not report.diagnostics


@pytest.mark.parametrize(
    "source",
    ["from unittest.mock import Mock\nMock()\ndef broken(\n", "# pyright: basic\n#" + "x" * 500_001],
    ids=("parse-failure", "file-size-limit"),
)
def test_unanalyzed_python_cannot_be_reported_as_clean(tmp_path: Path, source: str) -> None:
    path = tmp_path / "service.py"
    path.write_text(source, encoding="utf-8")
    report = analyze([str(path)], root=tmp_path)
    assert report.completion is Completion.FAILED
    assert report.conclusion is Conclusion.INCONCLUSIVE
    assert report.exit_code == 2
    assert report.issues[0].kind == "analyzer-failure"


@pytest.mark.parametrize(
    ("filename", "source", "missing"),
    [
        ("service.py", "def label() -> str:\n    return 42\n", {"ruff", "basedpyright"}),
        ("service.ts", "// @ts-nocheck\nexport const label: string = 42;\n", {"eslint"}),
    ],
)
def test_disabled_source_analyzers_remain_explicit_scope_boundaries(
    tmp_path: Path, filename: str, source: str, missing: set[str]
) -> None:
    (tmp_path / ".sarj-standards.toml").write_text(
        Manifest(version=api.__version__, configs=(), python_dest=".", typescript_dest=".").render(), encoding="utf-8"
    )
    (tmp_path / filename).write_text(source, encoding="utf-8")
    report = api.Standards(tmp_path).analyze(
        [filename], external=True, trust=TrustMode.TRUSTED, include_react_doctor=False
    )
    assert report.completion is Completion.COMPLETE
    assert report.exit_code == 0
    assert {item.source for item in report.coverage} == missing
    assert not any(item.blocking for item in report.coverage)


@pytest.mark.parametrize("native_only", [False, True])
def test_explicit_partial_checks_remain_scoped(tmp_path: Path, *, native_only: bool) -> None:
    (tmp_path / ".sarj-standards.toml").write_text(
        Manifest(version=api.__version__, configs=(), python_dest=".", typescript_dest=".").render(), encoding="utf-8"
    )
    (tmp_path / "service.py").write_text("value = 1\n", encoding="utf-8")
    report = api.Standards(tmp_path).analyze(
        ["service.py"], external=not native_only, rules=None if native_only else ["python:no-blanket-suppression"]
    )
    assert report.exit_code == 0
    assert not any(item.blocking for item in report.coverage)


def test_python_read_failure_cannot_be_reported_as_clean(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from sarj_python_lint import __main__ as native  # ruff: ignore[import-outside-top-level] -- load the native runner only for its read-failure boundary test.

    path = tmp_path / "service.py"
    path.write_text("value = 1\n", encoding="utf-8")

    def unreadable(_path: Path) -> str:
        message = "selected source became unreadable"
        raise PermissionError(message)

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- simulate the native runner's global file read failing after routing, independent of host privileges.
        native, "read_python_source", unreadable
    )
    report = analyze([str(path)], root=tmp_path)
    assert report.exit_code == 2
    assert report.completion is Completion.FAILED
    assert report.issues[0].kind == "analyzer-failure"
