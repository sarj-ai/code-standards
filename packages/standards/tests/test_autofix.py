from __future__ import annotations

import json
import stat
import sys
from typing import TYPE_CHECKING

import pytest

import sarj_standards.cli.main as cli
from sarj_standards.libs.adoption import lifecycle, manifest
from sarj_standards.libs.json_boundary import normalize_json_value, parse_json
from sarj_standards.libs.linting import autofix
from sarj_standards.libs.linting.policy import Policy


if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path


@pytest.mark.parametrize(
    ("name", "source", "retained"),
    [
        ("source.py", "# ========\r\nvalue = 1\r\n", "value = 1"),
        ("migration.sql", "-- ========\r\nSELECT 1;\r\n", "SELECT 1;"),
        ("main.tf", '# ========\r\nlocals { value = "α" }\r\n', 'value = "α"'),
        ("config.toml", "# Retry count is 3\r\nretry_count = 3\r\n", "retry_count = 3"),
    ],
)
def test_native_fixes_preserve_source_bytes_modes_and_converge(
    tmp_path: Path, name: str, source: str, retained: str
) -> None:
    path = tmp_path / name
    path.write_bytes(source.encode("utf-8"))
    path.chmod(0o750)
    changed = autofix.fix_paths(tmp_path, [str(path)])
    fixed = path.read_bytes()
    assert changed == (path,)
    assert retained.encode() in fixed
    assert b"========" not in fixed
    assert b"Retry count" not in fixed
    assert b"\r\n" in fixed
    assert stat.S_IMODE(path.stat().st_mode) == 0o750
    assert autofix.fix_paths(tmp_path, [str(path)]) == ()
    assert path.read_bytes() == fixed


def test_native_fixes_honor_path_rule_code_and_override_exclusions(tmp_path: Path) -> None:
    sources: dict[Path, bytes] = {}
    for name in ("excluded.py", "by_code.py", "by_id.py", "included.py"):
        path = tmp_path / name
        path.write_text("# ========\nvalue = 1\n", encoding="utf-8")
        sources[path] = path.read_bytes()
    adopted = manifest.Manifest(
        version="0.0.0",
        configs=(),
        python_dest=".",
        typescript_dest=".",
        excluded_paths=("excluded.py",),
        exclusion_overrides=(
            manifest.ExclusionOverride(
                paths=("by_code.py",), rules=("python:SARJ016",), reason="fixture code exclusion"
            ),
            manifest.ExclusionOverride(
                paths=("by_id.py",), rules=("python:no-comment-cruft",), reason="fixture ID exclusion"
            ),
        ),
    )
    policy = Policy.from_manifest(tmp_path, adopted)
    assert autofix.fix_paths(tmp_path, [str(path) for path in sources], policy=policy) == (tmp_path / "included.py",)
    assert all(path.read_bytes() == source for path, source in sources.items() if path.name != "included.py")


def test_native_fixes_preserve_python_encoding_cookie_and_bom(tmp_path: Path) -> None:
    latin = tmp_path / "latin.py"
    latin.write_bytes(b'# coding: latin-1\r\n\r\n# ========\r\nvalue = "caf\xe9"\r\n')
    bom = tmp_path / "bom.py"
    bom.write_bytes(b'\xef\xbb\xbf# ========\r\nvalue = "caf\xc3\xa9"\r\n')
    assert set(autofix.fix_paths(tmp_path, [str(latin), str(bom)])) == {latin, bom}
    assert latin.read_bytes() == b'# coding: latin-1\r\n\r\n\r\nvalue = "caf\xe9"\r\n'
    assert bom.read_bytes() == b'\xef\xbb\xbf\r\nvalue = "caf\xc3\xa9"\r\n'


def test_native_fix_plan_refuses_links_before_changing_any_source(tmp_path: Path) -> None:
    first = tmp_path / "first.py"
    original = b"# ========\nvalue = 1\n"
    first.write_bytes(original)
    target = tmp_path / "target.py"
    target.write_bytes(original)
    link = tmp_path / "link.py"
    link.symlink_to(target)
    with pytest.raises(ValueError, match="symlink"):
        autofix.fix_paths(tmp_path, [str(first), str(link)])
    assert first.read_bytes() == target.read_bytes() == original


