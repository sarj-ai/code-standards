from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from sarj_standards.libs.json_boundary import parse_json
from sarj_standards.libs.typed_containers import is_object_list


_SCRIPTS = Path(__file__).resolve().parents[3] / ".github/scripts"


@pytest.mark.parametrize(("failure", "expected"), [("", 0), ("git", 7), ("registry", 7), ("check", 9)])
def test_python_dogfood_keeps_literal_paths_and_rejects_partial_inventory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str, expected: int
) -> None:
    source = "packages/python/src/with space\nand newline.py"
    path = tmp_path / source
    path.parent.mkdir(parents=True)
    path.write_text("pass\n", encoding="utf-8")
    tools = tmp_path / "tools"
    tools.mkdir()
    git = tools / "git"
    git.write_text(
        f"#!{sys.executable}\nimport os, sys\nsys.stdout.write({json.dumps(source + chr(0))})\n"
        "sys.exit(7 if os.environ['FAILURE'] == 'git' else 0)\n",
        encoding="utf-8",
    )
    git.chmod(0o755)
    uv = tools / "uv"
    uv.write_text(
        f"#!{sys.executable}\nimport json, os, sys\nfrom pathlib import Path\n"
        "if sys.argv[-1] == 'list-rules':\n"
        "    print('SARJ001 first-rule\\nSARJ002 second-rule')\n"
        "    sys.exit(7 if os.environ['FAILURE'] == 'registry' else 0)\n"
        "Path('arguments.json').write_text(json.dumps(sys.argv[1:]))\n"
        "print('native diagnostic')\n"
        "sys.exit(9 if os.environ['FAILURE'] == 'check' else 0)\n",
        encoding="utf-8",
    )
    uv.chmod(0o755)
    monkeypatch.setenv("PATH", str(tools), prepend=os.pathsep)
    monkeypatch.setenv("FAILURE", failure)
    result = subprocess.run(
        ("bash", str(_SCRIPTS / "make-dogfood-python.sh")),
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == expected
    arguments = tmp_path / "arguments.json"
    if failure in {"git", "registry"}:
        assert not arguments.exists()
    else:
        argv = parse_json(arguments.read_text(encoding="utf-8"))
        assert is_object_list(argv)
        assert list(argv[-6:]) == ["--rule", "first-rule", "--rule", "second-rule", "--", source]
        assert "native diagnostic" in result.stdout
        assert ("0 blocking diagnostics" in result.stdout) is (not failure)


@pytest.mark.parametrize("directory_argument", [False, True])
def test_tsconfig_json_control_rejects_malformed_second_document(tmp_path: Path, *, directory_argument: bool) -> None:
    (tmp_path / "base.json").write_text("{}", encoding="utf-8")
    (tmp_path / "strict.json").write_text("{invalid", encoding="utf-8")
    argv = ("node", str(_SCRIPTS / "ci-validate-tsconfig.mjs"), *((str(tmp_path),) if directory_argument else ()))
    result = subprocess.run(argv, cwd=tmp_path, capture_output=True, check=False, timeout=10)
    assert result.returncode != 0
