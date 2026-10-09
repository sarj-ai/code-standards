from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from sarj_standards.libs.adoption import devops, doctor, lifecycle, manifest
from sarj_standards.libs.linting.devops_tools import NativeToolError, checked_tool, installed_compose_version
from sarj_standards.libs.linting.external import ProcessOutput


if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence
    from pathlib import Path


def test_required_tools_match_dockerfile_variants_and_skip_ignore_files(tmp_path: Path) -> None:
    variant = tmp_path / "python/integration/Dockerfile.migrate"
    variant.parent.mkdir(parents=True)
    variant.write_text("FROM scratch\n", encoding="utf-8")
    ignored = tmp_path / "Dockerfile.migrate.dockerignore"
    ignored.write_text("target\n", encoding="utf-8")
    assert devops.required_tools(tmp_path, (variant,), capabilities=("hadolint",)) == ("hadolint",)
    assert devops.required_tools(tmp_path, (ignored,), capabilities=("hadolint",)) == ()
    assert devops.required_tools(tmp_path, (variant,), capabilities=()) == ()
    commands = devops.install_commands(tmp_path, (variant,), capabilities=("hadolint",))
    assert commands[0].argv[-1] == "aqua:hadolint/hadolint@2.15.1"
    assert devops.install_commands(tmp_path, (ignored,), capabilities=("hadolint",)) == ()


def test_disabled_source_controls_do_not_provision_shell_parser(tmp_path: Path) -> None:
    workflow = tmp_path / ".github/workflows/ci.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text(
        "on: push\njobs:\n  check:\n    runs-on: ubuntu-latest\n    steps:\n      - run: echo fixture\n",
        encoding="utf-8",
    )
    assert devops.required_tools(tmp_path, (workflow,), capabilities=("yamllint",)) == ()
    assert devops.install_commands(tmp_path, (workflow,), capabilities=()) == ()
    assert devops.required_tools(tmp_path, (workflow,), capabilities=("shellcheck",)) == ("shfmt",)
    assert devops.required_tools(tmp_path, (workflow,), capabilities=("actionlint",)) == (
        "actionlint",
        "shellcheck",
        "shfmt",
    )


def test_consumer_compose_version_changes_attestation_and_setup(tmp_path: Path) -> None:
    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        assert argv == ("docker", "compose", "version", "--format", "json")
        assert cwd == tmp_path
        return ProcessOutput(0, '{"version":"v2.39.4"}', "")

    assert checked_tool("docker", root=tmp_path, runner=runner, expected_version="2.39.4").version == "2.39.4"
    assert installed_compose_version(tmp_path, runner=runner) == "2.39.4"
    adopted = manifest.Manifest("8.2.0", (), ".", ".", compose_version="2.39.4")
    (tmp_path / manifest.MANIFEST_NAME).write_text(adopted.render(), encoding="utf-8")
    compose = tmp_path / "compose.yaml"
    compose.write_text("services: {}\n", encoding="utf-8")
    assert manifest.load(tmp_path) == adopted
    commands = devops.install_commands(tmp_path, (compose,))
    assert commands[0].argv[-1] == "github:docker/compose@2.39.4"


@pytest.mark.parametrize("version", ["v2.39.4", "latest", "2.39", "2.39.4-beta", "02.39.4", "2.39.4;echo x"])
def test_consumer_compose_pin_requires_exact_semver(tmp_path: Path, version: str) -> None:
    adopted = manifest.Manifest("8.2.0", (), ".", ".", compose_version=version)
    (tmp_path / manifest.MANIFEST_NAME).write_text(adopted.render(), encoding="utf-8")
    with pytest.raises(ValueError, match="exact semantic version"):
        manifest.load(tmp_path)


def test_non_compose_tool_cannot_override_catalog_pin(tmp_path: Path) -> None:
    with pytest.raises(NativeToolError, match="Only Compose"):
        checked_tool("helm", root=tmp_path, expected_version="1.2.3")


@pytest.mark.parametrize(
    "payload", ['{"version":"v5.1.2","extra":true}', '[{"version":"v5.1.2"}]', '{"version":"v5.1.2 v5.1.2"}', "v5.1.2"]
)
def test_compose_ambiguous_version_protocol_is_rejected(tmp_path: Path, payload: str) -> None:
    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        assert argv[0] == "docker"
        assert cwd == tmp_path
        return ProcessOutput(0, payload, "")

    with pytest.raises(ValueError, match=r"Compose|exact version|Expecting value"):
        checked_tool("docker", root=tmp_path, runner=runner)


def test_tools_only_requires_existing_current_manifest(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="existing current-schema"):
        devops.setup_tools_only(tmp_path)
    (tmp_path / manifest.MANIFEST_NAME).write_text('schema = 3\nbundle = "8.2.0"\n', encoding="utf-8")
    with pytest.raises(ValueError, match="schema"):
        devops.setup_tools_only(tmp_path)


@pytest.mark.parametrize("install_status", [0, 7])
def test_tools_only_install_preserves_files_and_never_installs_hooks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, install_status: int
) -> None:
    adopted = manifest.Manifest("8.2.0", (), ".", ".")
    path = tmp_path / manifest.MANIFEST_NAME
    path.write_text(adopted.render(), encoding="utf-8")
    workflow = tmp_path / ".github" / "workflows" / "standards.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text(
        "on: push\njobs:\n  test:\n    runs-on: ubuntu-latest\n    steps:\n      - run: echo fixture\n",
        encoding="utf-8",
    )
    before = {file: file.read_bytes() for file in (path, workflow)}
    commands: list[lifecycle.Command] = []
    attested: list[Path] = []

    def install(planned: Iterable[lifecycle.Command]) -> int:
        commands.extend(planned)
        return install_status

    def attest(root: Path, files: Sequence[Path]) -> tuple[doctor.Finding, ...]:
        assert root == tmp_path
        assert workflow in files
        attested.append(root)
        return ()

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- intercept native installer dispatch; injecting a replacement dispatcher would bypass the public setup boundary under test.
        lifecycle, "execute", install
    )
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- observe global attestation dispatch; injecting findings would bypass the public setup boundary under test.
        devops, "health_findings", attest
    )
    result = devops.setup_tools_only(tmp_path)
    assert result.status == install_status
    assert result.findings == ()
    assert [command.label for command in commands] == ["Pinned native DevOps tools"]
    assert "aqua:rhysd/actionlint@1.7.12" in commands[0].argv
    assert commands[0].argv[:5] == ("mise", "--no-config", "--no-env", "--no-hooks", "install")
    assert attested == ([tmp_path] if install_status == 0 else [])
    assert {file: file.read_bytes() for file in before} == before
