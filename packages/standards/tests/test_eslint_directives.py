from __future__ import annotations

from collections.abc import Callable
from dataclasses import FrozenInstanceError, dataclass, field
import json
from pathlib import Path
import stat
import subprocess
import sys
from types import MappingProxyType
from typing import TYPE_CHECKING

import pytest

from sarj_standards.libs.adoption import lifecycle, transaction
from sarj_standards.libs.linting import directive_formatter, eslint_directives, native_byte_bridge
from sarj_standards.libs.staged_git import isolated_environment

from .native_package_fixture import materialize_installed_packages


if TYPE_CHECKING:
    from collections.abc import Collection, Iterable, Mapping, Sequence

    from sarj_standards.libs.linting.native_byte_process import JsonValue


_ROOT = Path(__file__).resolve().parents[3]
_BEFORE = b"/* eslint-disable no-alert */\nexport const original = 1;\n"
_AFTER = b"\nexport const original = 1;\n"


def _git(root: Path, *arguments: str) -> bytes:
    return subprocess.run(
        ("git", "--no-optional-locks", "-C", str(root), *arguments),
        env=isolated_environment(),
        capture_output=True,
        check=True,
        timeout=30,
    ).stdout


def _project(root: Path, sources: Mapping[str, bytes] | None = None) -> None:
    _git(root, "init", "--quiet", "--template=")
    (root / "package.json").write_text('{"private":true,"type":"module"}\n', encoding="utf-8")
    (root / "eslint.config.mjs").write_text("export default [];\n", encoding="utf-8")
    (root / ".gitignore").write_text("node_modules\n", encoding="utf-8")
    for name, content in ({"source.js": _BEFORE} if sources is None else sources).items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        path.chmod(0o640)
    _git(root, "add", "--all")


def _result(path: Path, output: str | None = None, *, remaining_error: bool = False) -> dict[str, JsonValue]:
    result: dict[str, JsonValue] = {
        "filePath": str(path),
        "messages": [],
        "suppressedMessages": [],
        "errorCount": 0,
        "warningCount": 0,
        "fatalErrorCount": 0,
        "fixableErrorCount": 0,
        "fixableWarningCount": 0,
    }
    if output is not None:
        result["output"] = output
    if remaining_error:
        result.update(
            {
                "messages": [{"ruleId": "fixture/problem", "severity": 2, "message": "Retained problem"}],
                "errorCount": 1,
                "fixableErrorCount": 1,
            }
        )
    return result


@dataclass
class _Native:
    stdout: str
    status: int = 0
    mutate: Callable[[], None] | None = None
    calls: list[lifecycle.Command] = field(default_factory=list)

    def __call__(self, command: lifecycle.Command) -> subprocess.CompletedProcess[str]:
        self.calls.append(command)
        assert "--fix" not in command.argv
        assert "--rule" not in command.argv
        if self.mutate is not None:
            self.mutate()
        return subprocess.CompletedProcess(command.argv, self.status, self.stdout, "")


def _native(*results: dict[str, JsonValue], status: int = 0, mutate: Callable[[], None] | None = None) -> _Native:
    return _Native(json.dumps(results), status, mutate)


