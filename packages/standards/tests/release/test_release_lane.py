from __future__ import annotations

from dataclasses import dataclass
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Literal, Protocol, runtime_checkable

import pytest

from sarj_standards.libs.release.process import run_process


@runtime_checkable
class PublisherLane(Protocol):
    LEGACY_COMMIT: str
    APPROVED_ADAPTER_SHA256: str
    APPROVED_LOCK_SHA256: str
    APPROVED_GITLEAKS_SHA256: str
    VERSION_PROJECTIONS: tuple[str, ...]
    DOC_EXAMPLES: str
    CLI_REFERENCE: str
    RELEASE_TARGETS: frozenset[str]

    def validate_lane(
        self, root: Path, *, source_ref: str, commit: str, detected_targets: str | None = None
    ) -> str: ...

    def main(self, argv: list[str] | None = None) -> int: ...


@runtime_checkable
class ActionPublisherLane(PublisherLane, Protocol):
    REPO_STANDARDS_ACTION_PROJECTIONS: dict[str, str]
    COMMIT_POLICY_BACKPORT_SHA256: dict[str, str]


@dataclass(frozen=True)
class Candidate:
    root: Path
    anchor: str
    commit: str


_REACT_SCOPE_TESTS = "packages/standards/tests/test_react_doctor_scope.py"
_COMMIT_POLICY_BACKPORT_PATHS = (
    "packages/standards/src/sarj_standards/libs/adoption/scaffold.py",
    "packages/standards/tests/test_adoption.py",
    ".github/workflows/commit-policy.yml",
)


_DOCS_DEPENDENCY_PATHS = ("apps/docs/package.json", "apps/docs/package-lock.json")
_DEPLOY_DEPENDENCY_PATHS = (".github/deploy/package.json", ".github/deploy/package-lock.json")
_DEPENDENCY_PATHS = (*_DOCS_DEPENDENCY_PATHS, *_DEPLOY_DEPENDENCY_PATHS)


def _git(root: Path, *arguments: str) -> str:
    return run_process(
        (
            "git",
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            *arguments,
        ),
        cwd=root,
        capture_output=True,
    ).stdout.strip()


def _commit(root: Path) -> str:
    _git(root, "add", ".")
    _git(root, "commit", "--quiet", "-m", "fixture")
    return _git(root, "rev-parse", "HEAD")


def _load_lane(path: Path, name: str, monkeypatch: pytest.MonkeyPatch) -> PublisherLane:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    assert isinstance(module, PublisherLane)
    return module


@pytest.fixture
def lane(monkeypatch: pytest.MonkeyPatch) -> PublisherLane:
    path = Path(__file__).resolve().parents[4] / ".github/scripts/release_lane.py"
    return _load_lane(path, "release_lane_fixture", monkeypatch)


@pytest.fixture
def candidate(tmp_path: Path, lane: PublisherLane, monkeypatch: pytest.MonkeyPatch) -> Candidate:
    _git(tmp_path, "init", "--quiet")
    files = {
        **{
            relative: run_process(
                ("git", "show", f"{lane.LEGACY_COMMIT}:{relative}"),
                cwd=Path(__file__).resolve().parents[4],
                capture_output=True,
            ).stdout
            for relative in (*_DEPENDENCY_PATHS, *_ACTION_DEFAULT_PATHS)
        },
        "packages/standards/pyproject.toml": '[project]\nversion = "8.101.1"\ndependencies = ["native==1.0"]\n',
        "packages/standards-compat/pyproject.toml": '[project]\nversion = "8.101.1"\ndependencies = ["code-standards==8.101.1"]\n',
        "packages/standards/uv.lock": 'version = 1\n[[package]]\nname = "code-standards"\nversion = "8.101.1"\n\n[[package]]\nname = "virtualenv"\nversion = "21.14.7"\nsdist = { url = "https://example.invalid/virtualenv", hash = "sha256:fixture-approved" }\n',
        ".sarj-standards.toml": 'bundle = "8.101.1"\nrule_profile = "all"\n',
        lane.CLI_REFERENCE: '{"version":"8.101.1","summary":"Version8.101.1","commands":[]}\n',
        ".gitleaks.toml": "[extend]\nuseDefault = true\n",
        lane.DOC_EXAMPLES: '{"catalogSha256":"legacy","cliSha256":"original","rules":[]}\n',
        "packages/standards/src/sarj_standards/libs/linting/external.py": "VALUE = 1\n",
        _REACT_SCOPE_TESTS: "SCOPE_TEST = 1\n",
        "packages/standards/src/sarj_standards/schemas/rule-catalog.v1.json": '{"rules":["retained"]}\n',
    }
    for relative, content in files.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    approved_lock = files["packages/standards/uv.lock"].replace('version = "21.14.7"', 'version = "21.14.12"')
    approved_gitleaks = files[".gitleaks.toml"] + "# reviewed public digest fixture\n"
    anchor = _commit(tmp_path)
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- exercise the real immutable-anchor lookup with private Git objects; injection would bypass that boundary.
        lane, "LEGACY_COMMIT", anchor
    )
    for relative in lane.VERSION_PROJECTIONS:
        path = tmp_path / relative
        path.write_text(path.read_text().replace("8.101.1", "8.101.2"))
    lock = tmp_path / "packages/standards/uv.lock"
    lock.write_text(lock.read_text().replace('version = "21.14.7"', 'version = "21.14.12"'))
    (tmp_path / ".gitleaks.toml").write_text(approved_gitleaks)
    cli_digest = hashlib.sha256((tmp_path / lane.CLI_REFERENCE).read_bytes()).hexdigest()
    (tmp_path / lane.DOC_EXAMPLES).write_text(
        json.dumps({"catalogSha256": "legacy", "cliSha256": cli_digest, "rules": []})
    )
    adapter = tmp_path / "packages/standards/src/sarj_standards/libs/linting/external.py"
    adapter.write_text("VALUE = 2\n")
    for name, payload in (
        ("APPROVED_ADAPTER_SHA256", adapter.read_bytes()),
        ("APPROVED_SCOPED_ADAPTER_SHA256", b"VALUE = 3\n"),
        ("APPROVED_SCOPED_TESTS_SHA256", b"SCOPE_TEST = 2\n"),
        ("APPROVED_LOCK_SHA256", approved_lock.encode()),
        (
            "APPROVED_PATCHED_LOCK_SHA256",
            approved_lock.replace('version = "21.14.12"', 'version = "21.14.13"').encode(),
        ),
        ("APPROVED_GITLEAKS_SHA256", approved_gitleaks.encode()),
    ):
        monkeypatch.setattr(  # sarj-noqa: SARJ445 -- exercise the real approved-digest lookup with private fixture bytes; injection would bypass that boundary.
            lane, name, hashlib.sha256(payload).hexdigest()
        )
    return Candidate(tmp_path, anchor, _commit(tmp_path))


