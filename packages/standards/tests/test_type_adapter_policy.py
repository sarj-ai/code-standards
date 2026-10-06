from __future__ import annotations

import subprocess
import sys
from typing import TYPE_CHECKING

import pytest

from sarj_standards._meta import RUFF_APPLICATION, RUFF_STRICT


if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("config", [RUFF_STRICT, RUFF_APPLICATION], ids=["strict", "application"])
@pytest.mark.parametrize(
    "source",
    [
        "from pydantic import TypeAdapter\nvalue = TypeAdapter(str).validate_python(raw)\n",
        "from pydantic import TypeAdapter as Adapter\nvalue = Adapter[datetime | None](datetime | None)\n",
        "import pydantic\nvalue = pydantic.TypeAdapter(list[CallId])\n",
        "import pydantic as pd\nvalue = pd.TypeAdapter(UnionModel).json_schema()\n",
        "from pydantic.type_adapter import TypeAdapter as Adapter\nvalue = Adapter(Model)\n",
        "import pydantic.type_adapter as adapters\nvalue = adapters.TypeAdapter(dict[str, str])\n",
        "from pydantic import TypeAdapter\nvalue: TypeAdapter[int]\n",
    ],
    ids=["scalar", "generic-alias", "collection", "module-alias", "submodule-import", "submodule-alias", "annotation"],
)
def test_type_adapter_is_banned(config: Path, source: str, tmp_path: Path) -> None:
    probe = tmp_path / "validation.py"
    probe.write_text(source)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--no-cache",
            "--select",
            "TID251",
            "--config",
            str(config),
            str(probe),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "Define a named Pydantic BaseModel or RootModel" in result.stdout
    assert "Found 1 error" in result.stdout


@pytest.mark.parametrize("config", [RUFF_STRICT, RUFF_APPLICATION], ids=["strict", "application"])
@pytest.mark.parametrize(
    "source",
    [
        "from pydantic import BaseModel\nclass PendingScheduleRow(BaseModel):\n    scheduled_at: datetime | None\n",
        "from pydantic import RootModel\nclass ContactIds(RootModel[list[str]]):\n    pass\n",
        "from psycopg.rows import class_row\nfactory = class_row(PendingScheduleRow)\n",
        "from elsewhere import TypeAdapter\nvalue = TypeAdapter(schema)\n",
        "# pydantic.TypeAdapter(str)\nexample = 'from pydantic import TypeAdapter'\n",
        "from pydantic import TypeAdapter  # noqa: TID251 -- dynamically supplied framework schemas require an adapter.\nvalue = TypeAdapter(runtime_schema)\n",
        "import pydantic\nvalue = pydantic.TypeAdapter(runtime_schema)  # noqa: TID251 -- dynamically supplied framework schemas require an adapter.\n",
    ],
    ids=["named-row", "named-root", "class-row", "unrelated", "comment-string", "import-escape", "call-escape"],
)
def test_named_models_and_reasoned_exceptions_are_allowed(config: Path, source: str, tmp_path: Path) -> None:
    probe = tmp_path / "validation.py"
    probe.write_text(source)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--no-cache",
            "--select",
            "TID251",
            "--config",
            str(config),
            str(probe),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
