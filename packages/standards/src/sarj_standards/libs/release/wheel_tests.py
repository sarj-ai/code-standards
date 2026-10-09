from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING, Annotated

import typer

from sarj_standards.libs.release.process import (
    ProcessFailureError,
    ProcessRunner,
    credential_free_environment,
    run_process,
    run_process_environment,
)


if TYPE_CHECKING:
    from collections.abc import Sequence


from sarj_standards.libs.release.test_selection import pytest_parallel_arguments, select_tests


_MAX_TEST_JOBS = 16
_TEST_PACKAGES = ("contracts", "python", "sql", "iac", "standards")


def run_wheel_tests(
    root: Path,
    *,
    jobs: int = 4,
    pytest_args: Sequence[str] = (),
    changed: bool = False,
    base: str = "origin/main",
    runner: ProcessRunner = run_process,
) -> None:
    if not 1 <= jobs <= _MAX_TEST_JOBS:
        msg = "test jobs must be between 1 and 16"
        raise ValueError(msg)
    root = root.resolve()
    package = root / "packages/standards"
    tests = ("tests/",)
    test_files: int | None = None
    if changed:
        plan = select_tests(root, base=base)
        tests = plan.tests
        test_files = len(tests)
        sys.stdout.write(f"Standards: {len(tests)}/{plan.total_files} test files; {plan.reason}\n")
    with TemporaryDirectory(prefix="sarj-wheel-tests-") as directory:
        destination = Path(directory)
        wheels = destination / "wheels"
        wheels.mkdir()
        with ThreadPoolExecutor(
            max_workers=min(jobs, len(_TEST_PACKAGES)), thread_name_prefix="wheel-build"
        ) as workers:
            pending = [
                workers.submit(
                    runner,
                    ("uv", "build", "--wheel", "--project", str(root / "packages" / name), "--out-dir", str(wheels)),
                    cwd=root,
                )
                for name in _TEST_PACKAGES
            ]
            for result in pending:
                result.result()
        artifacts = tuple(sorted(wheels.glob("*.whl")))
        if len(artifacts) != len(_TEST_PACKAGES):
            msg = f"expected five fresh local wheels, found {len(artifacts)}"
            raise ValueError(msg)
        environment_path = destination / "venv"
        runner(("uv", "venv", "--python", "3.14", str(environment_path)), cwd=root)
        bin_path = environment_path / ("Scripts" if sys.platform == "win32" else "bin")
        python = bin_path / ("python.exe" if sys.platform == "win32" else "python")
        runner(
            (
                "uv",
                "pip",
                "install",
                "--python",
                str(python),
                "pytest==9.1.1",
                "pytest-xdist==3.8.0",
                "jsonschema==4.25.1",
                *(str(path) for path in artifacts),
            ),
            cwd=root,
        )
        environment = credential_free_environment()
        environment["PATH"] = str(bin_path) + os.pathsep + environment.get("PATH", "")
        run_process_environment(
            (
                str(python),
                "-m",
                "pytest",
                "-q",
                *pytest_parallel_arguments(jobs, files=test_files),
                *tests,
                *pytest_args,
            ),
            cwd=package,
            environment=environment,
        )


def main(argv: Sequence[str] | None = None) -> int:
    app = typer.Typer(add_completion=False, pretty_exceptions_enable=False)
    exit_code = 0

    @app.command(context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
    def check(
        ctx: typer.Context,
        *,
        root: Annotated[Path, typer.Option("--root")] = Path(),
        jobs: Annotated[int, typer.Option("--jobs", min=1, max=_MAX_TEST_JOBS)] = 4,
        changed: Annotated[bool, typer.Option("--changed")] = False,
        base: Annotated[str, typer.Option("--base")] = "origin/main",
    ) -> None:
        nonlocal exit_code
        try:
            run_wheel_tests(root, jobs=jobs, pytest_args=ctx.args, changed=changed, base=base)
        except ProcessFailureError as exc:
            exit_code = exc.returncode
        except (OSError, ValueError) as exc:
            sys.stderr.write(f"error: {exc}\n")
            exit_code = 2

    try:
        app(args=None if argv is None else list(argv), prog_name="standards-wheel-tests")
    except SystemExit as exc:
        if exc.code != 0:
            raise
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