def test_main_keeps_existing_release_scope(candidate: Candidate, lane: PublisherLane) -> None:
    assert lane.validate_lane(candidate.root, source_ref="refs/heads/main", commit=candidate.commit) == "main"


def test_maintenance_accepts_reviewed_release_creation_owner(candidate: Candidate, lane: PublisherLane) -> None:
    path = candidate.root / ".github/scripts/release-github-release.sh"
    path.parent.mkdir(parents=True)
    path.write_text("#!/bin/sh\nexit 0\n")
    commit = _commit(candidate.root)
    assert (
        lane.validate_lane(candidate.root, source_ref="refs/heads/maintenance/standards-8.101", commit=commit)
        == "standards-maintenance"
    )


def test_maintenance_accepts_only_the_named_legacy_policy_lane(candidate: Candidate, lane: PublisherLane) -> None:
    targets = {name: "true" if name == "standards" else "false" for name in lane.RELEASE_TARGETS}
    assert (
        lane.validate_lane(
            candidate.root,
            source_ref="refs/heads/maintenance/standards-8.101",
            commit=candidate.commit,
            detected_targets=json.dumps(targets),
        )
        == "standards-maintenance"
    )


@pytest.mark.parametrize(
    "source_ref", ["refs/heads/feature/release", "refs/heads/maintenance/standards-8.102", "refs/tags/main"]
)
def test_other_branches_cannot_publish(candidate: Candidate, lane: PublisherLane, source_ref: str) -> None:
    with pytest.raises(ValueError, match="ref is not allowed"):
        lane.validate_lane(candidate.root, source_ref=source_ref, commit=candidate.commit)


@pytest.mark.parametrize("commit", ["HEAD", "a" * 40])
def test_publication_requires_the_exact_checkout(candidate: Candidate, lane: PublisherLane, commit: str) -> None:
    with pytest.raises(ValueError, match="exact checked-out"):
        lane.validate_lane(candidate.root, source_ref="refs/heads/main", commit=commit)


@pytest.mark.parametrize(
    "relative",
    [
        "packages/standards/src/sarj_standards/schemas/rule-catalog.v1.json",
        "packages/standards/src/sarj_standards/configs/ruff.strict.toml",
        "packages/python/pyproject.toml",
        "apps/docs/package-extra.json",
        "apps/docs/package-lock-extra.json",
        ".github/deploy/package-extra.json",
        ".github/deploy/package-lock-extra.json",
        "packages/standards/src/sarj_standards/libs/linting/another.py",
        ".github/scripts/release-github-release-extra.sh",
    ],
)
def test_maintenance_rejects_policy_and_component_drift(
    candidate: Candidate, lane: PublisherLane, relative: str
) -> None:
    path = candidate.root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("changed policy\n")
    commit = _commit(candidate.root)
    with pytest.raises(ValueError, match="legacy policy or an unapproved path"):
        lane.validate_lane(candidate.root, source_ref="refs/heads/maintenance/standards-8.101", commit=commit)


@pytest.mark.parametrize(
    ("relative", "before", "after"),
    [
        ("packages/standards/pyproject.toml", "native==1.0", "native==2.0"),
        ("packages/standards-compat/pyproject.toml", "code-standards==8.101.2", "code-standards==8.101.1"),
        ("packages/standards/uv.lock", "version = 1\n", "version = 2\n"),
        ("packages/standards/uv.lock", 'version = "21.14.12"', 'version = "21.14.13"'),
        ("packages/standards/uv.lock", 'version = "8.101.2"', 'version = "8.101.1"'),
        ("packages/standards/uv.lock", 'hash = "sha256:fixture-approved"', 'hash = "sha256:fixture-tampered"'),
        (
            "packages/standards/uv.lock",
            'url = "https://example.invalid/virtualenv"',
            'url = "https://elsewhere.invalid/virtualenv"',
        ),
        ("packages/standards/uv.lock", 'name = "code-standards"', 'name = "another-package"'),
        (".sarj-standards.toml", 'rule_profile = "all"', 'rule_profile = "none"'),
        ("packages/standards/src/sarj_standards/configs/cli-reference.v1.json", '"commands":[]', '"commands":["new"]'),
    ],
)
def test_version_projection_allowlist_does_not_hide_semantic_changes(
    candidate: Candidate, lane: PublisherLane, relative: str, before: str, after: str
) -> None:
    path = candidate.root / relative
    path.write_text(path.read_text().replace(before, after))
    commit = _commit(candidate.root)
    with pytest.raises(ValueError, match="only the legacy version projection"):
        lane.validate_lane(candidate.root, source_ref="refs/heads/maintenance/standards-8.101", commit=commit)


