from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

import pytest


_ADAPTER = Path(__file__).resolve().parents[3] / ".github/scripts/make-local-check.sh"
_VERIFY_TAIL = _ADAPTER.with_name("make-verify-tail.sh")
_MAKEFILE = _ADAPTER.parents[2] / "Makefile"
_TEST_LEAVES = (
    "check-versions-synced",
    "test-typescript",
    "test-bootstrap",
    "test-contracts",
    "test-python",
    "test-sql",
    "test-iac",
    "test-standards",
    "test-tsconfig",
)

_SUPERVISOR = """\
import os
import sys

if 'VERIFY_LEASE' not in os.environ:
    lease = os.getpid()
    with open(os.environ['VERIFY_TRACE'], 'a', encoding='utf-8') as stream:
        stream.write(f'admit|-|{lease}|{os.getppid()}\\n')
    os.environ['VERIFY_LEASE'] = str(lease)
os.execvp(sys.argv[1], sys.argv[1:])
"""
_LEAF = """\
import os
from pathlib import Path
import sys
import time

target = sys.argv[1]
record = f'leaf|{target}|{os.environ.get("VERIFY_LEASE", "0")}|{os.getppid()}\\n'
descriptor = os.open(os.environ['VERIFY_TRACE'], os.O_WRONLY | os.O_APPEND)
try:
    os.write(descriptor, record.encode())
finally:
    os.close(descriptor)
peers = {}
if os.environ['VERIFY_PARALLEL_TAIL'] == '1':
    peers.update({'repo-check': 'check-no-private-refs', 'check-no-private-refs': 'repo-check'})
if os.environ['VERIFY_PARALLEL_TESTS'] == '1':
    peers.update({'test-typescript': 'test-bootstrap', 'test-bootstrap': 'test-typescript'})
if target in peers:
    root = Path(os.environ['VERIFY_ROOT'])
    (root / f'{target}.ready').touch()
    peer = peers[target]
    deadline = time.monotonic() + 5
    while not (root / f'{peer}.ready').exists():
        if time.monotonic() >= deadline:
            raise SystemExit('parallel metadata peer never started; jobserver is unusable')
        time.sleep(0.01)
raise SystemExit(23 if target == os.environ['VERIFY_FAIL_TARGET'] else 0)
"""


@dataclass(frozen=True)
class _Event:
    kind: str
    target: str
    lease: int
    parent: int


@dataclass(frozen=True)
class _Verification:
    root: Path
    tools: Path
    make: str
    trace: Path
    leaves: Path

    def run(
        self,
        *options: str,
        target: str = "verify",
        makefile: Path | None = None,
        fail_target: str = "",
        parallel_tail: bool = False,
        parallel_tests: bool = False,
        inherited_lease: int | None = None,
    ) -> subprocess.CompletedProcess[str]:
        environment = {
            "PATH": f"{self.tools}:/usr/bin:/bin",
            "VERIFY_TRACE": str(self.trace),
            "VERIFY_ROOT": str(self.root),
            "VERIFY_FAIL_TARGET": fail_target,
            "VERIFY_PARALLEL_TAIL": "1" if parallel_tail else "0",
            "VERIFY_PARALLEL_TESTS": "1" if parallel_tests else "0",
        }
        if inherited_lease is not None:
            environment["VERIFY_LEASE"] = str(inherited_lease)
        return subprocess.run(
            (
                self.make,
                "--no-print-directory",
                "-f",
                str(makefile or (_MAKEFILE if target == "verify" else self.leaves)),
                *options,
                target,
                f"MAKE={shlex.join((self.make, '-f', str(self.leaves)))}",
            ),
            cwd=self.root,
            env=environment,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )

    def events(self) -> list[_Event]:
        if not self.trace.exists():
            return []
        events: list[_Event] = []
        for line in self.trace.read_text(encoding="utf-8").splitlines():
            kind, target, lease, parent = line.split("|")
            events.append(_Event(kind, target, int(lease), int(parent)))
        return events


@pytest.fixture
def verification(tmp_path: Path) -> _Verification:
    make = shutil.which("make")
    if make is None:
        pytest.skip("requires GNU Make to verify native admission and jobserver behavior")
    root = tmp_path / "checkout with spaces"
    scripts = root / ".github/scripts"
    scripts.mkdir(parents=True)
    for source in (_ADAPTER, _VERIFY_TAIL):
        shutil.copyfile(source, scripts / source.name)
    tools = root / "tools"
    tools.mkdir()
    supervisor = tools / "sarj-local-check"
    supervisor.write_text(f"#!{sys.executable}\n{_SUPERVISOR}", encoding="utf-8")
    supervisor.chmod(0o755)
    action = root / "record leaf.py"
    action.write_text(_LEAF, encoding="utf-8")
    leaves = root / "private leaves.mk"
    targets = " ".join(
        (
            "doctor",
            "docs-check",
            "format-check",
            "lint",
            "dogfood",
            "typecheck",
            "repo-check",
            "check-no-private-refs",
            "shell-check",
            "typescript-build",
            *_TEST_LEAVES,
        )
    )
    groups = _MAKEFILE.read_text(encoding="utf-8").split("TEST_TYPESCRIPT :=", 1)[1].split("\ntest-typescript:", 1)[0]
    leaves.write_text(
        f".PHONY: {targets} test verify-test-typescript verify-test-python verify-test-standards\n"
        f"TEST_TYPESCRIPT :={groups}\n"
        "docs-check dogfood typecheck test-standards: typescript-build\n"
        f"{targets}:\n"
        f"\t@exec {shlex.quote(sys.executable)} {shlex.quote(str(action))} $@\n",
        encoding="utf-8",
    )
    trace = root / "events.txt"
    trace.touch()
    return _Verification(root, tools, make, trace, leaves)