def _unit_projection_owners(
    monkeypatch: pytest.MonkeyPatch,
    root: Path,
    *,
    remaining_error: bool = False,
) -> None:
    formatter = directive_formatter.FormatterOwner(
        native_byte_bridge.NativeInvocation("prettier", Path(sys.executable), root / "fixture.js", root, ()),
        "3.9.10",
        (),
        (),
    )
    eslint = directive_formatter.FormatterOwner(
        native_byte_bridge.NativeInvocation("eslint", Path(sys.executable), root / "fixture.js", root, ()),
        "10.13.0",
        (),
        (),
    )

    def select(
        repository: Path,
        relative: str,
        tracked: Collection[str],
        *,
        runtimes: dict[Path, directive_formatter.RuntimeProof] | None = None,
        _node: Callable[[Path], Path] | None = None,
    ) -> directive_formatter.FormatterOwner:
        assert repository == root
        assert relative == "source.js"
        assert relative in tracked
        assert runtimes is not None
        assert _node is not None
        return formatter

    def select_eslint(
        repository: Path,
        project: Path,
        relative: str,
        tracked: Collection[str],
        *,
        runtimes: dict[Path, directive_formatter.RuntimeProof] | None = None,
        _node: Callable[[Path], Path] | None = None,
    ) -> directive_formatter.FormatterOwner:
        assert repository == project == root
        assert relative == "source.js"
        assert relative in tracked
        assert runtimes is not None
        assert _node is not None
        return eslint

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- assert the public planner's global formatter-owner lookup and arguments; injecting an owner would bypass this lookup.
        directive_formatter, "select", select
    )
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- assert the public planner's global ESLint-owner lookup and arguments; injecting an owner would bypass this lookup.
        directive_formatter, "eslint", select_eslint
    )

    def project(
        invocation: native_byte_bridge.NativeInvocation,
        source: bytes,
        *,
        run: Callable[[lifecycle.Command], subprocess.CompletedProcess[str]],
    ) -> native_byte_bridge.NativeBytes:
        assert isinstance(run, _Native)
        if invocation.tool == "prettier":
            return native_byte_bridge.NativeBytes(0, source, b"")
        result = _result(root / "source.js", remaining_error=remaining_error)
        return native_byte_bridge.NativeBytes(int(remaining_error), json.dumps([result]).encode(), b"")

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- intercept the global byte-runner call and validate its runner while testing native postimage/fixed-point rejection through the public planner.
        native_byte_bridge, "run_bytes", project
    )


@pytest.mark.parametrize(
    ("boundary", "message"),
    [
        pytest.param("preexisting-debt", "pre-existing project formatter debt", id="preexisting-debt"),
        pytest.param("not-fixed", "native fixed point", id="not-fixed"),
        pytest.param("genuine-changed", "changed genuine ESLint findings", id="genuine-changed"),
        pytest.param("directive-remains", "left another directive edit", id="directive-remains"),
    ],
)
def test_formatter_projection_refuses_debt_nonconvergence_and_changed_findings_before_source_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    boundary: str,
    message: str,
) -> None:
    _project(tmp_path)
    _unit_projection_owners(monkeypatch, tmp_path, remaining_error=True)
    calls = 0

    def project(
        invocation: native_byte_bridge.NativeInvocation,
        source: bytes,
        *,
        run: Callable[[lifecycle.Command], subprocess.CompletedProcess[str]],
    ) -> native_byte_bridge.NativeBytes:
        nonlocal calls
        assert isinstance(run, _Native)
        if invocation.tool == "prettier":
            calls += 1
            if (boundary == "preexisting-debt" and calls == 1) or (boundary == "not-fixed" and calls == 3):
                return native_byte_bridge.NativeBytes(0, source + b"\n", b"")
            return native_byte_bridge.NativeBytes(0, source, b"")
        result = _result(
            tmp_path / "source.js",
            _AFTER.decode() + "\n" if boundary == "directive-remains" else None,
            remaining_error=boundary != "genuine-changed",
        )
        return native_byte_bridge.NativeBytes(
            int(boundary != "genuine-changed"),
            json.dumps([result]).encode(),
            b"",
        )

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- intercept the global byte-runner call and validate its runner while testing native postimage/fixed-point rejection through the public planner.
        native_byte_bridge, "run_bytes", project
    )
    index = (tmp_path / ".git/index").read_bytes()
    with pytest.raises(ValueError, match=message):
        eslint_directives.plan(
            tmp_path,
            ["source.js"],
            run=_native(_result(tmp_path / "source.js", _AFTER.decode(), remaining_error=True), status=1),
        )
    assert (tmp_path / "source.js").read_bytes() == _BEFORE
    assert (tmp_path / ".git/index").read_bytes() == index


