from __future__ import annotations

from typing import TYPE_CHECKING

from sarj_standards.libs.adoption import manifest, scaffold


if TYPE_CHECKING:
    from pathlib import Path


def test_manifest_preserves_prepared_targets_compose_pin_and_configured_runner(tmp_path: Path) -> None:
    expected = manifest.Manifest(
        version=manifest.adopted_version(),
        configs=("zizmor", "checkov"),
        python_dest=".",
        typescript_dest=".",
        ci_runner="blacksmith-4vcpu-ubuntu-2404-arm",
        ci_bootstrap=("uv sync --frozen",),
        compose_version="5.1.2",
        prepared_targets=(manifest.PreparedTarget("release", "déploy.yaml"),),
    )
    (tmp_path / manifest.MANIFEST_NAME).write_text(expected.render(), encoding="utf-8")
    adopted = manifest.load(tmp_path)
    assert adopted is not None
    assert adopted == expected
    assert len(adopted.enabled_capabilities) == len(set(adopted.enabled_capabilities))


def test_generated_ci_keeps_configured_runner_and_native_tools_gate(tmp_path: Path) -> None:
    adopted = manifest.Manifest(
        version=manifest.adopted_version(),
        configs=(),
        python_dest=".",
        typescript_dest=".",
        ci_runner="blacksmith-4vcpu-ubuntu-2404-arm",
        prepared_targets=(manifest.PreparedTarget("release", "deploy.yaml"),),
    )
    (tmp_path / manifest.MANIFEST_NAME).write_text(adopted.render(), encoding="utf-8")
    workflow = scaffold.github_ci_workflow(tmp_path)
    assert "runs-on: blacksmith-4vcpu-ubuntu-2404-arm" in workflow
    assert "Harden the runner" not in workflow
    assert "setup --tools-only" in workflow
    assert workflow.index("setup --tools-only") < workflow.index("Run standards")
