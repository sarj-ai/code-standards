from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import stat
import subprocess
from typing import TYPE_CHECKING

import pytest

from sarj_standards import api
from sarj_standards.libs.adoption.manifest import Manifest
from sarj_standards.libs.linting import autofix
from sarj_standards.libs.staged_git import isolated_environment


if TYPE_CHECKING:
    from collections.abc import Sequence
    from typing import Literal, NoReturn


type _Operation = Literal["check", "analyze", "run", "fix"]


@dataclass(frozen=True, slots=True)
class _Snapshot:
    sources: dict[str, tuple[bytes, int]]
    index_bytes: bytes
    index_mode: int
    head_bytes: bytes
    entries: bytes
    flags: bytes


def _git(root: Path, *arguments: str) -> bytes:
    return subprocess.run(
        ("git", "--no-optional-locks", "--literal-pathspecs", "-C", str(root), *arguments),
        env=isolated_environment(),
        capture_output=True,
        check=True,
        timeout=30,
    ).stdout


def _project(root: Path) -> None:
    _git(root, "init", "--quiet", "--template=")
    # Every character is a valid path, so iterating a scalar string would reach
    # native work instead of being rejected accidentally by a missing filename.
    for name in ("a", "p", "y"):
        (root / name).write_bytes(b"literal character operand\n")
    (root / "a.py").write_bytes(b"# ========\nvalue = 1\n")
    (root / "a.py").chmod(0o640)
    (root / "victim.py").write_bytes(b"# ========\nother = 2\n")
    (root / ".sarj-standards.toml").write_text(
        Manifest(version=api.__version__, configs=(), python_dest=".", typescript_dest=".").render(),
        encoding="utf-8",
    )
    _git(root, "add", "--all")


def _snapshot(root: Path) -> _Snapshot:
    sources = {
        name: ((root / name).read_bytes(), stat.S_IMODE((root / name).stat().st_mode))
        for name in ("a", "p", "y", "a.py", "victim.py", ".sarj-standards.toml")
    }
    index = root / ".git/index"
    return _Snapshot(
        sources=sources,
        index_bytes=index.read_bytes(),
        index_mode=stat.S_IMODE(index.stat().st_mode),
        head_bytes=(root / ".git/HEAD").read_bytes(),
        entries=_git(root, "ls-files", "--stage", "-z"),
        flags=_git(root, "ls-files", "-v", "-z"),
    )


def _unexpected_manifest(_root: Path) -> NoReturn:
    message = "invalid API paths reached manifest loading"
    raise AssertionError(message)


@pytest.mark.parametrize(argnames="operation", argvalues=["check", "analyze", "run", "fix"])
@pytest.mark.parametrize(
    argnames="paths",
    argvalues=[
        "a.py",
        ".",
        "",
        b"a.py",
        b"",
        pytest.param(Path("a.py"), id="bare-path-object"),
        pytest.param([""], id="empty-path-member"),
        pytest.param([b"a.py"], id="bytes-path-member"),
        pytest.param([None], id="none-path-member"),
        pytest.param([1], id="integer-path-member"),
        pytest.param(["a.py", None], id="mixed-none-path-member"),
        pytest.param(["\0"], id="nul-path-member"),
        pytest.param(["victim.py", "\0"], id="valid-and-nul-path-members"),
        42,
        pytest.param(bytearray(b"a.py"), id="bare-bytearray"),
    ],
)
def test_invalid_paths_fail_before_policy_native_or_fix_and_preserve_source_and_index(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: _Operation,
    paths: Sequence[str],
) -> None:
    # Parametrized negatives intentionally include values outside the public
    # annotation: runtime callers still receive a structured input failure.
    _project(tmp_path)
    before = _snapshot(tmp_path)
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- intercept a lookup that invalid paths must never reach; injecting a dependency would change this public boundary.
        api, "load_manifest", _unexpected_manifest
    )
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- intercept the mutating dispatcher lookup; dependency injection would bypass the facade boundary being verified.
        autofix, "run", _unexpected_fix
    )
    standards = api.Standards(tmp_path)
    result: api.Result | api.AnalysisReport
    match operation:
        case "check":
            result = standards.check(paths)
        case "fix":
            result = standards.fix(paths)
        case "run":
            result = standards.run(paths)
        case "analyze":
            result = standards.analyze(paths)
    if isinstance(result, api.Result):
        assert result.status is api.Status.INVALID
        assert result.exit_code == 2
        assert result.changes == ()
        assert result.findings[0].id == f"{operation}.input.invalid"
    else:
        assert result.conclusion is api.Conclusion.INCONCLUSIVE
        assert result.issues[0].kind == "invalid-input"
    assert _snapshot(tmp_path) == before


