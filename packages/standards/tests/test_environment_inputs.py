from __future__ import annotations

import json
import subprocess
from typing import TYPE_CHECKING

import pytest

from sarj_standards.libs.adoption import manifest, transaction
from sarj_standards.libs.diagnostics import Completion, baseline
from sarj_standards.libs.linting import autofix
from sarj_standards.libs.linting.analysis import analyze
from sarj_standards.libs.linting.devops_tools import checked_tool
from sarj_standards.libs.linting.external import run_process_input
from sarj_standards.libs.linting.policy import Policy
from sarj_standards.libs.rules import RuleSelection
from sarj_standards.libs.staged_git import isolated_environment


if TYPE_CHECKING:
    from pathlib import Path


_INPUT_RULE = "iac:no-unused-module-inputs"
_TFVARS_RULE = "iac:no-dead-environment-input"


def _git(root: Path, *arguments: str) -> bytes:
    return subprocess.check_output(("git", "-C", str(root), *arguments), env=isolated_environment(), timeout=10)


def _repository(root: Path) -> None:
    _git(root, "init", "--quiet", "--template=")
    _git(root, "config", "core.hooksPath", str(root / ".git/hooks"))
    _git(root, "config", "user.name", "Private fixture")
    _git(root, "config", "user.email", "fixture@example.invalid")
    (root / "variables.tf").write_text('variable "live" { type = bool }\n')
    (root / "terraform.tfvars").write_text("live = false\nretired = true\n")
    _git(root, "add", ".")
    _git(root, "commit", "--quiet", "-m", "fixture")


@pytest.mark.parametrize("staged", [False, True])
def test_complete_source_snapshot_ignores_unstaged_declaration_and_assignment_bytes(
    tmp_path: Path, *, staged: bool
) -> None:
    _repository(tmp_path)
    (tmp_path / "variables.tf").write_text('variable "retired" { type = bool }\n')
    (tmp_path / "terraform.tfvars").write_text("unstaged = true\n")
    report = analyze(
        [],
        root=tmp_path,
        staged=staged,
        use_guard_contracts=False,
        rule_selection=RuleSelection.from_values((_TFVARS_RULE,)),
    )
    assert report.completion is Completion.COMPLETE
    assert len(report.diagnostics) == 1
    finding = report.diagnostics[0]
    assert "`retired`" in finding.message
    assert "unstaged" not in finding.message
    assert finding.severity.value == "warning"


def test_unchanged_callers_are_reanalyzed_when_only_shared_module_is_selected(tmp_path: Path) -> None:
    _repository(tmp_path)
    adopted = manifest.Manifest(manifest.adopted_version(), (), ".", ".", terraform_internal_modules=("child",))
    (tmp_path / manifest.MANIFEST_NAME).write_text(adopted.render())
    (tmp_path / "child").mkdir()
    (tmp_path / "main.tf").write_text(
        'module "child" {\n source = "./child"\n input = true\n}\noutput "live" { value = module.child.live }\n'
    )
    (tmp_path / "child/variables.tf").write_text('variable "input" { type = bool }\n')
    (tmp_path / "child/main.tf").write_text('locals { unused = var.input }\noutput "live" { value = true }\n')
    _git(tmp_path, "add", ".")
    selection = RuleSelection.from_values((_INPUT_RULE,))
    report = analyze(
        [str(tmp_path / "child/variables.tf")],
        root=tmp_path,
        staged=True,
        use_guard_contracts=False,
        rule_selection=selection,
    )
    assert not report.issues
    assert len(report.diagnostics) == 1
    assert report.diagnostics[0].location.path == "child/variables.tf"
    (tmp_path / "child/main.tf").write_text('output "live" { value = var.input }\n')
    _git(tmp_path, "add", ".")
    report = analyze([], root=tmp_path, staged=True, use_guard_contracts=False, rule_selection=selection)
    assert not report.issues
    assert not report.diagnostics


