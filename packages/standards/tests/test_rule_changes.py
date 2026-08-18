from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess

import pytest

from sarj_standards.cli.main import main
from sarj_standards.libs.repository import rule_changes


_INVENTORY = Path("packages/standards/src/sarj_standards/configs/rule-inventory.v1.json")
_CATALOG = Path("packages/standards/src/sarj_standards/schemas/rule-catalog.v1.json")


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ("git", *args),
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _rule(rule_id: str, *, level: str = "warning", summary: str = "Summary") -> dict[str, object]:
    return {
        "key": f"python:{rule_id}",
        "engine": "python",
        "id": rule_id,
        "code": "SARJ999",
        "summary": summary,
        "rationale": "Rationale",
        "remediation": "Remediation",
        "category": "correctness",
        "languages": ["python"],
        "defaultLevel": level,
        "autofix": "none",
        "status": "active",
        "aliases": [],
        "limitations": [],
        "filePatterns": ["**/*.py"],
        "messageIds": ["problem"],
        "optionsSchema": None,
        "references": [],
        "since": "1.0.0",
        "source": f"packages/python/src/rules/{rule_id}.py",
        "test": f"packages/python/tests/rules/test_{rule_id.replace('-', '_')}.py",
        "examples": [],
    }


def _write_revision(root: Path, rules: list[dict[str, object]], message: str) -> str:
    inventory_rules = [
        {
            "family": "python",
            "id": rule["id"],
            "code": rule["code"],
            "source": rule["source"],
            "test": rule["test"],
        }
        for rule in rules
    ]
    inventory = {"schemaVersion": 1, "rules": inventory_rules}
    catalog = {"schemaVersion": 1, "rules": rules}
    for path, payload in ((_INVENTORY, inventory), (_CATALOG, catalog)):
        destination = root / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    for rule in rules:
        for field in ("source", "test"):
            destination = root / str(rule[field])
            destination.parent.mkdir(parents=True, exist_ok=True)
            if not destination.exists():
                destination.write_text(f"# {field} for {rule['id']}\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-m", message)
    return _git(root, "rev-parse", "HEAD")


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.name", "Standards test")
    _git(tmp_path, "config", "user.email", "standards@example.invalid")
    return tmp_path


def test_changes_reports_sorted_additions_and_resolved_shas(repository: Path) -> None:
    before = _write_revision(repository, [_rule("existing")], "base")
    after = _write_revision(repository, [_rule("a-new"), _rule("existing"), _rule("z-new")], "candidate")

    result = rule_changes.compare(repository, before=before, after=after)

    assert result["schemaVersion"] == 1
    assert result["beforeSha"] == before
    assert result["afterSha"] == after
    assert [(item["kind"], item["key"]) for item in result["changes"]] == [
        ("added", "python:a-new"),
        ("added", "python:z-new"),
    ]
    added = result["changes"][0]["after"]
    assert added is not None
    assert added["releaseTarget"] == "python"
    assert [item["releaseTarget"] for item in result["changes"]] == ["python", "python"]


def test_changes_routes_removals_without_consumer_side_descriptor_branching(repository: Path) -> None:
    before = _write_revision(repository, [_rule("removed")], "base")
    after = _write_revision(repository, [], "candidate")

    result = rule_changes.compare(repository, before=before, after=after)

    assert result["changes"] == [
        {
            "kind": "removed",
            "key": "python:removed",
            "releaseTarget": "python",
            "before": {
                "key": "python:removed",
                "engine": "python",
                "family": "python",
                "id": "removed",
                "code": "SARJ999",
                "defaultLevel": "warning",
                "releaseTarget": "python",
                "source": "packages/python/src/rules/removed.py",
                "test": "packages/python/tests/rules/test_removed.py",
            },
            "after": None,
        }
    ]