@pytest.mark.parametrize("installed", [False, True])
@pytest.mark.parametrize(
    ("make_flags", "planning"),
    [
        pytest.param("", False, id="normal"),
        pytest.param("--warn-undefined-variables -rn -- TEST_JOBS=2", True, id="dry-run"),
        pytest.param("nr --warn-undefined-variables", True, id="leading-short-flags"),
        pytest.param("--warn-undefined-variables -tr", True, id="touch"),
        pytest.param("--warn-undefined-variables -rq", True, id="question"),
        pytest.param("--warn-undefined-variables -rI ntq", False, id="include-operand"),
        pytest.param("-rI with\\ space\\ -n", False, id="escaped-include-operand"),
        pytest.param("--include-dir -n", False, id="long-option-operand"),
        pytest.param("-r -- PYTEST_ARGS=-k ntq", False, id="variable-operand"),
    ],
)
def test_admission_adapter_executes_literal_arguments_and_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, installed: bool, make_flags: str, planning: bool
) -> None:
    tools = tmp_path / "tools"
    tools.mkdir()
    command = tools / "command with space"
    command.write_text(
        f"#!{sys.executable}\nimport os, sys\nprint(os.getpid())\nprint(repr(sys.argv[1:]))\nsys.exit(23)\n",
        encoding="utf-8",
    )
    command.chmod(0o755)
    if installed:
        helper = tools / "sarj-local-check"
        helper.write_text(
            f"#!{sys.executable}\nimport os, sys\nprint('admitted', flush=True)\nos.execv(sys.argv[1], sys.argv[1:])\n",
            encoding="utf-8",
        )
        helper.chmod(0o755)
    arguments = ("literal space", "*", "--", "line\nbreak")
    monkeypatch.setenv("PATH", f"{tools}:/usr/bin:/bin")
    monkeypatch.setenv("MAKEFLAGS", make_flags)
    with subprocess.Popen(
        ("bash", str(_ADAPTER), str(command), *arguments),
        cwd=tmp_path,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ) as process:
        try:
            stdout, stderr = process.communicate(timeout=10)
        except BaseException:
            process.kill()
            process.communicate()
            raise
    assert process.returncode == 23
    assert not stderr
    prefix = "admitted\n" if installed and not planning else ""
    assert stdout == f"{prefix}{process.pid}\n{list(arguments)!r}\n"


def test_verify_yields_between_test_groups_and_shares_the_final_tail_lease(verification: _Verification) -> None:
    result = verification.run()
    assert result.returncode == 0, result.stderr
    events = verification.events()
    admissions = [event for event in events if event.kind == "admit"]
    leaves = [event for event in events if event.kind == "leaf"]
    assert len(admissions) == 6
    assert [event.target for event in leaves] == [
        "doctor",
        "typescript-build",
        "docs-check",
        "format-check",
        "lint",
        "dogfood",
        "typecheck",
        *_TEST_LEAVES,
        "repo-check",
        "check-no-private-refs",
        "shell-check",
    ]
    by_target = {event.target: event for event in leaves}
    assert len({by_target[name].lease for name in ("test-typescript", "test-python", "test-standards")}) == 3
    tail = leaves[-5:]
    assert {event.lease for event in tail} == {admissions[-1].lease}
    assert all(event.parent != admissions[-1].lease for event in tail[:2])
    assert {event.parent for event in tail[2:]} == {admissions[-1].lease}


@pytest.mark.parametrize(
    "failed_target", ["test-typescript", "test-python", "test-standards", "test-tsconfig", "repo-check"]
)
def test_verify_preserves_first_failure_and_tail_status(verification: _Verification, failed_target: str) -> None:
    result = verification.run(fail_target=failed_target)
    assert result.returncode == 2
    leaves = [event.target for event in verification.events() if event.kind == "leaf"]
    assert leaves[-1] == failed_target
    assert "shell-check" not in leaves
    if failed_target.startswith("test-"):
        assert "repo-check" not in leaves


@pytest.mark.parametrize("option", ["--jobs=2", "-j2", "-kj2"])
def test_verify_preserves_a_usable_recursive_jobserver(verification: _Verification, option: str) -> None:
    result = verification.run(option, parallel_tail=True, parallel_tests=True)
    assert result.returncode == 0, result.stderr
    assert "jobserver unavailable" not in result.stderr
    events = verification.events()
    assert len([event for event in events if event.kind == "admit"]) == 4
    assert (verification.root / "repo-check.ready").exists()
    assert (verification.root / "check-no-private-refs.ready").exists()
    assert (verification.root / "test-typescript.ready").exists()
    assert (verification.root / "test-bootstrap.ready").exists()