@pytest.mark.parametrize("name", ["terraform.tfvars", "terraform.tfvars.json"])
@pytest.mark.parametrize("staged", [False, True])
def test_transaction_fixes_tracked_inputs_preserves_index_and_converges(
    tmp_path: Path, name: str, *, staged: bool
) -> None:
    _repository(tmp_path)
    path = tmp_path / name
    if name.endswith("json"):
        path.write_text('{"live":false,"retired":true}\n')
        (tmp_path / "terraform.tfvars").unlink()
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "--quiet", "--allow-empty", "-m", "selected inputs")
    index = _git(tmp_path, "write-tree")
    (tmp_path / "notes.txt").write_text("unrelated unstaged work\n")
    assert autofix.fix_paths(tmp_path, (str(path),), staged=staged) == (path,)
    assert _git(tmp_path, "write-tree") == index
    if name.endswith("json"):
        assert json.loads(path.read_text()) == {"live": False}
    else:
        assert path.read_text() == "live = false\n"
    assert (tmp_path / "notes.txt").read_text() == "unrelated unstaged work\n"
    _git(tmp_path, "add", name)
    assert autofix.fix_paths(tmp_path, (str(path),), staged=staged) == ()
    report = analyze(
        [],
        root=tmp_path,
        staged=True,
        use_guard_contracts=False,
        rule_selection=RuleSelection.from_values((_TFVARS_RULE,)),
    )
    assert not report.issues
    assert not report.diagnostics


def test_ignored_private_inputs_and_untracked_declarations_are_preserved(tmp_path: Path) -> None:
    _repository(tmp_path)
    path = tmp_path / "private.auto.tfvars"
    (tmp_path / ".gitignore").write_text(path.name + "\n")
    path.write_text('secret = "private-placeholder"\nretired = true\n')
    before = path.read_bytes()
    assert autofix.fix_paths(tmp_path, (str(path),)) == ()
    assert path.read_bytes() == before
    (tmp_path / "untracked.tf").write_text('variable "retired" { type = bool }\n')
    tracked = tmp_path / "terraform.tfvars"
    before = tracked.read_bytes()
    with pytest.raises(ValueError, match="membership differs"):
        autofix.fix_paths(tmp_path, (str(tracked),))
    assert tracked.read_bytes() == before


def test_staged_fix_rejects_unstaged_context(tmp_path: Path) -> None:
    _repository(tmp_path)
    path = tmp_path / "terraform.tfvars"
    before = path.read_bytes()
    (tmp_path / "variables.tf").write_text('variable "retired" { type = bool }\n')
    with pytest.raises(ValueError, match="differs from the staged index"):
        autofix.fix_paths(tmp_path, (str(path),), staged=True)
    assert path.read_bytes() == before


@pytest.mark.parametrize("change", ["declaration", "index"])
def test_context_changes_before_a_write_are_rejected_without_losing_user_edits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    _repository(tmp_path)
    path = tmp_path / "terraform.tfvars"
    before = path.read_bytes()
    capture = transaction.FileTransaction.capture

    def concurrent_capture(
        root: Path, paths: tuple[Path, ...], *, mode: transaction.CaptureMode
    ) -> transaction.FileTransaction:
        if change == "declaration":
            (root / "variables.tf").write_text('variable "live" { type = bool }\nvariable "retired" { type = bool }\n')
        else:
            (root / "unrelated.txt").write_text("other staged work\n")
            _git(root, "add", "unrelated.txt")
        return capture(root, paths, mode=mode)

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- Intercept the real transaction capture to change context after planning; retain actual precondition checks and durable writes.
        transaction.FileTransaction, "capture", concurrent_capture
    )
    with pytest.raises(OSError, match="changed"):
        autofix.fix_paths(tmp_path, (str(path),), staged=True)
    assert path.read_bytes() == before
    if change == "declaration":
        assert 'variable "retired"' in (tmp_path / "variables.tf").read_text()
    else:
        assert (tmp_path / "unrelated.txt").read_text() == "other staged work\n"


def test_all_fixes_roll_back_on_a_second_write_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _repository(tmp_path)
    other = tmp_path / "later.auto.tfvars.json"
    other.write_text('{"retired":false}\n')
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "--quiet", "-m", "second input")
    paths = (tmp_path / "terraform.tfvars", other)
    before = {path: path.read_bytes() for path in paths}
    original = transaction.FileTransaction.write_bytes
    written_paths: list[Path] = []

    def fail_second_write(self: transaction.FileTransaction, path: Path, contents: bytes) -> None:
        written_paths.append(path)
        if len(written_paths) == 2:
            message = "second input write failed"
            raise OSError(message)
        original(self, path, contents)

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- Intercept the real transaction write boundary to prove rollback after its first durable write; a different transaction would not exercise this contract.
        transaction.FileTransaction, "write_bytes", fail_second_write
    )
    with pytest.raises(OSError, match="second input write"):
        autofix.fix_paths(tmp_path, tuple(str(path) for path in paths))
    assert {path: path.read_bytes() for path in paths} == before