def test_changes_distinguishes_policy_and_implementation_changes(repository: Path) -> None:
    before = _write_revision(repository, [_rule("sample")], "base")
    changed = _rule("sample", level="error", summary="Changed summary")
    after = _write_revision(repository, [changed], "candidate")

    result = rule_changes.compare(repository, before=before, after=after)

    assert [(item["kind"], item["key"]) for item in result["changes"]] == [
        ("implementation-changed", "python:sample"),
        ("policy-changed", "python:sample"),
    ]
    assert result["changedSelectors"] == ["python:sample"]
    identity = {key: value for key, value in result.items() if key != "changeSetDigest"}
    expected_digest = hashlib.sha256(
        json.dumps(identity, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
    assert result["changeSetDigest"] == expected_digest


def test_change_set_digest_is_stable_for_repeated_comparisons(repository: Path) -> None:
    before = _write_revision(repository, [_rule("existing")], "base")
    after = _write_revision(repository, [_rule("a-new"), _rule("existing")], "candidate")

    first = rule_changes.compare(repository, before=before, after=after)
    second = rule_changes.compare(repository, before=before, after=after)

    assert first["changeSetDigest"] == second["changeSetDigest"]
    assert len(first["changeSetDigest"]) == 64


def test_changes_detects_source_only_implementation_change(repository: Path) -> None:
    before = _write_revision(repository, [_rule("sample")], "base")
    source = repository / "packages/python/src/rules/sample.py"
    source.write_text("# changed implementation\n", encoding="utf-8")
    _git(repository, "add", ".")
    _git(repository, "commit", "-m", "change implementation")
    after = _git(repository, "rev-parse", "HEAD")

    result = rule_changes.compare(repository, before=before, after=after)

    assert [(item["kind"], item["key"]) for item in result["changes"]] == [("implementation-changed", "python:sample")]


def test_changes_fails_when_inventory_and_catalog_disagree(repository: Path) -> None:
    before = _write_revision(repository, [_rule("existing")], "base")
    after = _write_revision(repository, [_rule("existing"), _rule("new")], "candidate")
    inventory = repository / _INVENTORY
    inventory.write_text('{"schemaVersion":1,"rules":[]}\n', encoding="utf-8")
    _git(repository, "add", ".")
    _git(repository, "commit", "-m", "break inventory")
    broken = _git(repository, "rev-parse", "HEAD")

    with pytest.raises(ValueError, match="inventory/catalog disagreement"):
        _ = rule_changes.compare(repository, before=before, after=broken)

    assert after != broken


@pytest.mark.parametrize("mutation", ["extra", "missing"])
def test_changes_rejects_inventory_entries_outside_exact_schema(repository: Path, mutation: str) -> None:
    before = _write_revision(repository, [_rule("existing")], "base")
    inventory_path = repository / _INVENTORY
    first: dict[str, object] = {
        "family": "python",
        "id": "existing",
        "code": "SARJ999",
        "source": "packages/python/src/rules/existing.py",
        "test": "packages/python/tests/rules/test_existing.py",
    }
    if mutation == "extra":
        first["owner"] = "standards"
    else:
        del first["test"]
    inventory: dict[str, object] = {"schemaVersion": 1, "rules": [first]}
    inventory_path.write_text(json.dumps(inventory, sort_keys=True) + "\n", encoding="utf-8")
    _git(repository, "add", ".")
    _git(repository, "commit", "-m", f"inventory {mutation} field")
    broken = _git(repository, "rev-parse", "HEAD")

    with pytest.raises(ValueError, match="inventory entry 1 has unexpected or missing fields"):
        _ = rule_changes.compare(repository, before=before, after=broken)


def test_cli_emits_versioned_json(repository: Path, capsys: pytest.CaptureFixture[str]) -> None:
    before = _write_revision(repository, [], "base")
    after = _write_revision(repository, [_rule("new-rule")], "candidate")

    status = main(
        [
            "--root",
            str(repository),
            "maintain",
            "rules",
            "changes",
            "--before",
            before,
            "--after",
            after,
            "--format",
            "json",
        ]
    )

    assert status == 0
    payload: dict[str, object] = json.loads(capsys.readouterr().out)  # pyright: ignore[reportAny]
    assert payload["schemaVersion"] == 1
    assert payload["changes"]


def test_cli_rejects_missing_revision(repository: Path, capsys: pytest.CaptureFixture[str]) -> None:
    current = _write_revision(repository, [], "base")

    status = main(
        [
            "--root",
            str(repository),
            "maintain",
            "rules",
            "changes",
            "--before",
            "missing",
            "--after",
            current,
        ]
    )

    assert status == 2
    assert "cannot compare rule revisions" in capsys.readouterr().err
