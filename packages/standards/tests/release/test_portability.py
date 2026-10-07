from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess

import pytest

from sarj_standards.libs.release.process import credential_free_environment, run_process


ROOT = Path(__file__).resolve().parents[4]


@pytest.mark.parametrize("failed", ["none", "cli", "hook", "warm"])
def test_portability_overlaps_both_lanes_and_propagates_each_failure(tmp_path: Path, failed: str) -> None:
    scripts = tmp_path / ".github/scripts"
    scripts.mkdir(parents=True)
    shutil.copy(ROOT / ".github/scripts/release-precommit.sh", scripts)
    (tmp_path / "packages/standards").mkdir(parents=True)
    run_process(("git", "init", "-q"), cwd=tmp_path)
    run_process(("git", "add", "."), cwd=tmp_path)
    run_process(
        ("git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "fixture"),
        cwd=tmp_path,
    )
    executable = tmp_path / "bin/uv"
    executable.parent.mkdir()
    executable.write_text(
        "#!/usr/bin/env bash\nset -eu\n"
        'if [[ "$1 $2 $3" == "run --frozen pytest" ]]; then\n'
        '  touch "$SIGNALS/cli"\n'
        '  for i in {1..500}; do [[ -f "$SIGNALS/hook" ]] && break; sleep 0.01; done\n'
        '  test -f "$SIGNALS/hook"\n'
        '  [[ "$FAILED" != cli ]]\n'
        "else\n"
        '  touch "$SIGNALS/hook"\n'
        '  for i in {1..500}; do [[ -f "$SIGNALS/cli" ]] && break; sleep 0.01; done\n'
        '  test -f "$SIGNALS/cli"\n'
        '  [[ "$FAILED" != hook ]]\n'
        '  if [[ -f "$SIGNALS/cold" && "$FAILED" == warm ]]; then echo "Installing environment"; fi\n'
        '  touch "$SIGNALS/cold"\n'
        "fi\n"
    )
    executable.chmod(0o755)
    reports = tmp_path / "reports"
    environment = credential_free_environment()
    environment.pop("GITHUB_SHA", None)
    environment.update(
        {
            "PATH": str(executable.parent) + os.pathsep + environment.get("PATH", os.defpath),
            "FAILED": failed,
            "SIGNALS": str(tmp_path),
            "RUNNER_TEMP": str(tmp_path),
            "PORTABILITY_REPORT_DIR": str(reports),
            "GITHUB_STEP_SUMMARY": str(tmp_path / "summary"),
        }
    )
    process = subprocess.run(
        ("bash", str(ROOT / ".github/scripts/release-portability.sh")),
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )
    assert process.returncode == (0 if failed == "none" else 1), process.stdout + process.stderr
    assert (tmp_path / "cli").exists()
    assert (tmp_path / "hook").exists()
    assert len((tmp_path / "summary").read_text().splitlines()) == 2
    assert (reports / "consumer-cli.log").exists()
    assert (reports / "pre-commit.log").exists()
