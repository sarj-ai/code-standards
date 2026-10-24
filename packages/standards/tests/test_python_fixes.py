from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
import subprocess
from typing import TYPE_CHECKING

import pytest

from sarj_standards import api
from sarj_standards.cli.main import main
from sarj_standards.libs.adoption import doctor, lifecycle
from sarj_standards.libs.adoption.manifest import ExclusionOverride, Manifest
from sarj_standards.libs.adoption.transaction import FileTransaction
from sarj_standards.libs.diagnostics import Completion, FixSafety, Severity, to_json, to_sarif
from sarj_standards.libs.linting.analysis import analyze
from sarj_standards.libs.linting.policy import Policy
from sarj_standards.libs.linting.python_fixes import fix_python
from sarj_standards.libs.rules import RuleSelection


if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path


SOURCE = "def render(item):\n    payload = item\n    return dict(payload=payload)\n"
FIXED = "def render(item):\n    return dict(payload=item)\n"
SELECTION = RuleSelection.from_values(("python:no-redundant-local-alias",))
MANIFEST = Manifest(api.__version__, ("ruff",), ".", ".")


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (SOURCE, FIXED),
        (SOURCE.replace("\n", "\r\n"), FIXED.replace("\n", "\r\n")),
        (SOURCE.replace("item", "\u00e9l\u00e9ment"), FIXED.replace("item", "\u00e9l\u00e9ment")),
    ],
    ids=("lf", "crlf", "unicode"),
)
def test_report_safe_python_edits(tmp_path: Path, source: str, expected: str) -> None:
    path = tmp_path / "case.py"
    raw = source.encode("utf-8")
    path.write_bytes(raw)
    report = analyze([str(path)], root=tmp_path, rule_selection=SELECTION)
    assert report.completion is Completion.COMPLETE
    [diagnostic] = report.diagnostics
    assert diagnostic.severity is Severity.WARNING
    [fix] = diagnostic.fixes
    assert fix.safety is FixSafety.SAFE
    changed = raw
    for edit in reversed(fix.edits):
        region = edit.location.region
        assert region is not None
        assert edit.expected_text_hash == sha256(raw[region.start.byte_offset : region.end.byte_offset]).hexdigest()
        changed = (
            changed[: region.start.byte_offset] + edit.replacement.encode("utf-8") + changed[region.end.byte_offset :]
        )
    assert changed == expected.encode("utf-8")
    assert '"fixes"' in to_json(report)
    assert '"fixes"' in to_sarif(report)
    assert path.read_bytes() == raw


def test_apply_native_fix_preserves_mode_and_converges(tmp_path: Path) -> None:
    path = tmp_path / "case.py"
    path.write_text(SOURCE)
    path.chmod(0o755)
    policy = Policy.from_manifest(tmp_path, None)
    assert fix_python([str(path)], root=tmp_path, policy=policy) == 1
    assert path.read_text() == FIXED
    assert path.stat().st_mode & 0o777 == 0o755
    assert fix_python([str(path)], root=tmp_path, policy=policy) == 0


def test_facade_fixes_before_upstream_commands(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "case.py"
    path.write_text(SOURCE)
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "example"\nversion = "0.0.0"\n')

    def execute(commands: Sequence[lifecycle.Command]) -> int:
        assert commands
        assert path.read_text() == FIXED
        return 0

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- Intercepts the real dispatch boundary; injection would skip it.
        lifecycle, "execute", execute
    )
    assert api.Standards(tmp_path).fix().ok


def test_cli_fixes_before_upstream_commands(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "case.py"
    path.write_text(SOURCE)

    def execute(commands: Sequence[lifecycle.Command]) -> int:
        assert commands
        assert path.read_text() == FIXED
        return 0

    def diagnose(_root: Path) -> list[doctor.Finding]:
        return []

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- Isolates CLI lookup from adoption; Git selection stays real.
        doctor, "diagnose", diagnose
    )
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- Intercepts the real dispatch boundary; injection would skip it.
        lifecycle, "execute", execute
    )
    monkeypatch.chdir(tmp_path)
    assert main(["fix", "case.py"]) == 0


@pytest.mark.parametrize(
    "manifest",
    [
        replace(MANIFEST, excluded_paths=("case.py",)),
        replace(MANIFEST, excluded_rules=("python:SARJ531",)),
        replace(MANIFEST, excluded_rules=("python:no-redundant-local-alias",)),
        replace(
            MANIFEST, exclusion_overrides=(ExclusionOverride(("case.py",), ("python:SARJ531",), "Reviewed boundary"),)
        ),
    ],
    ids=("path-off", "code-off", "id-off", "path-override"),
)
def test_policy_preserves_excluded_source(tmp_path: Path, manifest: Manifest) -> None:
    path = tmp_path / "case.py"
    path.write_text(SOURCE)
    assert fix_python([str(path)], root=tmp_path, policy=Policy.from_manifest(tmp_path, manifest)) == 0
    assert path.read_text() == SOURCE