def _unexpected_fix(
    _root: Path,
    _paths: Sequence[str],
    *,
    trusted: bool = False,
    eslint: bool = True,
    machine_output: bool = False,
    default_scope: bool = False,
    **_extra_options: bool,
) -> NoReturn:
    message = f"invalid API paths reached safe-fix work ({trusted=}, {eslint=}, {machine_output=}, {default_scope=})"
    raise AssertionError(message)


def test_scalar_fix_cannot_rewrite_a_sibling_through_its_dot_character(tmp_path: Path) -> None:
    # These are real facade/custom-fixer inputs, with no dispatcher/runner double.
    # In the old comprehension, "a.py" selects a, ., p, y; the dot exposes both
    # banner-bearing Python files, including the separate unselected victim.
    root = tmp_path / "scalar-negative"
    control = tmp_path / "explicit-positive"
    root.mkdir()
    control.mkdir()
    _project(root)
    _project(control)
    assert all((root / name).is_file() for name in ("a", "p", "y", "a.py", "victim.py"))
    control_index = (control / ".git/index").read_bytes()

    positive = api.Standards(control).fix(["victim.py"])

    assert positive.status is api.Status.CHANGED
    assert positive.exit_code == 0
    assert positive.changes == (api.Change("update", "applied safe fixes", control / "victim.py"),)
    assert (control / "victim.py").read_bytes() == b"\nother = 2\n"
    assert (control / "a.py").read_bytes() == b"# ========\nvalue = 1\n"
    assert (control / ".git/index").read_bytes() == control_index
    before = _snapshot(root)

    result = api.Standards(root).fix("a.py")

    assert result.status is api.Status.INVALID
    assert result.exit_code == 2
    assert result.findings[0].id == "fix.input.invalid"
    assert "pass a list of paths" in result.findings[0].message
    assert result.changes == ()
    assert (root / "victim.py").read_bytes() == b"# ========\nother = 2\n"
    assert _snapshot(root) == before


def test_prepared_only_cannot_hide_falsey_invalid_source_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _project(tmp_path)
    before = _snapshot(tmp_path)
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- observe that invalid prepared-only input stops before manifest lookup; injection would replace the boundary.
        api, "load_manifest", _unexpected_manifest
    )

    report = api.Standards(tmp_path).analyze("", prepared_only=True, prepared_devops=(tmp_path / "receipt.json",))

    assert report.conclusion is api.Conclusion.INCONCLUSIVE
    assert report.issues[0].kind == "invalid-input"
    assert "sequence of path strings" in report.issues[0].message
    assert _snapshot(tmp_path) == before


def test_valid_explicit_sequence_inputs_keep_empty_and_literal_filename_semantics(tmp_path: Path) -> None:
    _project(tmp_path)
    before = _snapshot(tmp_path)
    # A sequence preserves each whole filename, including literal whitespace and
    # leading hyphens; only the accidental scalar-to-character expansion is gone.
    names = ("source.py", "--root=literal.py", "line\nname.py", " ")
    selected = api._path_inputs(names)  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage] -- exercise validated whole-path tuple semantics with controlled fixture inputs.
    empty = api._path_inputs([])  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage] -- assert the explicit-empty input boundary without invoking native work.
    explicit_root = api._path_inputs(["."])  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage] -- distinguish an authored root element from an accidental scalar-character root.
    assert selected == names
    assert empty == ()
    assert explicit_root == (".",)
    assert _snapshot(tmp_path) == before