def test_generated_documentation_cannot_hide_catalog_drift(candidate: Candidate, lane: PublisherLane) -> None:
    path = candidate.root / lane.DOC_EXAMPLES
    path.write_text(path.read_text().replace("legacy", "modified"))
    commit = _commit(candidate.root)
    with pytest.raises(ValueError, match="retain the legacy catalog"):
        lane.validate_lane(candidate.root, source_ref="refs/heads/maintenance/standards-8.101", commit=commit)


def test_allowed_adapter_path_cannot_hide_unreviewed_source(candidate: Candidate, lane: PublisherLane) -> None:
    (candidate.root / "packages/standards/src/sarj_standards/libs/linting/external.py").write_text("VALUE = 3\n")
    commit = _commit(candidate.root)
    with pytest.raises(ValueError, match="adapter bytes do not match"):
        lane.validate_lane(candidate.root, source_ref="refs/heads/maintenance/standards-8.101", commit=commit)


@pytest.mark.parametrize("stage", [False, True], ids=["unstaged", "staged"])
def test_committed_adapter_approval_cannot_hide_dirty_build_inputs(
    candidate: Candidate, lane: PublisherLane, *, stage: bool
) -> None:
    path = "packages/standards/src/sarj_standards/libs/linting/external.py"
    (candidate.root / path).write_text("VALUE = 3\n")
    if stage:
        _git(candidate.root, "add", path)
    with pytest.raises(ValueError, match="clean working tree"):
        lane.validate_lane(candidate.root, source_ref="refs/heads/maintenance/standards-8.101", commit=candidate.commit)


def test_untracked_source_cannot_enter_a_maintenance_build(candidate: Candidate, lane: PublisherLane) -> None:
    (candidate.root / "packages/standards/src/sarj_standards/injected.py").write_text("VALUE = 3\n")
    with pytest.raises(ValueError, match="clean working tree"):
        lane.validate_lane(candidate.root, source_ref="refs/heads/maintenance/standards-8.101", commit=candidate.commit)


@pytest.mark.parametrize("target", ["python", "typescript", "bootstrap"])
def test_maintenance_cannot_publish_sibling_targets(candidate: Candidate, lane: PublisherLane, target: str) -> None:
    targets = dict.fromkeys(lane.RELEASE_TARGETS, "false")
    targets[target] = "true"
    with pytest.raises(ValueError, match="cannot publish sibling"):
        lane.validate_lane(
            candidate.root,
            source_ref="refs/heads/maintenance/standards-8.101",
            commit=candidate.commit,
            detected_targets=json.dumps(targets),
        )


@pytest.mark.parametrize("targets", ["{}", '{"python":true}'])
def test_incomplete_or_malformed_target_inventory_is_rejected(
    candidate: Candidate, lane: PublisherLane, targets: str
) -> None:
    with pytest.raises(ValueError, match=r"known release-target|Input should be"):
        lane.validate_lane(
            candidate.root,
            source_ref="refs/heads/maintenance/standards-8.101",
            commit=candidate.commit,
            detected_targets=targets,
        )


def test_cli_records_only_the_validated_lane(candidate: Candidate, lane: PublisherLane, tmp_path: Path) -> None:
    output = tmp_path / "github-output"
    assert (
        lane.main(
            [
                "--root",
                str(candidate.root),
                "--ref",
                "refs/heads/maintenance/standards-8.101",
                "--commit",
                candidate.commit,
                "--github-output",
                str(output),
            ]
        )
        == 0
    )
    assert output.read_text() == "lane=standards-maintenance\n"


@pytest.mark.parametrize(
    "scenario",
    ["exact", "branch", "sha", "repository", "workflow", "event", "missing-terminal"],
)
def test_exact_push_safety_gate_rejects_other_run_identities(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, scenario: str
) -> None:
    script = Path(__file__).resolve().parents[4] / ".github/scripts/release-require-checks.sh"
    binaries = tmp_path / "bin"
    binaries.mkdir()
    fixture = tmp_path / "responses.json"
    fixture.write_text(json.dumps({"scenario": scenario, "sha": "a" * 40}))
    (binaries / "gh").write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        "from pathlib import Path\n"
        "data = json.loads(Path(os.environ['RELEASE_GATE_FIXTURE']).read_text())\n"
        "endpoint = next(arg for arg in sys.argv if arg.startswith('repos/'))\n"
        "scenario = data['scenario']\n"
        "if '/workflows/' in endpoint:\n"
        "    workflow = endpoint.split('/workflows/')[1].split('/')[0]\n"
        "    run = {'id': 123, 'head_sha': data['sha'], 'head_branch': 'maintenance/standards-8.101',\n"
        "           'event': 'push', 'path': '.github/workflows/' + workflow, 'conclusion': None,\n"
        "           'head_repository': {'full_name': 'sarj-ai/code-standards'}}\n"
        "    updates = {'branch': {'head_branch': 'main'}, 'sha': {'head_sha': 'b' * 40},\n"
        "               'repository': {'head_repository': {'full_name': 'untrusted/fork'}},\n"
        "               'workflow': {'path': '.github/workflows/unrelated.yml'},\n"
        "               'event': {'event': 'workflow_dispatch'}}\n"
        "    run.update(updates.get(scenario, {}))\n"
        "    print(json.dumps({'workflow_runs': [run]}))\n"
        "else:\n"
        "    name = 'other' if scenario == 'missing-terminal' else 'CI complete'\n"
        "    print(json.dumps({'jobs': [{'name': name, 'status': 'completed', 'conclusion': 'success'}]}))\n"
    )
    (binaries / "gh").chmod(0o755)
    (binaries / "sleep").write_text("#!/bin/sh\nexit 86\n")
    (binaries / "sleep").chmod(0o755)
    monkeypatch.setenv("PATH", str(binaries), prepend=os.pathsep)
    monkeypatch.setenv("RELEASE_GATE_FIXTURE", str(fixture))
    monkeypatch.setenv("TARGET_SHA", "a" * 40)
    monkeypatch.setenv("TARGET_BRANCH", "maintenance/standards-8.101")
    monkeypatch.setenv("GITHUB_REPOSITORY", "sarj-ai/code-standards")

    completed = subprocess.run(("bash", str(script)), check=False, capture_output=True, text=True, timeout=10)

    assert completed.returncode == (0 if scenario == "exact" else 86)
    if scenario == "exact":
        assert completed.stdout.count("jobs succeeded") == 3