def test_formatter_projection_freezes_native_and_normalized_bytes_and_ignores_shifted_locations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _project(tmp_path)
    _unit_projection_owners(monkeypatch, tmp_path, remaining_error=True)
    native_after = b" \nexport const original = 1;\n"

    def project(
        invocation: native_byte_bridge.NativeInvocation,
        source: bytes,
        *,
        run: Callable[[lifecycle.Command], subprocess.CompletedProcess[str]],
    ) -> native_byte_bridge.NativeBytes:
        assert isinstance(run, _Native)
        if invocation.tool == "prettier":
            return native_byte_bridge.NativeBytes(0, _AFTER if source == native_after else source, b"")
        result = _result(tmp_path / "source.js", remaining_error=True)
        result["messages"] = [
            {"ruleId": "fixture/problem", "severity": 2, "message": "Retained problem", "line": 2, "column": 14},
        ]
        return native_byte_bridge.NativeBytes(1, json.dumps([result]).encode(), b"")

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- intercept the global byte-runner call and validate its runner while testing native postimage/fixed-point rejection through the public planner.
        native_byte_bridge, "run_bytes", project
    )
    result = _result(tmp_path / "source.js", native_after.decode(), remaining_error=True)
    result["messages"] = [
        {"ruleId": "fixture/problem", "severity": 2, "message": "Retained problem", "line": 3, "column": 14},
    ]
    expected = eslint_directives.plan(tmp_path, ["source.js"], run=_native(result, status=1))
    postimage = expected["source.js"]
    assert postimage.after == _AFTER
    assert postimage.projection is not None
    assert postimage.projection.native == native_after
    assert postimage.projection.normalized == _AFTER
    assert postimage.projection.diagnostics == ((False, False, "fixture/problem", 2, "Retained problem", ""),)


def test_successful_empty_formatter_postimage_is_a_valid_comment_only_fixed_point(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    before = b"/* eslint-disable no-alert */\n"
    native_after = b" \n"
    _project(tmp_path, {"source.js": before})
    _unit_projection_owners(monkeypatch, tmp_path)

    def project(
        invocation: native_byte_bridge.NativeInvocation,
        source: bytes,
        *,
        run: Callable[[lifecycle.Command], subprocess.CompletedProcess[str]],
    ) -> native_byte_bridge.NativeBytes:
        assert isinstance(run, _Native)
        if invocation.tool == "prettier":
            return native_byte_bridge.NativeBytes(0, before if source == before else b"", b"")
        return native_byte_bridge.NativeBytes(0, json.dumps([_result(tmp_path / "source.js")]).encode(), b"")

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- intercept the global byte-runner call and validate its runner while testing native postimage/fixed-point rejection through the public planner.
        native_byte_bridge, "run_bytes", project
    )
    index = (tmp_path / ".git/index").read_bytes()
    expected = eslint_directives.plan(
        tmp_path,
        ["source.js"],
        run=_native(_result(tmp_path / "source.js", native_after.decode())),
    )
    assert expected["source.js"].after == b""
    projection = expected["source.js"].projection
    assert projection is not None
    assert projection.native == native_after
    assert projection.normalized == b""
    eslint_directives.apply(tmp_path, expected)
    assert (tmp_path / "source.js").read_bytes() == b""
    assert stat.S_IMODE((tmp_path / "source.js").stat().st_mode) == 0o640
    assert (tmp_path / ".git/index").read_bytes() == index