def test_reviewed_rule_exception_is_honored_for_project_tfvars_diagnostics(tmp_path: Path) -> None:
    _repository(tmp_path)
    adopted = manifest.Manifest(manifest.adopted_version(), (), ".", ".", excluded_rules=(_TFVARS_RULE,))
    report = analyze(
        [],
        root=tmp_path,
        policy=Policy.from_manifest(tmp_path, adopted),
        staged=True,
        use_guard_contracts=False,
        rule_selection=RuleSelection.from_values((_TFVARS_RULE,)),
    )
    assert not report.issues
    assert not report.diagnostics
    assert (
        autofix.fix_paths(
            tmp_path, (str(tmp_path / "terraform.tfvars"),), policy=Policy.from_manifest(tmp_path, adopted)
        )
        == ()
    )


def test_replacing_one_violation_cannot_reuse_its_fingerprint_budget(tmp_path: Path) -> None:
    _repository(tmp_path)
    selection = RuleSelection.from_values((_TFVARS_RULE,))
    before = analyze([], root=tmp_path, staged=True, use_guard_contracts=False, rule_selection=selection)
    assert len(before.diagnostics) == 1
    fingerprint = before.diagnostics[0].fingerprint
    assert fingerprint is not None
    budget = baseline.Budget({fingerprint: 1}, None)
    assert baseline.within_budget(before.diagnostics, budget) == before.diagnostics
    (tmp_path / "terraform.tfvars").write_text("live = false\nnew_debt = true\n")
    _git(tmp_path, "add", ".")
    after = analyze([], root=tmp_path, staged=True, use_guard_contracts=False, rule_selection=selection)
    assert len(after.diagnostics) == 1
    assert after.diagnostics[0].fingerprint != fingerprint
    assert baseline.within_budget(after.diagnostics, budget) == ()


@pytest.mark.parametrize("source", ["retired = [\n", "live =\n"], ids=["unbalanced-value", "missing-value"])
def test_missing_context_is_inconclusive_and_does_not_erase_required_output_findings(
    tmp_path: Path, source: str
) -> None:
    _repository(tmp_path)
    (tmp_path / "child").mkdir()
    (tmp_path / "child/outputs.tf").write_text('output "unused" { value = true }\n')
    (tmp_path / "main.tf").write_text('module "child" { source = "./child" }\n')
    adopted = manifest.Manifest(manifest.adopted_version(), (), ".", ".", terraform_internal_modules=("child",))
    (tmp_path / manifest.MANIFEST_NAME).write_text(adopted.render())
    (tmp_path / "terraform.tfvars").write_text(source)
    _git(tmp_path, "add", ".")
    report = analyze(
        [],
        root=tmp_path,
        staged=True,
        use_guard_contracts=False,
        rule_selection=RuleSelection.from_values((_TFVARS_RULE, "iac:no-unused-module-outputs")),
    )
    assert report.completion is Completion.PARTIAL
    assert report.issues
    assert any(item.code == "SARJ223" and item.severity.value == "error" for item in report.diagnostics)


@pytest.mark.parametrize("name", ["terraform.tfvars", "terraform.tfvars.json"])
def test_fix_preserves_native_terraform_effective_values_and_formatting(tmp_path: Path, name: str) -> None:
    _repository(tmp_path)
    path = tmp_path / name
    if name.endswith("json"):
        path.write_text('{"live":false,"retired":true}\n')
        (tmp_path / "terraform.tfvars").unlink()
        _git(tmp_path, "add", ".")
        _git(tmp_path, "commit", "--quiet", "-m", "JSON input")
    tool = checked_tool("terraform", root=tmp_path)
    assert tool.executable is not None
    command = (str(tool.executable), "console", "-no-color")
    expression = "jsonencode({live = var.live})\n"
    before = run_process_input(command, cwd=tmp_path, source=expression)
    assert before.returncode == 0
    assert autofix.fix_paths(tmp_path, (str(path),), terraform=True) == (path,)
    after = run_process_input(command, cwd=tmp_path, source=expression)
    assert after.returncode == 0
    assert before.stdout.splitlines()[-1] == after.stdout.splitlines()[-1] == '"{\\"live\\":false}"'
    if not name.endswith("json"):
        formatted = run_process_input((str(tool.executable), "fmt", "-"), cwd=tmp_path, source=path.read_text())
        assert formatted.returncode == 0
        assert formatted.stdout == path.read_text()
    assert autofix.fix_paths(tmp_path, (str(path),), terraform=True) == ()


