from __future__ import annotations

from dataclasses import replace
import tomllib
from typing import TYPE_CHECKING

import pytest
from repo_standards.core.parser import parse_manifest_bytes
from repo_standards.policy_sarj import SarjPolicy

from sarj_standards import api
from sarj_standards.cli.main import main
from sarj_standards.libs.adoption import doctor, scaffold, service


if TYPE_CHECKING:
    from pathlib import Path

    from repo_standards.core.models import Rule, Severity


_RULE = "repository/artifacts/makefile-growth"
_CAP = (
    '\n[[makefiles.exceptions]]\npath = "Makefile"\nmax_lines = 12\n'
    'owner = "build-team"\nreason = "Preserve the required build graph"\nissue = "BUILD-123"\n'
    'created_on = "2026-10-01"\nexpires_on = "2026-10-30"\n'
)


def _manifest(root: Path, *, enabled: str = "") -> Path:
    path = root / ".repo-standards" / "repository.toml"
    path.parent.mkdir()
    path.write_text(
        f'repository_id = "fixture"\ncomponents = []\n{enabled}[commit_message]\nenforcement = "strict"\n' + _CAP,
        encoding="utf-8",
    )
    return path


def _rule_stage(monkeypatch: pytest.MonkeyPatch, stage: Severity) -> None:
    rules = tuple(
        replace(rule, default_severity=stage) if str(rule.rule_id) == _RULE else rule for rule in SarjPolicy.rules()
    )
    assert any(str(rule.rule_id) == _RULE for rule in rules)

    def installed_rules() -> tuple[Rule, ...]:
        return rules

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- installed release maturity is the adoption contract under test.
        SarjPolicy, "rules", staticmethod(installed_rules)
    )


def test_ordinary_setup_and_doctor_repair_preserve_rules_and_capped_exceptions(tmp_path: Path) -> None:
    enabled = 'enabled_rules = ["repository/artifacts/makefile-growth"] # explicit consumer policy\n'
    path = _manifest(tmp_path, enabled=enabled)
    before = path.read_bytes()

    assert main(["--root", str(tmp_path), "setup", "--no-install"]) == 0
    repair = service.plan_init(tmp_path)
    assert not repair.scaffold.errors
    assert path not in {target for target, _contents in repair.scaffold.writes}
    assert path.read_bytes() == before
    findings = doctor.diagnose_commit_policy(tmp_path)
    selected = [finding for finding in findings if finding.id == "doctor.repository.makefile-growth"]
    assert len(selected) == 1
    assert selected[0].level is doctor.Level.OK


def test_warning_release_cannot_be_activated_by_setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _rule_stage(monkeypatch, "warning")
    path = _manifest(tmp_path)
    before = path.read_bytes()

    status = main(["--root", str(tmp_path), "setup", "--no-install", "--enable-repository-rule", _RULE])
    result = api.Standards(tmp_path).setup(dry_run=True, enable_repository_rules=(_RULE,))

    assert status == 2
    assert result.exit_code == 2
    assert "error-stage release" in result.findings[0].message
    assert path.read_bytes() == before
    assert not (tmp_path / ".sarj-standards.toml").exists()


@pytest.mark.parametrize(
    "enabled", ["", "enabled_rules = []\n", 'enabled_rules = [\n  # preserve review context\n  "existing/rule",\n]\n']
)
def test_explicit_reviewed_activation_merges_rules_preserves_caps_and_is_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, enabled: str
) -> None:
    _rule_stage(monkeypatch, "error")
    path = _manifest(tmp_path, enabled=enabled)
    planned = service.plan_init(tmp_path, enable_repository_rules=(_RULE, _RULE))

    assert not planned.scaffold.errors
    scaffold.apply(planned.scaffold)
    contents = path.read_bytes()
    parsed = parse_manifest_bytes(contents)
    assert parsed.enabled_rules.count(_RULE) == 1
    assert len(parsed.makefile_exceptions) == 1
    assert parsed.makefile_exceptions[0].max_lines == 12
    assert _CAP.encode("utf-8") in contents
    if "existing/rule" in enabled:
        assert "existing/rule" in parsed.enabled_rules
        assert b"# preserve review context" in contents
    repeated = service.plan_init(tmp_path, enable_repository_rules=(_RULE,))
    assert path not in {target for target, _contents in repeated.scaffold.writes}
    assert path.read_bytes() == contents


def test_reviewed_activation_is_exposed_by_the_typed_setup_api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _rule_stage(monkeypatch, "error")

    result = api.Standards(tmp_path).setup(install=False, enable_repository_rules=(_RULE,))

    assert result.exit_code == 0
    parsed: dict[str, object] = tomllib.loads((tmp_path / ".repo-standards" / "repository.toml").read_text())
    assert parsed["enabled_rules"] == [_RULE]


@pytest.mark.parametrize("rule", ["missing/rule", _RULE + "@1"])
def test_unavailable_and_versioned_activation_cannot_write_policy(tmp_path: Path, rule: str) -> None:
    plan = service.plan_init(tmp_path, enable_repository_rules=(rule,))

    assert plan.scaffold.errors
    assert plan.sync is None
    assert not (tmp_path / ".repo-standards").exists()


@pytest.mark.parametrize("scope", ["--tools-only", "--commit-policy-only"])
def test_rule_activation_requires_full_setup_scope(tmp_path: Path, scope: str) -> None:
    assert main(["--root", str(tmp_path), "setup", scope, "--enable-repository-rule", _RULE]) == 2
    assert not (tmp_path / ".repo-standards").exists()
