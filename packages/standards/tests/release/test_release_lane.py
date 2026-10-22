from __future__ import annotations

from dataclasses import dataclass
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Protocol, runtime_checkable

import pytest

from sarj_standards.libs.release.process import run_process


@runtime_checkable
class PublisherLane(Protocol):
    LEGACY_COMMIT: str
    APPROVED_ADAPTER_SHA256: str
    VERSION_PROJECTIONS: tuple[str, ...]
    DOC_EXAMPLES: str
    CLI_REFERENCE: str
    RELEASE_TARGETS: frozenset[str]

    def validate_lane(
        self, root: Path, *, source_ref: str, commit: str, detected_targets: str | None = None
    ) -> str: ...

    def main(self, argv: list[str] | None = None) -> int: ...


@dataclass(frozen=True)
class Candidate:
    root: Path
    anchor: str
    commit: str


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


@pytest.fixture
def lane(monkeypatch: pytest.MonkeyPatch) -> PublisherLane:
    path = Path(__file__).resolve().parents[4] / ".github/scripts/release_lane.py"
    spec = importlib.util.spec_from_file_location("release_lane_fixture", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    assert isinstance(module, PublisherLane)
    return module


@pytest.fixture
def candidate(tmp_path: Path, lane: PublisherLane, monkeypatch: pytest.MonkeyPatch) -> Candidate:
    _git(tmp_path, "init", "--quiet")
    files = {
        "packages/standards/pyproject.toml": '[project]\nversion = "8.101.1"\ndependencies = ["native==1.0"]\n',
        "packages/standards-compat/pyproject.toml": '[project]\nversion = "8.101.1"\ndependencies = ["code-standards==8.101.1"]\n',
        "packages/standards/uv.lock": 'version = 1\n[[package]]\nname = "code-standards"\nversion = "8.101.1"\n',
        ".sarj-standards.toml": 'bundle = "8.101.1"\nrule_profile = "all"\n',
        lane.CLI_REFERENCE: '{"version":"8.101.1","summary":"Version8.101.1","commands":[]}\n',
        lane.DOC_EXAMPLES: '{"catalogSha256":"legacy","cliSha256":"original","rules":[]}\n',
        "packages/standards/src/sarj_standards/libs/linting/external.py": "VALUE = 1\n",
        "packages/standards/src/sarj_standards/schemas/rule-catalog.v1.json": '{"rules":["retained"]}\n',
    }
    for relative, content in files.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    anchor = _commit(tmp_path)
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- exercise the real immutable-anchor lookup with private Git objects; injection would bypass that boundary.
        lane, "LEGACY_COMMIT", anchor
    )
    for relative in lane.VERSION_PROJECTIONS:
        path = tmp_path / relative
        path.write_text(path.read_text().replace("8.101.1", "8.101.2"))
    cli_digest = hashlib.sha256((tmp_path / lane.CLI_REFERENCE).read_bytes()).hexdigest()
    (tmp_path / lane.DOC_EXAMPLES).write_text(
        json.dumps({"catalogSha256": "legacy", "cliSha256": cli_digest, "rules": []})
    )
    adapter = tmp_path / "packages/standards/src/sarj_standards/libs/linting/external.py"
    adapter.write_text("VALUE = 2\n")
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- exercise the real approved-digest lookup with private adapter bytes; injection would bypass that boundary.
        lane, "APPROVED_ADAPTER_SHA256", hashlib.sha256(adapter.read_bytes()).hexdigest()
    )
    return Candidate(tmp_path, anchor, _commit(tmp_path))


def test_main_keeps_existing_release_scope(candidate: Candidate, lane: PublisherLane) -> None:
    assert lane.validate_lane(candidate.root, source_ref="refs/heads/main", commit=candidate.commit) == "main"


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
        "packages/standards/src/sarj_standards/libs/linting/another.py",
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
