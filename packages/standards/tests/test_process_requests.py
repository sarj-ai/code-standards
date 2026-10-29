from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import subprocess
import sys
import time
from typing import TYPE_CHECKING

import pytest

from sarj_standards.libs.diagnostics import Completion
from sarj_standards.libs.linting import external
from sarj_standards.libs.linting.devops_tools import NativeTool, checked_runtime_tool
from sarj_standards.libs.linting.external import DEFAULT_EXECUTOR, analyze_external, process_request, run_process
from sarj_standards.libs.linting.process import (
    OutputLimitError,
    ProcessCapabilities,
    ProcessOutput,
    ProcessRequest,
    RequestExecutor,
)


if TYPE_CHECKING:
    from collections.abc import Callable


def _construct_with_mutable_input(request: ProcessRequest, mutable: bytearray) -> ProcessRequest:
    return ProcessRequest(
        request.argv,
        request.cwd,
        request.environment,
        input_bytes=mutable,  # pyright: ignore[reportArgumentType] -- the real constructor must reject mutable input even when an untyped caller violates its declared contract.
        max_input_bytes=1,
    )


def _replace_with_mutable_input(request: ProcessRequest, mutable: bytearray) -> ProcessRequest:
    return replace(request, input_bytes=mutable)


@pytest.mark.parametrize(
    "admit",
    [_construct_with_mutable_input, _replace_with_mutable_input],
    ids=("construction", "replace"),
)
def test_mutable_stdin_cannot_bypass_the_admitted_input_limit(
    tmp_path: Path, admit: Callable[[ProcessRequest, bytearray], ProcessRequest]
) -> None:
    request = ProcessRequest((sys.executable,), tmp_path, {}, input_bytes=b"x", max_input_bytes=1)
    mutable = bytearray(b"x")

    with pytest.raises(TypeError, match="immutable bytes"):
        admit(request, mutable)

    mutable.extend(b"now beyond the admitted bound")
    assert request.max_input_bytes is not None
    assert len(mutable) > request.max_input_bytes
    assert request.input_bytes == b"x"
    assert request.max_input_bytes == 1


@pytest.mark.parametrize("limit", ["max_input_bytes", "max_stdout_bytes", "max_stderr_bytes"])
@pytest.mark.parametrize(
    "invalid",
    [True, False, 1.0, 0.5, float("nan"), float("inf"), float("-inf"), -1, "128"],
    ids=("true", "false", "float-integer", "fraction", "nan", "infinity", "negative-infinity", "negative", "text"),
)
def test_invalid_byte_limits_fail_at_request_construction(tmp_path: Path, limit: str, invalid: float | str) -> None:
    request = process_request((sys.executable,), cwd=tmp_path, input_bytes=b"source")

    with pytest.raises((TypeError, ValueError), match="byte limit"):
        replace(request, **{limit: invalid})


@pytest.mark.parametrize("field_name", ["timeout_seconds", "deadline"])
@pytest.mark.parametrize(
    "invalid",
    [True, False, float("nan"), float("inf"), float("-inf"), "5", 10**1000],
    ids=("true", "false", "nan", "infinity", "negative-infinity", "text", "overflow"),
)
def test_invalid_time_domains_fail_at_request_construction(
    tmp_path: Path, field_name: str, invalid: float | str
) -> None:
    request = process_request((sys.executable,), cwd=tmp_path)

    with pytest.raises((TypeError, ValueError), match=r"process (timeout|deadline)"):
        replace(request, **{field_name: invalid})


def test_zero_byte_limits_and_finite_fractional_times_remain_supported(tmp_path: Path) -> None:
    request = process_request(
        (sys.executable,), cwd=tmp_path, input_bytes=b"", max_input_bytes=0, timeout_seconds=0.5, deadline=-1
    )
    request = replace(request, max_stdout_bytes=0, max_stderr_bytes=0)

    assert (request.max_input_bytes, request.max_stdout_bytes, request.max_stderr_bytes) == (0, 0, 0)
    assert request.timeout_seconds == pytest.approx(0.5)
    assert request.deadline == -1
    with pytest.raises(ValueError, match=r"timeout.*nonnegative"):
        replace(request, timeout_seconds=-1)