@pytest.mark.parametrize(
    "content", ["[extend]\nuseDefault = false\n", "[extend]\nuseDefault = true\n# altered projection\n"]
)
def test_maintenance_scanner_path_requires_exact_approved_bytes(
    candidate: Candidate, lane: PublisherLane, content: str
) -> None:
    (candidate.root / ".gitleaks.toml").write_text(content)
    commit = _commit(candidate.root)
    with pytest.raises(ValueError, match="scanner configuration must match"):
        lane.validate_lane(candidate.root, source_ref="refs/heads/maintenance/standards-8.101", commit=commit)


@pytest.mark.parametrize(
    ("version", "patched", "accepted"),
    [
        ("8.101.3", False, True),
        ("8.101.3", True, False),
        ("8.101.4", False, False),
        ("8.101.4", True, True),
        ("8.101.10", False, False),
        ("8.101.10", True, True),
    ],
)
def test_reviewed_lock_projection_requires_version_specific_security_fix(
    candidate: Candidate, lane: PublisherLane, version: str, *, patched: bool, accepted: bool
) -> None:
    if version == "8.101.10":
        _apply_reviewed_action_cohort(candidate.root, lane)
    if version not in {"8.101.2", "8.101.3"}:
        _apply_reviewed_docs_dependencies(candidate.root)
    for relative in lane.VERSION_PROJECTIONS:
        path = candidate.root / relative
        path.write_text(path.read_text().replace("8.101.2", version))
    if patched:
        lock = candidate.root / "packages/standards/uv.lock"
        lock.write_text(lock.read_text().replace('version = "21.14.12"', 'version = "21.14.13"'))
    if version == "8.101.10":
        (candidate.root / "packages/standards/src/sarj_standards/libs/linting/external.py").write_text("VALUE = 3\n")
        (candidate.root / _REACT_SCOPE_TESTS).write_text("SCOPE_TEST = 2\n")
    document = candidate.root / lane.DOC_EXAMPLES
    document.write_text(
        json.dumps(
            {
                "catalogSha256": "legacy",
                "cliSha256": hashlib.sha256((candidate.root / lane.CLI_REFERENCE).read_bytes()).hexdigest(),
                "rules": [],
            }
        )
    )
    commit = _commit(candidate.root)
    if not accepted:
        with pytest.raises(ValueError, match="only the legacy version projection"):
            lane.validate_lane(candidate.root, source_ref="refs/heads/maintenance/standards-8.101", commit=commit)
        return
    assert (
        lane.validate_lane(candidate.root, source_ref="refs/heads/maintenance/standards-8.101", commit=commit)
        == "standards-maintenance"
    )


@pytest.mark.parametrize(
    ("version", "cohort", "accepted"),
    [
        ("8.101.3", "legacy", True),
        ("8.101.4", "legacy", True),
        ("8.101.3", "paired", False),
        ("8.101.4", "paired", False),
        ("8.101.3", "tests-only", False),
        ("8.101.4", "tests-only", False),
        ("8.101.5", "legacy", False),
        ("8.101.5", "adapter-only", False),
        ("8.101.5", "tests-only", False),
        ("8.101.5", "paired", True),
        ("8.101.5", "adapter-drift", False),
        ("8.101.5", "tests-drift", False),
        ("8.101.10", "legacy", False),
        ("8.101.10", "paired", True),
    ],
)
def test_scoped_react_backport_requires_exact_versioned_pair(
    candidate: Candidate, lane: PublisherLane, version: str, cohort: str, *, accepted: bool
) -> None:
    if version == "8.101.10":
        _apply_reviewed_action_cohort(candidate.root, lane)
    _project_maintenance_version(candidate.root, version)
    if version not in {"8.101.2", "8.101.3"}:
        _apply_reviewed_docs_dependencies(candidate.root)
        lock = candidate.root / "packages/standards/uv.lock"
        lock.write_text(lock.read_text().replace('version = "21.14.12"', 'version = "21.14.13"'))
    adapter = candidate.root / "packages/standards/src/sarj_standards/libs/linting/external.py"
    if cohort in {"paired", "adapter-only", "tests-drift"}:
        adapter.write_text("VALUE = 3\n")
    elif cohort == "adapter-drift":
        adapter.write_text("VALUE = 4\n")
    if cohort in {"paired", "tests-only", "adapter-drift"}:
        (candidate.root / _REACT_SCOPE_TESTS).write_text("SCOPE_TEST = 2\n")
    elif cohort == "tests-drift":
        (candidate.root / _REACT_SCOPE_TESTS).write_text("SCOPE_TEST = 3\n")
    commit = _commit(candidate.root)
    if accepted:
        assert (
            lane.validate_lane(candidate.root, source_ref="refs/heads/maintenance/standards-8.101", commit=commit)
            == "standards-maintenance"
        )
    else:
        with pytest.raises(ValueError, match=r"adapter bytes do not match|scope tests do not match"):
            lane.validate_lane(candidate.root, source_ref="refs/heads/maintenance/standards-8.101", commit=commit)


