from __future__ import annotations

from pathlib import Path
import shlex
import subprocess
import sys

from pydantic import BaseModel
import pytest
import yaml


REPOSITORY = Path(__file__).resolve().parents[3]
POLICY = '[policy]\ntokens = ["fixture-only"]\n'


class _Step(BaseModel):
    name: str = ""
    run: str | None = None


class _Job(BaseModel):
    steps: tuple[_Step, ...]


class _Workflow(BaseModel):
    jobs: dict[str, _Job]


class _Scan(BaseModel):
    argv: list[str]
    mode: int
    policy: str


def _scan_command() -> tuple[str, ...]:
    source = (REPOSITORY / ".github/workflows/private-refs.yml").read_text(encoding="utf-8")
    workflow = _Workflow.model_validate(yaml.safe_load(source))
    step = next(step for step in workflow.jobs["scan"].steps if step.name == "Scan private references")
    assert step.run is not None
    return tuple(shlex.split(step.run))


@pytest.mark.parametrize("scanner_status", [pytest.param(0, id="success"), pytest.param(17, id="scanner-failure")])
def test_private_scan_uses_trusted_scanner_and_removes_private_policy(tmp_path: Path, scanner_status: int) -> None:
    scripts = tmp_path / "trusted/.github/scripts"
    scripts.mkdir(parents=True)
    (scripts / "ci-private-refs.sh").write_bytes((REPOSITORY / ".github/scripts/ci-private-refs.sh").read_bytes())
    scanner = tmp_path / "trusted/packages/standards/.venv/bin/code-standards"
    scanner.parent.mkdir(parents=True)
    scanner.write_text(
        f"#!{sys.executable}\n"
        "import json, pathlib, stat, sys\n"
        "policy = pathlib.Path(sys.argv[sys.argv.index('--private-refs-file') + 1])\n"
        "pathlib.Path('scan.json').write_text(json.dumps({'argv': sys.argv[1:], 'mode': stat.S_IMODE(policy.stat().st_mode), 'policy': policy.read_text()}))\n"
        f"sys.exit({scanner_status})\n",
        encoding="utf-8",
    )
    scanner.chmod(0o755)
    candidate = tmp_path / "candidate/packages/standards/.venv/bin/code-standards"
    candidate.parent.mkdir(parents=True)
    candidate.write_text("#!/bin/sh\nexit 99\n", encoding="utf-8")
    candidate.chmod(0o755)
    temporary = tmp_path / "runner"
    temporary.mkdir()

    result = subprocess.run(
        _scan_command(),
        cwd=tmp_path,
        env={
            "PATH": "/usr/bin:/bin",
            "RUNNER_TEMP": str(temporary),
            "PRIVATE_REFS_TOML": POLICY,
            "BASE_SHA": "a" * 40,
            "HEAD_SHA": "b" * 40,
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == scanner_status
    scan = _Scan.model_validate_json((tmp_path / "scan.json").read_text(encoding="utf-8"))
    assert scan.argv == [
        "--root",
        "candidate",
        "maintain",
        "check",
        "--policy-root",
        "trusted",
        "--private-refs-file",
        str(temporary / "private-refs.toml"),
        "--only",
        "private-refs",
        "--commits",
        f"{'a' * 40}..{'b' * 40}",
    ]
    assert scan.mode == 0o600
    assert scan.policy == POLICY
    assert list(temporary.iterdir()) == []
    assert POLICY not in result.stdout + result.stderr


def test_private_scan_requires_policy_before_creating_secret_file(tmp_path: Path) -> None:
    result = subprocess.run(
        ("bash", str(REPOSITORY / ".github/scripts/ci-private-refs.sh")),
        cwd=tmp_path,
        env={"PATH": "/usr/bin:/bin", "RUNNER_TEMP": str(tmp_path), "PRIVATE_REFS_TOML": ""},
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == 1
    assert list(tmp_path.iterdir()) == []