def test_directive_mode_keeps_canonical_owner_and_forbids_broad_fixes(tmp_path: Path) -> None:
    project = tmp_path / "packages/client"
    project.mkdir(parents=True)
    (project / "package.json").write_text("{}\n", encoding="utf-8")
    (project / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")
    (project / "eslint.config.mjs").write_text("export default [];\n", encoding="utf-8")
    source = project / "-source.js"
    source.write_bytes(_BEFORE)

    selection = lifecycle.select_eslint_commands(tmp_path, [str(source)], _directive_dry_run=True)

    assert selection.unowned_count == 0
    assert len(selection.commands) == 1
    command = selection.commands[0]
    assert command.cwd == project
    assert command.argv == (
        "pnpm",
        "exec",
        "eslint",
        "--config",
        "eslint.config.mjs",
        "--fix-dry-run",
        "--fix-type",
        "directive",
        "--format",
        "json",
        "--no-cache",
        "--",
        "-source.js",
    )
    with pytest.raises(ValueError, match="broad fixes or change rule severity"):
        lifecycle.select_eslint_commands(tmp_path, [str(source)], _directive_dry_run=True, fix=True)
    with pytest.raises(ValueError, match="broad fixes or change rule severity"):
        lifecycle.select_eslint_commands(tmp_path, [str(source)], _directive_dry_run=True, disabled_rules=("no-alert",))


def test_native_postimage_is_immutable_and_retains_remaining_findings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _project(tmp_path)
    source = tmp_path / "source.js"
    before_index = (tmp_path / ".git/index").read_bytes()
    native = _native(_result(source, _AFTER.decode(), remaining_error=True), status=1)
    _unit_projection_owners(monkeypatch, tmp_path, remaining_error=True)

    expected = eslint_directives.plan(tmp_path, ["source.js"], run=native)

    assert isinstance(expected, MappingProxyType)
    assert tuple(expected) == ("source.js",)
    assert expected["source.js"].before == _BEFORE
    assert expected["source.js"].after == _AFTER
    assert expected["source.js"].mode == 0o640
    assert expected["source.js"].projection is not None
    assert expected["source.js"].projection.native == _AFTER
    assert not hasattr(expected, "__setitem__")
    with pytest.raises(FrozenInstanceError):
        expected["source.js"].after = b"a different body"  # pyright: ignore[reportAttributeAccessIssue] -- deliberately exercise the frozen runtime assignment guard.
    assert source.read_bytes() == _BEFORE
    assert (tmp_path / ".git/index").read_bytes() == before_index
    assert native.status == 1
    assert len(native.calls) == 1

    eslint_directives.apply(tmp_path, expected)

    assert source.read_bytes() == _AFTER
    assert stat.S_IMODE(source.stat().st_mode) == 0o640
    assert (tmp_path / ".git/index").read_bytes() == before_index
    assert eslint_directives.validate(tmp_path, expected) == frozenset({"source.js"})
    repeated = eslint_directives.plan(
        tmp_path, ["source.js"], run=_native(_result(source, remaining_error=True), status=1)
    )
    assert not repeated


def test_string_candidacy_does_not_invent_a_directive_rewrite(tmp_path: Path) -> None:
    source = b'export const text = "eslint-disable no-alert";\n'
    _project(tmp_path, {"source.js": source})
    native = _native(_result(tmp_path / "source.js"))

    assert not eslint_directives.plan(tmp_path, ["source.js"], run=native)
    assert len(native.calls) == 1
    assert (tmp_path / "source.js").read_bytes() == source


@pytest.mark.parametrize("coverage", ["none", "partial"])
def test_canonical_selection_must_cover_all_eligible_inputs_without_any_source_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    coverage: str,
) -> None:
    _project(tmp_path, {"source.js": _BEFORE, "other.js": _BEFORE})
    canonical = lifecycle.select_eslint_commands(tmp_path, ["source.js", "other.js"], _directive_dry_run=True)
    command = canonical.commands[0]
    end = tuple(command.argv).index("--fix-dry-run")
    separator = tuple(command.argv).index("--", end)
    subset = lifecycle.Command(command.label, (*command.argv[: separator + 1], "source.js"), command.cwd)

    def incomplete(
        root: Path,
        paths: Iterable[str],
        *,
        label: str = "selected",
        fix: bool = False,
        expand_directories: bool = False,
        include_config_sources: bool = False,
        disabled_rules: Sequence[str] = (),
        _directive_dry_run: bool = False,
    ) -> lifecycle.EslintSelection:
        assert root == tmp_path
        assert set(paths) == {"source.js", "other.js"}
        assert label == "directive-only"
        assert _directive_dry_run is True
        assert fix is False
        assert expand_directories is False
        assert include_config_sources is False
        assert disabled_rules == ()
        return lifecycle.EslintSelection(() if coverage == "none" else (subset,), 0)

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- incomplete global canonical selections are the behavior under test; injecting a postimage would bypass coverage validation.
        lifecycle, "select_eslint_commands", incomplete
    )
    native = _native(_result(tmp_path / "source.js"))
    index = (tmp_path / ".git/index").read_bytes()
    with pytest.raises(ValueError, match="cover every eligible"):
        eslint_directives.plan(tmp_path, ["source.js", "other.js"], run=native)
    assert len(native.calls) == int(coverage == "partial")
    assert (tmp_path / "source.js").read_bytes() == _BEFORE
    assert (tmp_path / "other.js").read_bytes() == _BEFORE
    assert (tmp_path / ".git/index").read_bytes() == index