def _project_maintenance_version(checkout: Path, version: str = "8.101.3") -> None:
    cli = checkout / "packages/standards/src/sarj_standards/configs/cli-reference.v1.json"
    old_cli_digest = hashlib.sha256(cli.read_bytes()).hexdigest()
    for relative in (
        "packages/standards/pyproject.toml",
        "packages/standards-compat/pyproject.toml",
        "packages/standards/uv.lock",
        ".sarj-standards.toml",
        "packages/standards/src/sarj_standards/configs/cli-reference.v1.json",
    ):
        path = checkout / relative
        source = path.read_text()
        assert "8.101.2" in source
        path.write_text(source.replace("8.101.2", version))
    docs = checkout / "apps/docs/src/generated/formatted-code.v1.json"
    source = docs.read_text()
    assert source.count(old_cli_digest) == 1
    docs.write_text(source.replace(old_cli_digest, hashlib.sha256(cli.read_bytes()).hexdigest()))


def _reviewed_history_candidate(
    tmp_path: Path, projection: Literal["prefix", "reviewed", "adapter-drift", "path-drift"]
) -> Candidate:
    repository = Path(__file__).resolve().parents[4]
    checkout = tmp_path / "candidate"
    prefix = "8c9ddf4828e92873d1b4486ab79c02c6aa47266e"
    fix = "74e68908b6a5fea86282dbe0cdb98d5c1e10f28b"
    adapter = "packages/standards/src/sarj_standards/libs/linting/external.py"
    old_digest = "58b47b1defa519e1b690d9ab43530b23d89824ff28f4109be2941b2c8f62e254"
    reviewed_digest = "b949ddf7fb6aadbf9e5fd4520b67a322b114a0b54a0af2b32c21d1a2644d882c"
    _git(tmp_path, "clone", "--shared", "--no-checkout", str(repository), str(checkout))
    _git(checkout, "checkout", "--detach", prefix)
    assert hashlib.sha256((checkout / adapter).read_bytes()).hexdigest() == old_digest
    if projection == "prefix":
        return Candidate(checkout, prefix, prefix)

    patch = run_process(
        ("git", "diff", f"{fix}^", fix, "--", adapter, "packages/standards/tests/test_external_diagnostics.py"),
        cwd=repository,
        capture_output=True,
    ).stdout
    patch_path = tmp_path / "reviewed-backport.patch"
    patch_path.write_text(patch)
    _git(checkout, "apply", str(patch_path))
    assert hashlib.sha256((checkout / adapter).read_bytes()).hexdigest() == reviewed_digest
    _project_maintenance_version(checkout)
    controller = checkout / ".github/scripts/release_lane.py"
    source = controller.read_text()
    assert source.count(old_digest) == 1
    controller.write_text(source.replace(old_digest, reviewed_digest))
    tests = checkout / "packages/standards/tests/release/test_release_lane.py"
    anchor = "def test_main_keeps_existing_release_scope("
    source = tests.read_text()
    assert source.count(anchor) == 1
    digest_test = """def test_reviewed_adapter_digest_matches_checked_in_backport(lane: PublisherLane) -> None:
    root = Path(__file__).resolve().parents[4]
    adapter = root / "packages/standards/src/sarj_standards/libs/linting/external.py"
    assert hashlib.sha256(adapter.read_bytes()).hexdigest() == lane.APPROVED_ADAPTER_SHA256


"""
    tests.write_text(source.replace(anchor, digest_test + anchor))
    if projection == "adapter-drift":
        with (checkout / adapter).open("a") as stream:
            stream.write("\n")
    if projection == "path-drift":
        (checkout / "packages/standards/src/sarj_standards/libs/linting/another.py").write_text("VALUE = 3\n")
    return Candidate(checkout, prefix, _commit(checkout))


@pytest.mark.parametrize(
    ("controller", "projection", "message"),
    [
        ("A", "prefix", None),
        ("A", "reviewed", "adapter bytes do not match"),
        ("B", "reviewed", None),
        ("B", "prefix", "adapter bytes do not match"),
        ("B", "adapter-drift", "adapter bytes do not match"),
        ("B", "path-drift", "legacy policy or an unapproved path"),
    ],
)
def test_single_adapter_approval_transition_uses_actual_history(
    lane: PublisherLane,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    controller: Literal["A", "B"],
    projection: Literal["prefix", "reviewed", "adapter-drift", "path-drift"],
    message: str | None,
) -> None:
    candidate = _reviewed_history_candidate(tmp_path, projection)
    if controller == "A":
        repository = Path(__file__).resolve().parents[4]
        original = run_process(
            ("git", "show", "d60128eed5df2f5607c3ee8d8fb3faed634dfa65:.github/scripts/release_lane.py"),
            cwd=repository,
            capture_output=True,
        ).stdout
        assert hashlib.sha256(original.encode()).hexdigest() == (
            "180f43dd4fdff8bdce49301bef48676712cab2a091f701d7a67a7b37f331ae43"
        )
        path = tmp_path / "trusted-original-controller.py"
        path.write_text(original)
        lane = _load_lane(path, "release_lane_original_fixture", monkeypatch)
    if message is None:
        assert (
            lane.validate_lane(
                candidate.root, source_ref="refs/heads/maintenance/standards-8.101", commit=candidate.commit
            )
            == "standards-maintenance"
        )
    else:
        with pytest.raises(ValueError, match=message):
            lane.validate_lane(
                candidate.root, source_ref="refs/heads/maintenance/standards-8.101", commit=candidate.commit
            )


def _commit_policy_history_candidate(tmp_path: Path, *, apply_backport: bool) -> Candidate:
    repository = Path(__file__).resolve().parents[4]
    checkout = tmp_path / "candidate"
    prefix = "356560fbc7f76985f1b0997dde240aeb63a72fa9"
    fix = "8d2f22aea2f01172ad35e53e5974abd0f5c69852"
    _git(tmp_path, "clone", "--shared", "--no-checkout", str(repository), str(checkout))
    _git(checkout, "checkout", "--detach", prefix)
    if not apply_backport:
        return Candidate(checkout, prefix, prefix)
    patch = run_process(
        ("git", "diff", f"{fix}^", fix, "--", *_COMMIT_POLICY_BACKPORT_PATHS),
        cwd=repository,
        capture_output=True,
    ).stdout
    patch_path = tmp_path / "reviewed-commit-policy.patch"
    patch_path.write_text(patch)
    _git(checkout, "apply", str(patch_path))
    return Candidate(checkout, prefix, _commit(checkout))