@pytest.mark.parametrize(
    ("name", "source"),
    [
        ("case.pyi", SOURCE),
        ("case.py", "# Generated by a deterministic compiler.\n" + SOURCE),
        ("case.py", SOURCE.replace("payload = item", "payload = item  # sarj-noqa: SARJ531 -- Reviewed boundary")),
    ],
)
def test_suppressed_or_owned_source_is_preserved(tmp_path: Path, name: str, source: str) -> None:
    path = tmp_path / name
    path.write_text(source)
    assert fix_python([str(path)], root=tmp_path, policy=Policy.from_manifest(tmp_path, None)) == 0
    assert path.read_text() == source


@pytest.mark.parametrize(
    ("source", "expected", "encoding"),
    [
        (SOURCE, FIXED, "utf-8-sig"),
        (SOURCE.replace("\n", "\r\n"), FIXED.replace("\n", "\r\n"), "utf-8"),
        (SOURCE.replace("\n", "\r"), FIXED.replace("\n", "\r"), "utf-8"),
        (SOURCE.rstrip("\n"), FIXED.rstrip("\n"), "utf-8"),
        (SOURCE.replace("    ", "\t"), FIXED.replace("    ", "\t"), "utf-8"),
        (
            SOURCE.replace("dict(payload=payload)", "dict(\n        payload=payload,\n    )"),
            FIXED.replace("dict(payload=item)", "dict(\n        payload=item,\n    )"),
            "utf-8",
        ),
        ("# coding: utf-8\n" + SOURCE, "# coding: utf-8\n" + FIXED, "utf-8"),
        ("# coding: latin-1\n" + SOURCE, "# coding: latin-1\n" + SOURCE, "latin-1"),
    ],
)
def test_file_edits_preserve_bytes(tmp_path: Path, source: str, expected: str, encoding: str) -> None:
    path = tmp_path / "case.py"
    path.write_bytes(source.encode(encoding))
    assert fix_python([str(path)], root=tmp_path, policy=Policy.from_manifest(tmp_path, None)) == int(
        source != expected
    )
    assert path.read_bytes() == expected.encode(encoding)


def test_failed_batch_rolls_back_owned_writes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    first = tmp_path / "alpha.py"
    last = tmp_path / "beta.py"
    for path in (first, last):
        path.write_text(SOURCE)
        path.chmod(0o755)
    original = FileTransaction.write_bytes

    def write(transaction: FileTransaction, path: Path, contents: bytes) -> None:
        if path == last:
            msg = "simulated second write failure"
            raise OSError(msg)
        original(transaction, path, contents)

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- Injects a race or failure at the actual writer under test.
        FileTransaction, "write_bytes", write
    )
    with pytest.raises(OSError, match="simulated second"):
        fix_python([str(first), str(last)], root=tmp_path, policy=Policy.from_manifest(tmp_path, None))
    for path in (first, last):
        assert path.read_text() == SOURCE
        assert path.stat().st_mode & 0o777 == 0o755


def test_stale_source_preserves_concurrent_edit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    first = tmp_path / "alpha.py"
    last = tmp_path / "beta.py"
    for path in (first, last):
        path.write_text(SOURCE)
    concurrent = SOURCE + "unrelated = 1\n"
    original = FileTransaction.write_bytes

    def write(transaction: FileTransaction, path: Path, contents: bytes) -> None:
        if path == last:
            last.write_text(concurrent)
        original(transaction, path, contents)

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- Injects a race or failure at the actual writer under test.
        FileTransaction, "write_bytes", write
    )
    with pytest.raises(OSError, match="changed concurrently"):
        fix_python([str(first), str(last)], root=tmp_path, policy=Policy.from_manifest(tmp_path, None))
    assert first.read_text() == SOURCE
    assert last.read_text() == concurrent


@pytest.mark.parametrize("kind", ["symlink", "symlink-parent", "hardlink", "outside"])
def test_linked_and_outside_targets_are_preserved(tmp_path: Path, kind: str) -> None:
    root = tmp_path / "project"
    root.mkdir()
    outside = tmp_path / "outside.py"
    outside.write_text(SOURCE)
    path = root / "case.py"
    match kind:
        case "symlink":
            path.symlink_to(outside)
        case "symlink-parent":
            (root / "linked").symlink_to(tmp_path, target_is_directory=True)
            path = root / "linked" / outside.name
        case "hardlink":
            path.hardlink_to(outside)
        case _:
            path = outside
    with pytest.raises((OSError, ValueError), match=r"symlink|hard-linked|outside|escapes"):
        fix_python([str(path)], root=root, policy=Policy.from_manifest(root, None))
    assert outside.read_text() == SOURCE


