from __future__ import annotations

from contextlib import contextmanager
import json
import os
import select
import signal
import subprocess
import sys
import time
from typing import TYPE_CHECKING

import pytest

from sarj_standards_bootstrap.admission import check_slot


if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path


pytestmark = pytest.mark.skipif(os.name != "posix", reason="POSIX exec/lock contract; Windows retains its launcher")
PROBE = """\
from pathlib import Path
import time
Path('started').touch()
while not Path('release').exists():
    time.sleep(0.01)
raise SystemExit(7)
"""


@pytest.fixture
def environment(tmp_path: Path) -> dict[str, str]:
    uvx = tmp_path / "uvx"
    uvx.write_text(f"#!{sys.executable}\n{PROBE}", encoding="utf-8")
    uvx.chmod(0o755)
    result = {
        key: value
        for key, value in os.environ.items()  # ruff: ignore[banned-api] -- preserve the test runner's Python path.
        if not key.startswith("SARJ_LOCAL_CHECK_")
    }
    result.update(CI="false", SARJ_LOCAL_CHECK_STATE_DIR=str(tmp_path / "state"))
    result["PATH"] = f"{tmp_path}{os.pathsep}{result['PATH']}"
    return result


@contextmanager
def _launch(root: Path, environment: dict[str, str], *, command: str = "check") -> Generator[subprocess.Popen[str]]:
    root.mkdir()
    (root / ".sarj-standards.toml").write_text('schema = 4\nbundle = "9.8.7"\n', encoding="utf-8")
    with subprocess.Popen(
        [sys.executable, "-c", f"import sarj_standards_bootstrap as b; raise SystemExit(b.main([{command!r}]))"],
        cwd=root,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ) as process:
        try:
            yield process
        finally:
            if process.poll() is None:
                process.terminate()
            process.communicate(timeout=10)


def _started(root: Path) -> None:
    deadline = time.monotonic() + 10
    while not (root / "started").exists():
        if time.monotonic() >= deadline:
            pytest.fail("Pinned command did not start")
        time.sleep(0.01)


def _waiting(process: subprocess.Popen[str]) -> None:
    assert process.stderr is not None
    ready, _, _ = select.select([process.stderr], [], [], 10)
    assert ready, "Contended launcher did not report its wait"
    assert "waiting" in os.read(process.stderr.fileno(), 4096).decode()


def test_workspaces_share_the_slot_until_the_exec_replacement_exits(
    tmp_path: Path, environment: dict[str, str]
) -> None:
    first, second = tmp_path / "first", tmp_path / "second"
    with _launch(first, environment) as one:
        _started(first)
        with _launch(second, environment) as two:
            _waiting(two)
            assert not (second / "started").exists()
            (first / "release").touch()
            assert one.wait(timeout=10) == 7
            _started(second)
            (second / "release").touch()
            assert two.wait(timeout=10) == 7


@pytest.mark.parametrize("command", ["check", "doctor"])
def test_ci_and_noncheck_commands_keep_their_existing_execution(
    tmp_path: Path, environment: dict[str, str], command: str
) -> None:
    first, second = tmp_path / "first", tmp_path / "second"
    with _launch(first, environment):
        _started(first)
        options = {"SARJ_LOCAL_CHECK_JOBS": "invalid"}
        if command == "check":
            options["CI"] = "true"
        with _launch(second, {**environment, **options}, command=command) as two:
            _started(second)
            (second / "release").touch()
            assert two.wait(timeout=10) == 7


def test_a_sibling_cannot_reuse_another_launchers_live_marker(tmp_path: Path, environment: dict[str, str]) -> None:
    first, second = tmp_path / "first", tmp_path / "second"
    with _launch(first, environment):
        _started(first)
        marker = (tmp_path / "state/slot-0.lock").read_text(encoding="utf-8")
        options = {"SARJ_LOCAL_CHECK_LEASE": marker, "SARJ_LOCAL_CHECK_WAIT_SECONDS": "0"}
        with _launch(second, {**environment, **options}) as two:
            _, stderr = two.communicate(timeout=10)
            assert two.returncode == 2
            assert "no shared slot" in stderr
            assert not (second / "started").exists()


def test_an_ancestor_reservation_survives_closed_child_descriptors(tmp_path: Path, environment: dict[str, str]) -> None:
    root = tmp_path / "nested"
    with check_slot(environment), _launch(root, {**environment, "SARJ_LOCAL_CHECK_WAIT_SECONDS": "0"}) as process:
        _started(root)
        (root / "release").touch()
        assert process.wait(timeout=10) == 7


def test_explicit_capacity_allows_two_commands(tmp_path: Path, environment: dict[str, str]) -> None:
    options = {**environment, "SARJ_LOCAL_CHECK_JOBS": "2"}
    first, second = tmp_path / "first", tmp_path / "second"
    with _launch(first, options), _launch(second, options):
        _started(first)
        _started(second)