@pytest.mark.parametrize("apply_backport", [False, True], ids=["legacy-8.101.3", "reviewed-8.101.3"])
def test_commit_policy_approval_preserves_legacy_and_accepts_exact_history(
    lane: PublisherLane, tmp_path: Path, *, apply_backport: bool
) -> None:
    candidate = _commit_policy_history_candidate(tmp_path, apply_backport=apply_backport)
    assert (
        lane.validate_lane(candidate.root, source_ref="refs/heads/maintenance/standards-8.101", commit=candidate.commit)
        == "standards-maintenance"
    )


@pytest.mark.parametrize("relative", _COMMIT_POLICY_BACKPORT_PATHS)
def test_commit_policy_approval_rejects_each_partial_history(
    lane: PublisherLane, tmp_path: Path, relative: str
) -> None:
    candidate = _commit_policy_history_candidate(tmp_path, apply_backport=True)
    _git(candidate.root, "restore", "--source", candidate.anchor, "--", relative)
    commit = _commit(candidate.root)
    with pytest.raises(ValueError, match="requires all three approved files"):
        lane.validate_lane(candidate.root, source_ref="refs/heads/maintenance/standards-8.101", commit=commit)


@pytest.mark.parametrize("relative", _COMMIT_POLICY_BACKPORT_PATHS)
def test_commit_policy_approval_rejects_each_tampered_history(
    lane: PublisherLane, tmp_path: Path, relative: str
) -> None:
    candidate = _commit_policy_history_candidate(tmp_path, apply_backport=True)
    with (candidate.root / relative).open("a") as stream:
        stream.write("\n")
    commit = _commit(candidate.root)
    with pytest.raises(ValueError, match="must match the exact approved bytes"):
        lane.validate_lane(candidate.root, source_ref="refs/heads/maintenance/standards-8.101", commit=commit)


def test_commit_policy_approval_keeps_neighboring_policy_closed(lane: PublisherLane, tmp_path: Path) -> None:
    candidate = _commit_policy_history_candidate(tmp_path, apply_backport=True)
    (candidate.root / "packages/standards/src/sarj_standards/libs/adoption/scaffold_extra.py").write_text("VALUE = 3\n")
    commit = _commit(candidate.root)
    with pytest.raises(ValueError, match="legacy policy or an unapproved path"):
        lane.validate_lane(candidate.root, source_ref="refs/heads/maintenance/standards-8.101", commit=commit)


def _apply_reviewed_docs_dependencies(root: Path, paths: tuple[str, ...] = _DEPENDENCY_PATHS) -> None:
    replacements: dict[str, tuple[tuple[str, str], ...]] = {
        "apps/docs/package.json": (('"undici": "8.11.2"', '"undici": "8.12.2"'),),
        "apps/docs/package-lock.json": (
            ('"version": "3.1.8"', '"version": "3.1.9"'),
            (
                '"resolved": "https://registry.npmjs.org/fast-uri/-/fast-uri-3.1.8.tgz"',
                '"resolved": "https://registry.npmjs.org/fast-uri/-/fast-uri-3.1.9.tgz"',
            ),
            (
                '"integrity": "sha512-GZMtZUTNRpOVIECoXwLNZS5xUGE+mVNbTB8h/7Rwh2TFWcBQiPzTgyZi05BF9UMZKkLJv8XBRJTlU7zg8+ZfMg=="',
                '"integrity": "sha512-hS/0Wt3Ya043oKXs0sIxrMpKQITXhMLIrVAKKXi4gozGC9v7YRWVnXIZzjNPTO02M9BdxLCWqK1yRXgNziVyJQ=="',
            ),
            ('"version": "8.11.2"', '"version": "8.12.2"'),
            (
                '"resolved": "https://registry.npmjs.org/undici/-/undici-8.11.2.tgz"',
                '"resolved": "https://registry.npmjs.org/undici/-/undici-8.12.2.tgz"',
            ),
            (
                '"integrity": "sha512-u4UB2/IrKdU6lFxumHmmo1a3fCQO5tzQllRorfoRS63txhrB7xTpSn1PftwC4qEHkOaqP95fCWW4lJzwErwzhQ=="',
                '"integrity": "sha512-XtuDWVdqTLr3NAxm2ly9/hU6kUsJOgGh1RASzMBbsw6aWCOaQzHdW+QQDfdERjfJ2V5vL5pRPa4RetO9UfivDg=="',
            ),
        ),
    }
    replacements[".github/deploy/package.json"] = replacements["apps/docs/package.json"]
    replacements[".github/deploy/package-lock.json"] = replacements["apps/docs/package-lock.json"][3:]
    for relative in paths:
        path = root / relative
        source = path.read_text()
        for old, new in replacements[relative]:
            assert source.count(old) == 1
            source = source.replace(old, new)
        path.write_text(source)


