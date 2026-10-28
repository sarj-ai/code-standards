from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shlex
import shutil
import stat
import subprocess
import sys
from typing import TYPE_CHECKING, NamedTuple

import pytest

from sarj_standards import api
from sarj_standards.cli.main import main, staged_fix_paths
from sarj_standards.libs.diagnostics.baseline import changed_line_scope
from sarj_standards.libs.json_boundary import parse_json
from sarj_standards.libs.linting import external, repo_standards
from sarj_standards.libs.staged_git import staged_environment


if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from sarj_standards.libs.linting.external import ProcessRunner
    from sarj_standards.libs.rules import RuleSelection


_STAGED = b"# timeout = 30\ntimeout = 10\n"
_FIXED = b"\ntimeout = 10\n"
_INITIAL = b"timeout = 10\n"


def _fixture_environment() -> dict[str, str]:
    selected = {
        name: value
        for name, value in os.environ.items()  # ruff: ignore[banned-api] -- fixture commands must not inherit the enclosing hook's repository/index binding.
        if not name.startswith("GIT_")
    }
    selected["GIT_OPTIONAL_LOCKS"] = "0"
    return selected


def _git(root: Path, *arguments: str, environment: dict[str, str] | None = None) -> bytes:
    selected = _fixture_environment()
    if environment is not None:
        selected.update(environment)
    return subprocess.check_output(("git", "--no-optional-locks", *arguments), cwd=root, env=selected)


def _repository(root: Path) -> None:
    root.mkdir(exist_ok=True)
    _git(root, "init", "--template=", "-q")
    _git(root, "config", "core.hooksPath", str(root / ".git/hooks"))
    _git(root, "config", "user.name", "Private fixture")
    _git(root, "config", "user.email", "fixture@example.invalid")
    (root / "settings.toml").write_bytes(_INITIAL)
    _git(root, "add", "--all")
    _git(root, "commit", "-qm", "fixture baseline")


@pytest.mark.parametrize("relative", [False, True], ids=("absolute", "relative-to-selected-root"))
def test_staged_context_accepts_only_the_selected_worktree_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, relative: bool
) -> None:
    root = tmp_path / "repository"
    _repository(root)
    pending = root / ".git/pending-index"
    shutil.copyfile(root / ".git/index", pending)
    value = ".git/pending-index" if relative else str(pending)
    monkeypatch.setenv("GIT_INDEX_FILE", value)
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "core.worktree")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", str(tmp_path / "foreign"))

    environment = staged_environment(root)

    assert environment["GIT_INDEX_FILE"] == str(pending)
    assert environment["GIT_OPTIONAL_LOCKS"] == "0"
    assert {name for name in environment if name.startswith("GIT_")} == {"GIT_INDEX_FILE", "GIT_OPTIONAL_LOCKS"}
    assert os.environ["GIT_INDEX_FILE"] == value  # ruff: ignore[banned-api] -- the public guard must not mutate process-global routing for concurrent callers.


@pytest.mark.parametrize(
    "variable",
    ["GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_NAMESPACE", "GIT_SHALLOW", "GIT_QUARANTINE_PATH"],
)
def test_ordinary_pending_indexes_reject_object_store_overrides(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, variable: str
) -> None:
    root = tmp_path / "repository"
    _repository(root)
    pending = root / ".git/pending-index"
    shutil.copyfile(root / ".git/index", pending)
    before = pending.read_bytes()
    monkeypatch.delenv("SARJ_STANDARDS_INITIAL_IMPORT_SOURCE", raising=False)
    monkeypatch.setenv("GIT_INDEX_FILE", str(pending))
    monkeypatch.setenv(variable, str(root / ".git/objects"))

    with pytest.raises(ValueError, match="unsupported object-store context"):
        staged_environment(root)

    assert pending.read_bytes() == before


def test_public_analysis_accepts_a_same_worktree_pending_index_without_mutating_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _repository(tmp_path)
    source = tmp_path / "settings.toml"
    pending = tmp_path / ".git/pending-index"
    shutil.copyfile(tmp_path / ".git/index", pending)
    before = source.read_bytes(), (tmp_path / ".git/index").read_bytes(), pending.read_bytes()
    monkeypatch.setenv("GIT_INDEX_FILE", ".git/pending-index")

    report = api.Standards(tmp_path).analyze([str(source)], staged=True)

    assert report.exit_code == 0, report.as_dict()
    assert os.environ["GIT_INDEX_FILE"] == ".git/pending-index"  # ruff: ignore[banned-api] -- prove concurrent callers retain their original ambient index spelling.
    assert (source.read_bytes(), (tmp_path / ".git/index").read_bytes(), pending.read_bytes()) == before


