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


@pytest.mark.parametrize(
    ("failure", "expected", "output_lines"),
    [
        ("", 0, 0),
        ("", 0, 1),
        ("", 0, 50),
        ("", 0, 51),
        ("", 0, 20000),
        ("git", 7, 1),
        ("registry", 7, 1),
        ("check", 9, 0),
        ("check", 9, 1),
        ("check", 9, 51),
        ("check", 9, 20000),
        ("check", 37, 20000),
        ("check", 141, 20000),
    ],
)
def test_python_dogfood_keeps_literal_paths_and_rejects_partial_inventory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
    expected: int,
    output_lines: int,
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
        "for number in range(int(os.environ['OUTPUT_LINES'])):\n"
        "    print(f'native diagnostic {number}', file=sys.stderr if number % 2 else sys.stdout, flush=True)\n"
        "sys.exit(int(os.environ['CHECK_STATUS']) if os.environ['FAILURE'] == 'check' else 0)\n",
        encoding="utf-8",
    )
    uv.chmod(0o755)
    monkeypatch.setenv("PATH", str(tools), prepend=os.pathsep)
    monkeypatch.setenv("FAILURE", failure)
    monkeypatch.setenv("OUTPUT_LINES", str(output_lines))
    monkeypatch.setenv("CHECK_STATUS", str(expected))
    result = subprocess.run(
        ("bash", str(_SCRIPTS / "make-dogfood-python.sh"), "2"),
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == expected
    assert not result.stderr
    arguments = tmp_path / "arguments.json"
    if failure in {"git", "registry"}:
        assert not arguments.exists()
    else:
        argv = parse_json(arguments.read_text(encoding="utf-8"))
        assert is_object_list(argv)
        assert list(argv[-6:]) == ["--rule", "first-rule", "--rule", "second-rule", "--", source]
        assert list(argv[argv.index("--jobs") + 1 : argv.index("--jobs") + 2]) == ["2"]
        diagnostics = [f"native diagnostic {number}" for number in range(output_lines)]
        if failure:
            assert result.stdout == "\n".join(diagnostics) + "\n"
        else:
            displayed = diagnostics[:50]
            if output_lines > 50:
                displayed.append(
                    f"dogfood: {output_lines - 50} additional output lines omitted; "
                    "run sarj-python-lint check directly for full output"
                )
            displayed.append("dogfood: 2 Python rules, 1 source files, 0 blocking diagnostics")
            assert result.stdout == "\n".join(displayed) + "\n"


@pytest.mark.parametrize("directory_argument", [False, True])
def test_tsconfig_json_control_rejects_malformed_second_document(tmp_path: Path, *, directory_argument: bool) -> None:
    (tmp_path / "base.json").write_text("{}", encoding="utf-8")
    (tmp_path / "strict.json").write_text("{invalid", encoding="utf-8")
    argv = ("node", str(_SCRIPTS / "ci-validate-tsconfig.mts"), *((str(tmp_path),) if directory_argument else ()))
    result = subprocess.run(argv, cwd=tmp_path, capture_output=True, check=False, timeout=10)
    assert result.returncode != 0
