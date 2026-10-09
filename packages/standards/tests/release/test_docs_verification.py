from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess

import pytest


REPO_ROOT = Path(__file__).resolve().parents[4]


@pytest.mark.parametrize("failure", ["none", "examples", "catalog", "lint", "types", "build", "distribution"])
def test_complete_docs_gate_checks_projections_once_and_stops_on_failure(tmp_path: Path, failure: str) -> None:
    script = (REPO_ROOT / ".github/scripts/verify-docs.sh").read_text()
    commands = script[script.index("run_check()") :]
    signals = tmp_path / "signals"
    signals.mkdir()
    npm = tmp_path / "npm"
    npm.write_text(
        '#!/bin/sh\ncase "$*" in\n'
        '"run code-examples:check") name=examples;;\n'
        '"run third-party-catalog:check") name=catalog;;\n'
        '"--ignore-scripts run lint") name=lint;;\n'
        '"--ignore-scripts run check") name=types;;\n'
        '"--ignore-scripts run build") name=build;;\n'
        "*) exit 8;; esac\n"
        'if [ "$name" = lint ] || [ "$name" = types ]; then\n'
        'touch "$SIGNALS/$name.started"\n'
        'until test -f "$SIGNALS/lint.started" && test -f "$SIGNALS/types.started"; do sleep 0.01; done\n'
        'touch "$SIGNALS/$name.done"\nfi\n'
        'if [ "$name" = build ]; then\n'
        'test -f "$SIGNALS/lint.done" && test -f "$SIGNALS/types.done" || exit 9\nfi\n'
        'printf "%s\\n" "$name" >> "$SIGNALS/order"\n'
        '[ "$FAILURE" != "$name" ]\n'
    )
    npm.chmod(0o755)
    node = tmp_path / "node"
    node.write_text(
        '#!/bin/sh\ntest "$*" = "scripts/verify-third-party-catalog.mjs --dist" || exit 8\n'
        'printf "distribution\\n" >> "$SIGNALS/order"\n[ "$FAILURE" != distribution ]\n'
    )
    node.chmod(0o755)
    result = subprocess.run(
        (shutil.which("bash") or "/bin/bash", "-eu", "-o", "pipefail", "-c", commands),
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
        env={
            **os.environ,  # ruff: ignore[banned-api] -- actual verification shell with controlled package-manager inputs.
            "PATH": str(tmp_path) + os.pathsep + os.defpath,
            "SIGNALS": str(signals),
            "FAILURE": failure,
        },
    )
    expected = ["examples", "catalog", "lint", "types", "build", "distribution"]
    if failure != "none":
        expected = expected[: (4 if failure in {"lint", "types"} else expected.index(failure) + 1)]
    observed = (signals / "order").read_text().splitlines()
    assert observed[:2] == expected[:2]
    assert sorted(observed[2:4]) == sorted(expected[2:4])
    assert observed[4:] == expected[4:]
    assert (result.returncode == 0) == (failure == "none")
    assert len(result.stdout.splitlines()) == len(expected)