def test_native_global_config_exclusion_remains_outside_directive_cleanup(tmp_path: Path) -> None:
    _project(tmp_path)
    path = tmp_path / "eslint.config.mjs"
    path.write_bytes(_BEFORE)
    native = _Native("excluded native configuration must not be inspected")
    assert not eslint_directives.plan(tmp_path, ["eslint.config.mjs"], run=native)
    assert not native.calls
    assert path.read_bytes() == _BEFORE


@pytest.mark.parametrize(
    ("name", "content"),
    [
        ("plain.js", b"export const value = 1;\n"),
        ("build/generated.js", _BEFORE),
        ("source.generated.ts", _BEFORE),
        ("generated.js", b"// @generated -- DO NOT EDIT\n" + _BEFORE),
        (".agents/skills/example/source.js", _BEFORE),
        ("build/binary.js", b"\0\xff"),
        ("binary.generated.ts", b"\0\xff"),
        ("header.js", b"// @generated -- DO NOT EDIT\n\0\xff"),
    ],
)
def test_non_directive_and_generated_inputs_never_widen_native_selection(
    tmp_path: Path, name: str, content: bytes
) -> None:
    _project(tmp_path, {name: content})
    native = _Native("this must not be parsed")

    assert not eslint_directives.plan(tmp_path, [name], run=native)
    assert not native.calls
    assert (tmp_path / name).read_bytes() == content


def test_manifest_path_exclusion_is_kept_without_rule_severity_flags(tmp_path: Path) -> None:
    _project(tmp_path)
    (tmp_path / ".sarj-standards.toml").write_text(
        'schema = 4\nbundle = "8.132.7"\n[exclude]\npaths = ["source.js"]\n', encoding="utf-8"
    )
    native = _Native("not selected")

    assert not eslint_directives.plan(tmp_path, ["source.js"], run=native)
    assert not native.calls


def test_excluded_binary_js_does_not_require_owned_source_text(tmp_path: Path) -> None:
    _project(tmp_path, {"source.js": b"\0\xff"})
    (tmp_path / ".sarj-standards.toml").write_text(
        'schema = 4\nbundle = "8.132.7"\n[exclude]\npaths = ["source.js"]\n',
        encoding="utf-8",
    )
    native = _Native("excluded native source must not be inspected")
    index = (tmp_path / ".git/index").read_bytes()
    assert not eslint_directives.plan(tmp_path, ["source.js"], run=native)
    assert not native.calls
    assert (tmp_path / "source.js").read_bytes() == b"\0\xff"
    assert (tmp_path / ".git/index").read_bytes() == index


def test_disabled_eslint_capability_never_runs_a_directive_command(tmp_path: Path) -> None:
    _project(tmp_path)
    (tmp_path / ".sarj-standards.toml").write_text(
        'schema = 4\nbundle = "8.132.7"\n[capabilities]\ndisable = ["eslint"]\n', encoding="utf-8"
    )
    native = _Native("not selected")
    assert not eslint_directives.plan(tmp_path, ["source.js"], run=native)
    assert not native.calls


