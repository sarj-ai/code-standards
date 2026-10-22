from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
import subprocess

import pytest

from sarj_standards import api
from sarj_standards.libs.adoption.manifest import MANIFEST_NAME, Manifest
from sarj_standards.libs.diagnostics import baseline


_RULES = ("python:no-excessive-cognitive-complexity",)


def _git(root: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments], cwd=root, text=True, capture_output=True, check=True, shell=False
    ).stdout.strip()


def _function(name: str = "complexity") -> str:
    return f"def {name}(value):\n" + "".join(f"    if value == {index}:\n        value += 1\n" for index in range(21))


@dataclass(frozen=True, slots=True)
class _Subject:
    target: Path
    baseline: bytes


def _subject(root: Path, source: str, *, missing_base: bool = False) -> _Subject:
    target = root / "app.py"
    target.write_text(source, encoding="utf-8")
    _git(root, "init", "--quiet")
    _git(root, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "add", "app.py")
    _git(
        root,
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "commit",
        "--quiet",
        "-m",
        "fixture",
    )
    raw = api.Standards(root).analyze([str(target)], mode=api.AnalysisMode.RAW, rules=_RULES)
    assert raw.diagnostics
    document = baseline.render(
        raw.diagnostics,
        bundle_version=api.__version__,
        consumer_base_sha="f" * 40 if missing_base else _git(root, "rev-parse", "HEAD"),
        catalog_digest=baseline.bundled_catalog_digest(),
    )
    (root / "diagnostic-baseline.json").write_text(document, encoding="utf-8")
    manifest = Manifest(
        version=api.__version__,
        configs=(),
        python_dest=".",
        typescript_dest=".",
        hook_manager="none",
        diagnostic_baseline="diagnostic-baseline.json",
    )
    (root / MANIFEST_NAME).write_text(manifest.render(), encoding="utf-8")
    return _Subject(target, document.encode())


@pytest.mark.parametrize("owner", ["module", "class", "nested"], ids=["module", "class", "nested"])
def test_position_only_changes_reuse_exact_provenance_budget(tmp_path: Path, owner: str) -> None:
    source = _function()
    if owner == "class":
        source = "class Owner:\n" + "".join("    " + line + "\n" for line in source.splitlines())
    elif owner == "nested":
        source = "def outer():\n" + "".join("    " + line + "\n" for line in source.splitlines())
    subject = _subject(tmp_path, source)
    target = subject.target
    target.write_text("# unrelated prefix\n\n" + source, encoding="utf-8")
    _git(tmp_path, "add", "app.py")

    raw = api.Standards(tmp_path).analyze([str(target)], mode=api.AnalysisMode.RAW, rules=_RULES)
    policy = api.Standards(tmp_path).analyze([str(target)], staged=True, rules=_RULES)

    assert raw.diagnostics[0].message.startswith("Cognitive complexity 21 exceeds 20.")
    assert "Largest contributors: L" in raw.diagnostics[0].message
    assert policy.diagnostics == ()
    assert policy.issues == ()
    assert sum(tool.baselined_count for tool in policy.tools) == 1
    assert (tmp_path / "diagnostic-baseline.json").read_bytes() == subject.baseline


def test_exact_legacy_fingerprint_is_required(tmp_path: Path) -> None:
    source = _function()
    subject = _subject(tmp_path, source)
    target = subject.target
    raw = api.Standards(tmp_path).analyze([str(target)], mode=api.AnalysisMode.RAW, rules=_RULES)
    document = baseline.render(
        (replace(raw.diagnostics[0], fingerprint="a" * 64),),
        bundle_version=api.__version__,
        consumer_base_sha=_git(tmp_path, "rev-parse", "HEAD"),
        catalog_digest=baseline.bundled_catalog_digest(),
    )
    (tmp_path / "diagnostic-baseline.json").write_text(document, encoding="utf-8")
    target.write_text("# prefix\n\n" + source, encoding="utf-8")

    policy = api.Standards(tmp_path).analyze([str(target)], rules=_RULES)

    assert len(policy.diagnostics) == 1
    assert (tmp_path / "diagnostic-baseline.json").read_text(encoding="utf-8") == document


