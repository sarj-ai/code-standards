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
from sarj_standards.libs.adoption import devops
from sarj_standards.libs.adoption.manifest import Manifest, as_table, load
from sarj_standards.libs.json_boundary import parse_json
from sarj_standards.libs.linting.analysis import analyze as analyze_core
from sarj_standards.libs.linting.iac_guard_contracts import CONTRACT_PATH, CoreIAC
from sarj_standards.libs.staged_git import isolated_environment
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


def test_tools_setup_rejects_invalid_guard_provenance_before_installation(
    guard_adapter: _GuardFixture,
) -> None:
    root = guard_adapter.adapter.root
    (root / ".sarj-standards.toml").write_text(
        Manifest(
            version="9.4.5", configs=(), python_dest=".", typescript_dest=".", terraform_guard_contracts=CONTRACT_PATH
        ).render()
    )
    guard_adapter.state.original = _ORIGINAL.replace("condition = var.approved", "condition = true")

    with pytest.raises(ValueError, match="immutable original source"):
        devops.setup_tools_only(root)


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
        ('"schema": 1', '"schema": 1, "original_revision": "untrusted"'),
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


def _git(root: Path, *arguments: str) -> str:
    return subprocess.run(
        [
            "git",
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "-c",
            f"core.hooksPath={root / '.git' / 'hooks'}",
            "-c",
            "commit.gpgsign=false",
            "-c",
            "core.autocrlf=false",
            *arguments,
        ],
        cwd=root,
        env=isolated_environment(),
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    ).stdout.strip()


def _commit(root: Path, message: str) -> None:
    _git(root, "add", "--all")
    _git(root, "commit", "--quiet", "-m", message)


def _adoption_branch(root: Path, source: str = _ORIGINAL) -> bytes:
    _git(root, "init", "--quiet", "--template=", "--initial-branch=main")
    (root / "main.tf").write_text(_ORIGINAL)
    _commit(root, "Original guards")
    _git(root, "switch", "--quiet", "--create", "adoption")
    (root / "migration.txt").write_text("Preparatory tooling change\n")
    (root / "main.tf").write_text(source)
    _commit(root, "Prepare migration")
    manifest = CoreIAC(root).initialize(["main.tf"], original_revision=_git(root, "rev-parse", "HEAD"))
    (root / CONTRACT_PATH).write_text(manifest, newline="\n")
    (root / ".sarj-standards.toml").write_text(
        Manifest(
            version="9.4.6", configs=(), python_dest=".", typescript_dest=".", terraform_guard_contracts=CONTRACT_PATH
        ).render()
    )
    _commit(root, "Adopt guard contracts")
    return manifest.encode()


def _integrate(root: Path, method: str) -> None:
    match method:
        case "merge":
            _git(root, "merge", "--no-ff", "-m", "Merge adoption", "adoption")
        case "squash":
            _git(root, "merge", "--squash", "adoption")
            _commit(root, "Squash adoption")
        case "rebase":
            _git(root, "switch", "--quiet", "adoption")
            _git(root, "rebase", "main")
            _git(root, "switch", "--quiet", "main")
            _git(root, "merge", "--ff-only", "adoption")
        case _:
            message = "Unsupported fixture integration method"
            raise ValueError(message)
    _git(root, "branch", "--delete", "--force", "adoption")
    _git(root, "reflog", "expire", "--expire=now", "--all")
    _git(root, "gc", "--prune=now")


@pytest.mark.parametrize("method", ["merge", "squash", "rebase"])
@pytest.mark.parametrize("advance_main", [False, True])
def test_unchanged_guard_contract_survives_pr_integration(tmp_path: Path, method: str, *, advance_main: bool) -> None:
    manifest = _adoption_branch(tmp_path)
    assert CoreIAC(tmp_path).prepare() is not None
    _git(tmp_path, "switch", "--quiet", "main")
    if advance_main:
        (tmp_path / "unrelated.txt").write_text("Unrelated target-branch change\n")
        _commit(tmp_path, "Advance target branch")
    _integrate(tmp_path, method)

    assert (tmp_path / CONTRACT_PATH).read_bytes() == manifest
    assert (tmp_path / "main.tf").read_text() == _ORIGINAL
    assert CoreIAC(tmp_path).prepare() is not None
    report = Standards(tmp_path).analyze([], rules=["iac:no-terraform-guard-blocks"])
    assert report.issues == ()


@pytest.mark.parametrize("method", ["merge", "squash"])
def test_integration_cannot_grandfather_a_new_feature_branch_guard(tmp_path: Path, method: str) -> None:
    added = _ORIGINAL[_ORIGINAL.index("resource ") :].replace('"protected"', '"extra"')
    _adoption_branch(tmp_path, _ORIGINAL + added)
    assert CoreIAC(tmp_path).prepare() is not None
    _git(tmp_path, "switch", "--quiet", "main")
    _integrate(tmp_path, method)

    with pytest.raises(ValueError, match="immutable original source"):
        CoreIAC(tmp_path).prepare()
    report = Standards(tmp_path).analyze([], rules=["iac:no-terraform-guard-blocks"])
    assert any(issue.kind == "guard-contract-failure" for issue in report.issues)


