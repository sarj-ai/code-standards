"""Repository-level invariants that keep package publication fail closed."""

from __future__ import annotations

from pathlib import Path
import re

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
FULL_SHA_USE = re.compile(r"^\s*uses:\s+[^\s@]+@(?P<ref>[^\s#]+)", re.MULTILINE)


def test_every_action_is_pinned_to_a_full_commit_sha() -> None:
    workflows = sorted((REPO_ROOT / ".github/workflows").glob("*.yml"))
    violations: list[str] = []
    action_count = 0
    for workflow in workflows:
        text = workflow.read_text(encoding="utf-8")
        for match in FULL_SHA_USE.finditer(text):
            action_count += 1
            if re.fullmatch(r"[0-9a-f]{40}", match["ref"]) is None:
                violations.append(f"mutable action ref in {workflow}: {match[0]}")
    assert action_count > 0
    assert violations == []


def test_every_setup_uv_step_pins_the_uv_binary() -> None:
    workflows = sorted((REPO_ROOT / ".github/workflows").glob("*.yml"))
    violations: list[str] = []
    for workflow in workflows:
        text = workflow.read_text(encoding="utf-8")
        for match in re.finditer(r"(?m)^\s*- uses: astral-sh/setup-uv@[^\n]+$", text):
            following = text[match.end() :].split("\n      - ", 1)[0]
            if "version: '0.11.32'" not in following:
                violations.append(f"setup-uv does not pin uv 0.11.32 in {workflow}")
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
            first_use = FULL_SHA_USE.search(block)
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
    assert "--sdist" not in release
    assert re.search(r"(?m)^\s+path: .*dist/\*\s*$", release) is None
    assert "pypa/gh-action-pypi-publish@" in release


def test_typescript_release_does_not_emit_source_maps() -> None:
    config = (REPO_ROOT / "packages/typescript/tsup.config.ts").read_text(encoding="utf-8")
    assert "sourcemap: false" in config


def test_typescript_prepack_verifies_without_rebuilding_tested_output() -> None:
    manifest = (REPO_ROOT / "packages/typescript/package.json").read_text(encoding="utf-8")
    assert '"prepack": "npm run verify-package"' in manifest
    assert '"prepack": "npm run build' not in manifest


def test_release_has_no_tag_writer_or_write_capable_token() -> None:
    release = (REPO_ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    assert "\n  tag:\n" not in release
    assert "contents: write" not in release
    assert "git push" not in release


def test_publishers_have_distinct_identities_and_digest_binding() -> None:
    release = (REPO_ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    assert "environment: npm-release" not in release
    assert "environment: npm-typescript-release" in release
    assert "environment: npm-tsconfig-release" in release
    assert release.count("artifact_sha256:") == 6
    assert release.count("Verify build-bound artifact digest") == 6
    assert "test \"$actual_name\" = '@sarj/tsconfig'" in release


def test_npm_release_disables_install_scripts_and_keeps_publishers_dependency_free() -> None:
    release = (REPO_ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    typescript_ci = (REPO_ROOT / ".github/workflows/typescript-ci.yml").read_text(encoding="utf-8")

    assert "npm ci --ignore-scripts" in release
    assert 'npm pack --pack-destination "$RUNNER_TEMP/npm-artifacts" --ignore-scripts' in release
    assert "npm ci --ignore-scripts --no-audit --no-fund" in typescript_ci
    assert release.count("npm install --global npm@11.19.0 --ignore-scripts") == 2

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


def test_release_ready_is_one_stable_required_gate() -> None:
    workflow = (REPO_ROOT / ".github/workflows/repo-ci.yml").read_text(encoding="utf-8")
    assert workflow.startswith("name: release-ready\n")
    assert "\n  release-ready:\n" in workflow
    assert "make verify" in workflow
    assert "make build" in workflow


@pytest.mark.parametrize(
    ("package", "module", "executable"),
    [
        ("python", "sarj_python_lint", "sarj-python-lint"),
        ("sql", "sarj_sql_lint", "sarj-sql-lint"),
        ("iac", "sarj_iac_lint", "sarj-iac-lint"),
    ],
)
def test_python_publishers_smoke_and_bind_the_exact_wheels(
    package: str,
    module: str,
    executable: str,
) -> None:
    release = (REPO_ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    assert f'uv pip install --python "$RUNNER_TEMP/{package}-wheel/bin/python" dist/*.whl' in release
    assert f"import {module}" in release
    assert f'bin/{executable}" --help' in release
    assert release.count("wheels=(publish-dist/*.whl)") == 4
    assert "sarj_standards-*.whl pytest==9.1.1 ruff" in release
