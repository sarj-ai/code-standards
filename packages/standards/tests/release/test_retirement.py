from __future__ import annotations

from pathlib import Path

import pytest

from sarj_standards.libs.adoption import retired_suppressions
from sarj_standards.libs.release import retirement, rollout


SOURCE_FIXTURE = Path(__file__).parents[1] / "fixtures" / "retirement" / "guard.py.txt"


def test_canonical_retirement_removes_only_retired_suppression(tmp_path: Path) -> None:
    source = tmp_path / "guard.py"
    source.write_bytes(SOURCE_FIXTURE.read_bytes())
    expected = retirement.expected_rewrites(tmp_path, frozenset())
    assert expected == {"guard.py": b"import logging\n"}
    source.write_bytes(expected["guard.py"])
    permitted = retirement.validate_rewrites(tmp_path, expected)
    rollout.reject_unsafe_diff(("guard.py",), allowed_source_paths=permitted)


@pytest.mark.parametrize(
    "replacement",
    [b"import os\n", b"import logging\nraise RuntimeError()\n", SOURCE_FIXTURE.read_bytes()],
    ids=["changed-import", "added-executable-code", "unmigrated-suppression"],
)
def test_source_edits_and_unmigrated_suppression_are_rejected(tmp_path: Path, replacement: bytes) -> None:
    source = tmp_path / "guard.py"
    source.write_bytes(SOURCE_FIXTURE.read_bytes())
    expected = retirement.expected_rewrites(tmp_path, frozenset())
    source.write_bytes(replacement)
    with pytest.raises(ValueError, match="canonical rewrite"):
        retirement.validate_rewrites(tmp_path, expected)


def test_retirement_baseline_cannot_gain_allowances(tmp_path: Path) -> None:
    baseline = tmp_path / "suppression-baseline.json"
    baseline.write_bytes(SOURCE_FIXTURE.with_name("suppression-baseline.json.txt").read_bytes())
    expected = retirement.expected_rewrites(tmp_path, frozenset())
    assert set(expected) == {"suppression-baseline.json"}
    baseline.write_bytes(expected[baseline.name])
    assert retirement.validate_rewrites(tmp_path, expected) == frozenset({baseline.name})
    baseline.write_bytes(expected[baseline.name].replace(b'"noqa:F401": 2', b'"noqa:F401": 3'))
    with pytest.raises(ValueError, match="canonical rewrite"):
        retirement.validate_rewrites(tmp_path, expected)


def test_unrelated_source_and_active_suppressions_remain_protected(tmp_path: Path) -> None:
    (tmp_path / "active.py").write_text("import logging  # noqa: F401\n")
    assert retirement.expected_rewrites(tmp_path, frozenset()) == {}
    with pytest.raises(rollout.RolloutError, match="protected paths"):
        rollout.reject_unsafe_diff(("active.py",))


def test_managed_files_are_not_added_to_retirement_permissions(tmp_path: Path) -> None:
    (tmp_path / "guard.py").write_bytes(SOURCE_FIXTURE.read_bytes())
    assert retirement.expected_rewrites(tmp_path, frozenset({"guard.py"})) == {}


def test_deleted_retirement_target_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="canonical rewrite"):
        retirement.validate_rewrites(tmp_path, {"missing.py": b"import logging\n"})


def test_symlink_retirement_target_is_rejected(tmp_path: Path) -> None:
    original = tmp_path / "original.py"
    original.write_bytes(b"import logging\n")
    (tmp_path / "guard.py").symlink_to(original)
    with pytest.raises(ValueError, match="canonical rewrite"):
        retirement.validate_rewrites(tmp_path, {"guard.py": original.read_bytes()})


def test_mismatched_controller_cannot_authorize_retirement(tmp_path: Path) -> None:
    (tmp_path / "guard.py").write_bytes(SOURCE_FIXTURE.read_bytes())
    with pytest.raises(ValueError, match="exact target bundle"):
        retirement.expected_rewrites(tmp_path, frozenset(), target_version="0.0.0")


@pytest.mark.parametrize("suffix", [".tf", ".hcl", ".tfvars", ".ts", ".tsx"])
def test_other_source_languages_remain_protected(tmp_path: Path, suffix: str) -> None:
    target = tmp_path / f"guard{suffix}"
    target.write_bytes(SOURCE_FIXTURE.read_bytes())
    assert retirement.expected_rewrites(tmp_path, frozenset()) == {}
    with pytest.raises(rollout.RolloutError, match="protected paths"):
        rollout.reject_unsafe_diff((target.name,))


@pytest.mark.parametrize("opener", ["<<EOF", "<<-EOF", "<<END-MARKER", '<<"EOF"'])
@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_canonical_cleanup_preserves_hcl_heredoc_payload(tmp_path: Path, opener: str, newline: str) -> None:
    target = tmp_path / "main.tf"
    payload = SOURCE_FIXTURE.read_text().split("#", maxsplit=1)[1].strip()
    contents = newline.join((f"value = {opener}", f"# {payload}", f"// {payload}", "EOF", ""))
    target.write_bytes(contents.encode())
    assert retired_suppressions.plan((target,)) == ()
    assert target.read_bytes() == contents.encode()