@pytest.mark.parametrize(
    ("case", "message"),
    [
        pytest.param("invalid-json", "Expecting property", id="invalid-json"),
        pytest.param("object", "result array", id="object"),
        pytest.param("missing", "coverage or exit status", id="missing"),
        pytest.param("duplicate-result", "unknown, duplicate or noncanonical", id="duplicate-result"),
        pytest.param("duplicate-key", "duplicate", id="duplicate-key"),
        pytest.param("outside", "subpath", id="outside"),
        pytest.param("untracked", "unknown, duplicate or noncanonical", id="untracked"),
        pytest.param("unselected", "unknown, duplicate or noncanonical", id="unselected"),
        pytest.param("generated", "unknown, duplicate or noncanonical", id="generated"),
        pytest.param("nontext", "nontext source postimage", id="nontext"),
        pytest.param("binary", "binary content", id="binary"),
        pytest.param("surrogate", "surrogate", id="surrogate"),
        pytest.param("fatal", "fatal or malformed ESLint diagnostic", id="fatal"),
        pytest.param("counts", "inconsistent ESLint diagnostic counts", id="counts"),
        pytest.param("fixable-counts", "inconsistent ESLint fixable diagnostic counts", id="fixable-counts"),
        pytest.param("bad-severity", "fatal or malformed ESLint diagnostic", id="bad-severity"),
        pytest.param("exit-status", "coverage or exit status", id="exit-status"),
    ],
)
def test_malformed_or_unowned_native_output_fails_without_source_or_index_writes(
    tmp_path: Path, case: str, message: str
) -> None:
    _project(tmp_path, {"source.js": _BEFORE, "other.js": b"export const other = 1;\n", "build/generated.js": _BEFORE})
    source = tmp_path / "source.js"
    row = _result(source, _AFTER.decode())
    outputs: dict[str, object] = {
        "object": row,
        "missing": [],
        "duplicate-result": [row, row],
        "outside": [{**row, "filePath": str(tmp_path.parent / "foreign.js")}],
        "untracked": [{**row, "filePath": str(tmp_path / "rogue.js")}],
        "unselected": [{**row, "filePath": str(tmp_path / "other.js")}],
        "generated": [{**row, "filePath": str(tmp_path / "build/generated.js")}],
        "nontext": [{**row, "output": 17}],
        "binary": [{**row, "output": "source\0binary"}],
        "surrogate": [{**row, "output": "\ud800"}],
        "fatal": [
            {
                **row,
                "fatalErrorCount": 1,
                "errorCount": 1,
                "messages": [{"fatal": True, "ruleId": None, "severity": 2, "message": "Parse failure"}],
            }
        ],
        "counts": [{**row, "warningCount": 1}],
        "fixable-counts": [{**row, "fixableErrorCount": 1}],
        "bad-severity": [{**row, "messages": [{"ruleId": "fixture/problem", "message": "Malformed", "severity": {}}]}],
        "exit-status": [row],
    }
    invalid = {"invalid-json": "{", "duplicate-key": '[{"filePath":"duplicate","filePath":"again"}]'}
    stdout = invalid[case] if case in invalid else json.dumps(outputs[case])
    native = _Native(stdout, 1 if case in {"fatal", "exit-status"} else 0)
    index = (tmp_path / ".git/index").read_bytes()

    with pytest.raises(ValueError, match=message):
        eslint_directives.plan(tmp_path, ["source.js"], run=native)

    assert source.read_bytes() == _BEFORE
    assert (tmp_path / ".git/index").read_bytes() == index


@pytest.mark.parametrize("status", [2, 127, -9])
def test_infrastructure_or_native_fatal_exit_never_yields_a_plan(tmp_path: Path, status: int) -> None:
    _project(tmp_path)
    with pytest.raises(ValueError, match="native ESLint failed"):
        eslint_directives.plan(
            tmp_path, ["source.js"], run=_native(_result(tmp_path / "source.js", _AFTER.decode()), status=status)
        )
    assert (tmp_path / "source.js").read_bytes() == _BEFORE


@pytest.mark.parametrize(
    "case", ["outside", "absolute", "untracked", "duplicate", "binary", "non-utf8", "link", "parent-link", "hardlink"]
)
def test_invalid_inputs_fail_before_native_execution(tmp_path: Path, case: str) -> None:
    _project(tmp_path)
    source = tmp_path / "source.js"
    paths = ["source.js"]
    match case:
        case "outside":
            paths = ["../foreign.js"]
        case "absolute":
            paths = [str(source)]
        case "untracked":
            (tmp_path / "rogue.js").write_bytes(_BEFORE)
            paths = ["rogue.js"]
        case "duplicate":
            paths *= 2
        case "binary" | "non-utf8":
            source.write_bytes(b"x\0y" if case == "binary" else b"\xff")
        case "link":
            source.unlink()
            source.symlink_to(tmp_path / "package.json")
        case "parent-link":
            (tmp_path / "alias").symlink_to(tmp_path, target_is_directory=True)
            paths = ["alias/source.js"]
        case "hardlink":
            (tmp_path / "alias.js").hardlink_to(source)
        case _:
            pytest.fail(f"unknown directive input boundary: {case}")
    native = _Native("not executed")

    with pytest.raises((OSError, ValueError)):
        eslint_directives.plan(tmp_path, paths, run=native)

    assert not native.calls