def test_shared_capacity_change_reaches_an_existing_waiter(tmp_path: Path, environment: dict[str, str]) -> None:
    first, second = tmp_path / "first", tmp_path / "second"
    with _launch(first, {**environment, "SARJ_LOCAL_CHECK_JOBS": "1"}):
        _started(first)
        with _launch(second, {**environment, "SARJ_LOCAL_CHECK_JOBS": "1"}) as two:
            _waiting(two)
            (tmp_path / "state/capacity.json").write_text('{"slots": 2}', encoding="utf-8")
            _started(second)
            (second / "release").touch()
            assert two.wait(timeout=10) == 7


def test_fifo_waiters_and_a_crashed_waiter_cannot_block_following_work(
    tmp_path: Path, environment: dict[str, str]
) -> None:
    first, second, third = (tmp_path / name for name in ("first", "second", "third"))
    with _launch(first, environment) as one:
        _started(first)
        with _launch(second, environment) as two:
            _waiting(two)
            with _launch(third, environment) as three:
                assert three.stderr is not None
                ready, _, _ = select.select([three.stderr], [], [], 10)
                assert ready
                assert "queue position 2" in os.read(three.stderr.fileno(), 4096).decode()
                assert not (third / "started").exists()
                two.kill()
                two.wait(timeout=10)
                (first / "release").touch()
                assert one.wait(timeout=10) == 7
                _started(third)
                (third / "release").touch()
                assert three.wait(timeout=10) == 7


def test_invalid_shared_capacity_fails_before_execution(tmp_path: Path, environment: dict[str, str]) -> None:
    state = tmp_path / "state"
    state.mkdir()
    (state / "capacity.json").write_text('{"slots": true}', encoding="utf-8")
    root = tmp_path / "invalid"
    with _launch(root, environment) as process:
        _, stderr = process.communicate(timeout=10)
        assert process.returncode == 2, stderr
        assert "capacity.json" in stderr
        assert not (root / "started").exists()


@pytest.mark.parametrize("cache", ["", "relative-cache", "absolute"])
def test_invalid_cache_home_uses_the_shared_default(tmp_path: Path, environment: dict[str, str], cache: str) -> None:
    environment.pop("SARJ_LOCAL_CHECK_STATE_DIR")
    environment.pop("XDG_CACHE_HOME", None)
    environment["HOME"] = str(tmp_path / "home")
    first, second = tmp_path / "first", tmp_path / "second"
    with _launch(first, environment):
        _started(first)
        options = {
            "XDG_CACHE_HOME": str(tmp_path / "cache") if cache == "absolute" else cache,
            "SARJ_LOCAL_CHECK_WAIT_SECONDS": "0",
        }
        with _launch(second, {**environment, **options}) as two:
            if cache == "absolute":
                _started(second)
                (second / "release").touch()
                assert two.wait(timeout=10) == 7
            else:
                _, stderr = two.communicate(timeout=10)
                assert two.returncode == 2
                assert "no shared slot" in stderr
                assert not (second / "started").exists()


def test_cancelled_waiter_never_executes_and_terminated_owner_releases_the_slot(
    tmp_path: Path, environment: dict[str, str]
) -> None:
    first, second, third = (tmp_path / name for name in ("first", "second", "third"))
    with _launch(first, environment) as one:
        _started(first)
        with _launch(second, environment) as two:
            _waiting(two)
            two.send_signal(signal.SIGINT)
            assert two.wait(timeout=10) == 130
            assert not (second / "started").exists()
        one.terminate()
        one.wait(timeout=10)
        with _launch(third, environment):
            _started(third)


def test_an_unlocked_stale_marker_does_not_grant_admission(tmp_path: Path, environment: dict[str, str]) -> None:
    state = tmp_path / "state"
    state.mkdir()
    path = state / "slot-0.lock"
    marker = json.dumps({"path": str(path), "pid": os.getpid(), "token": "stale"})
    path.write_text(marker, encoding="utf-8")
    root = tmp_path / "fresh"
    with _launch(root, {**environment, "SARJ_LOCAL_CHECK_LEASE": marker}):
        _started(root)
        assert path.read_text(encoding="utf-8") != marker


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("SARJ_LOCAL_CHECK_JOBS", "0"),
        ("SARJ_LOCAL_CHECK_JOBS", "invalid"),
        ("SARJ_LOCAL_CHECK_WAIT_SECONDS", "-1"),
        ("SARJ_LOCAL_CHECK_WAIT_SECONDS", "nan"),
        ("SARJ_LOCAL_CHECK_WAIT_SECONDS", "inf"),
    ],
)
def test_invalid_capacity_fails_before_execution(
    tmp_path: Path, environment: dict[str, str], key: str, value: str
) -> None:
    root = tmp_path / "invalid"
    with _launch(root, {**environment, key: value}) as process:
        process.communicate(timeout=10)
        assert process.returncode == 2
        assert not (root / "started").exists()
