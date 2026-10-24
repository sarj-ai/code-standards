from __future__ import annotations

from contextlib import suppress
from itertools import product
import os
from pathlib import Path
import re
import shlex
import signal
import subprocess
from typing import NamedTuple

import pytest

from sarj_standards.libs.typed_containers import is_object_list, is_object_mapping
from sarj_standards.libs.yaml_boundary import parse_yaml


_ROOT = Path(__file__).resolve().parents[3]
_SUITES = frozenset({"standards", "bootstrap", "contracts", "python", "sql", "iac"})
_RECORDER = """#!/usr/bin/env python3
import fcntl
import os
from pathlib import Path
import sys
import time

args = sys.argv[1:]
if Path(sys.argv[0]).name == 'npm':
    assert args[:2] == ['--prefix', 'packages/typescript'], args
    assert args[2:] in (['run', 'build'], ['test']), args
    target = 'typescript-build' if args[2:] == ['run', 'build'] else 'typescript'
elif args[:2] == ['run', '--project']:
    if 'sarj_standards.libs.release.native_test_setup' in args:
        assert args == ['run', '--project', 'packages/standards', '--frozen', 'python',
                        '-m', 'sarj_standards.libs.release.native_test_setup', '--root', '.'], args
        handoff = Path(os.environ['GITHUB_PATH'])
        handoff.write_text(str(Path('attested tools').resolve()) + '\\n')
        Path('native-setup-path').write_text(str(handoff))
        raise SystemExit(29 if Path('fail-target').read_text() == 'native-setup' else 0)
    expected = ['run', '--project', 'packages/standards', '--frozen', 'python',
                '-m', 'sarj_standards.libs.release.wheel_tests', '--root', '.', '--jobs', '4']
    if '--changed' in args:
        expected += ['--changed', '--base', 'origin/branch with space', '-k', 'selected']
    assert args == expected, args
    assert os.environ['PATH'].split(os.pathsep)[0] == str(Path('attested tools').resolve())
    assert os.environ['GITHUB_PATH'] == str(Path('parent-path').resolve())
    assert Path('parent-path').read_text() == 'parent handoff retained'
    assert not Path(Path('native-setup-path').read_text()).parent.exists()
    target = 'standards'
elif args[:2] == ['--directory', 'packages/python']:
    assert args == ['--directory', 'packages/python', 'run', '--locked', '--with',
                    'pytest-xdist==3.8.0', 'pytest', '-q', '-n', '4', '--dist', 'worksteal'], args
    target = 'python'
else:
    assert len(args) == 5 and args[0] == '--directory' and args[2:] == ['run', 'pytest', '-q'], args
    target = Path(args[1]).name
    assert target in {'bootstrap', 'contracts', 'python', 'sql', 'iac'}, args

def record(action):
    with Path('events.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        with Path('events').open('a+') as stream:
            stream.write(action + ' ' + target + '\\n')
            stream.flush()
            stream.seek(0)
            active = sum(1 if line.startswith('start ') else -1 for line in stream)
        if active >= int(Path('barrier').read_text()):
            Path('overlap').touch()

record('start')
deadline = time.monotonic() + 5
while not Path('overlap').exists():
    assert time.monotonic() < deadline, 'native Make did not admit the expected recipes'
    time.sleep(.01)
record('end')
raise SystemExit(23 if Path('fail-target').read_text() == target else 0)
"""


class _Result(NamedTuple):
    process: subprocess.CompletedProcess[str]
    events: list[tuple[str, str]]
    peak_recipes: int


def _workflow_command(scopes: dict[str, str] | None = None) -> str:
    document = parse_yaml((_ROOT / ".github/workflows/ci.yml").read_text())
    assert is_object_mapping(document)
    jobs = document["jobs"]
    assert is_object_mapping(jobs)
    job = jobs["python-compatibility"]
    assert is_object_mapping(job)
    steps = job["steps"]
    assert is_object_list(steps)
    commands = [
        command
        for step in steps
        if is_object_mapping(step) and isinstance(command := step.get("run"), str) and command.startswith("make ")
    ]
    assert len(commands) == 1
    outputs = {} if scopes is None else scopes
    command = re.sub(
        r"\$\{\{ needs\.changes\.outputs\.([a-z]+) != 'false' && '([^']+)' \|\| '' \}\}",
        lambda match: "" if outputs.get(match[1], "").casefold() == "false" else match[2],
        commands[0],
    )
    assert "${{" not in command, command
    return command


@pytest.fixture
def make_probe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "Makefile").write_bytes((_ROOT / "Makefile").read_bytes())
    helper = Path(".github/scripts/make-native-test-tools.sh")
    (tmp_path / helper).parent.mkdir(parents=True)
    (tmp_path / helper).write_bytes((_ROOT / helper).read_bytes())
    (tmp_path / "attested tools").mkdir()
    (tmp_path / "parent-path").write_text("parent handoff retained")
    monkeypatch.setenv("GITHUB_PATH", str(tmp_path / "parent-path"))
    binaries = tmp_path / "bin"
    binaries.mkdir()
    for name in ("uv", "npm"):
        executable = binaries / name
        executable.write_text(_RECORDER)
        executable.chmod(0o755)
    for name in ("MAKEFLAGS", "MFLAGS", "MAKEOVERRIDES", "TEST_JOBS", "PYTEST_ARGS", "PYTEST_XDIST_AUTO_NUM_WORKERS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PATH", str(binaries), prepend=":")
    return tmp_path