def test_native_fix_plan_does_not_follow_parent_symlinks(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    source = outside / "source.py"
    original = b"# ========\nvalue = 1\n"
    source.write_bytes(original)
    root = tmp_path / "repository"
    root.mkdir()
    (root / "linked").symlink_to(outside, target_is_directory=True)
    with pytest.raises((OSError, ValueError), match=r"symlink|escapes|outside"):
        autofix.fix_paths(root, [str(root / "linked/source.py")])
    assert source.read_bytes() == original


def test_native_fix_paths_resolve_relative_inputs_against_the_explicit_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    source = root / "source.py"
    source.write_bytes(b"# ========\nvalue = 1\n")
    monkeypatch.chdir(tmp_path)
    assert autofix.fix_paths(root, ["source.py"]) == (source,)
    assert source.read_bytes() == b"\nvalue = 1\n"


def test_upstream_fix_plans_honor_rule_exclusions_and_disabled_engines(tmp_path: Path) -> None:
    source = tmp_path / "source.py"
    source.write_text("import os\n", encoding="utf-8")
    adopted = manifest.Manifest(
        version="8.105.11",
        configs=("ruff",),
        python_dest=".",
        typescript_dest=".",
        excluded_rules=("ruff:F401",),
    )
    path = tmp_path / manifest.MANIFEST_NAME
    path.write_text(adopted.render(), encoding="utf-8")
    fixes = next(
        command
        for command in lifecycle.selected_format_commands(tmp_path, [str(source)])
        if command.label == "Ruff fixes"
    )
    assert "--no-unsafe-fixes" in fixes.argv
    assert fixes.argv[fixes.argv.index("--extend-ignore") + 1] == "F401"
    path.write_text(
        manifest.Manifest(version="8.105.11", configs=(), python_dest=".", typescript_dest=".").render(),
        encoding="utf-8",
    )
    assert lifecycle.selected_format_commands(tmp_path, [str(source)]) == []


@pytest.mark.parametrize("machine_output", [False, True])
def test_fix_tool_output_preserves_machine_stdout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
    machine_output: bool,
) -> None:
    source = tmp_path / "source.py"
    source.write_text("value = 1\n", encoding="utf-8")
    tool = tmp_path / "fixture_tool.py"
    tool.write_text('print("fixture tool output")\n', encoding="utf-8")

    def commands(
        root: Path, paths: Iterable[str], *, trusted: bool = True, eslint: bool = True
    ) -> list[lifecycle.Command]:
        assert root == tmp_path
        assert tuple(paths) == (str(source),)
        assert not trusted
        assert eslint
        return [lifecycle.Command("fixture", (sys.executable, str(tool)), root)]

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- intercepts the external-tool plan to exercise real stdout descriptor routing with an isolated fixture.
        lifecycle, "selected_format_commands", commands
    )
    result = autofix.run(tmp_path, [str(source)], machine_output=machine_output)
    output = capfd.readouterr()
    assert result.status == 0
    assert result.changed == ()
    assert output.out == ("" if machine_output else "fixture tool output\n")
    assert output.err == ("fixture tool output\n" if machine_output else "")


@pytest.mark.parametrize("failed_status", [-9, -11, 2])
def test_failed_fix_tool_stops_remaining_commands_and_reports_infrastructure_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failed_status: int
) -> None:
    source = tmp_path / "source.py"
    source.write_text("# ========\nvalue = 1\n", encoding="utf-8")
    planned = [lifecycle.Command(label, (label,), tmp_path) for label in ("findings", "failure", "later")]
    executed: list[str] = []

    def commands(
        root: Path, paths: Iterable[str], *, trusted: bool = True, eslint: bool = True
    ) -> list[lifecycle.Command]:
        assert root == tmp_path
        assert tuple(paths) == (str(source),)
        assert not trusted
        assert eslint
        return planned

    def execute(commands: Iterable[lifecycle.Command]) -> int:
        labels = [command.label for command in commands]
        executed.extend(labels)
        return 1 if labels == ["findings"] else failed_status

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- the plan and executor model a remaining finding followed by a crashed external fixer.
        lifecycle, "selected_format_commands", commands
    )
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- negative process return codes must fail the real orchestration and stop later tools.
        lifecycle, "execute", execute
    )
    result = autofix.run(tmp_path, [str(source)])
    assert result.status == 2
    assert result.changed == (source,)
    assert executed == ["findings", "failure"]


