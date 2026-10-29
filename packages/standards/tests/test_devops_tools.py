from __future__ import annotations

import subprocess
import sys
from typing import TYPE_CHECKING

import pytest

from sarj_standards.libs.adoption import devops, doctor, lifecycle, manifest
from sarj_standards.libs.linting import devops_tools
from sarj_standards.libs.linting.devops_tools import NativeToolError, checked_tool, installed_compose_version
from sarj_standards.libs.linting.external import ProcessOutput, run_process
from sarj_standards.libs.linting.process import ProcessCapabilities, ProcessRequest, RequestExecutor
from tests.process_fakes import FakeProcessExecutor


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


@pytest.mark.parametrize(
    ("name", "expected"),
    [("dev.tfvars", ("terraform",)), ("routing.tftest.hcl", ("terraform",)), ("dev.tfvars.json", ())],
)
def test_variable_and_test_only_projects_provision_the_native_formatter(
    tmp_path: Path, name: str, expected: tuple[str, ...]
) -> None:
    path = tmp_path / name
    path.write_text("{}\n", encoding="utf-8")
    assert devops.required_tools(tmp_path, (path,), capabilities=("terraform", "tflint")) == expected
    assert devops.required_tools(tmp_path, (path,), capabilities=("tflint",)) == ()


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

    assert (
        checked_tool("docker", root=tmp_path, runner=FakeProcessExecutor(runner), expected_version="2.39.4").version
        == "2.39.4"
    )
    assert installed_compose_version(tmp_path, runner=FakeProcessExecutor(runner)) == "2.39.4"
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


def test_native_version_timeout_has_an_owned_tool_error(tmp_path: Path) -> None:
    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        assert argv == ("helm", "version", "--short")
        return run_process((sys.executable, "-c", "import time; time.sleep(10)"), cwd=cwd, timeout_seconds=0.05)

    with pytest.raises(NativeToolError, match="query timed out") as caught:
        checked_tool("helm", root=tmp_path, runner=FakeProcessExecutor(runner))
    assert isinstance(caught.value.__cause__, subprocess.TimeoutExpired)


@pytest.mark.parametrize("installed_version", ["4.3.1", "4.0.0"])
def test_timed_out_path_tool_preserves_pinned_mise_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, installed_version: str
) -> None:
    binary_directory = tmp_path / "bin"
    binary_directory.mkdir()
    suffix = ".exe" if sys.platform == "win32" else ""
    stalled = binary_directory / f"helm{suffix}"
    mise = binary_directory / f"mise{suffix}"
    installation = tmp_path / "installed"
    installation.mkdir()
    installed = installation / f"helm{suffix}"
    for executable in (stalled, mise, installed):
        executable.write_text("native protocol fixture", encoding="utf-8")
        executable.chmod(0o755)
    monkeypatch.setenv("PATH", str(binary_directory))
    calls: list[tuple[str, ...]] = []

    def resolve(request: ProcessRequest) -> ProcessOutput:
        argv, cwd, timeout_seconds = request.argv, request.cwd, request.timeout_seconds
        assert cwd == tmp_path
        assert timeout_seconds == 5
        calls.append(tuple(argv))
        if argv[0] == str(stalled):
            raise subprocess.TimeoutExpired(argv, timeout_seconds)
        if argv[0] == str(mise):
            path = installation if argv[4] == "where" else installed
            return ProcessOutput(0, f"{path}\n", "")
        assert argv == (str(installed), "version", "--short")
        return ProcessOutput(0, f"v{installed_version}\n", "")

    if installed_version == "4.3.1":
        assert (
            checked_tool("helm", root=tmp_path, runner=RequestExecutor(resolve, ProcessCapabilities())).executable
            == installed
        )
    else:
        with pytest.raises(NativeToolError, match=r"exact version 4\.3\.1"):
            checked_tool("helm", root=tmp_path, runner=RequestExecutor(resolve, ProcessCapabilities()))
    reference = "aqua:helm/helm@4.3.1"
    assert calls == [
        (str(stalled), "version", "--short"),
        (str(mise), "--no-config", "--no-env", "--no-hooks", "where", reference),
        (str(mise), "--no-config", "--no-env", "--no-hooks", "which", "--tool", reference, "helm"),
        (str(installed), "version", "--short"),
    ]


@pytest.mark.parametrize(
    "payload", ['{"version":"v5.6.1","extra":true}', '[{"version":"v5.6.1"}]', '{"version":"v5.6.1 v5.6.1"}', "v5.6.1"]
)
def test_compose_ambiguous_version_protocol_is_rejected(tmp_path: Path, payload: str) -> None:
    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        assert argv[0] == "docker"
        assert cwd == tmp_path
        return ProcessOutput(0, payload, "")

    with pytest.raises(NativeToolError, match=r"Compose|exact version"):
        checked_tool("docker", root=tmp_path, runner=FakeProcessExecutor(runner))