@pytest.mark.parametrize("method", ["merge", "squash", "rebase"])
def test_integration_rejects_target_branch_guard_drift(tmp_path: Path, method: str) -> None:
    manifest = _adoption_branch(tmp_path)
    _git(tmp_path, "switch", "--quiet", "main")
    (tmp_path / "main.tf").write_text(_ORIGINAL.replace("condition = var.approved", "condition = true"))
    _commit(tmp_path, "Change target guard")
    _integrate(tmp_path, method)

    assert (tmp_path / CONTRACT_PATH).read_bytes() == manifest
    with pytest.raises(ValueError, match="immutable original source"):
        CoreIAC(tmp_path).prepare()


@pytest.mark.parametrize("change", ["manifest", "remove-reintroduce"])
def test_committed_contract_history_cannot_replace_frozen_policy(tmp_path: Path, change: str) -> None:
    manifest = _adoption_branch(tmp_path)
    path = tmp_path / CONTRACT_PATH
    if change == "manifest":
        path.write_bytes(manifest + b" ")
        _commit(tmp_path, "Change contract")
    else:
        path.unlink()
        _commit(tmp_path, "Remove contract")
        path.write_bytes(manifest)
        _commit(tmp_path, "Reintroduce contract")

    with pytest.raises(ValueError, match=r"immutable.*changed|removed and reintroduced"):
        CoreIAC(tmp_path).prepare()


def _promotion_branches(root: Path, *, destination: str = "new.tf", initial_extra: bool = True) -> bytes:
    _git(root, "init", "--quiet", "--template=", "--initial-branch=dev")
    extra = _ORIGINAL[_ORIGINAL.index("resource ") :].replace('"protected"', '"relocated"')
    (root / "main.tf").write_text(_ORIGINAL + extra if initial_extra else _ORIGINAL)
    _commit(root, "Original shared guards")
    _git(root, "branch", "preview")
    _git(root, "branch", "production")
    (root / "main.tf").write_text(_ORIGINAL)
    (root / destination).parent.mkdir(parents=True, exist_ok=True)
    (root / destination).write_text(extra)
    _commit(root, "Split existing dev guards before adoption")
    manifest = CoreIAC(root).initialize(["main.tf", destination], original_revision=_git(root, "rev-parse", "HEAD"))
    (root / CONTRACT_PATH).write_text(manifest, newline="\n")
    (root / ".sarj-standards.toml").write_text(
        Manifest(
            version="9.4.6", configs=(), python_dest=".", typescript_dest=".", terraform_guard_contracts=CONTRACT_PATH
        ).render()
    )
    _commit(root, "Adopt existing dev guards")
    assert CoreIAC(root).prepare() is not None
    return manifest.encode()


@pytest.mark.parametrize("target", ["preview", "production"])
@pytest.mark.parametrize("staged", [False, True])
def test_promotion_preserves_previously_adopted_source_guards(tmp_path: Path, target: str, *, staged: bool) -> None:
    manifest = _promotion_branches(tmp_path)
    _git(tmp_path, "switch", "--quiet", "preview")
    _git(tmp_path, "merge", "--no-ff", "-m", "Promote dev to preview", "dev")
    if target == "production":
        _git(tmp_path, "switch", "--quiet", target)
        _git(tmp_path, "merge", "--no-ff", "-m", "Promote preview to production", "preview")

    assert (tmp_path / CONTRACT_PATH).read_bytes() == manifest
    assert CoreIAC(tmp_path, staged=staged).prepare() is not None
    report = Standards(tmp_path).analyze([], rules=["iac:no-terraform-guard-blocks"])
    assert report.issues == ()


@pytest.mark.parametrize("change", ["target-guard", "source-guard", "manifest", "remove-reintroduce"])
def test_promotion_still_rejects_guard_or_contract_drift(tmp_path: Path, change: str) -> None:
    manifest = _promotion_branches(tmp_path)
    if change == "target-guard":
        _git(tmp_path, "switch", "--quiet", "preview")
        (tmp_path / "main.tf").write_text(_ORIGINAL.replace("condition = var.approved", "condition = true"))
        _commit(tmp_path, "Change target guard")
    else:
        match change:
            case "source-guard":
                (tmp_path / "new.tf").write_text(_ORIGINAL.replace("condition = var.approved", "condition = true"))
            case "manifest":
                (tmp_path / CONTRACT_PATH).write_bytes(manifest + b" ")
            case _:
                (tmp_path / CONTRACT_PATH).unlink()
                _commit(tmp_path, "Remove source contract")
                (tmp_path / CONTRACT_PATH).write_bytes(manifest)
        _commit(tmp_path, "Change source after adoption")
        _git(tmp_path, "switch", "--quiet", "preview")
    _git(tmp_path, "merge", "--no-ff", "-Xours", "-m", "Promote source", "dev")

    with pytest.raises(ValueError, match=r"guard|contract|immutable"):
        CoreIAC(tmp_path).prepare()


@pytest.mark.parametrize(("destination", "initial_extra"), [("module/new.tf", True), ("new.tf", False)])
def test_promotion_cannot_grandfather_new_or_cross_module_guards(
    tmp_path: Path, destination: str, *, initial_extra: bool
) -> None:
    _promotion_branches(tmp_path, destination=destination, initial_extra=initial_extra)
    _git(tmp_path, "switch", "--quiet", "preview")
    _git(tmp_path, "merge", "--no-ff", "-m", "Promote source", "dev")

    with pytest.raises(ValueError, match=r"guard|contract|immutable"):
        CoreIAC(tmp_path).prepare()
