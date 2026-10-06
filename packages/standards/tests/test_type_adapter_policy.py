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


@pytest.mark.parametrize("config", [RUFF_STRICT, RUFF_APPLICATION], ids=["strict", "application"])
@pytest.mark.parametrize(
    ("api", "remediation"),
    [
        ("yaml.unsafe_load", "Use safe_load/safe_load_all"),
        ("yaml.unsafe_load_all", "Use safe_load/safe_load_all"),
        ("asyncio.create_subprocess_shell", "Prefer create_subprocess_exec with separate arguments"),
        ("asyncio.subprocess.create_subprocess_shell", "Prefer create_subprocess_exec with separate arguments"),
        ("pydantic.parse_obj_as", "Define a named Pydantic BaseModel or RootModel"),
        ("pydantic.tools.parse_obj_as", "Define a named Pydantic BaseModel or RootModel"),
        ("pydantic.deprecated.tools.parse_obj_as", "Define a named Pydantic BaseModel or RootModel"),
        ("typing_extensions.cast", "Prefer discriminated unions or `isinstance` narrowing"),
    ],
)
@pytest.mark.parametrize(
    ("template", "expected_count"),
    [
        ("import {module}\nvalue = {api}(raw)\n", 1),
        ("import {module} as library\nvalue = library.{symbol}(raw)\n", 1),
        ("from {module} import {symbol}\nvalue = {symbol}(raw)\n", 1),
        ("from {module} import {symbol} as target\nvalue = target(raw)\n", 1),
        (
            (
                "import {module} as library\n"
                "value = library.{symbol}(raw)  # noqa: TID251 -- required external boundary.\n"
            ),
            0,
        ),
        (
            "from {module} import {symbol}  # noqa: TID251 -- required external boundary.\nvalue = {symbol}(raw)\n",
            0,
        ),
        ("from elsewhere import {symbol}\nvalue = {symbol}(raw)\n# {api}(raw)\nexample = '{api}'\n", 0),
        ("import {module} as library\ndef use(library, raw):\n    return library.{symbol}(raw)\n", 0),
    ],
    ids=[
        "qualified",
        "module-alias",
        "import",
        "import-alias",
        "call-escape",
        "import-escape",
        "unrelated-comment-string",
        "shadowed-module",
    ],
)
def test_verified_banned_api_paths(
    *, config: Path, api: str, remediation: str, template: str, expected_count: int, tmp_path: Path
) -> None:
    module, symbol = api.rsplit(".", 1)
    probe = tmp_path / "validation.py"
    probe.write_text(template.format(module=module, symbol=symbol, api=api))
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
    assert result.returncode == expected_count, result.stdout + result.stderr
    if expected_count:
        assert remediation in result.stdout
        assert "Found 1 error" in result.stdout


@pytest.mark.parametrize("config", [RUFF_STRICT, RUFF_APPLICATION], ids=["strict", "application"])
@pytest.mark.parametrize(
    "source",
    [
        "import yaml\nvalue = yaml.safe_load(raw)\nvalues = yaml.safe_load_all(raw)\n",
        "import asyncio\nvalue = asyncio.create_subprocess_exec(program, argument)\n",
        "from pydantic import BaseModel\nclass Input(BaseModel):\n    value: str\nresult = Input.model_validate(raw)\n",
        "import asyncio\nvalue = asyncio.ensure_future(awaitable)\nloop = asyncio.get_event_loop()\n",
        (
            "import asyncio.tasks\nimport asyncio.events\n"
            "value = asyncio.tasks.ensure_future(awaitable)\nloop = asyncio.events.get_event_loop()\n"
        ),
        "import io\nimport pprint\npprint.pp(value, stream=io.StringIO())\n",
        "from fastapi.datastructures import UploadFile\nvalue = UploadFile(file=downloaded_file)\n",
        (
            "import _pickle\nimport _datetime\n"
            "value = _pickle.loads(raw)\nloader = _pickle.Unpickler(stream)\nvalue = _pickle.load(stream)\n"
            "stamp = _datetime.datetime.utcnow()\n"
        ),
    ],
    ids=[
        "safe-yaml",
        "argv",
        "named-model",
        "asyncio",
        "asyncio-submodules",
        "formatting",
        "downloaded-file",
        "private-aliases",
    ],
)
def test_safe_alternatives_and_rejected_bans_remain_allowed(config: Path, source: str, tmp_path: Path) -> None:
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
