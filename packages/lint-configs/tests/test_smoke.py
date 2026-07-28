from __future__ import annotations

import json
import re
import subprocess
import sys
import tomllib
from typing import TYPE_CHECKING

import pytest

from sarj_lint_configs import (
    CONFIGS_DIR,
    ESLINT_STRICT,
    MARKDOWNLINT_STRICT,
    PYRIGHT_STRICT,
    RUFF_STRICT,
    TAPLO_STRICT,
    YAMLLINT_STRICT,
    __version__,
)


if TYPE_CHECKING:
    from pathlib import Path


def test_version_string() -> None:
    assert __version__.count(".") == 2
    assert all(part.isdigit() for part in __version__.split("."))


def test_configs_dir_exists() -> None:
    assert CONFIGS_DIR.is_dir(), f"missing: {CONFIGS_DIR}"


def test_all_six_configs_bundled() -> None:
    for path in (RUFF_STRICT, PYRIGHT_STRICT, ESLINT_STRICT, MARKDOWNLINT_STRICT, TAPLO_STRICT, YAMLLINT_STRICT):
        assert path.is_file(), f"missing bundled config: {path}"
        assert path.stat().st_size > 0


def test_ruff_config_is_valid_toml() -> None:
    text = RUFF_STRICT.read_text()
    data = tomllib.loads(text)  # parses as TOML
    assert "lint" in data
    assert re.search(r'external\s*=\s*\[\s*"SARJ"\s*\]', text)
    assert re.search(r'select\s*=\s*\[\s*"ALL"\s*\]', text)


def test_pyright_config_is_valid_jsonc() -> None:
    # pyright loads its config as JSONC; a bare-key .toml is silently ignored by
    # `extends`, so the strict pyright config must ship as JSON(C), not TOML.
    raw = PYRIGHT_STRICT.read_text()
    assert isinstance(json.loads(re.sub(r"//.*", "", raw)), dict)  # parses as JSON(C)
    assert re.search(r'"typeCheckingMode"\s*:\s*"strict"', raw)
    assert re.search(r'"reportExplicitAny"\s*:\s*"error"', raw)


def test_eslint_config_is_esm() -> None:
    text = ESLINT_STRICT.read_text()
    assert "export default" in text


def test_promise_function_async_skips_method_declarations() -> None:
    # The autofix is destructive on framework-defined methods: React's ReactNode
    # includes Promise<AwaitedReactNode>, so a class component's render() infers
    # as promise-returning and the fixer adds `async`, which makes React throw
    # #482 at runtime. Checking methods must stay off.
    text = ESLINT_STRICT.read_text()
    assert re.search(
        r'"@typescript-eslint/promise-function-async"\s*:\s*\[\s*"error"\s*,\s*\{[^}]*checkMethodDeclarations\s*:\s*false',
        text,
    )


def test_prefer_nullish_coalescing_ignores_primitives() -> None:
    text = ESLINT_STRICT.read_text()
    assert re.search(
        r'"@typescript-eslint/prefer-nullish-coalescing"\s*:\s*\[\s*"error"\s*,\s*\{[^}]*ignorePrimitives\s*:\s*\{',
        text,
    )


def test_naming_convention_allows_framework_names() -> None:
    text = ESLINT_STRICT.read_text()
    assert re.search(
        r'"@typescript-eslint/naming-convention".+?format:\s*\["camelCase"\].+?filter:\s*\{\s*regex:\s*"\^\(UNSAFE_\|__\)"',
        text,
        re.DOTALL
    )


def test_cli_list(tmp_path: Path) -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "sarj_lint_configs", "list"],
        capture_output=True, text=True, check=True, cwd=tmp_path,
    )
    assert "ruff" in proc.stdout
    assert "pyright" in proc.stdout
    assert "eslint" in proc.stdout
    assert "markdownlint" in proc.stdout
    assert "taplo" in proc.stdout
    assert "yamllint" in proc.stdout


