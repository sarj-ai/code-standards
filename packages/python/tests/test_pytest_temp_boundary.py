from __future__ import annotations

import getpass
import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.parametrize("marker_kind", ["directory", "file"])
@pytest.mark.parametrize(
    ("tmp_root", "basetemp", "debug_root", "blocked"),
    [
        ("bad", None, None, True),
        ("good", None, None, False),
        ("bad", "good", None, False),
        ("good", "bad", None, True),
        ("good", None, "bad", True),
        ("bad", None, "good", False),
        ("bad-user", None, None, True),
    ],
)
def test_native_pytest_rejects_git_temp_ancestry_before_collection(
    tmp_path: Path,
    *,
    marker_kind: str,
    tmp_root: str,
    basetemp: str | None,
    debug_root: str | None,
    blocked: bool,
) -> None:
    roots = {name: tmp_path / name for name in ("good", "bad", "bad-user")}
    for root in roots.values():
        root.mkdir()
    user_root = roots["bad-user"] / f"pytest-of-{getpass.getuser()}"
    user_root.mkdir()
    unrelated = roots["good"] / "unrelated"
    unrelated.mkdir()
    for root in (roots["bad"], user_root, unrelated):
        marker = root / ".git"
        if marker_kind == "directory":
            marker.mkdir()
        else:
            marker.write_text("gitdir: unused\n")
    probe = tmp_path / "test_probe.py"
    collected = tmp_path / "collected"
    probe.write_text(
        "from pathlib import Path\n"
        "from sarj_python_lint.rules._first_party import project_root\n"
        f"Path({str(collected)!r}).write_text('collected')\n"
        "def test_native_root(tmp_path):\n"
        "    (tmp_path / 'pyproject.toml').write_text('[project]\\nname=\"sample\"\\nversion=\"0.0.0\"\\n')\n"
        "    source = tmp_path / 'sample.py'\n"
        "    source.write_text('value = 1\\n')\n"
        "    assert project_root(source) == tmp_path\n"
    )
    environment = os.environ.copy()  # ruff: ignore[banned-api] -- preserve the native pytest subprocess environment.
    environment.update({"TMPDIR": str(roots[tmp_root]), "PYTHONPATH": str(Path(__file__).parent)})
    environment.pop("PYTEST_ADDOPTS", None)
    environment.pop("PYTEST_DEBUG_TEMPROOT", None)
    if debug_root is not None:
        environment["PYTEST_DEBUG_TEMPROOT"] = str(roots[debug_root])
    command = [sys.executable, "-m", "pytest", "--noconftest", "-p", "conftest", "-q", str(probe)]
    if basetemp is not None:
        command.extend(["--basetemp", str(roots[basetemp] / "explicit")])
    result = subprocess.run(
        command,
        cwd=Path(__file__).parents[1],
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == (4 if blocked else 0), result.stdout + result.stderr
    assert collected.exists() is not blocked
    if blocked:
        assert "temporary directory outside Git" in result.stderr
        assert "TMPDIR or --basetemp" in result.stderr