class _ExternalIndexFixture(NamedTuple):
    root: Path
    source: Path
    external_index: Path
    before: tuple[bytes, bytes, bytes]

    def snapshot(self) -> tuple[bytes, bytes, bytes]:
        return self.source.read_bytes(), (self.root / ".git/index").read_bytes(), self.external_index.read_bytes()


def _external_index_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, index_kind: str) -> _ExternalIndexFixture:
    root = tmp_path / "repository"
    _repository(root)
    source = root / "settings.toml"
    source.write_bytes(_STAGED)
    _git(root, "add", "--", source.name)
    external_index = tmp_path / "foreign-index"
    shutil.copyfile(root / ".git/index", external_index)
    before = source.read_bytes(), (root / ".git/index").read_bytes(), external_index.read_bytes()
    monkeypatch.setenv("GIT_INDEX_FILE", str(external_index) if index_kind == "external" else "")
    return _ExternalIndexFixture(root, source, external_index, before)


@pytest.mark.parametrize("index_kind", ["external", "empty"])
def test_public_staged_analysis_refuses_external_indexes_without_mutating_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, index_kind: str
) -> None:
    fixture = _external_index_fixture(tmp_path, monkeypatch, index_kind)

    result = api.Standards(fixture.root).analyze([str(fixture.source)], staged=True)

    assert result.exit_code == 2
    assert any("active Git index" in issue.message for issue in result.issues)
    assert fixture.snapshot() == fixture.before


@pytest.mark.parametrize("entry", ["check", "fix"])
@pytest.mark.parametrize("index_kind", ["external", "empty"])
def test_staged_cli_verbs_refuse_external_indexes_without_mutating_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], entry: str, index_kind: str
) -> None:
    fixture = _external_index_fixture(tmp_path, monkeypatch, index_kind)
    options = {
        "check": ("--format", "json", "--fix", "--trust-repository-code"),
        "fix": (),
    }

    assert main(["--root", str(fixture.root), entry, "--staged", *options[entry]]) == 2

    captured = capsys.readouterr()
    assert "active Git index" in captured.out + captured.err
    assert fixture.snapshot() == fixture.before


@pytest.mark.parametrize("entry", ["selector", "policy", "external", "baseline"])
@pytest.mark.parametrize("index_kind", ["external", "empty"])
def test_staged_internal_readers_refuse_external_indexes_without_mutating_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, entry: str, index_kind: str
) -> None:
    fixture = _external_index_fixture(tmp_path, monkeypatch, index_kind)
    match entry:
        case "selector":
            with pytest.raises(ValueError, match="active Git index"):
                staged_fix_paths(fixture.root, ())
        case "policy":
            report = repo_standards.analyze(fixture.root, staged=True)
            assert report is not None
            assert any("active Git index" in issue.message for issue in report.issues)
        case "external":
            reports = external.analyze_external(
                [str(fixture.source)], root=fixture.root, trust=api.TrustMode.TRUSTED, react_doctor_staged=True
            )
            assert any("active Git index" in issue.message for report in reports for issue in report.issues)
        case "baseline":
            scope = changed_line_scope(fixture.root, staged=True, paths=(fixture.source.name,))
            assert scope is not None
            assert scope.failed
        case _:
            pytest.fail(f"unknown staged reader fixture: {entry}")
    assert fixture.snapshot() == fixture.before


@pytest.mark.parametrize("kind", ["symlink", "directory", "invalid-index", "foreign-worktree", "sibling-worktree"])
def test_staged_context_rejects_unverifiable_paths_and_worktree_bindings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    root = tmp_path / "repository"
    _repository(root)
    pending = root / ".git/pending-index"
    match kind:
        case "symlink":
            pending.symlink_to(root / ".git/index")
        case "directory":
            pending.mkdir()
        case "invalid-index":
            pending.write_bytes(b"This is not a Git index.\n")
        case "foreign-worktree":
            shutil.copyfile(root / ".git/index", pending)
            monkeypatch.setenv("GIT_WORK_TREE", str(tmp_path))
        case _:
            linked = tmp_path / "linked"
            _git(root, "worktree", "add", "-q", "-b", "private-linked", str(linked))
            # Its shared common directory must not authorize the sibling index.
            pending = Path(
                _git(linked, "rev-parse", "--path-format=absolute", "--git-path", "index").decode().removesuffix("\n")
            )
    monkeypatch.setenv("GIT_INDEX_FILE", str(pending))

    with pytest.raises(ValueError, match="active Git index"):
        staged_environment(root)


