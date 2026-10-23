from __future__ import annotations

import json
from pathlib import Path
import shlex
import subprocess

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[3]


def _test_command(target: str, assignments: tuple[str, ...]) -> tuple[str, ...]:
    result = subprocess.run(
        (
            "make",
            "--no-print-directory",
            "--dry-run",
            target,
            "BASE=origin/main",
            "PYTEST_ARGS=-k worker_budget_probe",
            *assignments,
        ),
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert not result.stderr
    command = shlex.split(result.stdout)
    return tuple(command[command.index("-m") + 1 :])


@pytest.mark.parametrize(
    ("target", "selection"),
    [
        pytest.param("test-standards", (), id="full-suite"),
        pytest.param("test-standards-changed", ("--changed", "--base", "origin/main"), id="changed-suite"),
    ],
)
@pytest.mark.parametrize(
    ("environment", "assignments", "expected_jobs"),
    [
        pytest.param({}, (), 4, id="default"),
        pytest.param({"PYTEST_XDIST_AUTO_NUM_WORKERS": ""}, (), 4, id="empty-budget"),
        pytest.param({"PYTEST_XDIST_AUTO_NUM_WORKERS": "2"}, (), 2, id="shared-budget"),
        pytest.param({"PYTEST_XDIST_AUTO_NUM_WORKERS": "0"}, (), 1, id="serial-budget"),
        pytest.param({"PYTEST_XDIST_AUTO_NUM_WORKERS": "2"}, ("TEST_JOBS=3",), 3, id="explicit-command-line"),
        pytest.param({"PYTEST_XDIST_AUTO_NUM_WORKERS": "2", "TEST_JOBS": "3"}, (), 3, id="explicit-environment"),
    ],
)
def test_native_make_preserves_test_selection_with_worker_budget(
    monkeypatch: pytest.MonkeyPatch,
    *,
    target: str,
    selection: tuple[str, ...],
    environment: dict[str, str],
    assignments: tuple[str, ...],
    expected_jobs: int,
) -> None:
    for name in ("PYTEST_XDIST_AUTO_NUM_WORKERS", "TEST_JOBS", "MAKEFLAGS", "MFLAGS", "MAKEOVERRIDES"):
        monkeypatch.delenv(name, raising=False)
    for name, value in environment.items():
        monkeypatch.setenv(name, value)

    assert _test_command(target, assignments) == (
        "sarj_standards.libs.release.wheel_tests",
        "--root",
        ".",
        "--jobs",
        str(expected_jobs),
        *selection,
        "-k",
        "worker_budget_probe",
    )


@pytest.mark.parametrize("target", ["test-standards", "test-standards-changed"])
def test_native_make_builds_plugin_before_wheel_tests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, target: str
) -> None:
    (tmp_path / "Makefile").write_bytes((_REPO_ROOT / "Makefile").read_bytes())
    helper = Path(".github/scripts/make-native-test-tools.sh")
    (tmp_path / helper).parent.mkdir(parents=True)
    (tmp_path / helper).write_bytes((_REPO_ROOT / helper).read_bytes())
    binaries = tmp_path / "bin"
    binaries.mkdir()
    command = (
        "#!/usr/bin/env python3\n"
        "import json\n"
        "import os\n"
        "from pathlib import Path\n"
        "import sys\n"
        "name = Path(sys.argv[0]).name\n"
        "built = Path('built-plugin')\n"
        "if name == 'uv' and not built.is_file():\n"
        "    raise SystemExit('wheel gate started before the plugin build')\n"
        "if name == 'uv' and 'sarj_standards.libs.release.native_test_setup' in sys.argv:\n"
        "    Path(os.environ['GITHUB_PATH']).touch()\n"
        "with Path('commands.jsonl').open('a') as stream:\n"
        "    stream.write(json.dumps([name, *sys.argv[1:]]) + '\\n')\n"
        "if name == 'npm':\n"
        "    built.touch()\n"
    )
    for name in ("npm", "uv"):
        executable = binaries / name
        executable.write_text(command, encoding="utf-8")
        executable.chmod(0o755)
    for name in ("MAKEFLAGS", "MFLAGS", "MAKEOVERRIDES"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PATH", str(binaries), prepend=":")
    result = subprocess.run(
        ("make", "--no-print-directory", target, "TEST_JOBS=2", "BASE=origin/main", "PYTEST_ARGS="),
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    commands = [json.loads(line) for line in (tmp_path / "commands.jsonl").read_text().splitlines()]
    assert commands[0] == ["npm", "--prefix", "packages/typescript", "run", "build"]
    selection = ["--changed", "--base", "origin/main"] if target.endswith("-changed") else []
    assert commands[1:] == [
        [
            "uv",
            "run",
            "--project",
            "packages/standards",
            "--frozen",
            "python",
            "-m",
            "sarj_standards.libs.release.native_test_setup",
            "--root",
            ".",
        ],
        [
            "uv",
            "run",
            "--project",
            "packages/standards",
            "--frozen",
            "python",
            "-m",
            "sarj_standards.libs.release.wheel_tests",
            "--root",
            ".",
            "--jobs",
            "2",
            *selection,
        ],
    ]