def test_request_repr_keeps_policy_summaries_without_captured_private_data(tmp_path: Path) -> None:
    request = ProcessRequest(
        ("sensitive-executable", "argv-sensitive-value"),
        tmp_path / "private-working-directory",
        {"PRIVATE_ENV_KEY": "environment-sensitive-value"},
        timeout_seconds=7,
        input_bytes=b"source-sensitive-value",
        max_stdout_bytes=128,
    )

    rendered = repr(request)

    for private in (
        "sensitive-executable",
        "argv-sensitive-value",
        "PRIVATE_ENV_KEY",
        "environment-sensitive-value",
        "source-sensitive-value",
        "private-working-directory",
    ):
        assert private not in rendered
    assert "timeout_seconds=7" in rendered
    assert "max_stdout_bytes=128" in rendered


@pytest.mark.parametrize(("incoming_offset", "expected_offset"), [(-30, -30), (30, 0), (None, 0)])
def test_eslint_composes_absolute_deadlines_and_preserves_other_request_policies(
    tmp_path: Path, incoming_offset: int | None, expected_offset: int
) -> None:
    aggregate = time.monotonic() + 300
    request = ProcessRequest(
        (sys.executable,),
        tmp_path,
        {"PLANNED_VALUE": "retained"},
        timeout_seconds=7,
        deadline=None if incoming_offset is None else aggregate + incoming_offset,
        input_bytes=b"retained input",
        max_input_bytes=128,
        max_stdout_bytes=256,
        max_stderr_bytes=64,
    )
    seen: list[ProcessRequest] = []

    def record(actual: ProcessRequest) -> ProcessOutput:
        seen.append(actual)
        return ProcessOutput(0, "retained output", "")

    result = external._execute_eslint(  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage] -- verify nested deadline composition at the actual ESLint policy wrapper.
        RequestExecutor(record, ProcessCapabilities()), request, deadline=aggregate
    )

    assert result.stdout == "retained output"
    assert len(seen) == 1
    forwarded = seen[0]
    assert forwarded.deadline == aggregate + expected_offset
    assert forwarded.timeout_seconds == 7
    assert (forwarded.argv, forwarded.cwd, forwarded.input_bytes) == (request.argv, request.cwd, request.input_bytes)
    assert (forwarded.max_input_bytes, forwarded.max_stdout_bytes, forwarded.max_stderr_bytes) == (128, 256, 64)
    assert forwarded.environment["PLANNED_VALUE"] == "retained"
    assert "NODE_OPTIONS" in forwarded.environment


def test_eslint_real_process_obeys_a_stricter_incoming_deadline(tmp_path: Path) -> None:
    request = process_request(
        (sys.executable, "-c", "import time; time.sleep(10)"),
        cwd=tmp_path,
        timeout_seconds=2,
        deadline=time.monotonic() + 0.05,
    )

    with pytest.raises(subprocess.TimeoutExpired) as failure:
        external._execute_eslint(  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage] -- a real child must retain the incoming deadline after ESLint's larger aggregate budget is applied.
            DEFAULT_EXECUTOR, request, deadline=time.monotonic() + 300
        )

    assert 0 <= failure.value.timeout <= 0.05


@pytest.mark.parametrize("decorated", [False, True], ids=("bare", "recording"))
@pytest.mark.parametrize("version", ["0.11.0", "0.10.0"], ids=("exact", "wrong-version"))
def test_shellcheck_adapter_uses_selected_executor_for_attestation_and_analysis(
    tmp_path: Path, version: str, *, decorated: bool
) -> None:
    source = tmp_path / "fixture.sh"
    source.write_text("#!/bin/sh\nprintf fixture\n", encoding="utf-8")
    seen: list[ProcessRequest] = []

    def record(request: ProcessRequest) -> ProcessOutput:
        seen.append(request)
        if request.argv[1:] == ("--version",):
            return ProcessOutput(0, f"version: {version}\n", "")
        return ProcessOutput(0, '{"comments":[]}', "")

    executor = RequestExecutor(record, DEFAULT_EXECUTOR.capabilities)
    if decorated:
        executor = RequestExecutor(executor.run, executor.capabilities)

    (report,) = analyze_external(
        (str(source),), root=tmp_path, trust="safe", runner=executor, capabilities=frozenset({"shellcheck"})
    )

    assert seen[0].argv == ("shellcheck", "--version")
    assert seen[0].timeout_seconds == 5
    assert seen[0].cwd == tmp_path
    if version == "0.11.0":
        assert len(seen) == 2
        assert seen[1].argv[0] == "shellcheck"
        assert str(source) in seen[1].argv
        assert report.completion is Completion.COMPLETE
        assert not report.issues
    else:
        assert len(seen) == 1
        assert report.completion is Completion.FAILED
        assert report.issues[0].kind == "version-mismatch"


