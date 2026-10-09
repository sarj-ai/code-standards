from __future__ import annotations

import ast
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile

import pytest
import yaml

from sarj_standards.libs.release.process import credential_free_environment
from sarj_standards.libs.typed_containers import is_object_list, is_object_mapping


REPO_ROOT = Path(__file__).resolve().parents[3]
ACTION_USE_PATTERN = re.compile(r"^\s*uses:\s+[^\s@]+@[^\s#]+", re.MULTILINE)


def _workflow_job(job_name: str, filename: str = "ci.yml") -> dict[object, object]:
    document: object = yaml.safe_load((REPO_ROOT / ".github/workflows" / filename).read_text())  # pyright: ignore[reportAny] -- narrow workflow YAML at its parser boundary.
    assert is_object_mapping(document)
    jobs = document["jobs"]
    assert is_object_mapping(jobs)
    job = jobs[job_name]
    assert is_object_mapping(job)
    return job


def _ci_steps(job_name: str, filename: str = "ci.yml") -> list[dict[object, object]]:
    job = _workflow_job(job_name, filename)
    steps = job["steps"]
    assert is_object_list(steps)
    assert all(is_object_mapping(step) for step in steps)
    return [dict(step) for step in steps if is_object_mapping(step)]


def _named_step(steps: list[dict[object, object]], name: str) -> dict[object, object]:
    return next(step for step in steps if step.get("name") == name)


def _record_commands(root: Path, *names: str) -> dict[str, str]:
    binaries = root / "bin"
    binaries.mkdir()
    body = (
        f"#!{sys.executable}\n"
        "import json, os, shutil, sys\n"
        "from pathlib import Path\n"
        "name = Path(sys.argv[0]).name\n"
        "record = [name, *sys.argv[1:]]\n"
        "if name == 'sha256sum': record.append(sys.stdin.read())\n"
        "with open(os.environ['COMMAND_LOG'], 'a') as log: log.write(json.dumps(record) + '\\n')\n"
        "if name == 'sha256sum': sys.exit(int(os.environ.get('CHECKSUM_STATUS', '0')))\n"
        "if name == 'tar': shutil.copy2(os.environ['SCANNER'], Path(os.environ['RUNNER_TEMP']) / 'gitleaks')\n"
        "if name == 'curl' and 'HTTP_STATUS' in os.environ:\n"
        "    sys.stdout.write(os.environ['HTTP_STATUS']); sys.exit(int(os.environ.get('CURL_STATUS', '0')))\n"
        "if name == 'uv' and sys.argv[1] == 'venv' and not sys.argv[-1].startswith('-'):\n"
        "    binaries = Path(sys.argv[-1]) / 'bin'; binaries.mkdir(parents=True)\n"
        "    for tool in ('python', 'code-standards', 'sarj-python-lint', 'sarj-sql-lint', 'sarj-iac-lint'):\n"
        "        shutil.copy2(sys.argv[0], binaries / tool)\n"
        "if name == 'code-standards' and 'BOOTSTRAP_CAPTURE' in os.environ:\n"
        "    Path(os.environ['BOOTSTRAP_CAPTURE']).write_text('code-standards\\ncode-standards==1.2.3\\n')\n"
    )
    for name in names:
        executable = binaries / name
        executable.write_text(body)
        executable.chmod(0o755)
    environment = credential_free_environment()
    environment.update(
        PATH=str(binaries) + os.pathsep + environment.get("PATH", os.defpath),
        RUNNER_TEMP=str(root),
        COMMAND_LOG=str(root / "commands.jsonl"),
        SCANNER=str(binaries / "gitleaks"),
    )
    scripts = root / ".github/scripts"
    scripts.parent.mkdir()
    scripts.symlink_to(REPO_ROOT / ".github/scripts", target_is_directory=True)
    return environment


