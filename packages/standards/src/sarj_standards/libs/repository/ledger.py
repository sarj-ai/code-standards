from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
import json
import re
from typing import TYPE_CHECKING, Final

from sarj_standards._meta import CONFIGS_DIR
from sarj_standards.libs.adoption.manifest import as_table, list_field, text_field


if TYPE_CHECKING:
    from collections.abc import Iterator


LEDGER_JSON: Final = CONFIGS_DIR / "rule-ledger.json"

#: The `kind` values that name an ESLint rule and a bare `SARJnnn` code; the rest
#: (`python`, `sql`, `iac`) are rule ids, which double as pre-commit hook ids.
ESLINT: Final = "eslint"
CODE: Final = "code"


class Status(StrEnum):
    """What became of a retired identifier."""

    REMOVED = "removed"
    RENAMED = "renamed"


@dataclass(frozen=True)
class Retired:
    id: str
    kind: str
    status: Status
    replacement: str | None
    note: str

    @property
    def pattern(self) -> re.Pattern[str]:
        """Match every spelling of this identifier a consumer repo can contain."""
        if self.kind == ESLINT:
            return re.compile(rf"(?<![\w/-]){re.escape(self.id)}(?![\w-])")
        if self.kind == CODE:
            return re.compile(rf"\b{re.escape(self.id)}\b")
        return re.compile(rf"(?<![\w-])(?:sarj-{re.escape(self.id)}|--rule[ =]{re.escape(self.id)})(?![\w-])")

    @property
    def advice(self) -> str:
        """Describe the fix in one line."""
        if self.status is Status.RENAMED and self.replacement is not None:
            return f"renamed to {self.replacement} -- {self.note}"
        return f"no longer exists -- {self.note}"


@dataclass(frozen=True)
class Ledger:
    rules: Mapping[str, tuple[str, ...]]
    codes: Mapping[str, tuple[str, ...]]
    retired: tuple[Retired, ...]

    def active_ids(self) -> frozenset[str]:
        live = {code for family in self.codes.values() for code in family}
        for family, names in self.rules.items():
            prefix = "@sarj/" if family == ESLINT else ""
            live.update(f"{prefix}{name}" for name in names)
        return frozenset(live)


def load() -> Ledger:
    parsed: object = json.loads(  # pyright: ignore[reportAny] -- json.loads is an untyped stdlib boundary; the shape is narrowed below
        LEDGER_JSON.read_text(encoding="utf-8")
    )
    data = as_table(parsed)
    return Ledger(
        rules=_families(data, "rules"),
        codes=_families(data, "codes"),
        retired=tuple(_retired(data)),
    )


def _families(data: Mapping[str, object], key: str) -> dict[str, tuple[str, ...]]:
    table = as_table(data.get(key))
    return {family: tuple(name for name in list_field(table, family) if isinstance(name, str)) for family in table}


def _retired(data: Mapping[str, object]) -> Iterator[Retired]:
    for entry in list_field(data, "retired"):
        row = as_table(entry)
        identifier = text_field(row, "id")
        kind = text_field(row, "kind")
        status = text_field(row, "status")
        if identifier is None or kind is None or status not in tuple(Status):
            continue
        yield Retired(
            id=identifier,
            kind=kind,
            status=Status(status),
            replacement=text_field(row, "replacement"),
            note=text_field(row, "note") or "",
        )
