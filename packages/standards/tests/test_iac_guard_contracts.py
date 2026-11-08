from __future__ import annotations

from dataclasses import dataclass
import shutil
import subprocess
from typing import TYPE_CHECKING

import pytest
from sarj_iac_lint.__main__ import analyze
from sarj_iac_lint.guard_contracts import GuardContracts, contracts_for_source, verify_sources
from sarj_iac_lint.rules.no_terraform_guard_blocks import NoTerraformGuardBlocks

from sarj_standards.api import AnalysisMode, Standards
from sarj_standards.libs.adoption.manifest import Manifest, as_table, load
from sarj_standards.libs.json_boundary import parse_json
from sarj_standards.libs.linting.analysis import analyze as analyze_core
from sarj_standards.libs.linting.iac_guard_contracts import CONTRACT_PATH, CoreIAC
from sarj_standards.libs.typed_containers import is_object_list, is_object_mapping


if TYPE_CHECKING:
    from pathlib import Path

    from sarj_iac_lint.guard_contracts import GuardContract


_ORIGINAL = """variable "approved" {
  type = bool
  default = false
}
resource "terraform_data" "protected" {
  input = "unchanged"
  lifecycle {
    precondition {
      condition = var.approved
      error_message = "Ownership approval is required."
    }
  }
}
"""
_REVISION = "a" * 40
_INTRODUCTION = "b" * 40
_GUARD = """    precondition {
      condition = var.approved
      error_message = "Ownership approval is required."
    }
"""


def _entries(source: str = _ORIGINAL) -> frozenset[GuardContract]:
    return frozenset(contracts_for_source("main.tf", source))


@dataclass
class _GitState:
    introduced: bool = False
    original: str = _ORIGINAL
    index_source: str = _ORIGINAL
    historic: str = ""
    index_manifest: str = ""
    option: bool = True
    index_option: bool = True


@dataclass
class _GuardFixture:
    adapter: CoreIAC
    state: _GitState


@pytest.fixture
def guard_adapter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> _GuardFixture:
    """Mock immutable Git reads without creating a checkout or installing a candidate."""
    (tmp_path / "main.tf").write_text(_ORIGINAL)
    (tmp_path / ".git").mkdir()
    state = _GitState()

    def git(_self: CoreIAC, *arguments: str, absent_ok: bool = False) -> str:
        assert isinstance(absent_ok, bool)
        if arguments[0] == "log":
            return _INTRODUCTION + "\n" if state.introduced else ""
        if arguments[:2] == ("rev-parse", "--verify"):
            return _REVISION + "\n"
        if arguments[0] in {"ls-tree", "ls-files"}:
            return "100644 blob fixture\tmain.tf\n"
        values = {
            f"{_REVISION}:main.tf": state.original,
            ":main.tf": state.index_source,
            f"{_INTRODUCTION}:{CONTRACT_PATH}": state.historic,
            f":{CONTRACT_PATH}": state.index_manifest,
            ":.sarj-standards.toml": _configuration() if state.index_option else "",
        }
        assert arguments[0] == "show"
        assert arguments[1] in values
        return values[arguments[1]]

    def configured(_root: Path) -> Manifest:
        return Manifest(
            version="9.4.5",
            configs=(),
            python_dest=".",
            typescript_dest=".",
            terraform_guard_contracts=CONTRACT_PATH if state.option else None,
        )

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- intercept the production provenance boundary to exercise fail-closed history and index states.
        CoreIAC, "_git", git
    )

    def environment(_root: Path) -> dict[str, str]:
        return {}

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- intercept the production provenance boundary to exercise fail-closed history and index states.
        "sarj_standards.libs.linting.iac_guard_contracts.staged_environment", environment
    )
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- intercept the production provenance boundary to exercise fail-closed history and index states.
        "sarj_standards.libs.linting.iac_guard_contracts.load", configured
    )
    adapter = CoreIAC(tmp_path)
    manifest = adapter.initialize(["main.tf"], original_revision=_REVISION)
    (tmp_path / CONTRACT_PATH).write_text(manifest)
    state.historic = state.index_manifest = manifest
    return _GuardFixture(adapter, state)


def _configuration() -> str:
    return '[iac.no-terraform-guard-blocks]\ncontracts = ".sarj-terraform-guards.json"\n'


def test_guard_contract_manifest_roundtrip(tmp_path: Path) -> None:
    manifest = Manifest(
        version="9.4.5", configs=(), python_dest=".", typescript_dest=".", terraform_guard_contracts=CONTRACT_PATH
    )
    (tmp_path / ".sarj-standards.toml").write_text(manifest.render())
    loaded = load(tmp_path)
    assert loaded is not None
    assert loaded.terraform_guard_contracts == CONTRACT_PATH
    (tmp_path / ".sarj-standards.toml").write_text(manifest.render().replace(CONTRACT_PATH, "../guards.json"))
    with pytest.raises(ValueError, match=r"guard|contract|SARJ222"):
        load(tmp_path)


