from __future__ import annotations

from pathlib import Path
import subprocess
import sys

import pytest


_ADAPTER = Path(__file__).resolve().parents[3] / ".github/scripts/make-local-check.sh"


@pytest.mark.parametrize("installed", [False, True])
@pytest.mark.parametrize(
    ("make_flags", "planning"),
    [
        pytest.param("", False, id="normal"),
        pytest.param("--warn-undefined-variables -rn -- TEST_JOBS=2", True, id="dry-run"),
        pytest.param("nr --warn-undefined-variables", True, id="leading-short-flags"),
        pytest.param("--warn-undefined-variables -tr", True, id="touch"),
        pytest.param("--warn-undefined-variables -rq", True, id="question"),
        pytest.param("--warn-undefined-variables -rI ntq", False, id="include-operand"),
        pytest.param("-rI with\\ space\\ -n", False, id="escaped-include-operand"),
        pytest.param("--include-dir -n", False, id="long-option-operand"),
        pytest.param("-r -- PYTEST_ARGS=-k ntq", False, id="variable-operand"),
    ],
)
def test_admission_adapter_executes_literal_arguments_and_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, installed: bool, make_flags: str, planning: bool
) -> None:
    tools = tmp_path / "tools"
    tools.mkdir()
    command = tools / "command with space"
    command.write_text(
        f"#!{sys.executable}\nimport os, sys\nprint(os.getpid())\nprint(repr(sys.argv[1:]))\nsys.exit(23)\n",
        encoding="utf-8",
    )
    command.chmod(0o755)
    if installed:
        helper = tools / "sarj-local-check"
        helper.write_text(
            f"#!{sys.executable}\nimport os, sys\nprint('admitted', flush=True)\nos.execv(sys.argv[1], sys.argv[1:])\n",
            encoding="utf-8",
        )
        helper.chmod(0o755)
    arguments = ("literal space", "*", "--", "line\nbreak")
    monkeypatch.setenv("PATH", f"{tools}:/usr/bin:/bin")
    monkeypatch.setenv("MAKEFLAGS", make_flags)
    with subprocess.Popen(
        ("bash", str(_ADAPTER), str(command), *arguments),
        cwd=tmp_path,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ) as process:
        try:
            stdout, stderr = process.communicate(timeout=10)
        except BaseException:
            process.kill()
            process.communicate()
            raise
    assert process.returncode == 23
    assert not stderr
    prefix = "admitted\n" if installed and not planning else ""
    assert stdout == f"{prefix}{process.pid}\n{list(arguments)!r}\n"
