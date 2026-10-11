from __future__ import annotations

import shutil
import subprocess
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING

import pytest
from sarj_rule_contracts import examples

from sarj_standards.libs.repository import rule_examples
from sarj_standards.libs.rules import RuleSelector


if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize(
    ("status", "stdout", "stderr"), [(0, "2\n", ""), (1, "", "installed dependency identity/version mismatch")]
)
def test_native_verifier_routes_to_selected_installed_package(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, status: int, stdout: str, stderr: str
) -> None:
    invoked: list[tuple[tuple[str, ...], Path]] = []

    def which(program: str) -> str | None:
        return f"/installed/{program}" if program in {"node", "npm"} else None

    def run(
        command: tuple[str, ...],
        *,
        cwd: Path,
        check: bool,
        timeout: float,
        capture_output: bool = False,
        text: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        invoked.append((command, cwd))
        if command[0] == "/installed/npm":
            assert check is True
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        assert check is False
        assert capture_output is True
        assert text is True
        assert timeout > 0
        return subprocess.CompletedProcess(command, status, stdout=stdout, stderr=stderr)

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- Installed executable discovery through ambient PATH is the routing boundary under test.
        shutil, "which", which
    )
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- Intercept only the external process boundary; the real package-build and verifier orchestration run.
        subprocess, "run", run
    )
    selector = RuleSelector.parse("eslint:prefer-zod-parse-output-type")
    if status:
        with pytest.raises(ValueError, match="installed dependency identity/version mismatch"):
            rule_examples.verify(tmp_path, selector)
    else:
        assert rule_examples.verify(tmp_path, selector) == 2
    (build_command, build_cwd), (command, cwd) = invoked
    assert build_command == ("/installed/npm", "run", "build", "--silent")
    assert build_cwd == tmp_path / "packages/typescript"
    assert command[:3] == ("/installed/node", "--input-type=module", "--eval")
    assert command[-1] == str(selector.rule_id)
    assert cwd == tmp_path / "packages/typescript"


def test_native_multifile_example_uses_canonical_temporary_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage = tmp_path / "storage"
    storage.mkdir()
    alias = tmp_path / "temporary-alias"
    alias.symlink_to(storage, target_is_directory=True)

    def temporary_directory(*, prefix: str) -> TemporaryDirectory[str]:
        return TemporaryDirectory(prefix=prefix, dir=alias)

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- Intercept the runner's temporary-workspace factory; injecting a canonical root would bypass the alias boundary under test.
        examples, "TemporaryDirectory", temporary_directory
    )
    selector = RuleSelector.parse("python:prefer-pytest-fixture-injection")
    assert rule_examples.verify(tmp_path, selector) == 4
    assert not list(storage.iterdir())
