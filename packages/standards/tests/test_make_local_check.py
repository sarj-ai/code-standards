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

_SUPERVISOR = """\
import os
import sys

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
record = f'leaf|{target}|{os.environ["VERIFY_LEASE"]}|{os.getppid()}\\n'
descriptor = os.open(os.environ['VERIFY_TRACE'], os.O_WRONLY | os.O_APPEND)
try:
    os.write(descriptor, record.encode())
finally:
    os.close(descriptor)
if os.environ['VERIFY_PARALLEL_TAIL'] == '1' and target in {'repo-check', 'check-no-private-refs'}:
    root = Path(os.environ['VERIFY_ROOT'])
    (root / f'{target}.ready').touch()
    peer = 'check-no-private-refs' if target == 'repo-check' else 'repo-check'
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
        self, *options: str, fail_target: str = "", parallel_tail: bool = False
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            (
                self.make,
                "--no-print-directory",
                "-f",
                str(_ADAPTER.parents[2] / "Makefile"),
                *options,
                "verify",
                f"MAKE={shlex.join((self.make, '-f', str(self.leaves)))}",
            ),
            cwd=self.root,
            env={
                "PATH": f"{self.tools}:/usr/bin:/bin",
                "VERIFY_TRACE": str(self.trace),
                "VERIFY_ROOT": str(self.root),
                "VERIFY_FAIL_TARGET": fail_target,
                "VERIFY_PARALLEL_TAIL": "1" if parallel_tail else "0",
            },
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
    targets = (
        "doctor docs-check format-check lint dogfood typecheck test "
        "repo-check check-no-private-refs shell-check typescript-build"
    )
    leaves.write_text(
        f".PHONY: {targets}\n"
        "docs-check dogfood typecheck test: typescript-build\n"
        f"{targets}:\n"
        f"\t@exec {shlex.quote(sys.executable)} {shlex.quote(str(action))} $@\n",
        encoding="utf-8",
    )
    return _Verification(root, tools, make, root / "events.txt", leaves)


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


def test_verify_shares_four_admissions_and_the_final_test_lease(verification: _Verification) -> None:
    result = verification.run()
    assert result.returncode == 0, result.stderr
    events = verification.events()
    admissions = [event for event in events if event.kind == "admit"]
    leaves = [event for event in events if event.kind == "leaf"]
    assert len(admissions) == 4
    assert [event.target for event in leaves] == [
        "doctor",
        "typescript-build",
        "docs-check",
        "format-check",
        "lint",
        "dogfood",
        "typecheck",
        "test",
        "repo-check",
        "check-no-private-refs",
        "shell-check",
    ]
    tail = leaves[-4:]
    assert {event.lease for event in tail} == {admissions[-1].lease}
    assert tail[0].parent != admissions[-1].lease
    assert {event.parent for event in tail[1:]} == {admissions[-1].lease}


@pytest.mark.parametrize("failed_target", ["test", "repo-check"])
def test_verify_preserves_first_failure_and_tail_status(verification: _Verification, failed_target: str) -> None:
    result = verification.run(fail_target=failed_target)
    assert result.returncode == 2
    leaves = [event.target for event in verification.events() if event.kind == "leaf"]
    assert leaves[-1] == failed_target
    assert "shell-check" not in leaves
    if failed_target == "test":
        assert "repo-check" not in leaves


def test_verify_preserves_a_usable_recursive_jobserver(verification: _Verification) -> None:
    result = verification.run("--jobs=2", parallel_tail=True)
    assert result.returncode == 0, result.stderr
    assert "jobserver unavailable" not in result.stderr
    events = verification.events()
    assert len([event for event in events if event.kind == "admit"]) == 4
    assert (verification.root / "repo-check.ready").exists()
    assert (verification.root / "check-no-private-refs.ready").exists()


@pytest.mark.parametrize("mode", ["--dry-run", "--touch", "--question"])
def test_verify_planning_invokes_no_admission_or_gate(verification: _Verification, mode: str) -> None:
    result = verification.run(mode)
    assert result.returncode in {0, 1}
    assert verification.events() == []
