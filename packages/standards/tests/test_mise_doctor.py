from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from sarj_standards.libs.adoption import doctor, launcher, manifest, scaffold


if TYPE_CHECKING:
    from pathlib import Path


def _findings(root: Path) -> list[doctor.Finding]:
    return [
        finding for finding in doctor.diagnose_adoption_health(root) if finding.id.startswith("doctor.version.mise")
    ]


def _configuration(version: str) -> str:
    return (
        "[tools]\n"
        f'"{launcher.MISE_BOOTSTRAP_TOOL}" = {{ version = "{version}", uvx_args = "{launcher.MISE_UVX_ARGS}" }}\n'
    )


def test_mise_doctor_no_pin_is_valid_fallback(tmp_path: Path) -> None:
    assert _findings(tmp_path) == []
    (tmp_path / "mise.toml").write_text('[tools]\nnode = "24"\n', encoding="utf-8")
    assert _findings(tmp_path) == []
    assert doctor.plan_version_pin_updates(tmp_path, {}) == ()


@pytest.mark.parametrize("filename", ["mise.toml", ".mise.toml"])
def test_mise_doctor_current_pin_is_healthy(tmp_path: Path, filename: str) -> None:
    (tmp_path / filename).write_text(_configuration(launcher.BOOTSTRAP_VERSION), encoding="utf-8")
    assert [finding.level for finding in _findings(tmp_path)] == [doctor.Level.OK]
    assert doctor.plan_version_pin_updates(tmp_path, {}) == ()


@pytest.mark.parametrize("filename", ["mise.toml", ".mise.toml"])
@pytest.mark.parametrize("expanded", [False, True])
def test_mise_doctor_repairs_only_stale_version_preserving_comments(
    tmp_path: Path, filename: str, expanded: bool
) -> None:
    old = "1.0.0"
    text = (
        f'# Example version "{old}"\n[tools]\nnode = "{old}" # unrelated tool\n'
        f"[tools.\"{launcher.MISE_BOOTSTRAP_TOOL}\"]\nversion = '{old}' # retain comment\n"
        f'uvx_args = "{launcher.MISE_UVX_ARGS}"\n'
        if expanded
        else f'# Example version "{old}"\n{_configuration(old)}node = "{old}" # unrelated tool\n'
    )
    path = tmp_path / filename
    path.write_text(text, encoding="utf-8")
    findings = _findings(tmp_path)
    assert [finding.level for finding in findings] == [doctor.Level.DRIFT]
    assert findings[0].remediation == "run `code-standards doctor --repair`"

    updates = doctor.plan_version_pin_updates(tmp_path, {})
    assert len(updates) == 1
    update = updates[0]
    quote = "'" if expanded else '"'
    expected = text.replace(f"version = {quote}{old}{quote}", f"version = {quote}{launcher.BOOTSTRAP_VERSION}{quote}")
    assert update.path == path
    assert update.contents == expected
    assert update.packages == (launcher.BOOTSTRAP_PACKAGE,)
    path.write_text(update.contents, encoding="utf-8")
    assert [finding.level for finding in _findings(tmp_path)] == [doctor.Level.OK]
    assert doctor.plan_version_pin_updates(tmp_path, {}) == ()


@pytest.mark.parametrize(
    "text",
    [
        "[tools\n",
        f'[tools]\n"{launcher.MISE_BOOTSTRAP_TOOL}" = "latest"\n',
        f'[tools]\n"{launcher.MISE_BOOTSTRAP_TOOL}" = {{version = "1.0.0"}}\n',
        _configuration("latest"),
        _configuration("1.0.0").replace("--no-config", "--with untrusted"),
    ],
    ids=["malformed-toml", "scalar-tool", "missing-options", "floating-version", "unexpected-options"],
)
def test_mise_doctor_reports_invalid_configuration_without_rewriting(tmp_path: Path, text: str) -> None:
    path = tmp_path / "mise.toml"
    path.write_text(text, encoding="utf-8")
    assert [finding.id for finding in _findings(tmp_path)] == ["doctor.version.mise-config"]
    assert doctor.plan_version_pin_updates(tmp_path, {}) == ()
    assert path.read_text(encoding="utf-8") == text


def test_mise_doctor_refuses_ambiguous_root_configurations(tmp_path: Path) -> None:
    for name in ("mise.toml", ".mise.toml"):
        (tmp_path / name).write_text(_configuration("1.0.0"), encoding="utf-8")
    assert [finding.id for finding in _findings(tmp_path)] == ["doctor.version.mise-config"]
    assert doctor.plan_version_pin_updates(tmp_path, {}) == ()


def test_mise_doctor_does_not_repair_a_linked_configuration(tmp_path: Path) -> None:
    target = tmp_path / "shared.toml"
    text = _configuration("1.0.0")
    target.write_text(text, encoding="utf-8")
    (tmp_path / "mise.toml").symlink_to(target)
    assert doctor.plan_version_pin_updates(tmp_path, {}) == ()
    assert target.read_text(encoding="utf-8") == text


def test_mise_doctor_preserves_crlf(tmp_path: Path) -> None:
    text = _configuration("1.0.0").replace("\n", "\r\n")
    (tmp_path / "mise.toml").write_bytes(text.encode("utf-8"))
    updates = doctor.plan_version_pin_updates(tmp_path, {})
    assert len(updates) == 1
    assert updates[0].contents == text.replace('version = "1.0.0"', f'version = "{launcher.BOOTSTRAP_VERSION}"')


def test_invalid_mise_in_adopted_repository_reports_findings_instead_of_raising(tmp_path: Path) -> None:
    adopted = manifest.Manifest(
        version=manifest.adopted_version(),
        configs=(),
        python_dest=".",
        typescript_dest=".",
    )
    (tmp_path / manifest.MANIFEST_NAME).write_text(adopted.render(), encoding="utf-8")
    (tmp_path / ".pre-commit-config.yaml").write_text("repos:\n" + scaffold.precommit_block(), encoding="utf-8")
    directory = tmp_path / ".github" / "workflows"
    directory.mkdir(parents=True)
    (directory / "standards.yml").write_text(scaffold.github_ci_workflow(tmp_path), encoding="utf-8")
    (tmp_path / "mise.toml").write_text("[tools\n", encoding="utf-8")
    findings = doctor.diagnose_adoption_health(tmp_path)
    assert any(finding.id == "doctor.version.mise-config" for finding in findings)
    assert any(finding.id == "doctor.version.mise-config" for finding in doctor.diagnose(tmp_path))