def _run(root: Path, command: str, *, fail: str = "", timeout_seconds: float = 10) -> _Result:
    jobs = next((arg.removeprefix("--jobs=") for arg in shlex.split(command) if arg.startswith("--jobs=")), "1")
    targets = [arg for arg in shlex.split(command) if arg.startswith("test-")]
    (root / "barrier").write_text(str(min(int(jobs), len(targets))))
    (root / "fail-target").write_text(fail)
    argv = ("bash", "-eu", "-o", "pipefail", "-c", command)
    process = subprocess.Popen(
        argv,
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout_seconds)
    except BaseException:
        # Keep the group leader unreaped until its private descendants are
        # stopped, so this process-group identity cannot be reused meanwhile.
        if process.returncode is None:
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
        process.communicate(timeout=2)
        raise
    assert process.returncode is not None
    result = subprocess.CompletedProcess(argv, process.returncode, stdout, stderr)
    events: list[tuple[str, str]] = []
    active: set[str] = set()
    peak = 0
    for line in (root / "events").read_text().splitlines():
        action, target = line.split()
        events.append((action, target))
        if action == "start":
            assert target not in active
            active.add(target)
            peak = max(peak, len(active))
        else:
            assert action == "end"
            active.remove(target)
    assert not active, result.stdout + result.stderr
    if (root / "native-setup-path").exists():
        assert not Path((root / "native-setup-path").read_text()).parent.exists()
    return _Result(result, events, peak)


def _assert_run(result: _Result, *, success: bool, standards: bool = True, suites: frozenset[str] = _SUITES) -> None:
    assert (result.process.returncode == 0) is success, result.process.stdout + result.process.stderr
    expected = (suites if standards else suites - {"standards"}) | {"typescript-build"}
    for action in ("start", "end"):
        assert sorted(target for event, target in result.events if event == action) == sorted(expected)
    assert result.peak_recipes == min(2, len(suites))
    if standards:
        assert result.events.index(("end", "typescript-build")) < result.events.index(("start", "standards"))


def test_compatibility_runs_every_native_suite_with_two_make_slots(make_probe: Path) -> None:
    _assert_run(_run(make_probe, _workflow_command()), success=True)


@pytest.mark.parametrize(("bootstrap", "python", "sql", "iac"), list(product(("false", "true"), repeat=4)))
def test_compatibility_runs_only_affected_native_suites(
    make_probe: Path, bootstrap: str, python: str, sql: str, iac: str
) -> None:
    scopes = {"bootstrap": bootstrap, "python": python, "sql": sql, "iac": iac}
    suites = {"standards"}
    if bootstrap == "true":
        suites.add("bootstrap")
    if python == "true":
        suites.update(("contracts", "python"))
    if sql == "true":
        suites.add("sql")
    if iac == "true":
        suites.add("iac")
    _assert_run(_run(make_probe, _workflow_command(scopes)), success=True, suites=frozenset(suites))


@pytest.mark.parametrize("scope", ["bootstrap", "python", "sql", "iac"])
@pytest.mark.parametrize("value", ["", "0", "unexpected", " false "])
def test_unknown_routing_includes_the_compatibility_suite(make_probe: Path, scope: str, value: str) -> None:
    scopes = dict.fromkeys(("bootstrap", "python", "sql", "iac"), "true") | {scope: value}
    _assert_run(_run(make_probe, _workflow_command(scopes)), success=True)


@pytest.mark.parametrize("value", ["False", "FALSE"])
def test_compatibility_matches_github_case_insensitive_string_comparison(make_probe: Path, value: str) -> None:
    scopes: dict[str, str] = dict.fromkeys(("bootstrap", "python", "sql", "iac"), value)
    _assert_run(_run(make_probe, _workflow_command(scopes)), success=True, suites=frozenset({"standards"}))


@pytest.mark.parametrize("suite", sorted(_SUITES))
def test_compatibility_failure_keeps_independent_suites_running(make_probe: Path, suite: str) -> None:
    _assert_run(_run(make_probe, _workflow_command(), fail=suite), success=False)


def test_failed_plugin_build_prevents_only_its_dependent_suite(make_probe: Path) -> None:
    _assert_run(_run(make_probe, _workflow_command(), fail="typescript-build"), success=False, standards=False)


def test_failed_native_setup_prevents_only_its_dependent_suite(make_probe: Path) -> None:
    result = _run(make_probe, _workflow_command(), fail="native-setup")
    _assert_run(result, success=False, standards=False)
    assert "Error 29" in result.process.stderr


@pytest.mark.parametrize("target", ["test-standards", "test-standards-changed"])
def test_native_setup_preserves_wheel_runner_arguments(make_probe: Path, target: str) -> None:
    command = f"make {target}"
    if target.endswith("-changed"):
        command += ' BASE="origin/branch with space" PYTEST_ARGS="-k selected"'
    result = _run(make_probe, command)
    assert result.process.returncode == 0, result.process.stdout + result.process.stderr
    assert result.events == [
        ("start", "typescript-build"),
        ("end", "typescript-build"),
        ("start", "standards"),
        ("end", "standards"),
    ]


@pytest.mark.parametrize("mutation", ["missing", "extra", "serial", "three-slots", "no-keep-going", "lost-status"])
def test_compatibility_controls_reject_incomplete_or_unsafe_commands(make_probe: Path, mutation: str) -> None:
    command = _workflow_command()
    fail = ""
    match mutation:
        case "missing":
            command = command.replace(" test-iac", "")
        case "extra":
            command += " test-typescript"
        case "serial":
            command = command.replace("--jobs=2", "--jobs=1")
        case "three-slots":
            command = command.replace("--jobs=2", "--jobs=3")
        case "no-keep-going":
            command = command.replace("--keep-going", "")
            fail = "bootstrap"
        case _:
            assert mutation == "lost-status"
            command += " || true"
            fail = "bootstrap"
    with pytest.raises(AssertionError):
        _assert_run(_run(make_probe, command, fail=fail), success=not fail)