@pytest.mark.parametrize("output_format", ["text", "json", "sarif", "github"])
@pytest.mark.parametrize(
    ("name", "original"),
    [
        ("bad_header.py", b'value = "\xff"\n'),
        ("bad_body.py", b'value = 1\nother = "\xff"\n'),
        ("bad.sql", b'SELECT "\xff";\n'),
    ],
)
def test_check_fixes_report_encoding_failures_without_changing_source(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], output_format: str, name: str, original: bytes
) -> None:
    source = tmp_path / name
    source.write_bytes(original)
    assert cli.main(["--root", str(tmp_path), "check", "--fix", "--format", output_format, "--", name]) == 2
    captured = capsys.readouterr()
    assert source.read_bytes() == original
    assert "cannot apply safe fixes" in captured.err
    if output_format in {"json", "sarif"}:
        payload = normalize_json_value(parse_json(captured.out))
        assert isinstance(payload, dict)
        if output_format == "json":
            assert payload["completion"] == "failed"
            assert payload["exitCode"] == 2
        else:
            runs = payload["runs"]
            assert isinstance(runs, list)
            run = runs[0]
            assert isinstance(run, dict)
            invocations = run["invocations"]
            assert isinstance(invocations, list)
            invocation = invocations[0]
            assert isinstance(invocation, dict)
            assert invocation["executionSuccessful"] is False
        assert "autofix-failed" in captured.out
    elif output_format == "github":
        assert "::error" in captured.out
        assert "autofix-failed" in captured.out
    else:
        assert not captured.out


@pytest.mark.parametrize("output_format", ["json", "sarif"])
def test_check_fixes_write_failure_reports_to_the_requested_destination(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], output_format: str
) -> None:
    original = b'value = "\xff"\n'
    source = tmp_path / "bad.py"
    source.write_bytes(original)
    destination = tmp_path / f"failure.{output_format}"
    assert (
        cli.main(
            [
                "--root",
                str(tmp_path),
                "check",
                "--fix",
                "--format",
                output_format,
                "--output",
                destination.name,
                "--",
                source.name,
            ]
        )
        == 2
    )
    assert not capsys.readouterr().out
    assert source.read_bytes() == original
    assert json.loads(destination.read_text())
    assert "autofix-failed" in destination.read_text()


@pytest.mark.parametrize("output_format", ["json", "sarif", "github"])
def test_check_fixes_report_failed_child_without_corrupting_machine_stdout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str], output_format: str
) -> None:
    source = tmp_path / "source.py"
    source.write_text("value = 1\n")
    child = tmp_path / "child.py"
    child.write_text('import sys\nprint("child detail")\nprint("child failure", file=sys.stderr)\nsys.exit(2)\n')

    def commands(
        root: Path, paths: Iterable[str], *, trusted: bool = True, eslint: bool = True
    ) -> list[lifecycle.Command]:
        assert root == tmp_path
        assert tuple(paths) == (str(source),)
        assert not trusted
        assert eslint
        return [lifecycle.Command("private child", (sys.executable, str(child)), root)]

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- run a real isolated child to verify failed-tool output and the CLI report contract together.
        lifecycle, "selected_format_commands", commands
    )
    assert cli.main(["--root", str(tmp_path), "check", "--fix", "--format", output_format, "--", source.name]) == 2
    captured = capfd.readouterr()
    assert "child detail" in captured.err
    assert "child failure" in captured.err
    assert "child detail" not in captured.out
    assert "autofix-failed" in captured.out
    assert source.read_text() == "value = 1\n"
    if output_format in {"json", "sarif"}:
        assert json.loads(captured.out)
    else:
        assert "::error" in captured.out