def test_unparseable_path_compose_preserves_pinned_mise_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    binary_directory = tmp_path / "bin"
    binary_directory.mkdir()
    suffix = ".exe" if sys.platform == "win32" else ""
    multicall = binary_directory / f"docker{suffix}"
    mise = binary_directory / f"mise{suffix}"
    installation = tmp_path / "installed"
    installation.mkdir()
    installed = installation / f"docker-compose{suffix}"
    for executable in (multicall, mise, installed):
        executable.write_text("native protocol fixture", encoding="utf-8")
        executable.chmod(0o755)
    monkeypatch.setenv("PATH", str(binary_directory))
    calls: list[tuple[str, ...]] = []

    def resolve(request: ProcessRequest) -> ProcessOutput:
        argv, cwd, timeout_seconds = request.argv, request.cwd, request.timeout_seconds
        assert cwd == tmp_path
        assert timeout_seconds == 5
        calls.append(tuple(argv))
        if argv[0] == str(multicall):
            return ProcessOutput(127, "", 'unsupported argv0 "docker-tools"\n')
        if argv[0] == str(mise):
            path = installation if argv[4] == "where" else installed
            return ProcessOutput(0, f"{path}\n", "")
        assert argv == (str(installed), "version", "--format", "json")
        return ProcessOutput(0, '{"version":"v5.6.1"}\n', "")

    tool = checked_tool(
        "docker", root=tmp_path, runner=RequestExecutor(resolve, ProcessCapabilities()), expected_version="5.6.1"
    )
    assert tool.executable == installed
    assert tool.standalone_compose
    reference = "github:docker/compose@5.6.1"
    assert calls == [
        (str(multicall), "compose", "version", "--format", "json"),
        (str(mise), "--no-config", "--no-env", "--no-hooks", "where", reference),
        (str(mise), "--no-config", "--no-env", "--no-hooks", "which", "--tool", reference, "docker-compose"),
        (str(installed), "version", "--format", "json"),
    ]


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


@pytest.mark.parametrize(
    ("name", "relative"),
    [
        ("helm", "helm"),
        ("helm", "bin/helm"),
        ("helm", "darwin-arm64/helm"),
        ("helm", "linux-amd64/helm"),
        ("shellcheck", "shellcheck-v0.11.0/shellcheck"),
    ],
)
def test_mise_resolves_backend_archive_layout_without_installing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str, relative: str
) -> None:
    installation = tmp_path / "installed"
    executable = installation / relative
    executable.parent.mkdir(parents=True)
    executable.write_text("native fixture")
    mise = tmp_path / "bin/mise"
    mise.parent.mkdir()
    mise.write_text("native protocol runner fixture")
    mise.chmod(0o755)
    monkeypatch.setenv("PATH", str(mise.parent))
    calls: list[tuple[str, ...]] = []
    tool = devops_tools.TOOLS[name]
    reference = f"{devops_tools.MISE_REFS[name]}@{tool.version}"

    def resolve(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        assert cwd == tmp_path
        calls.append(tuple(argv))
        if argv[4] == "where":
            return ProcessOutput(0, f"{installation}\n", "")
        assert argv[4:] == ("which", "--tool", reference, name)
        return ProcessOutput(0, f"{executable}\n", "")

    result = devops_tools._mise_tool(tool, root=tmp_path, runner=FakeProcessExecutor(resolve))  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage] -- focused native locator contract, separate from unchanged attestation protocol.
    assert result.executable == executable.resolve()
    assert calls == [
        (str(mise), "--no-config", "--no-env", "--no-hooks", "where", reference),
        (str(mise), "--no-config", "--no-env", "--no-hooks", "which", "--tool", reference, name),
    ]


@pytest.mark.parametrize(
    "case", ["relative", "multiline", "missing", "directory", "escape", "symlink-escape", "failure"]
)
def test_mise_rejects_ambiguous_or_escaping_executable_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    installation = tmp_path / "installed"
    installation.mkdir()
    executable = installation / "helm"
    outside = tmp_path / "outside"
    outside.write_text("native fixture")
    if case == "directory":
        executable.mkdir()
    elif case == "symlink-escape":
        executable.symlink_to(outside)
    elif case != "missing":
        executable.write_text("native fixture")
    payload = f"{executable}\n"
    if case == "relative":
        payload = "installed/helm\n"
    elif case == "multiline":
        payload += f"{outside}\n"
    elif case == "escape":
        payload = f"{outside}\n"
    mise = tmp_path / "bin/mise"
    mise.parent.mkdir()
    mise.write_text("native protocol runner fixture")
    mise.chmod(0o755)
    monkeypatch.setenv("PATH", str(mise.parent))

    def resolve(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        assert cwd == tmp_path
        if argv[4] == "where":
            return ProcessOutput(0, f"{installation}\n", "")
        return ProcessOutput(1 if case == "failure" else 0, payload, "")

    with pytest.raises((OSError, ValueError)):
        devops_tools._mise_tool(devops_tools.TOOLS["helm"], root=tmp_path, runner=FakeProcessExecutor(resolve))  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage] -- malformed native locator protocol must fail closed before attestation.