def test_linked_worktree_accepts_its_own_git_resolved_pending_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, linked = tmp_path / "repository", tmp_path / "linked"
    _repository(root)
    _git(root, "worktree", "add", "-q", "-b", "private-linked", str(linked))
    index = Path(_git(linked, "rev-parse", "--path-format=absolute", "--git-path", "index").decode().removesuffix("\n"))
    pending = index.with_name("pending-index")
    shutil.copyfile(index, pending)
    monkeypatch.setenv("GIT_INDEX_FILE", str(pending))

    assert staged_environment(linked)["GIT_INDEX_FILE"] == str(pending)


def test_default_react_runner_receives_validated_index_without_changing_security_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _repository(tmp_path)
    pending = tmp_path / ".git/pending-index"
    shutil.copyfile(tmp_path / ".git/index", pending)
    (tmp_path / "package.json").write_text('{"name":"fixture","dependencies":{"react":"19.2.0"}}\n', encoding="utf-8")
    source = tmp_path / "component.tsx"
    source.write_text("export const value = 1;\n", encoding="utf-8")
    monkeypatch.setenv("GIT_INDEX_FILE", ".git/pending-index")
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "core.worktree")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", str(tmp_path.parent / "foreign"))
    calls: list[tuple[tuple[str, ...], dict[str, str], float]] = []
    security_runners: list[ProcessRunner] = []

    def capture_process(
        arguments: Sequence[str],
        *,
        cwd: Path,
        environment: dict[str, str],
        timeout_seconds: float = 900,
        input_path: Path | None = None,
    ) -> external.ProcessOutput:
        assert cwd == tmp_path
        assert input_path is None
        calls.append((tuple(arguments), environment.copy(), timeout_seconds))
        return external.ProcessOutput(0, "", "")

    def observe_security(
        files: Sequence[str],
        *,
        root: Path,
        runner: ProcessRunner,
        capabilities: frozenset[str] | None,
        security_selection: RuleSelection | None = None,
    ) -> tuple[api.ToolReport, ...]:
        assert not files
        assert root == tmp_path
        assert capabilities == frozenset({"react-doctor"})
        assert security_selection is None
        security_runners.append(runner)
        return ()

    def observe_react(
        project: Path,
        *,
        projects: Sequence[Path],
        root: Path,
        runner: ProcessRunner,
        use_local_binary: bool,
        file_count: int,
        staged: bool,
        full_scan: bool = False,
    ) -> api.ToolReport:
        assert project == root == tmp_path
        assert tuple(projects) == (tmp_path,)
        assert use_local_binary
        assert file_count == 1
        assert staged
        assert not full_scan
        runner(("git", "diff", "--cached", "--name-only"), cwd=root)
        return api.ToolReport("react-doctor", api.Completion.COMPLETE)

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- observe the default process environment and deadline without starting third-party analyzer runtimes.
        external, "_run_process", capture_process
    )
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- this corpus has no IaC inputs; capture the security transport identity to verify its existing deadline stays selected.
        external, "_security_reports", observe_security
    )
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- execute the selected React transport with a Git request while keeping project selection and index validation real.
        external, "_invoke_react_doctor", observe_react
    )

    reports = external.analyze_external(
        [str(source)],
        root=tmp_path,
        trust=api.TrustMode.TRUSTED,
        capabilities=frozenset({"react-doctor"}),
        include_react_doctor=True,
        react_doctor_staged=True,
        eslint=False,
    )

    assert [report.name for report in reports] == ["react-doctor"]
    assert security_runners == [external.run_process]
    assert calls[0][0] == ("git", "diff", "--cached", "--name-only")
    assert calls[0][1]["GIT_INDEX_FILE"] == str(pending)
    assert {name for name in calls[0][1] if name.startswith("GIT_")} == {"GIT_INDEX_FILE", "GIT_OPTIONAL_LOCKS"}
    external._security_runner(  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage] -- verify the existing bounded security transport against the captured default runner identity.
        security_runners[0], ("checkov", "--version"), cwd=tmp_path, name="checkov"
    )
    assert calls[-1][2] == 300
    assert "GIT_INDEX_FILE" not in calls[-1][1]