@pytest.mark.parametrize("decorated", [False, True], ids=("bare", "recording"))
def test_request_preserves_environment_input_and_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, decorated: bool
) -> None:
    monkeypatch.setenv("PROCESS_REQUEST_SECRET", "must-not-be-inherited")
    environment = {"PROCESS_REQUEST_VALUE": "snapshot"}
    request = process_request(
        (
            sys.executable,
            "-c",
            (
                "import os, sys; print(os.getcwd()); print(os.environ['PROCESS_REQUEST_VALUE']); "
                "print(os.environ.get('PROCESS_REQUEST_SECRET', 'absent')); print(sys.stdin.read())"
            ),
        ),
        cwd=tmp_path,
        environment=environment,
        input_bytes=b"bounded input",
        max_input_bytes=1024 * 1024,
    )
    environment["PROCESS_REQUEST_VALUE"] = "changed after planning"
    seen: list[ProcessRequest] = []

    def record(actual: ProcessRequest) -> ProcessOutput:
        seen.append(actual)
        return DEFAULT_EXECUTOR.run(actual)

    executor = RequestExecutor(record, DEFAULT_EXECUTOR.capabilities) if decorated else DEFAULT_EXECUTOR
    result = executor.run(request)

    assert result.returncode == 0
    assert result.stdout.splitlines() == [str(tmp_path), "snapshot", "absent", "bounded input"]
    assert not result.stderr
    assert seen == ([request] if decorated else [])
    if decorated:
        assert seen[0] is request
        assert executor.capabilities is DEFAULT_EXECUTOR.capabilities


@pytest.mark.parametrize("decorated", [False, True], ids=("bare", "recording"))
def test_request_timeout_and_output_limits_survive_decoration(tmp_path: Path, *, decorated: bool) -> None:
    executor = RequestExecutor(DEFAULT_EXECUTOR.run, DEFAULT_EXECUTOR.capabilities) if decorated else DEFAULT_EXECUTOR
    request = process_request((sys.executable, "-c", "import time; time.sleep(10)"), cwd=tmp_path, timeout_seconds=0.05)

    with pytest.raises(subprocess.TimeoutExpired) as failure:
        executor.run(request)
    assert failure.value.timeout == pytest.approx(0.05)

    noisy = process_request((sys.executable, "-c", "print('x' * 10000)"), cwd=tmp_path)
    with pytest.raises(OutputLimitError, match="128 byte stdout"):
        executor.run(replace(noisy, max_stdout_bytes=128))


@pytest.mark.parametrize("decorated", [False, True], ids=("bare", "recording"))
@pytest.mark.parametrize("stream", ["stdout", "stderr"])
@pytest.mark.parametrize("limit", [0, 128, 65536], ids=("zero", "small", "read-boundary"))
def test_held_open_output_overflow_fails_before_timeout(
    tmp_path: Path, stream: str, limit: int, *, decorated: bool
) -> None:
    executor = RequestExecutor(DEFAULT_EXECUTOR.run, DEFAULT_EXECUTOR.capabilities) if decorated else DEFAULT_EXECUTOR
    request = ProcessRequest(
        (
            sys.executable,
            "-c",
            f"import sys, time; sys.{stream}.write('x' * {limit + 1}); sys.{stream}.flush(); time.sleep(10)",
        ),
        tmp_path,
        {},
        timeout_seconds=2,
        max_stdout_bytes=limit,
        max_stderr_bytes=limit,
    )

    with pytest.raises(OutputLimitError, match="analyzer output exceeded"):
        executor.run(request)


