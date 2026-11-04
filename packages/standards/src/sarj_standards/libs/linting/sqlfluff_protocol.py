from __future__ import annotations

from typing import ClassVar, Final, Literal

from pydantic import BaseModel, ConfigDict, Field


SQLFLUFF_VERSION: Final = "4.2.2"
RULES: Final = frozenset({"AM07", "AM08"})
MAX_INPUT_BYTES: Final = 1024 * 1024
MAX_QUERIES: Final = 32


class _ProtocolModel(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", strict=True, frozen=True)


class SQLRequest(_ProtocolModel):
    queries: tuple[str, ...] = Field(min_length=1, max_length=MAX_QUERIES)


class SQLViolation(_ProtocolModel):
    code: Literal["AM07", "AM08"]
    description: str = Field(min_length=1)
    line: int = Field(ge=1)
    column: int = Field(ge=1)


class SQLResult(_ProtocolModel):
    violations: tuple[SQLViolation, ...] = ()
    unsupported: bool = False


class SQLResponse(_ProtocolModel):
    version: str = Field(min_length=1)
    results: tuple[SQLResult, ...]
