from __future__ import annotations

from contextlib import ExitStack, contextmanager
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
    from typing import TextIO


if TYPE_CHECKING or os.name == "posix":
    import fcntl


pytestmark = pytest.mark.skipif(os.name != "posix", reason="POSIX exec/lock contract; Windows retains its launcher")
PROBE = """\
from pathlib import Path
import sys, time
Path('argv.txt').write_text(chr(0).join(sys.argv[1:]))
Path('started').touch()
while not Path('release').exists():
    time.sleep(0.01)
raise SystemExit(7)
"""
METADATA_PROBE = """\
from pathlib import Path
import fcntl, sys
import sarj_standards_bootstrap as bootstrap
original = fcntl.flock
def observe(handle, operation):
    try:
        return original(handle, operation)
    except BlockingIOError:
        if Path(handle.name).name == 'queue.lock':
            print('metadata contended', flush=True)
        raise
fcntl.flock = observe
raise SystemExit(bootstrap.main(('check',)))
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
def _launch(
    root: Path,
    environment: dict[str, str],
    *,
    command: str = "check",
    arguments: tuple[str, ...] = (),
    observe_metadata: bool = False,
) -> Generator[subprocess.Popen[str]]:
    root.mkdir()
    (root / ".sarj-standards.toml").write_text('schema = 4\nbundle = "9.8.7"\n', encoding="utf-8")
    with subprocess.Popen(
        [
            sys.executable,
            "-c",
            METADATA_PROBE
            if observe_metadata
            else f"import sarj_standards_bootstrap as b; raise SystemExit(b.main({(command, *arguments)!r}))",
        ],
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


@contextmanager
def _contended_metadata(
    tmp_path: Path, environment: dict[str, str], stage: str, *, timeout: float = 10
) -> Generator[subprocess.Popen[str]]:
    directory = tmp_path / "state"
    directory.mkdir()
    with ExitStack() as stack:
        queue = stack.enter_context((directory / "queue.lock").open("a+", encoding="utf-8"))
        if stage == "queue-position":
            slot = stack.enter_context((directory / "slot-0.lock").open("a+", encoding="utf-8"))
            fcntl.flock(slot, fcntl.LOCK_EX)
        else:
            fcntl.flock(queue, fcntl.LOCK_EX)
        options = {**environment, "SARJ_LOCAL_CHECK_WAIT_SECONDS": str(timeout)}
        process = stack.enter_context(_launch(tmp_path / "contended", options, observe_metadata=True))
        if stage == "queue-position":
            _waiting(process)
            fcntl.flock(queue, fcntl.LOCK_EX)
        yield process


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


@pytest.mark.parametrize(
    "arguments",
    [
        pytest.param(("--help",), id="long-help"),
        pytest.param(("-h",), id="short-help"),
        pytest.param(("src", "--help"), id="help-after-source"),
        pytest.param(("--help", "--", "file.py"), id="help-before-separator"),
    ],
)
def test_check_help_reaches_the_pinned_cli_while_capacity_is_full(
    tmp_path: Path, environment: dict[str, str], arguments: tuple[str, ...]
) -> None:
    first, second = tmp_path / "first", tmp_path / "second"
    with _launch(first, environment) as one:
        _started(first)
        with _launch(second, {**environment, "SARJ_LOCAL_CHECK_WAIT_SECONDS": "0"}, arguments=arguments) as two:
            (second / "release").touch()
            _, stderr = two.communicate(timeout=10)
            assert two.returncode == 7, stderr
            assert (second / "started").is_file()
            forwarded = (second / "argv.txt").read_text(encoding="utf-8").split(chr(0))
            assert forwarded[-len(arguments) - 1 :] == ["check", *arguments]
            assert one.poll() is None


def test_help_named_path_after_separator_still_requires_capacity(tmp_path: Path, environment: dict[str, str]) -> None:
    first, second = tmp_path / "first", tmp_path / "second"
    with _launch(first, environment):
        _started(first)
        with _launch(second, {**environment, "SARJ_LOCAL_CHECK_WAIT_SECONDS": "0"}, arguments=("--", "--help")) as two:
            _, stderr = two.communicate(timeout=10)
            assert two.returncode == 2, stderr
            assert "no shared slot" in stderr
            assert not (second / "started").exists()


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


@pytest.mark.parametrize("stage", ["registration", "queue-position"])
def test_metadata_contention_honors_the_admission_deadline(
    tmp_path: Path, environment: dict[str, str], stage: str
) -> None:
    with _contended_metadata(tmp_path, environment, stage, timeout=0.5) as process:
        _, stderr = process.communicate(timeout=10)
        assert process.returncode == 2, stderr
        assert "within 0.5s" in stderr
        assert "waiting for admission metadata lock" in stderr
        assert stderr.count("Local checks: waiting") <= 1
        assert not (tmp_path / "contended/started").exists()
    assert not list((tmp_path / "state").glob("wait-*.lock"))


@pytest.mark.parametrize("stage", ["registration", "queue-position"])
def test_metadata_wait_remains_interruptible_and_cleans_its_ticket(
    tmp_path: Path, environment: dict[str, str], stage: str
) -> None:
    with _contended_metadata(tmp_path, environment, stage) as process:
        assert process.stdout is not None
        ready, _, _ = select.select([process.stdout], [], [], 10)
        assert ready, "Metadata contention was not observed"
        assert "metadata contended" in os.read(process.stdout.fileno(), 4096).decode()
        process.send_signal(signal.SIGINT)
        assert process.wait(timeout=10) == 130
        assert not (tmp_path / "contended/started").exists()
    assert not list((tmp_path / "state").glob("wait-*.lock"))


def test_registration_error_removes_its_new_ticket(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    original = fcntl.flock

    def fail_ticket(handle: int | TextIO, operation: int) -> None:
        if operation == fcntl.LOCK_EX:
            message = "fixture ticket lock failure"
            raise OSError(message)
        original(handle, operation)

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- The native flock boundary must fail after creating a real owned ticket.
        fcntl, "flock", fail_ticket
    )
    with (
        pytest.raises(OSError, match="fixture ticket lock failure"),
        check_slot({"SARJ_LOCAL_CHECK_STATE_DIR": str(tmp_path)}),
    ):
        pytest.fail("Failed registration must not admit a check")
    assert not list(tmp_path.glob("wait-*.lock"))


def test_short_metadata_contentions_share_the_report_cadence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    clock = [0.0]
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- Verify production reads the native monotonic clock rather than another time source.
        time, "monotonic", lambda: clock[0]
    )
    with (
        (tmp_path / "queue.lock").open("a+", encoding="utf-8") as held,
        (tmp_path / "slot-0.lock").open("a+", encoding="utf-8") as occupied,
    ):
        fcntl.flock(held, fcntl.LOCK_EX)
        fcntl.flock(occupied, fcntl.LOCK_EX)
        queue_held = [True]

        def release_after_poll(seconds: float) -> None:
            clock[0] += seconds
            fcntl.flock(held, fcntl.LOCK_UN if queue_held[0] else fcntl.LOCK_EX)
            queue_held[0] = not queue_held[0]
            if clock[0] >= 1:
                fcntl.flock(occupied, fcntl.LOCK_UN)

        monkeypatch.setattr(  # sarj-noqa: SARJ445 -- Native polling releases real lock contention at each sleep boundary.
            time, "sleep", release_after_poll
        )
        with check_slot({"SARJ_LOCAL_CHECK_STATE_DIR": str(tmp_path), "SARJ_LOCAL_CHECK_WAIT_SECONDS": "10"}):
            assert clock[0] >= 1
    assert capsys.readouterr().err.count("waiting for admission metadata lock") == 1


def test_zero_budget_still_admits_a_free_slot_and_removes_its_ticket(
    tmp_path: Path, environment: dict[str, str]
) -> None:
    root = tmp_path / "zero-budget"
    with _launch(root, {**environment, "SARJ_LOCAL_CHECK_WAIT_SECONDS": "0"}) as process:
        _started(root)
        assert not list((tmp_path / "state").glob("wait-*.lock"))
        (root / "release").touch()
        assert process.wait(timeout=10) == 7


def test_expired_positive_budget_does_not_admit_even_when_metadata_is_free(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = iter([0.0, 1.0])
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- Native clock expiry before registration must reject the real admission path.
        time, "monotonic", lambda: next(clock, 1.0)
    )
    with (
        pytest.raises(TimeoutError, match=r"within 0\.5s"),
        check_slot({"SARJ_LOCAL_CHECK_STATE_DIR": str(tmp_path), "SARJ_LOCAL_CHECK_WAIT_SECONDS": "0.5"}),
    ):
        pytest.fail("Expired admission budget admitted a check")
    assert not list(tmp_path.glob("wait-*.lock"))


def test_budget_expiring_during_metadata_scan_does_not_acquire_a_free_slot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = [0.0]
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- Verify admission reads native elapsed time after metadata inspection.
        time, "monotonic", lambda: clock[0]
    )
    original = fcntl.flock

    def expire_during_metadata(handle: int | TextIO, operation: int) -> None:
        original(handle, operation)
        if operation == fcntl.LOCK_EX | fcntl.LOCK_NB and list(tmp_path.glob("wait-*.lock")):
            clock[0] = 1

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- Advance native time at the real metadata-lock acquisition boundary.
        fcntl, "flock", expire_during_metadata
    )
    with (
        pytest.raises(TimeoutError, match=r"within 0\.5s"),
        check_slot({"SARJ_LOCAL_CHECK_STATE_DIR": str(tmp_path), "SARJ_LOCAL_CHECK_WAIT_SECONDS": "0.5"}),
    ):
        pytest.fail("Metadata scan exhausted the budget before slot acquisition")
    assert not list(tmp_path.glob("wait-*.lock"))


def test_budget_expiring_at_an_occupied_slot_does_not_acquire_a_later_free_slot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = [0.0]
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- Verify native deadline reads occur between real slot-lock probes.
        time, "monotonic", lambda: clock[0]
    )
    original = fcntl.flock

    def expire_after_occupied_slot(handle: int | TextIO, operation: int) -> None:
        try:
            original(handle, operation)
        except BlockingIOError:
            clock[0] = 1
            raise

    with (tmp_path / "slot-0.lock").open("a+", encoding="utf-8") as occupied:
        fcntl.flock(occupied, fcntl.LOCK_EX)
        monkeypatch.setattr(  # sarj-noqa: SARJ445 -- The real occupied-slot syscall must consume the remaining deadline.
            fcntl, "flock", expire_after_occupied_slot
        )
        with (
            pytest.raises(TimeoutError, match=r"within 0\.5s"),
            check_slot(
                {
                    "SARJ_LOCAL_CHECK_STATE_DIR": str(tmp_path),
                    "SARJ_LOCAL_CHECK_WAIT_SECONDS": "0.5",
                    "SARJ_LOCAL_CHECK_JOBS": "2",
                }
            ),
        ):
            pytest.fail("Occupied slot exhausted the budget before the next free slot")
    assert not (tmp_path / "slot-1.lock").exists()
    assert not list(tmp_path.glob("wait-*.lock"))