@pytest.mark.parametrize("change", ["source", "same-bytes", "mode", "index", "non-directive-input"])
def test_dry_run_source_index_or_mode_races_invalidate_the_whole_plan(tmp_path: Path, change: str) -> None:
    _project(tmp_path, {"source.js": _BEFORE, "other.js": b"export const other = 1;\n"})
    source = tmp_path / "source.js"

    def mutate() -> None:
        match change:
            case "mode":
                source.chmod(0o600)
            case "index":
                _git(tmp_path, "update-index", "--assume-unchanged", "--", "source.js")
            case "non-directive-input":
                (tmp_path / "other.js").write_bytes(b"export const changed = 2;\n")
            case "same-bytes" | "source":
                source.write_bytes(_BEFORE if change == "same-bytes" else b"export const changed = 2;\n")
            case _:
                pytest.fail(f"unknown directive dry-run race: {change}")

    native = _native(_result(source, _AFTER.decode()), mutate=mutate)

    with pytest.raises(ValueError, match="changed during directive"):
        eslint_directives.plan(tmp_path, ["source.js", "other.js"], run=native)

    assert len(native.calls) == 1


@pytest.mark.parametrize("change", ["bytes", "mode"])
def test_apply_checks_all_preimages_before_its_first_write(tmp_path: Path, change: str) -> None:
    _project(tmp_path, {"a.js": _BEFORE, "b.js": _BEFORE})
    expected = {name: eslint_directives.SourcePostimage(_BEFORE, _AFTER, 0o640) for name in ("a.js", "b.js")}
    first, second = tmp_path / "a.js", tmp_path / "b.js"
    first_time = first.stat().st_mtime_ns
    if change == "bytes":
        second.write_bytes(b"user changed the body\n")
    else:
        second.chmod(0o600)

    with pytest.raises(ValueError, match="preimage"):
        eslint_directives.apply(tmp_path, expected)

    assert first.read_bytes() == _BEFORE
    assert first.stat().st_mtime_ns == first_time


def test_apply_rolls_back_its_first_write_if_a_later_write_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _project(tmp_path, {"a.js": _BEFORE, "b.js": _BEFORE})
    expected = {name: eslint_directives.SourcePostimage(_BEFORE, _AFTER, 0o640) for name in ("a.js", "b.js")}
    original_write = transaction.FileTransaction.write_bytes

    def fail_second(self: transaction.FileTransaction, path: Path, contents: bytes) -> None:
        if path.name == "b.js":
            msg = "simulated second write failure"
            raise OSError(msg)
        original_write(self, path, contents)

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- fail the actual transaction method after its first write; replacing the transaction would bypass the rollback owner under test.
        transaction.FileTransaction, "write_bytes", fail_second
    )

    with pytest.raises(OSError, match="second write failure"):
        eslint_directives.apply(tmp_path, expected)

    assert all((tmp_path / name).read_bytes() == _BEFORE for name in expected)
    assert all(stat.S_IMODE((tmp_path / name).stat().st_mode) == 0o640 for name in expected)


@pytest.mark.parametrize("mode", [-1, 0o10000, True])
def test_apply_rejects_invalid_full_permission_modes_before_write(tmp_path: Path, mode: int) -> None:
    _project(tmp_path)
    expected = {"source.js": eslint_directives.SourcePostimage(_BEFORE, _AFTER, mode)}
    with pytest.raises(ValueError, match="invalid directive-fix source mode"):
        eslint_directives.apply(tmp_path, expected)
    assert (tmp_path / "source.js").read_bytes() == _BEFORE


@pytest.mark.parametrize("change", ["body", "mode", "link"])
def test_validate_rejects_same_path_unplanned_body_or_metadata_changes(tmp_path: Path, change: str) -> None:
    _project(tmp_path)
    source = tmp_path / "source.js"
    expected = {"source.js": eslint_directives.SourcePostimage(_BEFORE, _AFTER, 0o640)}
    eslint_directives.apply(tmp_path, expected)
    match change:
        case "body":
            source.write_bytes(_AFTER.replace(b"original", b"changed"))
        case "mode":
            source.chmod(0o600)
        case "link":
            source.unlink()
            source.symlink_to(tmp_path / "package.json")
        case _:
            pytest.fail(f"unknown directive validation mutation: {change}")

    with pytest.raises((OSError, ValueError)):
        eslint_directives.validate(tmp_path, expected)