@pytest.mark.parametrize(
    ("mode", "filename"),
    [
        pytest.param("only", "chosen.toml", id="only"),
        pytest.param("all", "chosen.toml", id="all"),
        pytest.param("only", "0:probe.toml", id="only-stage-prefix-path"),
    ],
)
def test_native_commit_fixes_the_actual_pending_index_and_preserves_index_entries(
    tmp_path: Path, mode: str, filename: str
) -> None:
    _repository(tmp_path)
    chosen, ordinary = tmp_path / filename, tmp_path / "ordinary.toml"
    for source in (chosen, ordinary):
        source.write_bytes(_INITIAL)
    (tmp_path / "lefthook.yml").write_text("pre-commit:\n  commands: {}\n", encoding="utf-8")
    assert main(["--root", str(tmp_path), "setup", "--hooks", "lefthook", "--config", "taplo", "--no-install"]) == 0
    _git(tmp_path, "add", "--all")
    _git(tmp_path, "commit", "-qm", "adopt fixture")
    ordinary.write_bytes(_STAGED)
    _git(tmp_path, "add", "--", ordinary.name)
    chosen.write_bytes(_STAGED)
    before_head = _git(tmp_path, "rev-parse", "HEAD")
    before_index = _git(tmp_path, "ls-files", "--stage", "-z")
    receipt = tmp_path.parent / f"{tmp_path.name}-{mode}-pending-index.json"
    script = (
        "from hashlib import sha256\n"
        "from importlib.metadata import version\n"
        "import json\n"
        "from pathlib import Path\n"
        "from repo_standards.repository import git_index_identity, read_tracked_blob_contents\n"
        "from sarj_standards.cli.main import main\n"
        "from sarj_standards.libs.adoption.manifest import REPO_STANDARDS_VERSION\n"
        "from sarj_standards.libs.staged_git import staged_environment\n"
        f"root = Path({str(tmp_path)!r})\n"
        "environment = staged_environment(root)\n"
        "index = Path(environment['GIT_INDEX_FILE'])\n"
        "before = sha256(index.read_bytes()).hexdigest()\n"
        "assert version('repo-standards') == REPO_STANDARDS_VERSION\n"
        "identity = git_index_identity(root)\n"
        f"blobs = read_tracked_blob_contents(root, ({chosen.name!r}, 'ordinary.toml'), identity=identity)\n"
        "policy = {blob.path: blob.content.hex() for blob in blobs}\n"
        "status = main(['--root', str(root), 'check', '--staged', '--fix', '--trust-repository-code'])\n"
        f"Path({str(receipt)!r}).write_text(json.dumps({{'exit': status, 'policy': policy, 'active_index_preserved': before == sha256(index.read_bytes()).hexdigest()}}))\n"
        "raise SystemExit(status)\n"
    )
    hook = tmp_path / ".git/hooks/pre-commit"
    hook.parent.mkdir(exist_ok=True)
    hook.write_text("#!/bin/sh\nexec " + shlex.join((sys.executable, "-c", script)) + "\n", encoding="utf-8")
    hook.chmod(0o700)
    command = ["git", "commit", "-m", "fixture fixes require review"]
    command.extend(("--only", "--", chosen.name) if mode == "only" else ("-a",))

    result = subprocess.run(
        command, cwd=tmp_path, env=_fixture_environment(), capture_output=True, text=True, check=False
    )

    assert result.returncode != 0, result.stdout + result.stderr
    observed = parse_json(receipt.read_text())
    assert isinstance(observed, dict)
    assert observed["exit"] == 1
    assert observed["active_index_preserved"] is True
    policy = observed["policy"]
    assert isinstance(policy, dict)
    assert policy == {
        chosen.name: _STAGED.hex(),
        ordinary.name: (_INITIAL if mode == "only" else _STAGED).hex(),
    }
    assert chosen.read_bytes() == _FIXED
    assert ordinary.read_bytes() == (_STAGED if mode == "only" else _FIXED)
    assert _git(tmp_path, "rev-parse", "HEAD") == before_head
    assert _git(tmp_path, "ls-files", "--stage", "-z") == before_index
    assert _git(tmp_path, "show", f":0:{chosen.name}") == _INITIAL
    assert _git(tmp_path, "show", f":0:{ordinary.name}") == _STAGED


@dataclass(frozen=True, slots=True)
class _ColdIndexFixture:
    root: Path
    chosen: Path
    ordinary: Path
    pending: Path


@dataclass(frozen=True, slots=True)
class _IndexImage:
    contents: bytes
    mode: int
    mtime_ns: int


@dataclass(frozen=True, slots=True)
class _SourceImage:
    contents: bytes
    mode: int