@pytest.mark.parametrize("managed", [False, True], ids=("runtime", "managed"))
@pytest.mark.parametrize(
    ("name", "stdout", "elapsed", "error"),
    [
        pytest.param("knip", "6.42.1\n", 6, None, id="six-second-exact-knip"),
        pytest.param("knip", "6.42.0\n", 6, "exact version 6.42.1", id="slow-wrong-knip"),
        pytest.param("knip", "6.42.1\n", 16, "timed out after 15", id="knip-exceeds-owned-bound"),
        pytest.param("helm", "v4.3.1\n", 6, "timed out after 5", id="other-tool-keeps-short-bound"),
        pytest.param("docker", '{"version":"v5.6.1"}\n', 6, "timed out after 5", id="compose-keeps-short-bound"),
    ],
)
def test_version_deadline_accepts_slow_knip_without_relaxing_other_native_contracts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    name: str,
    stdout: str,
    elapsed: int,
    error: str | None,
    managed: bool,
) -> None:
    # An aliased Knip gets its semantic budget; a non-Knip named "knip" does not.
    executable = tmp_path / ("renamed-native-launcher" if name == "knip" else "knip")
    executable.write_text("controlled native process fixture", encoding="utf-8")
    executable.chmod(0o755)
    calls: list[tuple[tuple[str, ...], float]] = []

    def which(command: str, *, path: str | None = None) -> str | None:
        assert path is None or sys.executable.startswith(path)
        return str(executable) if command == name else None

    def native_process(request: ProcessRequest) -> ProcessOutput:
        argv, cwd, timeout_seconds = request.argv, request.cwd, request.timeout_seconds
        assert cwd == tmp_path
        calls.append((tuple(argv), timeout_seconds))
        # Model the bounded OS runner, not the attestation's choice of deadline.
        if elapsed > timeout_seconds:
            raise subprocess.TimeoutExpired(argv, timeout_seconds)
        return ProcessOutput(0, stdout, "")

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- model executable discovery for the public managed/runtime attestation boundary.
        "shutil.which", which
    )
    tool = devops_tools.TOOLS[name]
    executor = RequestExecutor(native_process, ProcessCapabilities())

    def attest() -> devops_tools.NativeTool:
        return (
            checked_tool(name, root=tmp_path, runner=executor)
            if managed
            else devops_tools.checked_runtime_tool(tool, root=tmp_path, runner=executor)
        )

    if error is None:
        installed = attest()
        assert installed.executable == executable.resolve()
        assert installed.version == "6.42.1"
    else:
        with pytest.raises(NativeToolError, match=error):
            attest()
    assert calls == [((str(executable), *tool.version_args), 15 if name == "knip" else 5)]


def test_managed_knip_keeps_mise_queries_short_before_attesting_aliased_native_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = tmp_path / "bin"
    directory.mkdir()
    mise = directory / "mise"
    mise.write_text("controlled mise fixture", encoding="utf-8")
    mise.chmod(0o755)
    installation = tmp_path / "installed"
    installation.mkdir()
    executable = installation / "renamed-native-launcher"
    executable.write_text("controlled native fixture", encoding="utf-8")
    executable.chmod(0o755)
    calls: list[tuple[tuple[str, ...], float]] = []

    def which(command: str, *, path: str | None = None) -> str | None:
        assert path is None or sys.executable.startswith(path)
        return str(mise) if command == "mise" else None

    def native_process(request: ProcessRequest) -> ProcessOutput:
        argv, cwd, timeout_seconds = request.argv, request.cwd, request.timeout_seconds
        assert cwd == tmp_path
        calls.append((tuple(argv), timeout_seconds))
        if argv[0] == str(mise):
            target = installation if argv[4] == "where" else executable
            return ProcessOutput(0, f"{target}\n", "")
        if timeout_seconds < 6:
            raise subprocess.TimeoutExpired(argv, timeout_seconds)
        return ProcessOutput(0, "6.42.1\n", "")

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- isolate managed executable lookup from the host environment.
        "shutil.which", which
    )
    executor = RequestExecutor(native_process, ProcessCapabilities())
    result = checked_tool("knip", root=tmp_path, runner=executor)

    assert result.executable == executable.resolve()
    assert calls == [
        ((str(mise), "--no-config", "--no-env", "--no-hooks", "where", "npm:knip@6.42.1"), 5),
        ((str(mise), "--no-config", "--no-env", "--no-hooks", "which", "--tool", "npm:knip@6.42.1", "knip"), 5),
        ((str(executable), "--version"), 15),
    ]