@pytest.mark.parametrize(
    ("dependency_paths", "other_paths"),
    [(_DOCS_DEPENDENCY_PATHS, _DEPLOY_DEPENDENCY_PATHS), (_DEPLOY_DEPENDENCY_PATHS, _DOCS_DEPENDENCY_PATHS)],
    ids=["site", "deployment"],
)
@pytest.mark.parametrize(
    ("version", "member_indexes", "accepted"),
    [
        ("8.101.2", (), True),
        ("8.101.2", (0,), False),
        ("8.101.2", (1,), False),
        ("8.101.2", (0, 1), False),
        ("8.101.3", (), True),
        ("8.101.3", (0,), False),
        ("8.101.3", (1,), False),
        ("8.101.3", (0, 1), False),
        ("8.101.4", (), False),
        ("8.101.4", (0,), False),
        ("8.101.4", (1,), False),
        ("8.101.4", (0, 1), True),
        ("8.101.10", (), False),
        ("8.101.10", (0,), False),
        ("8.101.10", (1,), False),
        ("8.101.10", (0, 1), True),
    ],
)
def test_docs_dependencies_require_the_exact_version_specific_pair(
    candidate: Candidate,
    lane: PublisherLane,
    version: str,
    member_indexes: tuple[int, ...],
    *,
    dependency_paths: tuple[str, str],
    other_paths: tuple[str, str],
    accepted: bool,
) -> None:
    if version == "8.101.10":
        _apply_reviewed_action_cohort(candidate.root, lane)
    _project_maintenance_version(candidate.root, version)
    if version == "8.101.10":
        (candidate.root / "packages/standards/src/sarj_standards/libs/linting/external.py").write_text("VALUE = 3\n")
        (candidate.root / _REACT_SCOPE_TESTS).write_text("SCOPE_TEST = 2\n")
    historical = version in {"8.101.2", "8.101.3"}
    if not historical:
        lock = candidate.root / "packages/standards/uv.lock"
        lock.write_text(lock.read_text().replace('version = "21.14.12"', 'version = "21.14.13"'))
        _apply_reviewed_docs_dependencies(candidate.root, other_paths)
    paths = tuple(dependency_paths[index] for index in member_indexes)
    _apply_reviewed_docs_dependencies(candidate.root, paths)
    commit = _commit(candidate.root) if _git(candidate.root, "status", "--porcelain") else candidate.commit
    if not accepted:
        with pytest.raises(ValueError, match="docs dependencies must match the exact reviewed version-specific bytes"):
            lane.validate_lane(candidate.root, source_ref="refs/heads/maintenance/standards-8.101", commit=commit)
        return
    assert (
        lane.validate_lane(candidate.root, source_ref="refs/heads/maintenance/standards-8.101", commit=commit)
        == "standards-maintenance"
    )


@pytest.mark.parametrize("relative", _DEPENDENCY_PATHS)
def test_docs_dependency_projection_rejects_each_tampered_member(
    candidate: Candidate, lane: PublisherLane, relative: str
) -> None:
    _project_maintenance_version(candidate.root, "8.101.4")
    lock = candidate.root / "packages/standards/uv.lock"
    lock.write_text(lock.read_text().replace('version = "21.14.12"', 'version = "21.14.13"'))
    _apply_reviewed_docs_dependencies(candidate.root)
    with (candidate.root / relative).open("a") as stream:
        stream.write("\n")
    commit = _commit(candidate.root)
    with pytest.raises(ValueError, match="docs dependencies must match the exact reviewed version-specific bytes"):
        lane.validate_lane(candidate.root, source_ref="refs/heads/maintenance/standards-8.101", commit=commit)


_ACTION_DEFAULT_PATHS = (
    "packages/standards/src/sarj_standards/libs/adoption/manifest.py",
    "packages/standards/tests/test_repo_standards_pins.py",
)


_ACTION_PATHS = (*_ACTION_DEFAULT_PATHS, ".github/workflows/ci.yml", ".github/workflows/commit-policy.yml")


_COMMIT_POLICY_PATHS = (
    "packages/standards/src/sarj_standards/libs/adoption/scaffold.py",
    "packages/standards/tests/test_adoption.py",
    ".github/workflows/commit-policy.yml",
)


_ACTION_REVISION = "e83f20a4781a721dc13c8d5d73f75647ea903621"


_LEGACY_ACTION_REVISION = "aed2501dc09aa5701c984544d4fa20bea91661f9"


_ACTION_COHORT_COMMIT = "67a597eeb79985edf7567d0564beff9b13375574"


def _apply_reviewed_action_cohort(root: Path, lane: PublisherLane) -> None:
    assert isinstance(lane, ActionPublisherLane)
    assert set(lane.REPO_STANDARDS_ACTION_PROJECTIONS) == set(_ACTION_PATHS)
    assert set(lane.COMMIT_POLICY_BACKPORT_SHA256) == set(_COMMIT_POLICY_PATHS)
    reviewed = {**lane.COMMIT_POLICY_BACKPORT_SHA256, **lane.REPO_STANDARDS_ACTION_PROJECTIONS}
    source = Path(__file__).resolve().parents[4]
    for relative, digest in reviewed.items():
        payload = run_process(
            ("git", "show", f"{_ACTION_COHORT_COMMIT}:{relative}"), cwd=source, capture_output=True
        ).stdout.encode()
        assert hashlib.sha256(payload).hexdigest() == digest
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)


def _prepare_action_context(candidate: Candidate, lane: PublisherLane, version: str, *, actions: bool = True) -> None:
    _project_maintenance_version(candidate.root, version)
    lock = candidate.root / "packages/standards/uv.lock"
    lock.write_text(lock.read_text().replace('version = "21.14.12"', 'version = "21.14.13"'))
    _apply_reviewed_docs_dependencies(candidate.root)
    (candidate.root / "packages/standards/src/sarj_standards/libs/linting/external.py").write_text("VALUE = 3\n")
    (candidate.root / _REACT_SCOPE_TESTS).write_text("SCOPE_TEST = 2\n")
    if actions:
        _apply_reviewed_action_cohort(candidate.root, lane)


