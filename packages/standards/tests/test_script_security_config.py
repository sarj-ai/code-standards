import subprocess
import sys
from typing import TYPE_CHECKING

import pytest

from sarj_standards._meta import RUFF_STRICT


if TYPE_CHECKING:
    from pathlib import Path


def test_all_rules_need_no_redundant_explicit_selections() -> None:
    selections: list[str] = []
    for extra in ([], ["--config", 'lint.extend-select=["ANN401","B904","UP045","ASYNC100","FBT001"]']):
        result = subprocess.run(
            [sys.executable, "-m", "ruff", "check", "--config", str(RUFF_STRICT), *extra, "--show-settings", __file__],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        enabled = result.stdout.partition("linter.rules.enabled = [\n")[2].partition("\n]")[0]
        assert enabled
        selections.append(enabled)
    assert selections[0] == selections[1]


@pytest.mark.parametrize(
    "filename", ["scripts/example.py", ".github/scripts/example.py", "package/scripts/example.py", "src/example.py"]
)
@pytest.mark.parametrize(
    ("source", "rule"),
    [
        ('import subprocess\nsubprocess.run("echo unsafe", shell=True)\n', "S602"),
        ('try:\n    int("bad")\nexcept Exception:\n    pass\n', "BLE001"),
        ('raise Exception("unspecified failure")\n', "TRY002"),
    ],
)
def test_scripts_enforce_source_security_policy(tmp_path: Path, filename: str, source: str, rule: str) -> None:
    config = tmp_path / "ruff.toml"
    config.write_text(RUFF_STRICT.read_text(encoding="utf-8"), encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--no-cache",
            "--config",
            str(config),
            "--select",
            rule,
            "--output-format",
            "json",
            "--stdin-filename",
            filename,
            "-",
        ],
        input=source,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert result.stdout.count(f'"code": "{rule}"') == 1


@pytest.mark.parametrize(
    ("source", "rules"),
    [
        ('print("CLI output")\n', "T201,INP001"),
        ('try:\n    int("bad")\nexcept Exception:\n    raise\n', "BLE001"),
        (
            'import logging\ntry:\n    int("bad")\nexcept Exception:\n    logging.exception("Failed")\n',
            "BLE001",
        ),
        ('raise ValueError("invalid value")\n', "TRY002"),
    ],
)
def test_scripts_allow_cli_output_and_specific_exception_handling(tmp_path: Path, source: str, rules: str) -> None:
    config = tmp_path / "ruff.toml"
    config.write_text(RUFF_STRICT.read_text(encoding="utf-8"), encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--no-cache",
            "--config",
            str(config),
            "--select",
            rules,
            "--stdin-filename",
            "scripts/example.py",
            "-",
        ],
        input=source,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
