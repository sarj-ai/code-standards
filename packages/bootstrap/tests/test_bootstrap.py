from __future__ import annotations

import os
import shutil
import subprocess
import sys
from typing import TYPE_CHECKING

import pytest

from sarj_standards_bootstrap import cli as bootstrap


if TYPE_CHECKING:
    from pathlib import Path


def _manifest(root: Path, *, schema: object = 3, bundle: object = "5.16.5") -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / bootstrap.MANIFEST_NAME).write_text(
        f"schema = {schema!r}\nbundle = {bundle!r}\n".replace("'", '"'),
        encoding="utf-8",
    )


def test_finds_nearest_manifest_from_nested_directory(tmp_path: Path) -> None:
    _manifest(tmp_path, bundle="1.2.3")
    nested = tmp_path / "one" / "two"
    nested.mkdir(parents=True)

    assert bootstrap.find_root(nested) == tmp_path


def test_explicit_root_is_removed_from_forwarded_arguments(tmp_path: Path) -> None:
    parsed = bootstrap.explicit_root(("check", "--root", "repo", "file.py"), cwd=tmp_path)

    assert parsed.root == tmp_path / "repo"
    assert parsed.forwarded == ("check", "file.py")


@pytest.mark.parametrize(
    "arguments",
    [("--root", "one", "--root=two"), ("--root",)],
    ids=["duplicate", "missing-value"],
)
def test_rejects_invalid_explicit_root(arguments: tuple[str, ...], tmp_path: Path) -> None:
    with pytest.raises(bootstrap.BootstrapError):
        bootstrap.explicit_root(arguments, cwd=tmp_path)


def test_missing_manifest_is_concise(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    assert bootstrap.main(("check",)) == 2

    assert bootstrap.MANIFEST_NAME in capsys.readouterr().err


@pytest.mark.parametrize(
    ("contents", "message"),
    [
        ("not toml = [", "not valid TOML"),
        ('schema = 2\nbundle = "1.2.3"\n', "schema must equal 3"),
        ('schema = 3\nbundle = "latest"\n', "exact canonical X.Y.Z"),
        ('schema = 3\nbundle = "01.2.3"\n', "exact canonical X.Y.Z"),
        ("schema = 3\nbundle = 123\n", "exact canonical X.Y.Z"),
    ],
)
def test_rejects_invalid_manifest(tmp_path: Path, contents: str, message: str) -> None:
    (tmp_path / bootstrap.MANIFEST_NAME).write_text(contents, encoding="utf-8")

    with pytest.raises(bootstrap.BootstrapError, match=message):
        bootstrap.bundle(tmp_path)


def test_execs_exact_bundle_and_preserves_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _manifest(tmp_path, bundle="5.16.5")
    nested = tmp_path / "nested"
    nested.mkdir()
    monkeypatch.setenv("UV_OFFLINE", "1")
    monkeypatch.setenv("UV_INDEX_URL", "https://packages.example/simple")
    monkeypatch.setenv("SSL_CERT_FILE", "/certificates/enterprise.pem")

    def fake_which(_name: str) -> str:
        return "/tools/uvx"

    monkeypatch.setattr(shutil, "which", fake_which)
    captured: dict[str, object] = {}

    def fake_execute(arguments: tuple[str, ...], environment: dict[str, str]) -> None:
        captured.update(arguments=arguments, environment=environment)
        message = "exec sentinel"
        raise RuntimeError(message)

    monkeypatch.setattr(bootstrap, "execute", fake_execute)

    with pytest.raises(RuntimeError, match="exec sentinel"):
        bootstrap.run(("check", "src"), cwd=nested)

    assert captured["arguments"] == (
        "/tools/uvx",
        "--no-config",
        "--isolated",
        "--python",
        "3.14",
        "--from",
        "code-standards==5.16.5",
        "code-standards",
        "--root",
        str(tmp_path),
        "check",
        "src",
    )
    captured_environment = captured["environment"]
    assert isinstance(captured_environment, dict)
    assert captured_environment["UV_OFFLINE"] == "1"
    assert captured_environment["UV_INDEX_URL"] == "https://packages.example/simple"
    assert captured_environment["SSL_CERT_FILE"] == "/certificates/enterprise.pem"


def test_windows_waits_for_standards_and_forwards_its_exit_code(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_run(
        arguments: tuple[str, ...],
        *,
        env: dict[str, str],
        check: bool,
        shell: bool,
    ) -> subprocess.CompletedProcess[str]:
        captured.update(arguments=arguments, environment=env, check=check, shell=shell)
        return subprocess.CompletedProcess(arguments, 17)

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(SystemExit) as raised:
        bootstrap.execute(("C:/tools/uvx.exe", "check"), {"UV_OFFLINE": "1"}, platform="nt")

    assert raised.value.code == 17
    assert captured == {
        "arguments": ("C:/tools/uvx.exe", "check"),
        "environment": {"UV_OFFLINE": "1"},
        "check": False,
        "shell": False,
    }


@pytest.fixture
def fake_uvx(tmp_path: Path) -> Path:
    if os.name == "nt":
        executable = tmp_path / "uvx.cmd"
        executable.write_text("@echo off\r\necho cwd=%CD%\r\necho args=%*\r\nexit /b 7\r\n", encoding="utf-8")
    else:
        executable = tmp_path / "uvx"
        executable.write_text(
            "#!/bin/sh\nprintf 'cwd=%s\\n' \"$PWD\"\nprintf 'args=%s\\n' \"$*\"\nexit 7\n",
            encoding="utf-8",
        )
        executable.chmod(0o755)
    return executable


def test_fake_uvx_receives_arguments_and_owns_exit_status(tmp_path: Path, fake_uvx: Path) -> None:
    repo = tmp_path / "repo"
    _manifest(repo, bundle="9.8.7")
    nested = repo / "nested"
    nested.mkdir()
    environment = os.environ.copy()  # ruff: ignore[banned-api] — preserve the test runner's Python path.
    environment["PATH"] = f"{fake_uvx.parent}{os.pathsep}{environment['PATH']}"
    completed = subprocess.run(
        [sys.executable, "-c", "import sarj_standards_bootstrap as b; b.main(['check'])"],
        cwd=nested,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 7
    assert f"cwd={nested}" in completed.stdout
    assert "--from code-standards==9.8.7 code-standards" in completed.stdout
    assert f"--root {repo} check" in completed.stdout
