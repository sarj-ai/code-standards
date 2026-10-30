from __future__ import annotations

import ctypes
from enum import StrEnum
import os
from pathlib import Path  # ruff: ignore[typing-only-standard-library-import] -- Typer resolves Path at runtime.
import signal
import sys
import threading
import time
from typing import TYPE_CHECKING

import typer

from sarj_standards.libs.diagnostics import Completion, ToolReport
from sarj_standards.libs.linting import external
from sarj_standards.libs.linting.process import RequestExecutor
from sarj_standards.libs.linting.scheduling import analyze_groups


if TYPE_CHECKING:
    import subprocess


_LEADER = (
    "import os, subprocess, sys\n"
    "from pathlib import Path\n"
    "child = subprocess.Popen((sys.executable, '-c', 'import time; time.sleep(30)'))\n"
    "Path('descendant.pid').write_text(str(child.pid))\n"
    "Path('leader.pid').write_text(str(os.getpid()))\n"
    "os._exit(0)\n"
)
_OUTER_LEADER = (
    "import os, subprocess, sys\n"
    "from pathlib import Path\n"
    "child = subprocess.Popen((sys.executable, '-c', 'import time; time.sleep(30)'))\n"
    "Path('descendant.pid').write_text(str(child.pid))\n"
    "Path('leader.pid').write_text(str(os.getpid()))\n"
    "Path('outer.ready').touch()\n"
    "os._exit(0)\n"
)
_CLOSED_STREAMS_LEADER = (
    "import os, subprocess, sys, time\n"
    "from pathlib import Path\n"
    "child = subprocess.Popen((sys.executable, '-c', 'import time; time.sleep(30)'), "
    "stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n"
    "Path('descendant.pid').write_text(str(child.pid))\n"
    "Path('leader.pid').write_text(str(os.getpid()))\n"
    "os.close(1)\n"
    "os.close(2)\n"
    "time.sleep(30)\n"
)


class CleanupMode(StrEnum):
    TIMEOUT = "timeout"
    INTERRUPT = "interrupt"
    OUTER_INTERRUPT = "outer-interrupt"
    CLOSED_STREAMS = "closed-streams"


class ExecutorMode(StrEnum):
    BARE = "bare"
    RECORDING = "recording"


class ProbeMode(StrEnum):
    WAITID = "waitid"
    FALLBACK = "fallback"


def _enable_subreaping() -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(36, 1, 0, 0, 0) != 0:
        message = "cannot enable child subreaping for process cleanup fixture"
        raise OSError(message)


def _install_exit_probe(directory: Path, *, mode: str, fallback: bool) -> None:
    descendant_file = directory / "descendant.pid"
    wait_without_reaping = os.waitid
    wait_nowait = os.WNOWAIT
    if fallback:
        del os.WNOWAIT  # sarj-noqa: SARJ442 -- this isolated real-OS probe removes the capability flag to exercise fallback ownership without replacing process facts or cleanup.
    original_probe = external._leader_exited  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage] -- observe the real exit-probe branch without replacing process facts or cleanup.

    def observe_exit(process: subprocess.Popen[bytes]) -> bool | None:
        exited = original_probe(process)
        if fallback and (exited is not None or process.returncode is not None):
            message = "fallback exit probing must preserve unreaped leader ownership"
            raise RuntimeError(message)
        if (
            mode == "interrupt"
            and descendant_file.exists()
            and wait_without_reaping(os.P_PID, process.pid, os.WEXITED | os.WNOHANG | wait_nowait) is not None
        ):
            message = "process cleanup fixture interruption"
            raise KeyboardInterrupt(message)
        return exited

    external._leader_exited = observe_exit  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage] -- inject interruption through the real wait loop after an observed real leader exit.


def _run_leader(directory: Path, *, mode: str, decorated: bool) -> str:
    executor = (
        RequestExecutor(external.DEFAULT_EXECUTOR.run, external.DEFAULT_EXECUTOR.capabilities)
        if decorated
        else external.DEFAULT_EXECUTOR
    )
    source = _CLOSED_STREAMS_LEADER if mode == "closed-streams" else _LEADER
    try:
        executor.run(external.process_request((sys.executable, "-c", source), cwd=directory, timeout_seconds=2))
    except BaseException as error:  # ruff: ignore[blind-except] -- fixture cleanup must still reap real children when the implementation fails unexpectedly.
        return type(error).__name__
    return "no-failure"


