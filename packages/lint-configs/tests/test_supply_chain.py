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
