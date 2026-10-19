from __future__ import annotations

import subprocess
import sys
from typing import TYPE_CHECKING

import pytest


if TYPE_CHECKING:
    from pathlib import Path


_DEFINITIONS = (
    "from dataclasses import asdict, dataclass\n"
    "from typing import ClassVar, Final, Literal, TypeAliasType, assert_type\n"
    "@dataclass\nclass Team:\n    scope: Literal['team']\n    team_id: str\n"
    "@dataclass\nclass Global:\n    scope: Literal['global']\n    group: str\n"
    "type Access = Team | Global\n"
)
_NARROWING = (
    "def identify(access: Access) -> str:\n"
    "    if access.scope == 'team':\n"
    "        assert_type(access, Team)\n        return access.team_id\n"
    "    assert_type(access, Global)\n    return access.group\n"
)
_EXPLICIT_CONSTRUCTORS = (
    "assert identify(Team('team', 't')) == 't'\n"
    "assert identify(Global('global', 'g')) == 'g'\n"
    "assert asdict(Team('team', 't')) == {'scope': 'team', 'team_id': 't'}\n"
)
_FINAL_DEFINITIONS = (
    _DEFINITIONS.replace("scope: Literal['team']", "scope: Final[Literal['team']] = 'team'")
    .replace("scope: Literal['global']", "scope: Final[Literal['global']] = 'global'")
    .replace("team_id: str", "team_id: str = 't'")
    .replace("group: str", "group: str = 'g'")
)


@pytest.mark.parametrize(
    "source",
    [
        _DEFINITIONS.replace(
            "@dataclass\nclass Team:",
            "TeamScope = TypeAliasType('TeamScope', Literal['team'])\n@dataclass\nclass Team:",
        ).replace("scope: Literal['team']", "scope: TeamScope")
        + _NARROWING
        + _EXPLICIT_CONSTRUCTORS,
        _FINAL_DEFINITIONS
        + _NARROWING
        + "assert identify(Team()) == 't'\nassert identify(Global()) == 'g'\n"
        + "assert asdict(Team()) == {'scope': 'team', 'team_id': 't'}\n",
        _FINAL_DEFINITIONS.replace("Final[Literal['team']]", "ClassVar[Final[Literal['team']]]")
        .replace("Final[Literal['global']]", "ClassVar[Final[Literal['global']]]")
        .replace("team_id: str = 't'", "team_id: str")
        .replace("group: str = 'g'", "group: str")
        + _NARROWING
        + "assert identify(Team('t')) == 't'\nassert identify(Global('g')) == 'g'\n"
        + "assert asdict(Team('t')) == {'team_id': 't'}\n",
        (_DEFINITIONS + _NARROWING + _EXPLICIT_CONSTRUCTORS).replace("scope", "__kind__"),
    ],
    ids=("type-alias-type", "final-instance-tag", "final-class-variable-tag", "public-dunder-tag"),
)
def test_supported_tags_preserve_narrowing_and_runtime_contracts(source: str, tmp_path: Path) -> None:
    target = tmp_path / "access.py"
    target.write_text(source, encoding="utf-8")
    runtime = subprocess.run([sys.executable, str(target)], capture_output=True, text=True, check=False)
    assert runtime.returncode == 0, runtime.stderr
    config = tmp_path / "pyrightconfig.json"
    config.write_text('{"typeCheckingMode": "basic", "pythonVersion": "3.14"}', encoding="utf-8")
    compiler = subprocess.run(
        [sys.executable, "-m", "basedpyright", "--pythonpath", sys.executable, "--project", str(config), str(target)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert compiler.returncode == 0, compiler.stdout + compiler.stderr
