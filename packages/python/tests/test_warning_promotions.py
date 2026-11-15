from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sarj_rule_contracts import RuleId

from sarj_python_lint.__main__ import main


if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize(
    ("rule_id", "code", "source", "status"),
    [
        pytest.param(
            RuleId("prefer-optional-composite"),
            "SARJ541",
            "from dataclasses import dataclass\n@dataclass\nclass State:\n"
            "    version_id: str | None\n    version_number: int | None\n",
            1,
            id="optional-composite-blocks",
        ),
        pytest.param(
            RuleId("prefer-optional-composite"),
            "SARJ541",
            "from dataclasses import dataclass\n@dataclass\nclass State:\n"
            "    version_id: str | None  # sarj-noqa: SARJ541 -- Preserve the established wire schema.\n"
            "    version_number: int | None\n",
            0,
            id="optional-composite-reviewed-exception",
        ),
        pytest.param(
            RuleId("no-custom-control-flow-exception"),
            "SARJ542",
            "class Rejected(ValueError):\n    pass\n"
            "def read(known: bool) -> str:\n    if not known:\n        raise Rejected\n    return 'value'\n",
            1,
            id="exception-contract-blocks",
        ),
        pytest.param(
            RuleId("no-custom-control-flow-exception"),
            "SARJ542",
            "class Rejected(ValueError):  # sarj-noqa: SARJ542 -- Preserve the public exception protocol.\n"
            "    pass\n"
            "def read(known: bool) -> str:\n    if not known:\n        raise Rejected\n    return 'value'\n",
            0,
            id="exception-contract-reviewed-exception",
        ),
        pytest.param(
            RuleId("no-custom-control-flow-exception"),
            "SARJ542",
            "from pydantic import BaseModel, field_validator\n"
            "class Rejected(ValueError):\n    pass\n"
            "class Record(BaseModel):\n    value: str\n"
            "    @field_validator('value')\n    @classmethod\n"
            "    def validate(cls, value: str) -> str:\n"
            "        if not value:\n            raise Rejected\n        return value\n",
            0,
            id="validator-rejection-protocol-remains-valid",
        ),
    ],
)
def test_native_cli_enforces_promotions_and_preserves_reviewed_contracts(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    *,
    rule_id: RuleId,
    code: str,
    source: str,
    status: int,
) -> None:
    path = tmp_path / "model.py"
    path.write_text(source, encoding="utf-8")

    assert main(["check", "--rule", rule_id, str(path)]) == status

    output = capsys.readouterr().out
    assert (code in output) is (status == 1)
    assert "warning:" not in output