def test_unchanged_guard_and_unrelated_policies(tmp_path: Path) -> None:
    path = tmp_path / "main.tf"
    path.write_text(_ORIGINAL)
    policy = GuardContracts(tmp_path, _entries())
    assert NoTerraformGuardBlocks(policy).check(path, _ORIGINAL) == []
    assert [d.code for d in NoTerraformGuardBlocks().check(path, _ORIGINAL)] == ["SARJ222"]
    diagnostics = analyze(["no-terraform-guard-blocks", "no-terraform-data-condition"], [path], guard_contracts=policy)
    assert [d.code for d in diagnostics] == ["SARJ210"]


@pytest.mark.parametrize(
    "source",
    [
        _ORIGINAL.replace("condition = var.approved", "condition = true"),
        _ORIGINAL.replace('"protected"', '"other"'),
        _ORIGINAL.replace("Ownership approval is required.", "Ignored."),
        _ORIGINAL.replace("precondition {", "postcondition {"),
        _ORIGINAL.replace(_GUARD, ""),
        _ORIGINAL.replace(_GUARD, _GUARD + _GUARD),
        _ORIGINAL
        + '\nvariable "extra" {\n validation {\n condition = var.extra\n error_message = "Required."\n }\n}\n',
    ],
)
def test_changed_or_missing_guard_rejected(source: str) -> None:
    with pytest.raises(ValueError, match=r"guard|contract|SARJ222"):
        verify_sources(_entries(), {"main.tf": source})


@pytest.mark.parametrize("path", ["../main.tf", "/main.tf", "./main.tf", "a//main.tf", "a\\main.tf", "main.hcl"])
def test_contract_exact_paths(path: str) -> None:
    with pytest.raises(ValueError, match=r"guard|contract|SARJ222"):
        contracts_for_source(path, _ORIGINAL)


@pytest.mark.parametrize(
    "source",
    [
        _ORIGINAL[:-5],
        _ORIGINAL + _ORIGINAL,
        _ORIGINAL.replace("condition = var.approved", "condition = var.approved\n condition = true"),
        _ORIGINAL.replace("    }\n", "      unknown = true\n    }\n"),
    ],
)
def test_malformed_or_ambiguous_guard_rejected(source: str) -> None:
    with pytest.raises((ValueError, TypeError)):
        contracts_for_source("main.tf", source)


def test_contract_normalizer_preserves_literals() -> None:
    verify_sources(
        _entries(), {"main.tf": _ORIGINAL.replace("condition = var.approved", "condition   =   var.approved # policy")}
    )
    verify_sources(_entries(), {"main.tf": _ORIGINAL + "\nlocals { first = true }\nlocals { second = false }\n"})
    with pytest.raises(ValueError, match=r"guard|contract|SARJ222"):
        verify_sources(_entries(), {"main.tf": _ORIGINAL.replace("Ownership approval", "Ownership  approval")})


def test_initializer_and_immutable_manifest(guard_adapter: _GuardFixture) -> None:
    adapter, state = guard_adapter.adapter, guard_adapter.state
    policy = adapter.prepare()
    assert policy is not None
    assert policy.entries == _entries()
    state.introduced = True
    assert adapter.prepare() == policy
    with pytest.raises(ValueError, match="regeneration"):
        adapter.initialize(["main.tf"], original_revision=_REVISION)
    path = adapter.root / CONTRACT_PATH
    path.write_text(path.read_text() + " ")
    with pytest.raises(ValueError, match=r"immutable.*changed"):
        adapter.prepare()


def test_initializer_rejects_candidate_postimages(guard_adapter: _GuardFixture) -> None:
    adapter = guard_adapter.adapter
    (adapter.root / CONTRACT_PATH).unlink()
    (adapter.root / "main.tf").write_text(_ORIGINAL.replace("condition = var.approved", "condition = true"))
    with pytest.raises(ValueError, match=r"guard|contract|SARJ222"):
        adapter.initialize(["main.tf"], original_revision=_REVISION)
    with pytest.raises(ValueError, match="exact immutable original HEAD"):
        adapter.initialize(["main.tf"], original_revision="c" * 40)


@pytest.mark.parametrize(
    ("before", "after"),
    [
        ('"schema": 1', '"schema": true'),
        ('"schema": 1', '"schema": 0, "schema": 1'),
        (_REVISION, "c" * 40),
        ('"protected"', '"other"'),
        ('"main.tf"', '"missing.tf"'),
        ('"kind": "precondition"', '"kind": "validation"'),
    ],
)
def test_contract_tamper_rejected(guard_adapter: _GuardFixture, before: str, after: str) -> None:
    adapter = guard_adapter.adapter
    path = adapter.root / CONTRACT_PATH
    path.write_text(path.read_text().replace(before, after))
    with pytest.raises((ValueError, AssertionError)):
        adapter.prepare()


@pytest.mark.parametrize("staged", [False, True])
@pytest.mark.parametrize("missing", ["guard", "manifest", "option"])
def test_stale_or_missing_contract_fails_closed(guard_adapter: _GuardFixture, *, staged: bool, missing: str) -> None:
    adapter, state = guard_adapter.adapter, guard_adapter.state
    adapter.staged = staged
    state.introduced = True
    match missing:
        case "guard":
            (adapter.root / "main.tf").write_text(_ORIGINAL.replace(_GUARD, ""))
        case "manifest":
            (adapter.root / CONTRACT_PATH).unlink()
        case _:
            state.option = False
    with pytest.raises(ValueError, match=r"guard|contract|SARJ222"):
        adapter.prepare()