def test_verify_preserves_an_inherited_recursive_jobserver(verification: _Verification) -> None:
    parent = verification.root / "parent makefile"
    command = shlex.join((verification.make, "--no-print-directory", "-f", str(_MAKEFILE), "verify"))
    parent.write_text(f".PHONY: inherited\ninherited:\n\t+{command}\n", encoding="utf-8")
    result = verification.run("--jobs=2", target="inherited", makefile=parent, parallel_tail=True, parallel_tests=True)
    assert result.returncode == 0, result.stderr
    assert "jobserver unavailable" not in result.stderr
    assert len([event for event in verification.events() if event.kind == "admit"]) == 4


@pytest.mark.parametrize("option", ["--jobs=1", "-j1", "--keep-going", "-k"])
def test_verify_keeps_explicit_scheduling_in_one_test_admission(verification: _Verification, option: str) -> None:
    result = verification.run(option)
    assert result.returncode == 0, result.stderr
    events = verification.events()
    assert len([event for event in events if event.kind == "admit"]) == 4
    tests = [event for event in events if event.target in _TEST_LEAVES]
    assert sorted(event.target for event in tests) == sorted(_TEST_LEAVES)
    assert len({event.lease for event in tests}) == 1


def test_verify_keep_going_finishes_test_siblings_before_suppressing_tail(verification: _Verification) -> None:
    result = verification.run("--keep-going", fail_target="test-typescript")
    assert result.returncode == 2
    leaves = [event.target for event in verification.events() if event.kind == "leaf"]
    assert all(target in leaves for target in _TEST_LEAVES)
    assert "repo-check" not in leaves


def test_verify_reuses_an_inherited_outer_lease(verification: _Verification) -> None:
    result = verification.run(inherited_lease=12345)
    assert result.returncode == 0, result.stderr
    events = verification.events()
    assert not any(event.kind == "admit" for event in events)
    assert {event.lease for event in events} == {12345}


@pytest.mark.parametrize("target", ["verify", "test"])
def test_canonical_test_union_and_typescript_build_are_complete(verification: _Verification, target: str) -> None:
    result = verification.run(target=target)
    assert result.returncode == 0, result.stderr
    leaves = [event.target for event in verification.events() if event.kind == "leaf"]
    assert sorted(leaf for leaf in leaves if leaf in _TEST_LEAVES) == sorted(_TEST_LEAVES)
    assert leaves.count("typescript-build") == 1


@pytest.mark.parametrize("target", ["verify", "test"])
def test_new_group_member_joins_verify_and_direct_test(verification: _Verification, target: str) -> None:
    source = verification.leaves.read_text(encoding="utf-8").replace("TEST_PYTHON :=", "TEST_PYTHON := test-extra")
    command = f"{shlex.quote(sys.executable)} {shlex.quote(str(verification.root / 'record leaf.py'))}"
    verification.leaves.write_text(
        source + f"\n.PHONY: test-extra\ntest-extra:\n\t@exec {command} $@\n", encoding="utf-8"
    )
    result = verification.run(target=target)
    assert result.returncode == 0, result.stderr
    leaves = [event.target for event in verification.events() if event.kind == "leaf"]
    assert leaves.count("test-extra") == 1


def test_command_variable_words_do_not_change_verify_scheduling(verification: _Verification) -> None:
    result = verification.run("PYTEST_ARGS=-j9 --jobserver-auth=private -k literal space")
    assert result.returncode == 0, result.stderr
    assert len([event for event in verification.events() if event.kind == "admit"]) == 6


@pytest.mark.parametrize("directory", ["include space -j9", "include\ttab\t--jobserver-auth=private"])
def test_include_directory_words_preserve_argv_with_aggregate_fallback(
    verification: _Verification, directory: str
) -> None:
    include = verification.root / directory
    include.mkdir()
    (include / "private-options.mk").write_text(
        "# The literal include directory must reach recursive Make.\n", encoding="utf-8"
    )
    with verification.leaves.open("a", encoding="utf-8") as stream:
        stream.write("\ninclude private-options.mk\n")
    result = verification.run("-I", str(include))
    assert result.returncode == 0, result.stderr
    events = verification.events()
    assert len([event for event in events if event.kind == "admit"]) == 4
    tests = [event for event in events if event.target in _TEST_LEAVES]
    assert sorted(event.target for event in tests) == sorted(_TEST_LEAVES)
    assert len({event.lease for event in tests}) == 1


@pytest.mark.parametrize("mode", ["--dry-run", "--touch", "--question"])
def test_verify_planning_invokes_no_admission_or_gate(verification: _Verification, mode: str) -> None:
    result = verification.run(mode)
    assert result.returncode in {0, 1}
    assert verification.events() == []
