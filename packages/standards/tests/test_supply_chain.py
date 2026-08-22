from __future__ import annotations

import ast
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
            if "version: '0.12.5'" not in following:
                violations.append(f"setup-uv does not pin uv 0.12.5 in {workflow}")
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
    assert release.count("uv build\n") == 5  # sarj-noqa: SARJ402 -- workflow text is the release-policy contract
    assert release.count("*.tar.gz") >= 8
    assert re.search(r"(?m)^\s+path: .*dist/\*\s*$", release) is None
    assert "pypa/gh-action-pypi-publish@" in release


def test_standards_release_builds_the_legacy_distribution_bridge() -> None:
    release = (REPO_ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")

    assert (  # sarj-noqa: SARJ402 -- workflow text is the release-policy contract
        "uv build --project ../standards-compat --out-dir dist" in release
    )
    assert (
        "./dist/code_standards-*.whl" in release
    )  # sarj-noqa: SARJ402 -- workflow text is the release-policy contract


def test_release_waits_for_exact_revision_safety_checks() -> None:
    release = (REPO_ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")

    assert "\n  release-safety:\n" in release  # sarj-noqa: SARJ402 -- workflow text is the release-policy contract
    assert "release-safety:\n    needs: detect\n" in release
    release_safety = release.partition("\n  release-safety:\n")[2].partition("\n  detect:\n")[0]
    for package in ("typescript", "bootstrap", "python", "sql", "iac", "standards", "tsconfig"):
        assert f"needs.detect.outputs.{package} == 'true'" in release_safety
    assert "actions: read" in release
    for specification in (
        "repo-ci.yml|release-ready",
        "private-refs.yml|private references",
        "bootstrap-ci.yml|bootstrap CI",
        "python-ci.yml|python CI",
        "typescript-ci.yml|typescript CI",
        "sql-ci.yml|sql CI",
        "iac-ci.yml|iac CI",
        "tsconfig-ci.yml|tsconfig CI",
        "standards-ci.yml|standards CI",
    ):
        assert specification in release
    assert "head_sha == $sha" in release
    assert "head_repository.full_name == $repo" in release
    assert '.event == "push"' in release
    assert "actions/runs/$run_id/jobs" in release
    assert "pending_jobs == 0 && successful_jobs > 0" in release
    assert "timed out waiting for $expected_name" in release
    assert release.count("needs: [detect, release-safety]") == 7
    assert "needs.release-safety.result == 'success'" in release


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
    assert "contents: write" not in release
    assert "git push" not in release


def test_release_tags_publish_a_github_release_for_new_standards_versions() -> None:
    workflow = (REPO_ROOT / ".github/workflows/release-tags.yml").read_text(encoding="utf-8")

    assert (  # sarj-noqa: SARJ402 -- workflow text is the release-policy contract
        "standards_tag: ${{ steps.recovery.outputs.standards_tag }}" in workflow
    )
    assert "STANDARDS_TAG: ${{ needs.preflight.outputs.standards_tag }}" in workflow
    assert 'case "$release_status" in' in workflow
    assert "404)" in workflow
    assert "gh release create" in workflow
    assert "--verify-tag --generate-notes" in workflow


def test_publishers_have_distinct_identities_and_digest_binding() -> None:
    release = (REPO_ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    assert (  # sarj-noqa: SARJ402 -- workflow text is the release-policy contract
        "environment: npm-release" not in release
    )
    assert "environment: npm-typescript-release" in release
    assert "environment: npm-tsconfig-release" in release
    assert "environment: pypi-bootstrap-release" in release
    assert release.count("artifact_sha256:") == 7
    assert release.count("Verify build-bound artifact digest") == 7
    assert "test \"$actual_name\" = '@sarj/tsconfig'" in release
    assert release.count("Verify registry bytes and source-bound provenance") == 2
    verifier = (  # sarj-noqa: SARJ402 -- verifier text is the pinned supply-chain contract
        REPO_ROOT / ".github/scripts/verify_registry_publication.py"
    ).read_text(encoding="utf-8")
    assert (  # sarj-noqa: SARJ402 -- verifier text is the pinned supply-chain contract
        'entry.get("predicateType") != "https://slsa.dev/provenance/v1"' in verifier
    )
    assert "NPM_ATTESTATION_ATTEMPTS = 18" in verifier
    assert "range(NPM_ATTESTATION_ATTEMPTS)" in verifier


def test_registry_verifier_parses_on_release_runner_python() -> None:
    verifier = (REPO_ROOT / ".github/scripts/verify_registry_publication.py").read_text(encoding="utf-8")

    ast.parse(verifier, feature_version=(3, 12))


def test_security_workflow_scans_tree_and_history_with_pinned_gitleaks() -> None:
    security = (REPO_ROOT / ".github/workflows/security.yml").read_text(encoding="utf-8")

    assert (  # sarj-noqa: SARJ402 -- workflow text is the security-policy contract
        "gitleaks_8.30.1_linux_x64.tar.gz" in security
    )
    assert "551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb" in security
    assert "fetch-depth: 0" in security
    assert 'gitleaks" dir . --config .gitleaks.toml' in security
    assert 'gitleaks" git --config .gitleaks.toml' in security
    assert "--log-opts='--all'" in security


@pytest.mark.parametrize(
    ("needle", "expected_count"),
    [
        ("path: verified-dist", 5),
        ("verified-dist/SHA256SUMS", 5),
        ("Stage verified distributions for publication", 5),
        ("cp verified-dist/*.whl verified-dist/*.tar.gz publish-dist/", 5),
        ("packages-dir: publish-dist/", 5),
    ],
    ids=["staged-path", "checksums", "staging-step", "wheel-copy", "publish-path"],
)
def test_pypi_publishers_exclude_checksum_manifests(needle: str, expected_count: int) -> None:
    release = (REPO_ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")

    assert (  # sarj-noqa: SARJ402 -- workflow text is the release-policy contract
        release.count(needle) == expected_count
    )


def test_npm_release_disables_install_scripts_and_keeps_publishers_dependency_free() -> None:
    release = (REPO_ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    typescript_ci = (REPO_ROOT / ".github/workflows/typescript-ci.yml").read_text(encoding="utf-8")

    assert "npm ci --ignore-scripts" in release  # sarj-noqa: SARJ402 -- workflow text is the publishing-policy contract
    assert 'npm pack --pack-destination "$RUNNER_TEMP/npm-artifacts" --ignore-scripts' in release
    assert (  # sarj-noqa: SARJ402 -- workflow text is the publishing-policy contract
        "npm ci --ignore-scripts --no-audit --no-fund" in typescript_ci
    )
    assert release.count("npm install --global npm@12.0.2 --ignore-scripts") == 2

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
    tsconfig_workflow = (REPO_ROOT / ".github/workflows/tsconfig-ci.yml").read_text(encoding="utf-8")

    assert (  # sarj-noqa: SARJ402 -- workflow text is the required-check contract
        workflow.startswith("name: release-ready\n")
    )
    assert "\n  release-ready:\n" in workflow
    assert "make verify" not in workflow
    assert "make build" not in workflow
    assert "Cross-package repository policy" in workflow
    assert "packages/standards --locked --dev" in workflow
    assert "cancel-in-progress: true" in workflow
    assert "typescript@6.0.3" in tsconfig_workflow  # sarj-noqa: SARJ402 -- workflow text is the required-check contract
    assert "typescript@latest" not in tsconfig_workflow


def test_warning_first_gate_prints_an_executable_command_for_each_rule() -> None:
    workflow = (REPO_ROOT / ".github/workflows/repo-ci.yml").read_text(encoding="utf-8")

    assert (  # sarj-noqa: SARJ402 -- workflow text is the author contract
        "new judgment rules must enter the fleet at error level" in workflow
    )
    assert (  # sarj-noqa: SARJ402 -- exact remediation is the contract
        "Promote the rule before release: $selector" in workflow
    )


def test_parallel_package_workflows_are_always_present_with_stable_contexts() -> None:
    expected_names = {
        "bootstrap-ci.yml": "name: bootstrap package",
        "python-ci.yml": "name: python package",
        "typescript-ci.yml": "name: typescript plugin (${{ matrix.node }})",
        "sql-ci.yml": "name: sql package",
        "iac-ci.yml": "name: iac package",
        "tsconfig-ci.yml": "name: tsconfig package",
        "standards-ci.yml": "name: standards package",
    }
    for filename, job_name in expected_names.items():
        workflow = (REPO_ROOT / ".github/workflows" / filename).read_text(encoding="utf-8")
        trigger = workflow.partition("\npermissions:\n")[0]
        assert "paths:" not in trigger
        assert job_name in workflow


def test_pre_push_keeps_complete_tests_in_ci() -> None:
    lefthook = (REPO_ROOT / "lefthook.yml").read_text(encoding="utf-8")
    pre_push = lefthook.partition("\npre-push:\n")[2]
    assert "run: make lint" in pre_push
    assert "make verify" not in pre_push


def test_documentation_deploy_is_revision_bound_self_verifying_and_single_site() -> None:
    workflow = (REPO_ROOT / ".github/workflows/docs.yml").read_text(encoding="utf-8")
    verifier = (REPO_ROOT / "apps/docs/scripts/verify-deployment.mjs").read_text(encoding="utf-8")

    assert "branches: [main]" in workflow  # sarj-noqa: SARJ402 -- workflow text is the deployment-policy contract
    assert "schedule:" not in workflow
    assert "WORKERS_CI_COMMIT_SHA: ${{ github.sha }}" in workflow
    assert "Verify production credentials" in workflow
    assert "actions/upload-artifact@" in workflow
    assert "actions/download-artifact@" in workflow
    assert "Verify deployed revision" in workflow
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
        ("python", "sarj_python_lint", "sarj-python-lint"),
        ("sql", "sarj_sql_lint", "sarj-sql-lint"),
        ("iac", "sarj_iac_lint", "sarj-iac-lint"),
    ],
)
def test_python_publishers_smoke_and_bind_wheels_and_sdists(
    package: str,
    module: str,
    executable: str,
) -> None:
    release = (REPO_ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    assert (  # sarj-noqa: SARJ402 -- workflow text is the publishing-policy contract
        f'uv pip install --python "$RUNNER_TEMP/{package}-wheel/bin/python" dist/*.whl' in release
    )
    assert f'uv pip install --python "$RUNNER_TEMP/{package}-sdist/bin/python"' in release
    assert f"import {module}" in release
    assert f'bin/{executable}" --help' in release
    assert release.count("sha256sum --check --strict SHA256SUMS") == 5
    assert "code_standards-*.whl pytest==9.1.1 'jsonschema>=4.26,<5' ruff" in release
