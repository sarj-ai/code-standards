from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from sarj_standards.libs.adoption import doctor, manifest, scaffold


if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("filename", ["mise.toml", ".mise.toml"])
@pytest.mark.parametrize(
    "contents",
    [
        '[tools]\nnode = "24"\n',
        '[tools]\n"pipx:sarj-standards-bootstrap" = {version = "1.0.0"}\n',
        '[tools]\n"pipx:sarj-standards-bootstrap" = "latest"\n',
        "[tools\n",
    ],
)
def test_doctor_does_not_manage_mise_configuration(tmp_path: Path, filename: str, contents: str) -> None:
    path = tmp_path / filename
    path.write_text(contents, encoding="utf-8")

    assert not any(
        finding.id.startswith("doctor.version.mise") for finding in doctor.diagnose_adoption_health(tmp_path)
    )
    assert doctor.plan_version_pin_updates(tmp_path, {}) == ()
    assert path.read_text(encoding="utf-8") == contents


def test_invalid_mise_does_not_break_adopted_repository_diagnosis(tmp_path: Path) -> None:
    adopted = manifest.Manifest(version=manifest.adopted_version(), configs=(), python_dest=".", typescript_dest=".")
    (tmp_path / manifest.MANIFEST_NAME).write_text(adopted.render(), encoding="utf-8")
    (tmp_path / ".pre-commit-config.yaml").write_text("repos:\n" + scaffold.precommit_block(), encoding="utf-8")
    directory = tmp_path / ".github" / "workflows"
    directory.mkdir(parents=True)
    (directory / "standards.yml").write_text(scaffold.github_ci_workflow(tmp_path), encoding="utf-8")
    for filename in ("mise.toml", ".mise.toml"):
        (tmp_path / filename).write_text("[tools\n", encoding="utf-8")

    findings = doctor.diagnose_adoption_health(tmp_path)
    assert not any(finding.id.startswith("doctor.version.mise") for finding in findings)
    assert not any(finding.id.startswith("doctor.version.mise") for finding in doctor.diagnose(tmp_path))