def test_staged_guard_and_option_cannot_hide_behind_worktree(guard_adapter: _GuardFixture) -> None:
    adapter, state = guard_adapter.adapter, guard_adapter.state
    adapter.staged = True
    assert adapter.prepare() is not None
    state.index_source = _ORIGINAL.replace("condition = var.approved", "condition = true")
    with pytest.raises(ValueError, match=r"guard|contract|SARJ222"):
        adapter.prepare()
    state.index_source = _ORIGINAL.replace(_GUARD, "")
    with pytest.raises(ValueError, match=r"guard|contract|SARJ222"):
        adapter.prepare()
    state.index_source = _ORIGINAL
    state.index_option = False
    with pytest.raises(ValueError, match=r"guard|contract|SARJ222"):
        adapter.prepare()


def test_contract_failures_block_empty_partial_and_full_selection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(_self: CoreIAC) -> None:
        message = "missing guard in index"
        raise ValueError(message)

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- intercept the production provenance boundary to exercise fail-closed history and index states.
        CoreIAC, "prepare", fail
    )
    (tmp_path / "unrelated.txt").write_text("unrelated\n")
    (tmp_path / "main.tf").write_text(_ORIGINAL)
    for selected in ([], ["unrelated.txt"], ["main.tf"]):
        report = analyze_core(selected, root=tmp_path)
        assert any(issue.kind == "guard-contract-failure" for tool in report.tools for issue in tool.issues)


def test_unlisted_guard_remains_error_and_nonbaselineable(tmp_path: Path) -> None:
    path = tmp_path / "new.tf"
    path.write_text(_ORIGINAL)
    diagnostics = analyze(["no-terraform-guard-blocks"], [path], guard_contracts=GuardContracts(tmp_path, _entries()))
    assert len(diagnostics) == 1
    assert diagnostics[0].code == "SARJ222"
    assert not diagnostics[0].baselineable
    assert not diagnostics[0].suppressible


def test_guard_contract_keeps_terraform_fail_closed_and_resource_address(tmp_path: Path) -> None:
    executable = shutil.which("terraform")
    assert executable is not None, "Terraform is required for the mandatory guard contract behavior proof"
    path = tmp_path / "main.tf"
    path.write_text(_ORIGINAL)
    original = path.read_bytes()
    assert NoTerraformGuardBlocks(GuardContracts(tmp_path, _entries())).check(path, _ORIGINAL) == []

    def terraform(*arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [executable, *arguments], cwd=tmp_path, capture_output=True, text=True, check=False, timeout=30
        )

    assert terraform("init", "-backend=false", "-input=false", "-no-color").returncode == 0
    denied = terraform("plan", "-input=false", "-no-color", "-var=approved=false")
    assert denied.returncode == 1
    assert "Ownership approval is required." in denied.stderr
    assert not (tmp_path / "terraform.tfstate").exists()
    assert terraform("plan", "-input=false", "-no-color", "-var=approved=true", "-out=valid.plan").returncode == 0
    shown = terraform("show", "-json", "valid.plan")
    assert shown.returncode == 0
    document = as_table(parse_json(shown.stdout))
    assert is_object_mapping(document)
    changes = document["resource_changes"]
    assert is_object_list(changes)
    assert len(changes) == 1
    resource = changes[0]
    assert is_object_mapping(resource)
    assert resource["address"] == "terraform_data.protected"
    change = resource["change"]
    assert is_object_mapping(change)
    assert change["actions"] == ["create"]
    after = change["after"]
    assert is_object_mapping(after)
    assert after["input"] == "unchanged"
    assert path.read_bytes() == original


def test_core_passes_verified_contracts_into_native_iac(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "main.tf").write_text(_ORIGINAL)
    policy = GuardContracts(tmp_path, _entries())

    def prepared(_self: CoreIAC) -> GuardContracts:
        return policy

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- intercept the production provenance boundary to exercise fail-closed history and index states.
        CoreIAC, "prepare", prepared
    )
    report = analyze_core(["main.tf"], root=tmp_path)
    assert not any(tool.issues for tool in report.tools)
    codes = {item.code for item in report.diagnostics}
    assert "SARJ222" not in codes
    assert "SARJ210" in codes


@pytest.mark.parametrize("mode", [AnalysisMode.RAW, AnalysisMode.CORPUS])
def test_policy_free_iac_analysis_retains_the_default_guard_ban(tmp_path: Path, mode: AnalysisMode) -> None:
    (tmp_path / "main.tf").write_text(_ORIGINAL)
    (tmp_path / ".sarj-standards.toml").write_text("schema = [\n")
    report = Standards(tmp_path).analyze(["main.tf"], mode=mode, rules=["iac:no-terraform-guard-blocks"])
    assert not report.issues
    assert [item.code for item in report.diagnostics] == ["SARJ222"]