def test_native_bom_crlf_and_non_bmp_output_round_trips_exactly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    before = '\ufeff/* eslint-disable no-alert */\r\nexport const symbol = "😀";\r\n'.encode()
    after = '\ufeff\r\nexport const symbol = "😀";\r\n'.encode()
    _project(tmp_path, {"source.js": before})
    _unit_projection_owners(monkeypatch, tmp_path)
    expected = eslint_directives.plan(
        tmp_path, ["source.js"], run=_native(_result(tmp_path / "source.js", after.decode()))
    )

    assert expected["source.js"].before == before
    assert expected["source.js"].after == after
    eslint_directives.apply(tmp_path, expected)
    assert (tmp_path / "source.js").read_bytes() == after
    assert eslint_directives.validate(tmp_path, expected) == frozenset({"source.js"})


def test_actual_pinned_eslint_fixes_only_unused_directives_and_converges(tmp_path: Path) -> None:
    source_bytes = (
        b"export function original() {\n  /* eslint-disable no-alert */\n  /* eslint-disable no-console */\n"
        b"  console.log('kept');\n}\n"
    )
    local = materialize_installed_packages(
        tmp_path,
        {
            "eslint": _ROOT / "packages/typescript/node_modules/eslint",
            "prettier": _ROOT / "apps/docs/node_modules/prettier",
        },
        expected_versions={"eslint": "10.13.0", "prettier": "3.9.10"},
    )
    _project(tmp_path, {"source.js": source_bytes, "unselected.js": _BEFORE})
    assert local.roots["eslint"].version == "10.13.0"
    assert local.roots["prettier"].version == "3.9.10"
    (tmp_path / "package.json").write_text(
        '{"private":true,"type":"module","scripts":{"format":"prettier --write ."},'
        '"devDependencies":{"eslint":"10.13.0","prettier":"3.9.10"}}\n',
        encoding="utf-8",
    )
    (tmp_path / "package-lock.json").write_text('{"lockfileVersion":3}\n', encoding="utf-8")
    (tmp_path / ".prettierrc.json").write_text('{"singleQuote":true}\n', encoding="utf-8")
    (tmp_path / "eslint.config.mjs").write_text(
        "const problem = {meta:{type:'problem',fixable:'code',schema:[]},create(context){return {"
        "Identifier(node){if(node.name==='original'){context.report({node,message:'Retained fixable problem',"
        "fix(fixer){return fixer.replaceText(node,'changed');}});}}};}};\n"
        "export default [{linterOptions:{reportUnusedDisableDirectives:'error'},"
        "plugins:{fixture:{rules:{problem}}},rules:{'no-alert':'error','no-console':'error','fixture/problem':'error'}}];\n",
        encoding="utf-8",
    )
    _git(tmp_path, "add", "--all")
    statuses: list[tuple[str, int]] = []

    def native(command: lifecycle.Command) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            command.argv,
            cwd=command.cwd,
            env=native_byte_bridge.child_environment(),
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
        statuses.append((command.label, result.returncode))
        if command.label == "native Node runtime path":
            assert result.returncode == 0, result
            assert not result.stderr, result
        return result

    before_index = (tmp_path / ".git/index").read_bytes()

    expected = eslint_directives.plan(tmp_path, ["source.js"], run=native)

    assert tuple(expected) == ("source.js",)
    assert b"no-alert" not in expected["source.js"].after
    assert b"eslint-disable no-console" in expected["source.js"].after
    assert b"export function original() {" in expected["source.js"].after
    assert b"  console.log('kept');\n}\n" in expected["source.js"].after
    assert b"changed" not in expected["source.js"].after
    projection = expected["source.js"].projection
    assert projection is not None
    assert projection.native != projection.normalized
    assert projection.normalized == expected["source.js"].after
    assert any(not item[0] and item[2] == "fixture/problem" for item in projection.diagnostics)
    assert any(item[0] and item[2] == "no-console" for item in projection.diagnostics)
    assert (tmp_path / "source.js").read_bytes() == source_bytes
    eslint_directives.apply(tmp_path, expected)
    assert not eslint_directives.plan(tmp_path, ["source.js"], run=native)
    assert [code for label, code in statuses if label.startswith("ESLint (")] == [1, 1]
    assert all(code == 0 for label, code in statuses if not label.startswith("ESLint ("))
    assert (tmp_path / "unselected.js").read_bytes() == _BEFORE
    assert (tmp_path / ".git/index").read_bytes() == before_index