@pytest.mark.parametrize("stream", ["stdout", "stderr"])
@pytest.mark.parametrize("limit", [0, 128, 65536], ids=("zero", "small", "read-boundary"))
def test_output_exactly_at_limit_is_captured_completely(tmp_path: Path, stream: str, limit: int) -> None:
    request = ProcessRequest(
        (sys.executable, "-c", f"import sys; sys.{stream}.write('x' * {limit})"),
        tmp_path,
        {},
        max_stdout_bytes=limit,
        max_stderr_bytes=limit,
    )

    output = DEFAULT_EXECUTOR.run(request)

    assert output.returncode == 0
    assert output.stdout == ("x" * limit if stream == "stdout" else "")
    assert output.stderr == ("x" * limit if stream == "stderr" else "")


def test_expired_deadline_prevents_process_launch(tmp_path: Path) -> None:
    marker = tmp_path / "launched"
    request = process_request(
        (sys.executable, "-c", "from pathlib import Path; Path('launched').touch()"),
        cwd=tmp_path,
        deadline=time.monotonic() - 1,
    )

    with pytest.raises(subprocess.TimeoutExpired) as failure:
        DEFAULT_EXECUTOR.run(request)

    assert failure.value.timeout == 0
    assert not marker.exists()


@pytest.mark.parametrize("decorated", [False, True], ids=("bare", "recording"))
def test_version_probe_keeps_resolution_attestation_and_five_second_policy(tmp_path: Path, *, decorated: bool) -> None:
    seen: list[ProcessRequest] = []

    def record(request: ProcessRequest) -> ProcessOutput:
        seen.append(request)
        return DEFAULT_EXECUTOR.run(request)

    executor = RequestExecutor(record, DEFAULT_EXECUTOR.capabilities)
    if decorated:
        executor = RequestExecutor(executor.run, executor.capabilities)
    tool = NativeTool(sys.executable, "1.2.3", ("-c", "print('1.2.3')"), r"^(?P<version>1\.2\.3)$")

    attested = checked_runtime_tool(tool, root=tmp_path, runner=executor)

    assert attested.executable == Path(sys.executable).resolve()
    assert len(seen) == 1
    assert seen[0].argv[0] == str(attested.executable)
    assert seen[0].timeout_seconds == 5
    assert seen[0].max_stdout_bytes == 16 * 1024 * 1024
    assert seen[0].max_stderr_bytes == 64 * 1024


def test_legacy_callable_injection_reports_missing_explicit_capabilities(tmp_path: Path) -> None:
    def legacy(_argv: tuple[str, ...], *, cwd: Path) -> ProcessOutput:
        pytest.fail(f"legacy callback unexpectedly executed in {cwd}")

    (report,) = analyze_external(
        (),
        root=tmp_path,
        trust="safe",
        runner=legacy,  # pyright: ignore[reportArgumentType] -- legacy injection must fail explicitly before execution.
    )

    assert report.issues[0].kind == "invalid-input"
    assert "explicit ProcessCapabilities" in report.issues[0].message


@pytest.mark.skipif(sys.platform != "linux", reason="isolated descendant reaping uses Linux's subreaper API")
@pytest.mark.parametrize("mode", ["timeout", "interrupt", "closed-streams"])
@pytest.mark.parametrize("decorated", [False, True], ids=("bare", "recording"))
@pytest.mark.parametrize("fallback", [False, True], ids=("waitid", "without-wnowait"))
def test_owned_process_cleanup_reaps_descendants_and_drains_threads(
    tmp_path: Path, mode: str, *, decorated: bool, fallback: bool
) -> None:
    probe = Path(__file__).with_name("process_cleanup_probe.py")

    output = run_process(
        (
            sys.executable,
            str(probe),
            str(tmp_path),
            mode,
            "recording" if decorated else "bare",
            "fallback" if fallback else "waitid",
        ),
        cwd=tmp_path,
        timeout_seconds=10,
    )

    assert output.returncode == 0, output.stderr
    expected = "KeyboardInterrupt" if mode == "interrupt" else "TimeoutExpired"
    assert output.stdout.split() == [expected, "True", "True", "True", "True"]