@pytest.mark.parametrize("stale", [False, True])
def test_staged_fix_respects_index_selection(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, stale: bool) -> None:
    subprocess.run(("git", "init", "--quiet", str(tmp_path)), check=True, capture_output=True, shell=False)
    selected = tmp_path / "selected.py"
    other = tmp_path / "other.py"
    selected.write_text(SOURCE)
    other.write_text(SOURCE)
    subprocess.run(("git", "-C", str(tmp_path), "add", "selected.py"), check=True, capture_output=True, shell=False)
    if stale:
        selected.write_text(SOURCE + "unrelated = 1\n")

    def diagnose(_root: Path) -> list[doctor.Finding]:
        return []

    commands_seen: list[lifecycle.Command] = []

    def execute(commands: Sequence[lifecycle.Command]) -> int:
        commands_seen.extend(commands)
        return 0

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- Isolates CLI lookup from adoption; Git selection stays real.
        doctor, "diagnose", diagnose
    )
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- Intercepts the real dispatch boundary; injection would skip it.
        lifecycle, "execute", execute
    )
    assert main(["--root", str(tmp_path), "fix", "--staged"]) == (2 if stale else 0)
    assert selected.read_text() == (SOURCE + "unrelated = 1\n" if stale else FIXED)
    assert other.read_text() == SOURCE
    assert bool(commands_seen) is not stale


@pytest.mark.parametrize(
    ("name", "data"),
    [
        ("large.ts", b"// " + b"x" * 2_097_152),
        ("large.yml", b"# " + b"x" * 2_097_152),
        ("legacy.py", b"\xff\xfe"),
        ("legacy.py", SOURCE.encode()),
    ],
    ids=("large-typescript", "large-yaml", "undecodable-python", "unowned-python"),
)
def test_eslint_only_default_fix_preserves_python_ownership(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str, data: bytes
) -> None:
    (tmp_path / "package.json").write_text('{"name":"example","private":true}\n')
    adopted = replace(MANIFEST, configs=("eslint",))
    (tmp_path / ".sarj-standards.toml").write_text(adopted.render())
    path = tmp_path / name
    path.write_bytes(data)
    dispatched: list[lifecycle.Command] = []

    def execute(commands: Sequence[lifecycle.Command]) -> int:
        dispatched.extend(commands)
        return 0

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- Intercepts the actual dispatcher to verify ownership and pre-dispatch failures.
        lifecycle, "execute", execute
    )
    assert api.Standards(tmp_path).fix().ok
    assert dispatched
    assert path.read_bytes() == data


def test_explicit_typescript_fix_ignores_unrelated_python(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "package.json").write_text('{"name":"example","private":true}\n')
    path = tmp_path / "large.ts"
    data = b"// " + b"x" * 2_097_152
    path.write_bytes(data)
    (tmp_path / "legacy.py").write_bytes(b"\xff\xfe")

    def diagnose(_root: Path) -> list[doctor.Finding]:
        return []

    def execute(commands: Sequence[lifecycle.Command]) -> int:
        assert commands
        return 0

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- Isolates CLI lookup from adoption; source selection stays real.
        doctor, "diagnose", diagnose
    )
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- Intercepts the actual dispatcher to verify selected-language routing.
        lifecycle, "execute", execute
    )
    assert main(["--root", str(tmp_path), "fix", "large.ts"]) == 0
    assert path.read_bytes() == data


def test_default_fix_stays_within_adopted_python_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    backend = tmp_path / "backend"
    backend.mkdir()
    (backend / "pyproject.toml").write_text('[project]\nname = "example"\nversion = "0.0.0"\n')
    (backend / "case.py").write_text(SOURCE)
    (tmp_path / "legacy.py").write_text(SOURCE)
    (tmp_path / "invalid.py").write_bytes(b"\xff\xfe")
    (tmp_path / ".sarj-standards.toml").write_text(replace(MANIFEST, python_dest="backend").render())

    def execute(commands: Sequence[lifecycle.Command]) -> int:
        assert commands
        return 0

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- Intercepts formatter dispatch to verify actual native ownership boundaries.
        lifecycle, "execute", execute
    )
    assert api.Standards(tmp_path).fix().ok
    assert (backend / "case.py").read_text() == FIXED
    assert (tmp_path / "legacy.py").read_text() == SOURCE
    assert (tmp_path / "invalid.py").read_bytes() == b"\xff\xfe"