@pytest.mark.parametrize(
    ("partial", "binary"),
    [
        pytest.param(False, False, id="safe-fix-review"),
        pytest.param(True, False, id="partial-refusal"),
        pytest.param(False, True, id="binary-safe-fix-review"),
        pytest.param(True, True, id="binary-partial-refusal"),
    ],
)
def test_real_staged_cli_preserves_a_cold_alternate_index_and_validates_selected_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], partial: bool, binary: bool
) -> None:
    fixture = _cold_index_fixture(tmp_path, attributes="*.toml -diff\n" if binary else None)
    if partial:
        fixture.chosen.write_bytes(_STAGED + b"# user work\n")
    monkeypatch.setenv("GIT_INDEX_FILE", str(fixture.pending))
    sources = _tracked_source_images(fixture.root)
    active = _index_image(fixture.pending)
    ordinary = _index_image(fixture.root / ".git/index")
    head = _git(fixture.root, "rev-parse", "HEAD")
    entries = _git(fixture.root, "ls-files", "--stage", "-z", environment={"GIT_INDEX_FILE": str(fixture.pending)})
    flags = _git(fixture.root, "ls-files", "-v", "-z", environment={"GIT_INDEX_FILE": str(fixture.pending)})
    capsys.readouterr()

    status = main(["--root", str(fixture.root), "check", "--staged", "--fix", "--trust-repository-code"])

    captured = capsys.readouterr()
    assert status == (2 if partial else 1)
    if partial:
        assert "unstaged content" in captured.err
    else:
        assert "Safe fixes applied" in captured.err
    expected_sources = dict(sources)
    if not partial:
        expected_sources[fixture.chosen.name] = _SourceImage(contents=_FIXED, mode=sources[fixture.chosen.name].mode)
    assert _tracked_source_images(fixture.root) == expected_sources
    assert _index_image(fixture.pending) == active
    assert _index_image(fixture.root / ".git/index") == ordinary
    assert _git(fixture.root, "rev-parse", "HEAD") == head
    assert (
        _git(fixture.root, "ls-files", "--stage", "-z", environment={"GIT_INDEX_FILE": str(fixture.pending)}) == entries
    )
    assert _git(fixture.root, "ls-files", "-v", "-z", environment={"GIT_INDEX_FILE": str(fixture.pending)}) == flags
    assert (
        _git(
            fixture.root,
            "show",
            f":0:{fixture.chosen.name}",
            environment={"GIT_INDEX_FILE": str(fixture.pending)},
        )
        == _STAGED
    )


def _cold_index_fixture(root: Path, *, attributes: str | None = None) -> _ColdIndexFixture:
    _repository(root)
    if attributes is not None:
        (root / ".gitattributes").write_text(attributes, encoding="utf-8")
    fixture = _ColdIndexFixture(
        root=root,
        chosen=root / "chosen\tname.toml",
        ordinary=root / "ordinary.toml",
        pending=root / ".git/pending-cold-index",
    )
    for source in (fixture.chosen, fixture.ordinary):
        source.write_bytes(_INITIAL)
    if attributes is not None:
        assert _git(root, "check-attr", "-z", "diff", "--", fixture.chosen.name).split(b"\0") == [
            os.fsencode(fixture.chosen.name),
            b"diff",
            b"unset",
            b"",
        ]
    (root / "lefthook.yml").write_text("pre-commit:\n  commands: {}\n", encoding="utf-8")
    assert main(["--root", str(root), "setup", "--hooks", "lefthook", "--config", "taplo", "--no-install"]) == 0
    _git(root, "add", "--all")
    _git(root, "commit", "-qm", "adopt cold-index fixture")
    fixture.ordinary.write_bytes(_STAGED)
    _git(root, "add", "--", fixture.ordinary.name)
    fixture.chosen.write_bytes(_STAGED)
    builder = {"GIT_INDEX_FILE": str(root / ".git/index-construction")}
    _git(root, "read-tree", "HEAD", environment=builder)
    _git(root, "add", "--", fixture.chosen.name, environment=builder)
    tree = _git(root, "write-tree", environment=builder).decode().strip()
    _git(root, "read-tree", tree, environment={"GIT_INDEX_FILE": str(fixture.pending)})
    debug = _git(
        root, "ls-files", "--debug", "--", fixture.chosen.name, environment={"GIT_INDEX_FILE": str(fixture.pending)}
    )
    assert b"ctime: 0:0" in debug
    assert b"mtime: 0:0" in debug
    return fixture


def _index_image(path: Path) -> _IndexImage:
    metadata = path.stat()
    return _IndexImage(contents=path.read_bytes(), mode=stat.S_IMODE(metadata.st_mode), mtime_ns=metadata.st_mtime_ns)


def _tracked_source_images(root: Path) -> Mapping[str, _SourceImage]:
    names = _git(root, "ls-files", "--cached", "-z").decode().split("\0")
    return {
        name: _SourceImage(contents=(root / name).read_bytes(), mode=stat.S_IMODE((root / name).stat().st_mode))
        for name in names
        if name
    }
