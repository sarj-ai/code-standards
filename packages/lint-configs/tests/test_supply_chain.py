"""Repository-level invariants that keep package publication fail closed."""

from __future__ import annotations

from pathlib import Path
import re


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


def test_privileged_tag_job_is_dependency_free_and_publish_gated() -> None:
    release = (REPO_ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    tag_job = release.partition("\n  tag:\n")[2]
    assert "egress-policy: block" in tag_job
    assert "persist-credentials: false" in tag_job
    assert "setup-uv" not in tag_job
    assert "uv run" not in tag_job
    assert "repo release create-tags" not in tag_job
    assert "needs.publish-python.result == 'success'" in tag_job
    assert "needs.detect.outputs.python != 'true'" not in tag_job
    assert '[[ "${peeled:-$existing}" == "$GITHUB_SHA" ]]' in tag_job


def test_npm_publishers_have_distinct_identities_and_digest_binding() -> None:
    release = (REPO_ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    assert "environment: npm-release" not in release
    assert "environment: npm-typescript-release" in release
    assert "environment: npm-tsconfig-release" in release
    assert release.count("artifact_sha256:") == 2
    assert release.count("Verify build-bound artifact digest") == 2
    assert "test \"$actual_name\" = '@sarj/tsconfig'" in release


def test_npm_release_disables_install_scripts_and_pins_publisher_cli() -> None:
    release = (REPO_ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    typescript_ci = (REPO_ROOT / ".github/workflows/typescript-ci.yml").read_text(encoding="utf-8")

    assert "npm ci --ignore-scripts" in release
    assert "npm ci --ignore-scripts --no-audit --no-fund" in typescript_ci
    assert release.count("npm install --global npm@11.19.0 --ignore-scripts") == 4
    assert release.count("Install the manifest-declared npm without lifecycle scripts") == 2
