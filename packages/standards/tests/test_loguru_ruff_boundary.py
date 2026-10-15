from __future__ import annotations

from pathlib import Path
import subprocess
import sys

from pydantic import BaseModel, RootModel
import pytest


_CONFIG = Path(__file__).parents[1] / "src/sarj_standards/configs/ruff.strict.toml"


class RuffDiagnostic(BaseModel):
    code: str


class RuffReport(RootModel[list[RuffDiagnostic]]):
    pass


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ('from loguru import logger\nlogger.info("value {}", 1)\n', []),
        ('from loguru import logger as events\nevents.info("value {}", 1)\n', []),
        ('from loguru import logger\nlogger.exception("failed", exc_info=False)\n', []),
        (
            'from loguru import logger\ntry:\n    run()\nexcept ValueError:\n    logger.error("failed", exc_info=True)\n',
            [],
        ),
        ('import logging\nlogging.warning("value %s", 1, 2)\n', ["PLE1205"]),
        ('import logging\nlogging.exception("failed", exc_info=False)\n', ["LOG007"]),
        ('import logging\ntry:\n    run()\nexcept ValueError:\n    logging.error("failed", exc_info=True)\n', ["G201"]),
        ('import logging\ntry:\n    run()\nexcept ValueError:\n    logging.error("failed")\n', ["TRY400"]),
    ],
)
def test_logging_rules_respect_library_semantics(source: str, expected: list[str]) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--config",
            str(_CONFIG),
            "--select",
            "PLE1205,PLE1206,LOG007,TRY400,G201",
            "--output-format",
            "json",
            "--stdin-filename",
            "src/service.py",
            "-",
        ],
        input=source,
        text=True,
        capture_output=True,
        check=False,
    )
    assert not result.stderr
    diagnostics = RuffReport.model_validate_json(result.stdout)
    assert [diagnostic.code for diagnostic in diagnostics.root] == expected
    assert result.returncode == bool(expected)
