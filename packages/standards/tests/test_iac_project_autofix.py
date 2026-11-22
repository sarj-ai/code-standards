from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
import subprocess

import pytest

from sarj_standards.cli.main import main
from sarj_standards.libs.adoption import manifest, transaction
from sarj_standards.libs.linting import autofix
from sarj_standards.libs.linting.iac_guard_contracts import CoreIAC
from sarj_standards.libs.linting.policy import Policy
from sarj_standards.libs.staged_git import isolated_environment


def _git(root: Path, *arguments: str) -> bytes:
    return subprocess.check_output(("git", "-C", str(root), *arguments), env=isolated_environment(), timeout=10)


@dataclass(frozen=True, slots=True)
class _Fixture:
    source: Path
    target: Path


def _repository(root: Path) -> _Fixture:
    _git(root, "init", "--quiet", "--template=")
    _git(root, "config", "core.hooksPath", str(root / ".git/hooks"))
    _git(root, "config", "user.name", "Private fixture")
    _git(root, "config", "user.email", "fixture@example.invalid")
    (root / "retained.tf").write_text('locals { retained = "owned" }\n')
    _git(root, "add", ".")
    _git(root, "commit", "--quiet", "-m", "fixture")
    source = root / "service.tf"
    target = root / "variables.tf"
    source.write_text('variable "region" { type = string }\nresource "terraform_data" "this" { input = var.region }\n')
    target.write_text('variable "project" { type = string }\n')
    _git(root, "add", ".")
    return _Fixture(source, target)


@pytest.mark.parametrize("staged", [False, True])
@pytest.mark.parametrize("prefix", [b"", b"\xef\xbb\xbf"])
def test_project_fixes_use_one_transaction_preserve_bytes_and_converge(
    tmp_path: Path, *, staged: bool, prefix: bytes
) -> None:
    fixture = _repository(tmp_path)
    for path in (fixture.source, fixture.target):
        path.write_bytes(prefix + path.read_bytes().replace(b"\n", b"\r\n"))
        path.chmod(0o640)
    _git(tmp_path, "add", ".")
    index_before = _git(tmp_path, "write-tree")

    assert set(autofix.fix_paths(tmp_path, (str(fixture.source), str(fixture.target)), staged=staged)) == {
        fixture.source,
        fixture.target,
    }
    assert fixture.source.read_bytes() == prefix + b'resource "terraform_data" "this" { input = var.region }\r\n'
    assert fixture.target.read_bytes().startswith(prefix)
    assert b'variable "region"' in fixture.target.read_bytes()
    assert all(path.stat().st_mode & 0o777 == 0o640 for path in (fixture.source, fixture.target))
    assert _git(tmp_path, "write-tree") == index_before
    _git(tmp_path, "add", ".")
    assert autofix.fix_paths(tmp_path, (str(fixture.source), str(fixture.target)), staged=staged) == ()


def test_policy_exclusion_or_unselected_destination_refuses_movement(tmp_path: Path) -> None:
    fixture = _repository(tmp_path)
    original = fixture.source.read_bytes(), fixture.target.read_bytes()
    adopted = manifest.Manifest(
        manifest.adopted_version(), (), ".", ".", excluded_rules=("iac:canonical-terraform-declarations",)
    )
    policy = Policy.from_manifest(tmp_path, adopted)

    assert autofix.fix_paths(tmp_path, (str(fixture.source), str(fixture.target)), policy=policy) == ()
    assert autofix.fix_paths(tmp_path, (str(fixture.source),)) == ()
    assert (fixture.source.read_bytes(), fixture.target.read_bytes()) == original


def test_unstaged_module_context_cannot_qualify_a_staged_move(tmp_path: Path) -> None:
    fixture = _repository(tmp_path)
    (tmp_path / "retained.tf").write_text('locals { retained = "unstaged" }\n')
    original = fixture.source.read_bytes(), fixture.target.read_bytes()

    with pytest.raises(ValueError, match="module context differs"):
        autofix.fix_paths(tmp_path, (str(fixture.source), str(fixture.target)), staged=True)
    assert (fixture.source.read_bytes(), fixture.target.read_bytes()) == original


