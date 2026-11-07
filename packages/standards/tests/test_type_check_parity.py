from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import subprocess
import time

import pytest

from sarj_standards.libs.diagnostics import Location
from sarj_standards.libs.linting.oxlint import type_check_diagnostic
from tests.oxlint_json import OxlintReport


BINARIES = Path(__file__).resolve().parents[3] / "packages/typescript/node_modules/.bin"
CORPORA = [
    entry
    for entry in os.environ.get("SARJ_TYPE_CHECK_PARITY", "").split(os.pathsep)  # ruff: ignore[banned-api] -- opt-in corpus list for a manual parity run.
    if entry
]
_TSRS_ERROR = re.compile(r"^(?:(?P<file>.+?)\((?P<line>\d+),\d+\): )?error (?P<code>TS\d+): ")

type Finding = tuple[str, int, str]


def _environment_without_agent_variables() -> dict[str, str]:
    inherited = {name: os.environ[name] for name in ("PATH", "HOME")}  # ruff: ignore[banned-api] -- keep the runner's tool path.
    return {**inherited, "OXLINT_TSGOLINT_PATH": str(BINARIES / "tsrs-lint")}


def _tsrs(repo: Path, tsconfig: Path) -> set[Finding]:
    completed = subprocess.run(
        (str(BINARIES / "tsrs"), "--noEmit", "--pretty", "false", "-p", str(tsconfig)),
        cwd=repo,
        env=_environment_without_agent_variables(),
        capture_output=True,
        text=True,
        check=False,
        timeout=600,
    )
    findings: set[Finding] = set()
    for line in completed.stdout.splitlines():
        if match := _TSRS_ERROR.match(line):
            path = tsconfig if match["file"] is None else repo / match["file"]
            findings.add((path.resolve().relative_to(repo).as_posix(), int(match["line"] or 0), match["code"]))
    return findings


@dataclass(frozen=True, slots=True)
class _OxlintRun:
    findings: set[Finding]
    rejected_tsconfigs: set[str]


def _oxlint(repo: Path, target: Path) -> _OxlintRun:
    completed = subprocess.run(
        (str(BINARIES / "oxlint"), "--type-aware", "--type-check", "-f", "json", str(target.relative_to(repo))),
        cwd=repo,
        env=_environment_without_agent_variables(),
        capture_output=True,
        text=True,
        check=False,
        timeout=600,
    )
    assert completed.returncode in {0, 1}, completed.stderr
    findings: set[Finding] = set()
    rejected: set[str] = set()
    for raw in OxlintReport.model_validate_json(completed.stdout).diagnostics:
        if not raw.filename:
            continue
        mapped = type_check_diagnostic(raw.code, raw.message, Location(raw.filename), help_text=raw.help)
        if mapped is None:
            continue
        if mapped.rule_id == "tsc/tsconfig-error":
            rejected.add(mapped.location.path)
            continue
        findings.add((mapped.location.path, raw.labels[0].span.line if raw.labels else 0, mapped.code))
    return _OxlintRun(findings, rejected)


@pytest.mark.skipif(
    not CORPORA,
    reason=(
        "set SARJ_TYPE_CHECK_PARITY to os.pathsep-separated <repo> or <repo>#<subdirectory> entries; use disposable "
        "copies with dependencies installed because tsrs --noEmit still writes .tsbuildinfo"
    ),
)
@pytest.mark.parametrize("entry", CORPORA)
def test_type_check_never_silently_passes_what_tsrs_rejects(entry: str) -> None:
    repo_text, _, subdirectory = entry.partition("#")
    repo = Path(repo_text).resolve()
    target = repo / subdirectory
    tsconfigs = sorted(path for path in target.rglob("tsconfig.json") if "node_modules" not in path.parts)

    started = time.monotonic()
    expected = {tsconfig.relative_to(repo).as_posix(): _tsrs(repo, tsconfig) for tsconfig in tsconfigs}
    tsrs_seconds = time.monotonic() - started
    started = time.monotonic()
    run = _oxlint(repo, target)
    reported, rejected = run.findings, run.rejected_tsconfigs
    oxlint_seconds = time.monotonic() - started

    missing_outside_rejected_projects = {
        finding
        for tsconfig, findings in expected.items()
        if tsconfig not in rejected
        for finding in findings
        if finding not in reported
    }
    expected_findings = {finding for findings in expected.values() for finding in findings}
    print(  # ruff: ignore[print] -- the opt-in corpus run records timing and gaps for the stage 2 decision.
        f"{entry}: tsrs {len(expected_findings)} errors in {tsrs_seconds:.2f}s; oxlint {len(reported)} errors "
        f"in {oxlint_seconds:.2f}s; rejected tsconfigs {sorted(rejected)}; "
        f"oxlint-only {len(reported - expected_findings)}"
    )
    assert missing_outside_rejected_projects == set()