def test_cli_path_ruff() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "sarj_lint_configs", "path", "ruff"],
        capture_output=True, text=True, check=True,
    )
    assert proc.stdout.strip() == str(RUFF_STRICT)


def test_cli_sync_writes_files(tmp_path: Path) -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "sarj_lint_configs", "sync", "--dest", str(tmp_path)],
        capture_output=True, text=True, check=True,
    )
    assert (tmp_path / ".ruff-strict.toml").is_file()
    assert (tmp_path / ".pyright-strict.json").is_file()
    assert (tmp_path / "eslint.strict.mjs").is_file()
    assert (tmp_path / ".markdownlint.yaml").is_file()
    assert (tmp_path / ".taplo.toml").is_file()
    assert (tmp_path / ".yamllint.yaml").is_file()
    assert "synced 6/6" in proc.stdout


def test_cli_sync_skips_existing_without_force(tmp_path: Path) -> None:
    (tmp_path / ".ruff-strict.toml").write_text("pre-existing")
    proc = subprocess.run(
        [sys.executable, "-m", "sarj_lint_configs", "sync",
         "--only", "ruff", "--dest", str(tmp_path)],
        capture_output=True, text=True, check=True,
    )
    assert "skip" in proc.stdout
    assert (tmp_path / ".ruff-strict.toml").read_text() == "pre-existing"


def test_cli_sync_force_overwrites(tmp_path: Path) -> None:
    (tmp_path / ".ruff-strict.toml").write_text("pre-existing")
    subprocess.run(
        [sys.executable, "-m", "sarj_lint_configs", "sync",
         "--only", "ruff", "--force", "--dest", str(tmp_path)],
        check=True,
    )
    assert (tmp_path / ".ruff-strict.toml").read_text() != "pre-existing"


def test_cli_sync_only_ruff(tmp_path: Path) -> None:
    subprocess.run(
        [sys.executable, "-m", "sarj_lint_configs", "sync",
         "--only", "ruff", "--dest", str(tmp_path)],
        check=True,
    )
    assert (tmp_path / ".ruff-strict.toml").is_file()
    assert not (tmp_path / ".pyright-strict.json").exists()
    assert not (tmp_path / "eslint.strict.mjs").exists()


def test_cli_unknown_subcommand_exits_nonzero(tmp_path: Path) -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "sarj_lint_configs", "bogus"],
        capture_output=True, text=True, cwd=tmp_path, check=False,
    )
    assert proc.returncode != 0


def test_synced_ruff_parses_as_toml(tmp_path: Path) -> None:
    subprocess.run(
        [sys.executable, "-m", "sarj_lint_configs", "sync",
         "--only", "ruff", "--dest", str(tmp_path)],
        check=True,
    )
    tomllib.loads((tmp_path / ".ruff-strict.toml").read_text())


def test_sync_to_nonexistent_dest_errors(tmp_path: Path) -> None:
    bogus = tmp_path / "does-not-exist"
    proc = subprocess.run(
        [sys.executable, "-m", "sarj_lint_configs", "sync", "--dest", str(bogus)],
        capture_output=True, text=True, check=False,
    )
    assert proc.returncode != 0


def test_ruff_consumes_synced_extend_file(tmp_path: Path) -> None:
    pytest.importorskip("ruff", reason="ruff not installed in this env")
    subprocess.run(
        [sys.executable, "-m", "sarj_lint_configs", "sync",
         "--only", "ruff", "--dest", str(tmp_path)],
        check=True,
    )
    (tmp_path / "pyproject.toml").write_text(
        '[tool.ruff]\nextend = ".ruff-strict.toml"\n'
    )
    (tmp_path / "ok.py").write_text("x = 1\n")
    proc = subprocess.run(
        ["ruff", "check", "--no-cache", str(tmp_path / "ok.py")],
        capture_output=True, text=True, cwd=tmp_path, check=False,
    )
    assert "error reading config" not in proc.stderr.lower()
    assert "could not resolve" not in proc.stderr.lower()