def test_real_staged_cli_fixes_both_files_and_requires_review_without_staging(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fixture = _repository(tmp_path)
    before = _git(tmp_path, "write-tree")

    assert main(["--root", str(tmp_path), "check", "--staged", "--fix", "--trust-repository-code"]) == 1

    assert "Safe fixes applied" in capsys.readouterr().err
    assert 'variable "region"' not in fixture.source.read_text()
    assert 'variable "region"' in fixture.target.read_text()
    assert _git(tmp_path, "write-tree") == before
    _git(tmp_path, "add", ".")
    assert autofix.fix_paths(tmp_path, (str(fixture.source), str(fixture.target)), staged=True) == ()


@pytest.mark.parametrize("change", ["source", "membership", "index"])
def test_stale_module_preconditions_fail_before_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    fixture = _repository(tmp_path)
    original = fixture.source.read_bytes(), fixture.target.read_bytes()
    capture = transaction.FileTransaction.capture

    def concurrent_capture(
        root: Path, paths: tuple[Path, ...], *, mode: transaction.CaptureMode
    ) -> transaction.FileTransaction:
        if change == "source":
            (root / "retained.tf").write_text('locals { retained = "concurrent" }\n')
        elif change == "membership":
            (root / "new.tf").write_text("locals {}\n")
        else:
            (root / "unrelated.txt").write_text("new staged content\n")
            _git(root, "add", "unrelated.txt")
        return capture(root, paths, mode=mode)

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- inject a real concurrent edit at capture; retain real planning, validation and file writes.
        transaction.FileTransaction, "capture", concurrent_capture
    )
    with pytest.raises((OSError, ValueError), match="changed"):
        autofix.fix_paths(tmp_path, (str(fixture.source), str(fixture.target)), staged=True)
    assert (fixture.source.read_bytes(), fixture.target.read_bytes()) == original
    if change == "source":
        assert "concurrent" in (tmp_path / "retained.tf").read_text()


def test_a_failed_second_write_rolls_back_the_first_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fixture = _repository(tmp_path)
    original = fixture.source.read_bytes(), fixture.target.read_bytes()
    write = transaction.FileTransaction.write_bytes
    calls: list[Path] = []

    def fail_second(self: transaction.FileTransaction, path: Path, contents: bytes) -> None:
        calls.append(path)
        if len(calls) == 2:
            message = "injected second write failure"
            raise OSError(message)
        write(self, path, contents)

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- fail the actual second transaction write after the first has published; exercise real rollback.
        transaction.FileTransaction, "write_bytes", fail_second
    )
    with pytest.raises(OSError, match="second write"):
        autofix.fix_paths(tmp_path, (str(fixture.source), str(fixture.target)))
    assert (fixture.source.read_bytes(), fixture.target.read_bytes()) == original


def test_existing_immutable_guard_contracts_refuse_redundant_validation_deletion(tmp_path: Path) -> None:
    _repository(tmp_path)
    guarded = tmp_path / "guarded.tf"
    guarded.write_text(
        'variable "value" {\n type = string\n nullable = false\n validation {\n condition = var.value != null\n error_message = "Preserve the existing contract."\n }\n}\n'
    )
    adopted = manifest.Manifest(manifest.adopted_version(), (), ".", ".")
    (tmp_path / manifest.MANIFEST_NAME).write_text(adopted.render())
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "--quiet", "-m", "guard baseline")
    revision = _git(tmp_path, "rev-parse", "HEAD").decode().strip()
    content = CoreIAC(tmp_path).initialize(("guarded.tf",), original_revision=revision)
    (tmp_path / ".sarj-terraform-guards.json").write_text(content)
    (tmp_path / manifest.MANIFEST_NAME).write_text(
        replace(adopted, terraform_guard_contracts=".sarj-terraform-guards.json").render()
    )
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "--quiet", "-m", "existing guard contract")
    original = guarded.read_bytes()

    assert autofix.fix_paths(tmp_path, (str(guarded),), staged=True) == ()
    assert guarded.read_bytes() == original


@pytest.mark.parametrize("override", ["override.tf", "nullable_override.tf.json"])
@pytest.mark.parametrize("staged", [False, True])
def test_module_overrides_refuse_guard_removal_without_silencing_its_diagnostic(
    tmp_path: Path, override: str, *, staged: bool
) -> None:
    _repository(tmp_path)
    path = tmp_path / "variables.tf"
    source = 'variable "value" {\n  type = string\n  nullable = false\n  validation {\n    condition = var.value != null\n    error_message = "Required."\n  }\n}\n'
    path.write_text(source)
    (tmp_path / override).write_text(
        '{"variable":{"value":{"nullable":true}}}'
        if override.endswith(".json")
        else 'variable "value" { nullable = true }\n'
    )
    _git(tmp_path, "add", ".")

    assert autofix.fix_paths(tmp_path, (str(path),), staged=staged) == ()
    assert path.read_text() == source