@pytest.mark.parametrize(
    ("version", "actions", "accepted"),
    [
        ("8.101.5", False, True),
        ("8.101.5", True, True),
        ("8.101.6", False, False),
        ("8.101.6", True, True),
        ("8.101.10", False, False),
    ],
)
def test_action_floor_preserves_legacy_and_complete_older_candidates(
    candidate: Candidate, lane: PublisherLane, version: str, *, actions: bool, accepted: bool
) -> None:
    _prepare_action_context(candidate, lane, version, actions=actions)
    commit = _commit(candidate.root)
    if not accepted:
        with pytest.raises(ValueError, match="maintenance RepoStandards actions must match the exact approved bytes"):
            lane.validate_lane(candidate.root, source_ref="refs/heads/maintenance/standards-8.101", commit=commit)
        return
    assert (
        lane.validate_lane(candidate.root, source_ref="refs/heads/maintenance/standards-8.101", commit=commit)
        == "standards-maintenance"
    )


def test_partial_actions_do_not_opt_older_candidates_out_of_the_complete_cohort(
    candidate: Candidate, lane: PublisherLane
) -> None:
    _prepare_action_context(candidate, lane, "8.101.5")
    relative = _ACTION_DEFAULT_PATHS[1]
    (candidate.root / relative).write_text(_git(candidate.root, "show", f"{candidate.anchor}:{relative}") + "\n")
    commit = _commit(candidate.root)
    with pytest.raises(ValueError, match=f"exact approved bytes in {re.escape(relative)}"):
        lane.validate_lane(candidate.root, source_ref="refs/heads/maintenance/standards-8.101", commit=commit)


def test_inactive_action_approval_rejects_introduced_defaults(
    candidate: Candidate, lane: PublisherLane, monkeypatch: pytest.MonkeyPatch
) -> None:
    _prepare_action_context(candidate, lane, "8.101.6")
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- exercise the fail-closed approval boundary without replacing validation.
        lane, "REPO_STANDARDS_ACTION_FIRST_PATCH", None
    )
    commit = _commit(candidate.root)
    with pytest.raises(ValueError, match="maintenance changes legacy policy or an unapproved path"):
        lane.validate_lane(candidate.root, source_ref="refs/heads/maintenance/standards-8.101", commit=commit)


@pytest.mark.parametrize(
    ("relative", "before", "after"),
    [
        (
            _ACTION_DEFAULT_PATHS[0],
            'REPO_STANDARDS_VERSION: Final = "6.11.0"',
            'REPO_STANDARDS_VERSION: Final = "6.12.1"',
        ),
        (
            _ACTION_DEFAULT_PATHS[0],
            'REPO_STANDARDS_ACTION_VERSION: Final = "6.12.1"',
            'REPO_STANDARDS_ACTION_VERSION: Final = "6.11.0"',
        ),
        (_ACTION_DEFAULT_PATHS[0], _ACTION_REVISION, _LEGACY_ACTION_REVISION),
        (_ACTION_DEFAULT_PATHS[1], None, "\n# altered action expectations\n"),
        (".github/workflows/ci.yml", _ACTION_REVISION, _LEGACY_ACTION_REVISION),
        (".github/workflows/commit-policy.yml", _ACTION_REVISION, _LEGACY_ACTION_REVISION),
    ],
)
def test_action_cohort_rejects_mixed_defaults_and_each_unapproved_source(
    candidate: Candidate, lane: PublisherLane, relative: str, before: str | None, after: str
) -> None:
    _prepare_action_context(candidate, lane, "8.101.6")
    path = candidate.root / relative
    source = path.read_text()
    if before is None:
        path.write_text(source + after)
    else:
        assert before in source
        path.write_text(source.replace(before, after, 1))
    commit = _commit(candidate.root)
    with pytest.raises(
        ValueError,
        match=f"maintenance RepoStandards actions must match the exact approved bytes in {re.escape(relative)}",
    ):
        lane.validate_lane(candidate.root, source_ref="refs/heads/maintenance/standards-8.101", commit=commit)


@pytest.mark.parametrize(
    ("relative", "before", "after"),
    [
        ("packages/standards/pyproject.toml", "native==1.0", "repo-standards==6.12.1"),
        ("packages/standards/uv.lock", "sha256:fixture-approved", "sha256:unreviewed-lock"),
    ],
)
def test_action_approval_does_not_relax_legacy_package_or_patched_lock(
    candidate: Candidate, lane: PublisherLane, relative: str, before: str, after: str
) -> None:
    _prepare_action_context(candidate, lane, "8.101.6")
    path = candidate.root / relative
    source = path.read_text()
    assert source.count(before) == 1
    path.write_text(source.replace(before, after))
    commit = _commit(candidate.root)
    with pytest.raises(ValueError, match="only the legacy version projection"):
        lane.validate_lane(candidate.root, source_ref="refs/heads/maintenance/standards-8.101", commit=commit)


@pytest.mark.parametrize("relative", _COMMIT_POLICY_PATHS)
@pytest.mark.parametrize("missing", [False, True])
def test_action_backport_retains_the_complete_commit_policy_cohort(
    candidate: Candidate, lane: PublisherLane, relative: str, *, missing: bool
) -> None:
    _prepare_action_context(candidate, lane, "8.101.6")
    path = candidate.root / relative
    if missing:
        path.unlink()
    else:
        path.write_text(path.read_text() + "\n# unreviewed cohort source\n")
    commit = _commit(candidate.root)
    if missing and relative == ".github/workflows/commit-policy.yml":
        with pytest.raises(subprocess.CalledProcessError) as failure:
            lane.validate_lane(candidate.root, source_ref="refs/heads/maintenance/standards-8.101", commit=commit)
        assert failure.value.returncode == 128
        assert f"{commit}:{relative}" in str(failure.value)
        return
    message = (
        "maintenance commit-policy backport requires all three approved files"
        if missing
        else f"maintenance {'RepoStandards actions' if relative in _ACTION_PATHS else 'commit-policy backport'} must match the exact approved bytes in {re.escape(relative)}"
    )
    with pytest.raises(ValueError, match=message):
        lane.validate_lane(candidate.root, source_ref="refs/heads/maintenance/standards-8.101", commit=commit)