def _run_outer_groups(directory: Path, *, decorated: bool) -> str:
    executor = (
        RequestExecutor(external.DEFAULT_EXECUTOR.run, external.DEFAULT_EXECUTOR.capabilities)
        if decorated
        else external.DEFAULT_EXECUTOR
    )
    # Prepare on the caller thread: dispatch must also bind requests that predate the worker context.
    request = external.process_request((sys.executable, "-c", _OUTER_LEADER), cwd=directory, timeout_seconds=5)
    completed = ToolReport("native", Completion.COMPLETE)
    native_reports: list[tuple[ToolReport, ...]] = []
    native_finished = threading.Event()
    finished = threading.Event()
    worker_failures: list[str] = []

    def native() -> tuple[ToolReport, ...]:
        reports = (completed,)
        native_reports.append(reports)
        native_finished.set()
        return reports

    def external_group() -> tuple[ToolReport, ...]:
        try:
            executor.run(request)
        except BaseException as error:
            worker_failures.append(type(error).__name__)
            raise
        return ()

    def interrupt_caller() -> None:
        deadline = time.monotonic() + 3
        while not finished.wait(0.01):
            if native_finished.is_set() and (directory / "outer.ready").exists():
                # Signal only this isolated probe, after its real child published ownership evidence.
                os.kill(os.getpid(), signal.SIGINT)
                return
            if time.monotonic() >= deadline:
                return

    watcher = threading.Thread(target=interrupt_caller, name="outer-interrupt-signal")
    watcher.start()
    observed = "no-failure"
    try:
        analyze_groups(directory, native, external_group, jobs=2)
    except BaseException as error:  # ruff: ignore[blind-except] -- report the outer caller's actual interruption separately from the worker's outcome.
        observed = type(error).__name__
    finally:
        finished.set()
        watcher.join(timeout=4)
    if watcher.is_alive():
        message = "outer interruption watcher did not stop"
        raise RuntimeError(message)
    worker_outcome = worker_failures[0] if worker_failures else "no-failure"
    preserved = native_reports == [(completed,)]
    return f"{observed}:{worker_outcome}:{preserved}"


def main(directory: Path, mode: CleanupMode, executor: ExecutorMode, probe: ProbeMode) -> None:
    _enable_subreaping()
    _install_exit_probe(directory, mode=mode.value, fallback=probe is ProbeMode.FALLBACK)
    observed = (
        _run_outer_groups(directory, decorated=executor is ExecutorMode.RECORDING)
        if mode is CleanupMode.OUTER_INTERRUPT
        else _run_leader(directory, mode=mode.value, decorated=executor is ExecutorMode.RECORDING)
    )
    descendant_file = directory / "descendant.pid"
    descendant = int(descendant_file.read_text(encoding="utf-8"))
    leader = int((directory / "leader.pid").read_text(encoding="utf-8"))
    deadline = time.monotonic() + 2
    reaped = False
    while time.monotonic() < deadline:
        waited, _status = os.waitpid(descendant, os.WNOHANG)
        if waited == descendant:
            reaped = True
            break
        time.sleep(0.01)
    drained = not any(thread.name.startswith("sarj-process-") for thread in threading.enumerate())
    if not reaped:
        # waitpid just proved this live child remains ours, so its PID cannot be reused.
        os.kill(descendant, signal.SIGKILL)
        os.waitpid(descendant, 0)
    leader_reaped = False
    try:
        os.waitpid(leader, os.WNOHANG)
    except ChildProcessError:
        leader_reaped = True
    no_children = False
    try:
        os.waitpid(-1, os.WNOHANG)
    except ChildProcessError:
        no_children = True
    sys.stdout.write(f"{observed} {reaped} {drained} {leader_reaped} {no_children}\n")


if __name__ == "__main__":
    typer.run(main)
