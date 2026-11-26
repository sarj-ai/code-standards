from pathlib import Path

import pytest
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze
from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules.require_total_enum_mapping import RequireTotalEnumMapping


_STATES = "from enum import StrEnum\nclass Status(StrEnum):\n    OPEN = 'open'\n    CLOSED = 'closed'\n"
_TABLE = "TABLE: dict[Status, str] = {Status.OPEN: 'open'}\n"


def test_documented_examples() -> None:
    verify_native_rule(RequireTotalEnumMapping, analyze)


def test_imported_invite_enum_and_literal_narrowing(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'example'\nversion = '0.1.0'\n")
    states = tmp_path / "states.py"
    states.write_text(_STATES + _TABLE + "from typing import Literal\ntype Automatic = Literal[Status.OPEN]\n")
    path = tmp_path / "service.py"
    path.write_text(
        "from states import Status as InviteStatus, Automatic, TABLE as SUPPORTED\n"
        "import states as source\n"
        "from typing import Final\n"
        "TABLE: Final[dict[InviteStatus, str]] = {source.Status.OPEN: 'added'}\n"
        "NARROW: Final[dict[Automatic, str]] = {InviteStatus.OPEN: 'add'}\n"
        "def lookup(status: InviteStatus) -> str:\n    return TABLE[status]\n"
        "def supported():\n    return SUPPORTED.items()\n"
    )
    [finding] = analyze([RequireTotalEnumMapping.id], [path, states])

    assert (finding.path, finding.line, finding.col, finding.severity) == (path, 4, 8, Severity.WARNING)
    assert "CLOSED" in finding.message
    assert "subscript read" in finding.message


@pytest.mark.parametrize(
    ("table", "indexed"),
    [
        pytest.param(
            "from types import MappingProxyType as freeze\n"
            "from collections.abc import Mapping as Lookup\n"
            "REFUSALS: Lookup[Status, str] = freeze({Status.OPEN: 'wait'})\n"
            "def refuse(reason: Status) -> str:\n    return REFUSALS[reason]\n",
            True,
            id="callback-refusal",
        ),
        pytest.param(
            "from typing import Final, Mapping\n"
            "MODEL_ORDER: Final[Mapping[Status, Mapping[str, tuple[str, ...]]]] = {Status.OPEN: {'fast': ('one',)}}\n"
            "def models(job: Status) -> tuple[str, ...]:\n    return MODEL_ORDER[job]['fast']\n",
            True,
            id="nested-model-order",
        ),
        pytest.param(
            "from collections.abc import Mapping\n"
            "COVERAGE: Mapping[Status, str] = {Status.OPEN: 'routine'}\n"
            "def labels(plan: list[Status]) -> list[str]:\n    return [COVERAGE[item] for item in plan]\n",
            True,
            id="coverage-comprehension-read",
        ),
        pytest.param(
            "from typing import Final\n"
            "ROLES: Final[dict[Status, str]] = {Status.OPEN: 'development'}\n"
            "class Service:\n"
            "    def __init__(self, environment: Status):\n"
            "        if environment not in ROLES:\n            raise ValueError('unsupported environment')\n"
            "        self.environment = environment\n"
            "    def role(self) -> str:\n        return ROLES[self.environment]\n",
            True,
            id="role-selection",
        ),
        pytest.param(
            "from collections import OrderedDict\n"
            "class Registry:\n    TABLE: OrderedDict[Status, str] = {Status.OPEN: 'open'}\n",
            False,
            id="class-table-without-local-read",
        ),
        pytest.param(
            "from typing import Literal\ntype Mode = Literal['open', 'CLOSED']\n"
            "TABLE: dict[Mode, str] = {'open': 'start'}\n",
            False,
            id="literal-alias",
        ),
    ],
)
def test_missing_declared_key(table: str, indexed: bool) -> None:
    [finding] = RequireTotalEnumMapping().check(Path("dispatch.py"), _STATES + table)

    assert "CLOSED" in finding.message
    assert ("subscript read" in finding.message) is indexed


@pytest.mark.parametrize(
    "table",
    [
        pytest.param("def build():\n    " + _TABLE, id="local-client-builder"),
        pytest.param(
            "def payload(force: bool):\n    carried: dict[Status, object | None] = {Status.OPEN: force}\n",
            id="local-partial-payload",
        ),
        pytest.param("TABLE: dict[Status, str | None] = {Status.OPEN: 'open', Status.CLOSED: None}\n", id="total"),
        pytest.param("TABLE: dict[Status, str] = {**other, Status.OPEN: 'open'}\n", id="spread"),
        pytest.param("TABLE: dict[Status, str] = {member: member.value for member in Status}\n", id="comprehension"),
        pytest.param("TABLE: dict[Status, str] = {Status('open'): 'open'}\n", id="computed-key"),
        pytest.param(
            "from collections import defaultdict\nTABLE: defaultdict[Status, str] = {Status.OPEN: 'open'}\n",
            id="defaultdict",
        ),
        pytest.param("dict = CustomMapping\n" + _TABLE, id="shadowed-mapping"),
        pytest.param("from elsewhere import Status\n" + _TABLE, id="rebound-enum"),
        pytest.param(_TABLE + "def lookup(key: Status):\n    return TABLE.get(key, 'fallback')\n", id="sparse-get"),
        pytest.param(
            _TABLE + "def lookup(key: Status):\n"
            "    if key not in {Status.OPEN}:\n        raise ValueError('unsupported')\n"
            "    return TABLE[key]\n",
            id="guarded-membership",
        ),
        pytest.param(
            _TABLE + "def lookup(key: Status):\n"
            "    match key:\n        case Status.OPEN:\n            return TABLE[key]\n"
            "        case Status.CLOSED:\n            return 'closed'\n",
            id="narrowed-match-case",
        ),
        pytest.param(_TABLE + "alias = TABLE\nalias.update({Status.CLOSED: 'closed'})\n", id="escaping-mutable-table"),
        pytest.param(
            "class Registry:\n    " + _TABLE + "Registry.TABLE[Status.CLOSED] = 'closed'\n", id="class-table-write"
        ),
        pytest.param("TABLE: dict[Status, str = {}\n", id="malformed"),
    ],
)
def test_tables_without_a_proven_total_contract(table: str) -> None:
    assert not RequireTotalEnumMapping().check(Path("dispatch.py"), _STATES + table)


@pytest.mark.parametrize(
    "mutation",
    [
        "TABLE[Status.CLOSED] = 'closed'",
        "TABLE.update({Status.CLOSED: 'closed'})",
        "TABLE.setdefault(Status.CLOSED, 'closed')",
        "TABLE |= {Status.CLOSED: 'closed'}",
        "TABLE.pop(Status.OPEN)",
        "del TABLE[Status.OPEN]",
    ],
)
def test_mutated_table(mutation: str) -> None:
    assert not RequireTotalEnumMapping().check(Path("dispatch.py"), _STATES + _TABLE + f"{mutation}\n")


@pytest.mark.parametrize(
    ("enum", "missing"),
    [
        pytest.param("Enum):\n    OPEN = auto()\n    CLOSED = auto()\n", True, id="auto-members"),
        pytest.param("IntEnum):\n    OPEN = 1\n    CLOSED = 1\n", False, id="member-alias"),
        pytest.param("Flag):\n    OPEN = 1\n    CLOSED = 2\n", False, id="flag"),
    ],
)
def test_enum_member_identity(enum: str, missing: bool) -> None:
    source = f"from enum import Enum, IntEnum, Flag, auto\nclass Status({enum}{_TABLE}"
    assert bool(RequireTotalEnumMapping().check(Path("dispatch.py"), source)) is missing


def test_native_suppression(tmp_path: Path) -> None:
    path = tmp_path / "dispatch.py"
    path.write_text(_STATES + _TABLE.rstrip() + "  # sarj-noqa: SARJ600 -- intentionally partial\n")

    assert not analyze([RequireTotalEnumMapping.id], [path])
