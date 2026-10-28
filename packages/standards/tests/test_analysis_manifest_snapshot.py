from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from sarj_standards import api
from sarj_standards.libs.adoption.manifest import Manifest, load


if TYPE_CHECKING:
    from pathlib import Path


_RULE = "python:no-secret-in-log"
_SOURCE = "logger.info('request', token=token)\n"


def _manifest(directory: str) -> str:
    return Manifest(api.__version__, (), ".", ".", hook_manager="none", verify_paths=(directory,)).render()


@pytest.mark.parametrize("mode", [api.AnalysisMode.POLICY, api.AnalysisMode.CORPUS, api.AnalysisMode.OBSERVE])
def test_analysis_uses_one_manifest_for_policy_and_implicit_input_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: api.AnalysisMode
) -> None:
    for directory in ("selected", "later"):
        root = tmp_path / directory
        root.mkdir()
        (root / "service.py").write_text(_SOURCE, encoding="utf-8")
    manifest = tmp_path / ".sarj-standards.toml"
    manifest.write_text(_manifest("selected"), encoding="utf-8")
    loads = 0

    def load_and_replace(root: Path) -> Manifest | None:
        nonlocal loads
        loads += 1
        adopted = load(root)
        manifest.write_text(_manifest("later"), encoding="utf-8")
        return adopted

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- mutate the actual manifest after capture to expose a second input-selection read.
        api, "load_manifest", load_and_replace
    )
    standards = api.Standards(tmp_path)

    first = standards.analyze(mode=mode, rules=[_RULE])

    assert loads == 1
    assert first.completion is api.Completion.COMPLETE
    assert {item.location.path for item in first.diagnostics if item.code == "SARJ012"} == {"selected/service.py"}

    second = standards.analyze(mode=mode, rules=[_RULE])

    assert loads == 2
    assert second.completion is api.Completion.COMPLETE
    assert {item.location.path for item in second.diagnostics if item.code == "SARJ012"} == {"later/service.py"}


@pytest.mark.parametrize("paths", [None, ["service.py"]], ids=("implicit", "explicit"))
def test_corpus_invalid_manifest_fallback_applies_to_explicit_and_implicit_inputs(
    tmp_path: Path, paths: list[str] | None
) -> None:
    (tmp_path / ".sarj-standards.toml").write_text("schema = [\n", encoding="utf-8")
    (tmp_path / "service.py").write_text(_SOURCE, encoding="utf-8")

    report = api.Standards(tmp_path).analyze(paths, mode=api.AnalysisMode.CORPUS, rules=[_RULE])

    assert report.completion is api.Completion.COMPLETE
    assert {item.location.path for item in report.diagnostics if item.code == "SARJ012"} == {"service.py"}


@pytest.mark.parametrize("paths", [None, ["service.py"]], ids=("implicit", "explicit"))
def test_raw_analysis_never_loads_the_adoption_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, paths: list[str] | None
) -> None:
    (tmp_path / ".sarj-standards.toml").write_text("schema = [\n", encoding="utf-8")
    (tmp_path / "service.py").write_text(_SOURCE, encoding="utf-8")

    def unexpected_manifest(_root: Path) -> Manifest | None:
        pytest.fail("raw analysis must not read adoption policy")

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- assert the public raw-mode policy boundary without replacing source analysis.
        api, "load_manifest", unexpected_manifest
    )
    report = api.Standards(tmp_path).analyze(paths, mode=api.AnalysisMode.RAW, rules=[_RULE])

    assert report.completion is api.Completion.COMPLETE
    assert {item.location.path for item in report.diagnostics if item.code == "SARJ012"} == {"service.py"}


@pytest.mark.parametrize("mode", [api.AnalysisMode.POLICY, api.AnalysisMode.OBSERVE])
def test_policy_modes_still_reject_invalid_adoption_manifests(tmp_path: Path, mode: api.AnalysisMode) -> None:
    (tmp_path / ".sarj-standards.toml").write_text("schema = [\n", encoding="utf-8")
    (tmp_path / "service.py").write_text(_SOURCE, encoding="utf-8")

    report = api.Standards(tmp_path).analyze(mode=mode, rules=[_RULE])

    assert report.completion is api.Completion.FAILED
    assert report.conclusion is api.Conclusion.INCONCLUSIVE
    assert report.issues[0].kind == "invalid-input"