def _run_ci_step(
    step: dict[object, object], *, root: Path, environment: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    command = step["run"]
    assert isinstance(command, str)
    return subprocess.run(
        ("bash", "-e", "-c", command),
        cwd=root,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )


def _recorded_commands(root: Path) -> list[list[str]]:
    commands: list[list[str]] = []
    for line in (root / "commands.jsonl").read_text().splitlines():
        value: object = json.loads(line)  # pyright: ignore[reportAny] -- narrow test command records immediately.
        assert is_object_list(value)
        assert all(isinstance(argument, str) for argument in value)
        commands.append([argument for argument in value if isinstance(argument, str)])
    return commands


def test_every_setup_uv_step_pins_the_uv_binary() -> None:
    workflows = sorted((REPO_ROOT / ".github/workflows").glob("*.yml"))
    violations: list[str] = []
    for workflow in workflows:
        text = workflow.read_text(encoding="utf-8")
        for match in re.finditer(r"(?m)^\s*- uses: astral-sh/setup-uv@[^\n]+$", text):
            following = text[match.end() :].split("\n      - ", 1)[0]
            if "version: '0.12.24'" not in following:
                violations.append(f"setup-uv does not pin uv 0.12.24 in {workflow}")
    assert violations == []


def test_read_only_workflows_do_not_persist_checkout_credentials() -> None:
    workflows = sorted((REPO_ROOT / ".github/workflows").glob("*.yml"))
    violations: list[str] = []
    for workflow in workflows:
        if workflow.name == "release-tags.yml":
            continue
        text = workflow.read_text(encoding="utf-8")
        for match in re.finditer(r"(?m)^\s*- (?:name: [^\n]+\n\s+)?uses: actions/checkout@[^\n]+$", text):
            following = text[match.end() :].split("\n      - ", 1)[0]
            if "persist-credentials: false" not in following:
                violations.append(f"checkout persists credentials in {workflow}: {match[0]}")
    assert violations == []


def test_every_job_starts_with_harden_runner() -> None:
    workflows = sorted((REPO_ROOT / ".github/workflows").glob("*.yml"))
    violations: list[str] = []
    job_count = 0
    for workflow in workflows:
        text = workflow.read_text(encoding="utf-8")
        job_blocks = re.split(r"(?m)^  [a-zA-Z0-9_-]+:\n", text.partition("\njobs:\n")[2])[1:]
        for block in job_blocks:
            job_count += 1
            first_use = ACTION_USE_PATTERN.search(block)
            if first_use is None or "step-security/harden-runner@" not in first_use[0]:
                violations.append(f"Harden Runner is not first in {workflow}")
    assert job_count > 0
    assert violations == []


def test_release_has_no_manual_or_tag_publish_bypass() -> None:
    release = (REPO_ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    trigger = release.partition("\npermissions:\n")[0]
    assert "workflow_dispatch" not in trigger
    assert "tags:" not in trigger
    assert "branches: [main]" in trigger
    assert (
        re.search(r"(?m)^\s+path: .*dist/\*\s*$", release) is None
    )  # sarj-noqa: SARJ402 -- workflow text is the artifact-path contract
    assert "pypa/gh-action-pypi-publish@" in release  # sarj-noqa: SARJ402 -- workflow text is the publisher contract


def test_standards_release_builds_the_legacy_distribution_bridge(tmp_path: Path) -> None:
    environment = _record_commands(tmp_path, "uv")
    workdir = tmp_path / "packages/standards"
    workdir.mkdir(parents=True)
    build = _named_step(_ci_steps("build-standards", "release.yml"), "Build package and exact local dependency wheels")
    result = _run_ci_step(build, root=workdir, environment=environment)
    assert result.returncode == 0, result.stderr
    assert _recorded_commands(tmp_path) == [
        ["uv", "build"],
        ["uv", "build", "--project", "../standards-compat", "--out-dir", "dist"],
        *[
            ["uv", "build", "--wheel", "--project", f"../{dependency}", "--out-dir", "dist/deps"]
            for dependency in ("contracts", "python", "sql", "iac")
        ],
    ]


def test_release_waits_for_exact_revision_safety_checks() -> None:
    release = (REPO_ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")

    assert "\n  release-safety:\n" in release  # sarj-noqa: SARJ402 -- workflow text is the release-policy contract
    assert (
        "release-safety:\n    needs: detect\n" in release
    )  # sarj-noqa: SARJ402 -- workflow text is the release-policy contract
    release_safety = release.partition("\n  release-safety:\n")[2].partition("\n  detect:\n")[0]
    for package in ("typescript", "bootstrap", "contracts", "python", "sql", "iac", "standards", "tsconfig"):
        assert (
            f"needs.detect.outputs.{package} == 'true'" in release_safety
        )  # sarj-noqa: SARJ402 -- workflow text is the release-gate contract
    assert "actions: read" in release  # sarj-noqa: SARJ402 -- workflow text is the release-gate contract
    for package in ("typescript", "bootstrap", "contracts", "python", "sql", "iac", "standards", "tsconfig"):
        publisher = re.search(rf"(?ms)^  publish-{package}:\n.*?(?=^  [a-zA-Z0-9_-]+:\n|\Z)", release)
        assert publisher is not None
        assert (  # sarj-noqa: SARJ402 -- exact-revision safety now gates every publisher
            "release-safety" in publisher[0]
        )
        assert (  # sarj-noqa: SARJ402 -- a failed exact-revision check must prevent publication
            "needs.release-safety.result == 'success'" in publisher[0]
        )
        assert (  # sarj-noqa: SARJ402 -- publication must retain successful artifact verification
            f"needs.build-{package}.result == 'success'" in publisher[0]
        )
    for package in ("python", "sql", "iac"):
        job = re.search(rf"(?ms)^  build-{package}:\n.*?(?=^  [a-zA-Z0-9_-]+:\n|\Z)", release)
        assert job is not None
        assert (  # sarj-noqa: SARJ402 -- workflow text is the core publication gate contract
            "needs: [detect, publish-contracts]" in job[0]
        )
        assert (  # sarj-noqa: SARJ402 -- workflow text is the core publication gate contract
            "needs.publish-contracts.result == 'success' || needs.publish-contracts.result == 'skipped'" in job[0]
        )


def test_typescript_release_does_not_emit_source_maps() -> None:
    config = (REPO_ROOT / "packages/typescript/tsup.config.ts").read_text(encoding="utf-8")
    assert "sourcemap: false" in config  # sarj-noqa: SARJ402 -- build config text is the packaging-policy contract


def test_typescript_prepack_builds_clean_source_before_verifying_exports() -> None:
    manifest = (REPO_ROOT / "packages/typescript/package.json").read_text(encoding="utf-8")
    assert (  # sarj-noqa: SARJ402 -- manifest text is the packaging-policy contract
        '"prepack": "npm run build && npm run verify-package"' in manifest
    )


def test_release_has_no_tag_writer_or_write_capable_token() -> None:
    release = (REPO_ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    assert "\n  tag:\n" not in release  # sarj-noqa: SARJ402 -- workflow text is the release-policy contract
    assert "contents: write" not in release  # sarj-noqa: SARJ402 -- workflow text is the release-policy contract
    assert "git push" not in release  # sarj-noqa: SARJ402 -- workflow text is the release-policy contract


@pytest.mark.parametrize("status", ["200", "404", "403"])
def test_release_tags_publish_a_github_release_for_new_standards_versions(tmp_path: Path, status: str) -> None:
    environment = _record_commands(tmp_path, "curl", "gh")
    environment.update(
        HTTP_STATUS=status,
        STANDARDS_TAG="standards-v1.2.3",
        GH_TOKEN="test-token",
        GITHUB_API_URL="https://api.github.invalid",
        GITHUB_REPOSITORY="example/repo",
    )
    step = _named_step(_ci_steps("tag", "release-tags.yml"), "Publish the Standards GitHub Release")
    result = _run_ci_step(step, root=tmp_path, environment=environment)
    assert result.returncode == (1 if status == "403" else 0), result.stderr
    calls = _recorded_commands(tmp_path)
    assert calls[0][-1] == "https://api.github.invalid/repos/example/repo/releases/tags/standards-v1.2.3"
    if status == "404":
        assert calls[1:] == [
            [
                "gh",
                "release",
                "create",
                "standards-v1.2.3",
                "--verify-tag",
                "--generate-notes",
                "--title",
                "Standards 1.2.3",
            ]
        ]
    else:
        assert len(calls) == 1


def test_publishers_have_distinct_identities_and_digest_binding() -> None:
    release = (REPO_ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    assert (  # sarj-noqa: SARJ402 -- workflow text is the release-policy contract
        "environment: npm-release" not in release
    )
    assert (
        "environment: npm-typescript-release" in release
    )  # sarj-noqa: SARJ402 -- workflow text is the publisher-identity contract
    assert (
        "environment: npm-tsconfig-release" in release
    )  # sarj-noqa: SARJ402 -- workflow text is the publisher-identity contract
    assert (
        "environment: pypi-bootstrap-release" in release
    )  # sarj-noqa: SARJ402 -- workflow text is the publisher-identity contract
    assert (
        release.count("artifact_sha256:") == 8
    )  # sarj-noqa: SARJ402 -- workflow text is the artifact-integrity contract
    assert (
        release.count("Verify build-bound artifact digest") == 8
    )  # sarj-noqa: SARJ402 -- workflow text is the artifact-integrity contract
    assert (
        release.count("Publish and verify registry bytes and source-bound provenance") == 2
    )  # sarj-noqa: SARJ402 -- workflow text is the artifact-integrity contract
    verifier = (  # sarj-noqa: SARJ402 -- verifier text is the pinned supply-chain contract
        REPO_ROOT / ".github/scripts/verify_registry_publication.py"
    ).read_text(encoding="utf-8")
    assert (  # sarj-noqa: SARJ402 -- verifier text is the pinned supply-chain contract
        'entry.get("predicateType") != "https://slsa.dev/provenance/v1"' in verifier
    )
    for stage_timeout in (
        "NPM_METADATA_TIMEOUT = timedelta(minutes=15)",
        "NPM_PROVENANCE_TIMEOUT = timedelta(minutes=10)",
        "NPM_INSTALL_TIMEOUT = timedelta(minutes=10)",
    ):
        assert stage_timeout in verifier  # sarj-noqa: SARJ402 -- verifier text is the pinned retry contract


@pytest.mark.parametrize(
    ("name", "version", "valid"),
    [
        ("@sarj/tsconfig", "1.2.3", True),
        ("other", "1.2.3", False),
        ("@sarj/tsconfig", "9.9.9", False),
        ("@sarj/tsconfig", 123, False),
    ],
)
def test_tsconfig_artifact_identity_matches_the_current_manifest(
    tmp_path: Path, name: str, version: str | int, valid: bool
) -> None:
    environment = _record_commands(tmp_path, "uv")
    workdir = tmp_path / "packages/tsconfig"
    workdir.mkdir(parents=True)
    (workdir / "package.json").write_text(json.dumps({"version": "1.2.3"}), encoding="utf-8")
    artifact = tmp_path / "npm-artifacts/package.tgz"
    artifact.parent.mkdir()
    manifest = json.dumps({"name": name, "version": version}).encode()
    with tarfile.open(artifact, "w:gz") as archive:
        member = tarfile.TarInfo("package/package.json")
        member.size = len(manifest)
        archive.addfile(member, io.BytesIO(manifest))
    output = tmp_path / "github-output"
    environment["GITHUB_OUTPUT"] = str(output)
    step = _named_step(_ci_steps("build-tsconfig", "release.yml"), "Verify artifact identity and bind digest")
    result = _run_ci_step(step, root=workdir, environment=environment)
    assert (result.returncode == 0) is valid, result.stderr
    if valid:
        assert output.read_text() == f"sha256={hashlib.sha256(artifact.read_bytes()).hexdigest()}\n"
    else:
        assert not output.exists()


def test_registry_verifier_parses_on_release_runner_python() -> None:
    verifier = (REPO_ROOT / ".github/scripts/verify_registry_publication.py").read_text(encoding="utf-8")

    ast.parse(verifier, feature_version=(3, 12))


@pytest.mark.parametrize("checksum_status", [0, 1], ids=["verified", "mismatch"])
def test_security_workflow_scans_tree_and_history_with_pinned_gitleaks(tmp_path: Path, checksum_status: int) -> None:
    steps = _ci_steps("gitleaks")
    checkout_index, checkout = next(
        (index, step) for index, step in enumerate(steps) if str(step.get("uses", "")).startswith("actions/checkout@")
    )
    options = checkout["with"]
    assert is_object_mapping(options)
    assert options["fetch-depth"] == 0
    assert options["persist-credentials"] is False
    execution = [(index, step) for index, step in enumerate(steps) if "run" in step]
    assert execution
    assert all(index > checkout_index for index, _ in execution)
    environment = _record_commands(tmp_path, "curl", "sha256sum", "tar", "gitleaks")
    environment["CHECKSUM_STATUS"] = str(checksum_status)
    result = _run_ci_step(execution[0][1], root=tmp_path, environment=environment)
    for _, step in execution[1:]:
        if result.returncode:
            break
        result = _run_ci_step(step, root=tmp_path, environment=environment)
    assert result.returncode == checksum_status
    expected = [
        [
            "curl",
            "--fail",
            "--location",
            "--silent",
            "--show-error",
            "--output",
            str(tmp_path / "gitleaks.tar.gz"),
            "https://github.com/gitleaks/gitleaks/releases/download/v8.30.1/gitleaks_8.30.1_linux_x64.tar.gz",
        ],
        [
            "sha256sum",
            "--check",
            "--strict",
            f"551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb  {tmp_path / 'gitleaks.tar.gz'}\n",
        ],
    ]
    if checksum_status == 0:
        expected.extend(
            [
                ["tar", "-xzf", str(tmp_path / "gitleaks.tar.gz"), "-C", str(tmp_path), "gitleaks"],
                ["gitleaks", "dir", ".", "--config", ".gitleaks.toml", "--redact", "--no-banner"],
                ["gitleaks", "git", "--config", ".gitleaks.toml", "--redact", "--no-banner", "--log-opts=--all"],
            ]
        )
    assert _recorded_commands(tmp_path) == expected


@pytest.mark.parametrize("package", ["bootstrap", "contracts", "python", "sql", "iac", "standards"])
@pytest.mark.parametrize("tampered", [None, "SHA256SUMS", "example.whl", "example.tar.gz"])
def test_pypi_publishers_exclude_checksum_manifests(tmp_path: Path, package: str, tampered: str | None) -> None:
    environment = _record_commands(tmp_path, "uv")
    # The runner uses GNU sha256sum; shasum supplies the same check/strict ABI on macOS too.
    checksum = tmp_path / "bin/sha256sum"
    checksum.write_text('#!/bin/sh\nexec shasum -a 256 "$@"\n', encoding="utf-8")
    checksum.chmod(0o755)
    workdir = tmp_path / "packages" / package
    dist = workdir / "dist"
    dist.mkdir(parents=True)
    for name in ("example.whl", "example.tar.gz"):
        (dist / name).write_text("verified artifact")
    output = tmp_path / "github-output"
    environment["GITHUB_OUTPUT"] = str(output)
    bind = _named_step(_ci_steps(f"build-{package}", "release.yml"), "Bind artifact digest to the build job")
    result = _run_ci_step(bind, root=workdir, environment=environment)
    assert result.returncode == 0, result.stderr
    environment["EXPECTED_SHA256"] = output.read_text().strip().removeprefix("sha256=")
    verified = tmp_path / "verified-dist"
    shutil.copytree(dist, verified)
    if tampered is not None:
        (verified / tampered).write_text("tampered")
    steps = _ci_steps(f"publish-{package}", "release.yml")
    verify = _named_step(steps, "Verify build-bound artifact digest")
    assert verify["env"] == {"EXPECTED_SHA256": f"${{{{ needs.build-{package}.outputs.artifact_sha256 }}}}"}
    stage = _named_step(steps, "Stage verified distributions for publication")
    result = _run_ci_step(verify, root=tmp_path, environment=environment)
    if result.returncode == 0:
        result = _run_ci_step(stage, root=tmp_path, environment=environment)
    assert (result.returncode == 0) is (tampered is None), result.stderr
    staged = tmp_path / "publish-dist"
    if tampered is None:
        assert {path.name for path in staged.iterdir()} == {"example.whl", "example.tar.gz"}
    else:
        assert not staged.exists()
    publisher = next(step for step in steps if str(step.get("uses", "")).startswith("pypa/gh-action-pypi-publish@"))
    options = publisher["with"]
    assert is_object_mapping(options)
    assert options["packages-dir"] == "publish-dist/"


def test_npm_release_disables_install_scripts_and_keeps_publishers_dependency_free(tmp_path: Path) -> None:
    release = (REPO_ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    ci = (REPO_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    typescript_job = re.search(r"(?ms)^  typescript:\n.*?(?=^  [a-zA-Z0-9_-]+:\n|\Z)", ci)
    assert typescript_job is not None
    typescript_ci = typescript_job[0]

    assert "npm ci --ignore-scripts" in release  # sarj-noqa: SARJ402 -- workflow text is the publishing-policy contract
    environment = _record_commands(tmp_path, "npm")
    workdir = tmp_path / "packages/tsconfig"
    workdir.mkdir(parents=True)
    pack = _named_step(_ci_steps("build-tsconfig", "release.yml"), "Pack publishable artifact")
    result = _run_ci_step(pack, root=workdir, environment=environment)
    assert result.returncode == 0, result.stderr
    assert _recorded_commands(tmp_path) == [
        ["npm", "pack", "--pack-destination", str(tmp_path / "npm-artifacts"), "--ignore-scripts"]
    ]
    assert (  # sarj-noqa: SARJ402 -- workflow text is the publishing-policy contract
        "npm ci --ignore-scripts --no-audit --no-fund" in typescript_ci
    )
    assert (
        release.count("npm install --global npm@12.1.0 --ignore-scripts") == 2
    )  # sarj-noqa: SARJ402 -- workflow text is the publishing-policy contract

    def assert_dependency_free(job: str) -> None:
        match = re.search(rf"(?ms)^  {job}:\n.*?(?=^  [a-zA-Z0-9_-]+:\n|\Z)", release)
        assert match is not None
        publisher = match[0]
        assert "npm install" not in publisher
        assert "npm ci" not in publisher

    assert_dependency_free("publish-typescript")
    assert_dependency_free("publish-tsconfig")


def test_every_workflow_job_has_a_timeout() -> None:
    workflows = sorted((REPO_ROOT / ".github/workflows").glob("*.yml"))
    violations: list[str] = []
    for workflow in workflows:
        text = workflow.read_text(encoding="utf-8")
        job_blocks = re.split(r"(?m)^  [a-zA-Z0-9_-]+:\n", text.partition("\njobs:\n")[2])[1:]
        for index, block in enumerate(job_blocks, start=1):
            header = block.partition("\n    steps:\n")[0]
            if "timeout-minutes:" not in header:
                violations.append(f"job {index} in {workflow} has no timeout")
    assert violations == []


def test_release_ready_is_one_stable_required_gate(tmp_path: Path) -> None:
    workflow = (REPO_ROOT / ".github/workflows/repo-ci.yml").read_text(encoding="utf-8")

    assert (  # sarj-noqa: SARJ402 -- workflow text is the required-check contract
        workflow.startswith("name: release-ready\n")
    )
    assert "\n  release-ready:\n" in workflow  # sarj-noqa: SARJ402 -- workflow text is the required-check contract
    assert "make verify" not in workflow  # sarj-noqa: SARJ402 -- workflow text is the required-check contract
    assert "make build" not in workflow  # sarj-noqa: SARJ402 -- workflow text is the required-check contract
    assert (
        "Cross-package repository policy" in workflow
    )  # sarj-noqa: SARJ402 -- workflow text is the required-check contract
    assert (
        "packages/standards --locked --dev" in workflow
    )  # sarj-noqa: SARJ402 -- workflow text is the required-check contract
    assert "cancel-in-progress: true" in workflow  # sarj-noqa: SARJ402 -- workflow text is the required-check contract
    steps = _ci_steps("tsconfig")
    node_index, node = next(
        (index, step) for index, step in enumerate(steps) if str(step.get("uses", "")).startswith("actions/setup-node@")
    )
    assert node["with"] == {"node-version": "24"}
    environment = _record_commands(tmp_path, "npm", "tsc")
    workdir = tmp_path / "packages/tsconfig"
    compiler = workdir / "node_modules/.bin/tsc"
    compiler.parent.mkdir(parents=True)
    compiler.symlink_to(tmp_path / "bin/tsc")
    smoke_index, smoke = next(
        (index, step)
        for index, step in enumerate(steps)
        if step.get("name") == "Smoke test — extend strict.json against a sample"
    )
    assert node_index < smoke_index
    result = _run_ci_step(smoke, root=workdir, environment=environment)
    assert result.returncode == 0, result.stderr
    assert _recorded_commands(tmp_path) == [
        ["npm", "install", "--ignore-scripts", "--no-audit", "--no-fund", "--save-dev", "typescript@7.0.2"],
        ["tsc", "--noEmit", "-p", "tsconfig.json"],
    ]


def test_warning_first_gate_prints_an_executable_command_for_each_rule() -> None:
    workflow = (REPO_ROOT / ".github/workflows/repo-ci.yml").read_text(encoding="utf-8")

    assert (  # sarj-noqa: SARJ402 -- workflow text is the author contract
        "maintain rules changes" in workflow
    )
    assert (  # sarj-noqa: SARJ402 -- exact remediation is the contract
        "--require-added-level warning" in workflow
    )
    assert "jq -r" not in workflow  # sarj-noqa: SARJ402 -- exact remediation shape is the author contract


def test_parallel_package_workflows_are_always_present_with_stable_contexts() -> None:
    workflow = (REPO_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    trigger = workflow.partition("\npermissions:\n")[0]
    assert "paths:" not in trigger
    for job_name in (
        "bootstrap package",
        "python package",
        "typescript plugin (${{ matrix.node }})",
        "sql package",
        "iac package",
        "tsconfig package",
        "standards package",
    ):
        assert (
            f"name: {job_name}" in workflow
        )  # sarj-noqa: SARJ402 -- exact required check names are the merge contract


def test_standards_package_dogfoods_full_scope_on_pull_requests_and_pushes() -> None:
    workflow = (REPO_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert (  # sarj-noqa: SARJ402 -- explicit root is the PR and push scope parity contract
        "uv run code-standards --root ../.. check --jobs 2 ." in workflow
    )


def test_pre_push_keeps_complete_tests_in_ci() -> None:
    lefthook = (REPO_ROOT / "lefthook.yml").read_text(encoding="utf-8")
    pre_push = lefthook.partition("\npre-push:\n")[2]
    assert "run: make lint" in pre_push
    assert "make verify" not in pre_push


def test_documentation_deploy_is_revision_bound_self_verifying_and_single_site() -> None:
    workflow = (REPO_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    verifier = (REPO_ROOT / "apps/docs/scripts/verify-deployment.mjs").read_text(encoding="utf-8")

    assert "branches: [main]" in workflow  # sarj-noqa: SARJ402 -- workflow text is the deployment-policy contract
    assert (
        "github.event_name == 'push' || github.event_name == 'workflow_dispatch'" in workflow
    )  # sarj-noqa: SARJ402 -- workflow text is the deployment-policy contract
    assert (
        "WORKERS_CI_COMMIT_SHA: ${{ github.sha }}" in workflow
    )  # sarj-noqa: SARJ402 -- workflow text is the deployment-policy contract
    assert (
        "Verify production credentials" in workflow
    )  # sarj-noqa: SARJ402 -- workflow text is the deployment-policy contract
    assert (
        "actions/upload-artifact@" in workflow
    )  # sarj-noqa: SARJ402 -- workflow text is the deployment-policy contract
    assert (
        "actions/download-artifact@" in workflow
    )  # sarj-noqa: SARJ402 -- workflow text is the deployment-policy contract
    assert (
        "Verify deployed revision" in workflow
    )  # sarj-noqa: SARJ402 -- workflow text is the deployment-policy contract
    assert "npm run verify:deployment" in workflow  # sarj-noqa: SARJ402 -- deployment-policy contract
    assert "name: docs-ui-site" not in workflow  # sarj-noqa: SARJ402 -- standalone repository owns this deployment
    assert "Deploy documentation UI first" not in workflow  # sarj-noqa: SARJ402 -- prevent competing production writers
    assert "assert.equal(health.commit, expectedCommit" in verifier  # sarj-noqa: SARJ402 -- deployment contract
    assert "health.catalogSha256" in verifier  # sarj-noqa: SARJ402 -- deployment-policy contract
    assert "pagefind/pagefind.js" in verifier  # sarj-noqa: SARJ402 -- deployment-policy contract
    assert "wasm-unsafe-eval" in verifier  # sarj-noqa: SARJ402 -- deployment-policy contract


@pytest.mark.parametrize(
    ("package", "module", "executable"),
    [
        ("bootstrap", "sarj_standards_bootstrap", "code-standards"),
        ("contracts", "sarj_rule_contracts", None),
        ("python", "sarj_python_lint", "sarj-python-lint"),
        ("sql", "sarj_sql_lint", "sarj-sql-lint"),
        ("iac", "sarj_iac_lint", "sarj-iac-lint"),
    ],
)
@pytest.mark.parametrize("runtime", ["3.14", "3.15"])
def test_python_publishers_smoke_and_bind_wheels_and_sdists(
    tmp_path: Path, package: str, module: str, executable: str | None, runtime: str
) -> None:
    environment = _record_commands(tmp_path, "uv")
    environment["GITHUB_WORKSPACE"] = str(tmp_path)
    environment["STANDARDS_PYTHON"] = runtime
    workdir = tmp_path / "packages" / package
    dist = workdir / "dist"
    dist.mkdir(parents=True)
    for name in ("example.whl", "example.tar.gz"):
        (dist / name).write_text("artifact")
    steps = _ci_steps(f"build-{package}", "release.yml")
    for label in ("Smoke test the exact wheel", "Smoke test the source distribution"):
        step = _named_step(steps, label)
        result = _run_ci_step(step, root=workdir, environment=environment)
        assert result.returncode == 0, result.stderr
    calls = _recorded_commands(tmp_path)
    for format_name, suffix in (("wheel", "whl"), ("sdist", "tar.gz")):
        venv = str(tmp_path / f"{package}-{format_name}")
        assert ["uv", "venv", "--python", runtime, venv] in calls
        assert ["uv", "pip", "install", "--python", venv + "/bin/python", f"dist/example.{suffix}"] in calls
    imports = [call for call in calls if call[0] == "python"]
    assert [call[-1] for call in imports] == [module] * (2 if package == "contracts" else 1)
    if executable is not None:
        cli_calls = [call for call in calls if call[0] == executable]
        expected_args = ["--root", str(tmp_path), "check"] if package == "bootstrap" else ["--help"]
        assert cli_calls == [[executable, *expected_args]] * 2


@pytest.mark.parametrize("package", ["typescript", "tsconfig"])
@pytest.mark.parametrize("state", ["intact", "tampered", "missing"])
def test_npm_publishers_verify_the_build_bound_tarball(tmp_path: Path, package: str, state: str) -> None:
    environment = _record_commands(tmp_path, "uv")
    checksum = tmp_path / "bin/sha256sum"
    checksum.write_text('#!/bin/sh\nexec shasum -a 256 "$@"\n', encoding="utf-8")
    checksum.chmod(0o755)
    workdir = tmp_path / "packages" / package
    workdir.mkdir(parents=True)
    (workdir / "package.json").write_text(json.dumps({"version": "1.2.3"}), encoding="utf-8")
    artifact = tmp_path / "npm-artifacts/package.tgz"
    artifact.parent.mkdir()
    name = "@sarj/tsconfig" if package == "tsconfig" else "@sarj/eslint-plugin"
    manifest = json.dumps({"name": name, "version": "1.2.3"}).encode()
    with tarfile.open(artifact, "w:gz") as archive:
        member = tarfile.TarInfo("package/package.json")
        member.size = len(manifest)
        archive.addfile(member, io.BytesIO(manifest))
    output = tmp_path / "github-output"
    environment["GITHUB_OUTPUT"] = str(output)
    label = (
        "Verify artifact identity and bind digest" if package == "tsconfig" else "Bind artifact digest to the build job"
    )
    bind = _named_step(_ci_steps(f"build-{package}", "release.yml"), label)
    result = _run_ci_step(bind, root=workdir, environment=environment)
    assert result.returncode == 0, result.stderr
    expected = hashlib.sha256(artifact.read_bytes()).hexdigest()
    assert output.read_text() == f"sha256={expected}\n"
    environment["EXPECTED_SHA256"] = expected
    if state == "tampered":
        artifact.write_bytes(artifact.read_bytes() + b"tampered")
    elif state == "missing":
        artifact.unlink()
    assert not (tmp_path / "verified-dist").exists()
    verify = _named_step(_ci_steps(f"publish-{package}", "release.yml"), "Verify build-bound artifact digest")
    assert verify["env"] == {"EXPECTED_SHA256": f"${{{{ needs.build-{package}.outputs.artifact_sha256 }}}}"}
    result = _run_ci_step(verify, root=tmp_path, environment=environment)
    assert (result.returncode == 0) is (state == "intact"), result.stderr
    if state == "intact":
        assert "package.tgz: OK" in result.stdout
    else:
        assert "package.tgz: FAILED" in result.stdout
