from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
from typing import TYPE_CHECKING

import pytest

from sarj_standards.libs.repository import rule_catalog_artifact


if TYPE_CHECKING:
    from collections.abc import Sequence


def test_projection_builds_fresh_unless_the_invocation_explicitly_provides_a_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    commands: list[tuple[str, ...]] = []

    def run(argv: Sequence[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(tuple(argv))
        return subprocess.CompletedProcess(argv, 0, stdout="[]", stderr="")

    def executable(name: str) -> str:
        return f"/tools/{name}"

    monkeypatch.setattr(shutil, "which", executable)  # sarj-noqa: SARJ445 -- exercise the real build dispatch boundary
    monkeypatch.setattr(subprocess, "run", run)  # sarj-noqa: SARJ445 -- count compiler launches
    assert rule_catalog_artifact.typescript_specs(tmp_path) == ()
    assert rule_catalog_artifact.typescript_specs(tmp_path, already_built=True) == ()
    assert rule_catalog_artifact.typescript_specs(tmp_path) == ()
    assert [argv[0] for argv in commands] == ["/tools/npm", "/tools/node", "/tools/node", "/tools/npm", "/tools/node"]


def test_full_verification_shares_one_typescript_build_between_catalog_docs_and_dogfood() -> None:
    make = shutil.which("make")
    if make is None:
        pytest.skip("requires make to inspect the verification dependency graph")
    root = Path(__file__).resolve().parents[3]
    result = subprocess.run(
        (make, "--dry-run", "verify"), cwd=root, check=True, capture_output=True, text=True, timeout=10
    )
    assert sum(line.strip() == "cd packages/typescript && npm run build" for line in result.stdout.splitlines()) == 1
    assert "maintain catalog check --typescript-built" in result.stdout
    assert "npm run dogfood:built" in result.stdout
