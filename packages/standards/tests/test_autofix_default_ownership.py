from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from sarj_standards import api
from sarj_standards.libs.adoption import lifecycle, manifest
from sarj_standards.libs.linting import autofix, runner


if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path


@pytest.mark.parametrize(
    ("name", "contents"),
    [
        ("large.ts", b"// " + b"x" * 2_097_152),
        ("large.yml", b"# " + b"x" * 2_097_152),
        ("legacy.py", b"\xff\xfe"),
        ("legacy.py", b"# ========\nvalue = 1\n"),
    ],
    ids=("large-typescript", "large-yaml", "undecodable-python", "unowned-python"),
)
def test_default_eslint_ownership_precedes_native_discovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str, contents: bytes
) -> None:
    (tmp_path / "owned.ts").write_text("export const owned = 1;\n")
    (tmp_path / "package.json").write_text('{"name":"example","private":true}\n')
    _adopt(tmp_path, configs=("eslint",), python_dest=".")
    path = tmp_path / name
    path.write_bytes(contents)
    commands = _capture_commands(monkeypatch)

    assert api.Standards(tmp_path).fix().ok
    assert commands
    assert path.read_bytes() == contents


def test_default_owned_backend_preserves_all_native_engines(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    backend = tmp_path / "backend"
    backend.mkdir()
    (backend / "pyproject.toml").write_text('[project]\nname = "example"\nversion = "0.0.0"\n')
    (tmp_path / "package.json").write_text('{"name":"example","private":true}\n')
    _adopt(tmp_path, configs=("ruff", "eslint"), python_dest="backend")
    sources = _write_native_sources(tmp_path, python_name="backend/source.py")
    unowned = tmp_path / "unowned.py"
    unowned.write_bytes(b"\xff\xfe")
    commands = _capture_commands(monkeypatch)

    assert api.Standards(tmp_path).fix().ok
    assert commands
    _assert_native_sources_fixed(sources)
    assert unowned.read_bytes() == b"\xff\xfe"


def test_explicit_selection_preserves_all_native_engines(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sources = _write_native_sources(tmp_path, python_name="source.py")
    commands = _capture_commands(monkeypatch)

    assert api.Standards(tmp_path).fix([path.name for path in sources]).ok
    assert commands
    _assert_native_sources_fixed(sources)


def test_explicit_legacy_python_does_not_require_project_detection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "legacy.py"
    path.write_bytes(b"# ========\r\nvalue = 1\r\n")
    _capture_commands(monkeypatch)

    assert api.Standards(tmp_path).fix([path.name]).ok
    assert path.read_bytes() == b"\r\nvalue = 1\r\n"


@pytest.mark.parametrize("entry", ["facade", "dispatcher"])
def test_explicit_empty_fix_never_becomes_repository_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, entry: str
) -> None:
    path = tmp_path / "source.py"
    original = b"# ========\nvalue = 1\n"
    path.write_bytes(original)
    commands = _capture_commands(monkeypatch)

    if entry == "facade":
        assert api.Standards(tmp_path).fix([]).ok
    else:
        result = autofix.run(tmp_path, [], default_scope=False)
        assert result.status == 0
        assert result.changed == ()
    assert path.read_bytes() == original
    assert commands == []


def test_explicit_directory_selection_keeps_unselected_sources(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    selected = tmp_path / "selected"
    selected.mkdir()
    path = selected / "source.py"
    other = tmp_path / "other.py"
    original = b"# ========\nvalue = 1\n"
    path.write_bytes(original)
    other.write_bytes(original)
    _capture_commands(monkeypatch)

    assert api.Standards(tmp_path).fix([selected.name]).ok
    assert path.read_bytes() == b"\nvalue = 1\n"
    assert other.read_bytes() == original


@pytest.mark.parametrize("name", ["large.ts", "large.yml"])
def test_check_discovery_keeps_its_existing_size_guard(tmp_path: Path, name: str) -> None:
    path = tmp_path / name
    path.write_bytes(b"# " + b"x" * 2_097_152)

    with pytest.raises(ValueError, match="analysis limit"):
        runner.group_paths([str(path)])


def _adopt(root: Path, *, configs: tuple[str, ...], python_dest: str) -> None:
    adopted = manifest.Manifest(api.__version__, configs, python_dest, ".")
    (root / ".sarj-standards.toml").write_text(adopted.render())


def _write_native_sources(root: Path, *, python_name: str) -> dict[Path, bytes]:
    samples = {
        python_name: b"# ========\r\nvalue = 1\r\n",
        "migration.sql": b"-- ========\r\nSELECT 1;\r\n",
        "main.tf": b'# ========\r\nlocals { value = "safe" }\r\n',
        "config.toml": b"# Retry count is 3\r\nretry_count = 3\r\n",
    }
    sources: dict[Path, bytes] = {}
    for name, contents in samples.items():
        path = root / name
        path.write_bytes(contents)
        path.chmod(0o750)
        sources[path] = contents
    return sources


def _assert_native_sources_fixed(sources: dict[Path, bytes]) -> None:
    for path, original in sources.items():
        fixed = path.read_bytes()
        assert fixed != original
        assert b"========" not in fixed
        assert b"Retry count" not in fixed
        assert b"\r\n" in fixed
        assert path.stat().st_mode & 0o777 == 0o750


def _capture_commands(monkeypatch: pytest.MonkeyPatch) -> list[lifecycle.Command]:
    commands: list[lifecycle.Command] = []

    def execute(selected: Sequence[lifecycle.Command]) -> int:
        commands.extend(selected)
        return 0

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- Intercepts the real external dispatch; native file APIs stay genuine.
        lifecycle, "execute", execute
    )
    return commands