def test_replaced_git_blobs_cannot_substitute_the_provenance_owner(tmp_path: Path) -> None:
    source = _function()
    subject = _subject(tmp_path, source)
    target = subject.target
    original_oid = _git(tmp_path, "rev-parse", "HEAD:app.py")
    changed = source.replace("value == 0", "value == 100")
    target.write_text(changed, encoding="utf-8")
    replacement = _git(tmp_path, "hash-object", "-w", "app.py")
    _git(tmp_path, "replace", original_oid, replacement)
    target.write_text("# prefix\n\n" + changed, encoding="utf-8")

    policy = api.Standards(tmp_path).analyze([str(target)], rules=_RULES)

    assert len(policy.diagnostics) == 1
    assert (tmp_path / "diagnostic-baseline.json").read_bytes() == subject.baseline


@pytest.mark.parametrize(
    "change",
    ["body", "name", "scope", "duplicate", "new-finding", "touched-owner"],
    ids=["body", "name", "scope", "duplicate", "new-finding", "touched-owner"],
)
def test_changed_or_ambiguous_owners_remain_active(tmp_path: Path, change: str) -> None:
    source = _function()
    subject = _subject(tmp_path, source)
    target = subject.target
    match change:
        case "body":
            changed = source.replace("value == 0", "value == 100")
        case "name":
            changed = source.replace("def complexity", "def renamed")
        case "scope":
            changed = "class Owner:\n" + "".join("    " + line + "\n" for line in source.splitlines())
        case "duplicate":
            changed = source + "\n" + source
        case "new-finding":
            changed = source + "\n" + _function("new_complexity")
        case _:
            changed = source.replace("def complexity(value):", "def complexity(value):  # touched")
    target.write_text("# prefix\n\n" + changed, encoding="utf-8")
    _git(tmp_path, "add", "app.py")

    policy = api.Standards(tmp_path).analyze([str(target)], staged=change == "touched-owner", rules=_RULES)

    assert policy.diagnostics
    assert all(item.code == "SARJ444" for item in policy.diagnostics)
    assert (tmp_path / "diagnostic-baseline.json").read_bytes() == subject.baseline


def test_missing_provenance_does_not_create_a_budget(tmp_path: Path) -> None:
    source = _function()
    subject = _subject(tmp_path, source, missing_base=True)
    target = subject.target
    target.write_text("# prefix\n\n" + source, encoding="utf-8")

    policy = api.Standards(tmp_path).analyze([str(target)], rules=_RULES)

    assert len(policy.diagnostics) == 1
    assert policy.issues == ()
    assert (tmp_path / "diagnostic-baseline.json").read_bytes() == subject.baseline


def test_unexpected_git_tree_failure_stays_observable_and_recovers(tmp_path: Path) -> None:
    source = _function("unavailable_git_tree")
    subject = _subject(tmp_path, source)
    subject.target.write_text("# prefix\n\n" + source, encoding="utf-8")
    tree_oid = _git(tmp_path, "rev-parse", "HEAD^{tree}")
    tree = tmp_path / ".git" / "objects" / tree_oid[:2] / tree_oid[2:]
    unavailable = tmp_path / "unavailable-tree"
    tree.rename(unavailable)
    try:
        assert _git(tmp_path, "cat-file", "-t", "HEAD") == "commit"
        policy = api.Standards(tmp_path).analyze([str(subject.target)], rules=_RULES)
    finally:
        unavailable.rename(tree)

    assert len(policy.diagnostics) == 1
    assert len(policy.issues) == 1
    assert policy.issues[0].kind == "baseline-compatibility-failure"
    assert "128" in policy.issues[0].message
    assert sum(tool.baselined_count for tool in policy.tools) == 0
    recovered = api.Standards(tmp_path).analyze([str(subject.target)], rules=_RULES)
    assert recovered.diagnostics == ()
    assert recovered.issues == ()
    assert sum(tool.baselined_count for tool in recovered.tools) == 1
    assert (tmp_path / "diagnostic-baseline.json").read_bytes() == subject.baseline