@pytest.mark.parametrize("metadata", [False, "generated - do not edit"], ids=["comment", "generated-owner"])
def test_native_json_comment_semantics_and_generated_ownership_are_preserved(
    tmp_path: Path, metadata: bool | str
) -> None:
    _repository(tmp_path)
    (tmp_path / "terraform.tfvars").unlink()
    path = tmp_path / "terraform.tfvars.json"
    source = json.dumps({"//": metadata, "live": True, "retired": False}) + "\n"
    path.write_text(source)
    _git(tmp_path, "add", ".")
    tool = checked_tool("terraform", root=tmp_path)
    assert tool.executable is not None
    native = run_process_input((str(tool.executable), "console", "-no-color"), cwd=tmp_path, source="var.live\n")
    assert native.returncode == 0
    assert native.stdout.splitlines()[-1] == "true"
    assert "retired" in native.stdout + native.stderr
    assert "//" not in native.stdout + native.stderr
    report = analyze(
        [],
        root=tmp_path,
        staged=True,
        use_guard_contracts=False,
        rule_selection=RuleSelection.from_values((_TFVARS_RULE,)),
    )
    assert not report.issues
    assert len(report.diagnostics) == (1 if metadata is False else 0)
    assert autofix.fix_paths(tmp_path, (str(path),), staged=True) == ()
    assert path.read_text() == source


@pytest.mark.parametrize(
    "value",
    [".5", "\u0661", "true\u00a0", "1e10000000000", "1e-10000000000"],
    ids=["leading-dot", "unicode-digit", "unicode-whitespace", "overflow", "underflow"],
)
def test_fix_preserves_native_terraform_parse_failures(tmp_path: Path, value: str) -> None:
    _repository(tmp_path)
    path = tmp_path / "terraform.tfvars"
    source = "live = false\nretired = " + value + "\n"
    path.write_text(source)
    _git(tmp_path, "add", ".")
    tool = checked_tool("terraform", root=tmp_path)
    assert tool.executable is not None
    command = (str(tool.executable), "console", "-no-color")
    before = run_process_input(command, cwd=tmp_path, source="var.live\n")
    assert before.returncode != 0
    assert autofix.fix_paths(tmp_path, (str(path),), staged=True) == ()
    assert path.read_text() == source
    after = run_process_input(command, cwd=tmp_path, source="var.live\n")
    assert after.returncode == before.returncode


@pytest.mark.parametrize("name", ["terraform.tfvars", "terraform.tfvars.json"])
@pytest.mark.parametrize("value", ["true", "123456"], ids=["boolean-string", "numeric-string"])
def test_quoted_scalars_remain_strings_and_are_never_automatically_deleted(
    tmp_path: Path, name: str, value: str
) -> None:
    _repository(tmp_path)
    (tmp_path / "terraform.tfvars").unlink()
    path = tmp_path / name
    source = (
        json.dumps({"live": False, "retired": value}) + "\n"
        if name.endswith("json")
        else "live = false\nretired = " + json.dumps(value) + "\n"
    )
    path.write_text(source)
    _git(tmp_path, "add", ".")
    assert autofix.fix_paths(tmp_path, (str(path),), staged=True) == ()
    assert path.read_text() == source


def test_unchanged_child_module_cannot_observe_a_changed_input_file(tmp_path: Path) -> None:
    _repository(tmp_path)
    (tmp_path / "reader").mkdir()
    (tmp_path / ".gitignore").write_text(".terraform/\n")
    (tmp_path / "main.tf").write_text(
        'module "reader" { source = "./reader" }\noutput "hash" { value = module.reader.hash }\n'
    )
    (tmp_path / "reader/outputs.tf").write_text('output "hash" { value = filesha1("${path.root}/terraform.tfvars") }\n')
    _git(tmp_path, "add", ".")
    tool = checked_tool("terraform", root=tmp_path)
    assert tool.executable is not None
    initialized = run_process_input(
        (str(tool.executable), "init", "-backend=false", "-input=false", "-no-color"), cwd=tmp_path, source=""
    )
    assert initialized.returncode == 0
    command = (str(tool.executable), "console", "-no-color")
    before = run_process_input(command, cwd=tmp_path, source="module.reader.hash\n")
    assert before.returncode == 0
    path = tmp_path / "terraform.tfvars"
    original = path.read_bytes()
    assert autofix.fix_paths(tmp_path, (str(path),), staged=True) == ()
    assert path.read_bytes() == original
    after = run_process_input(command, cwd=tmp_path, source="module.reader.hash\n")
    assert after.returncode == 0
    assert before.stdout.splitlines()[-1] == after.stdout.splitlines()[-1]
