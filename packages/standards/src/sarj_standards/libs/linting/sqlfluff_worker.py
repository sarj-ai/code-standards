from __future__ import annotations

from importlib.metadata import version
import re
import sys
from typing import ClassVar, Final, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field
from sqlfluff.core import FluffConfig, Linter

from .sqlfluff_protocol import (
    MAX_INPUT_BYTES,
    RULES,
    SQLFLUFF_VERSION,
    SQLRequest,
    SQLResponse,
    SQLResult,
    SQLViolation,
)


_PARSE_CODES: Final = frozenset({"PRS", "LXR", "TMP"})
_NAMED_PARAMETER: Final = re.compile(r"%\([^)]+\)s")
_INLINE_CONFIG: Final = re.compile(r"(?im)^\s*--\s*sqlfluff\s*:")


class _NativeViolation(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", strict=True)

    code: Literal["AM07", "AM08"]
    description: str = Field(min_length=1)
    line: int = Field(validation_alias=AliasChoices("start_line_no", "line_no"), ge=1)
    column: int = Field(validation_alias=AliasChoices("start_line_pos", "line_pos"), ge=1)


def main() -> None:
    actual_version = version("sqlfluff")
    if actual_version != SQLFLUFF_VERSION:
        message = f"Expected SQLFluff {SQLFLUFF_VERSION}; found {actual_version}"
        raise ValueError(message)
    data = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
    if len(data) > MAX_INPUT_BYTES:
        message = "SQL worker input exceeds its byte limit"
        raise ValueError(message)
    request = SQLRequest.model_validate_json(data)
    clients: dict[str, Linter] = {}
    response = SQLResponse(version=actual_version, results=tuple(_lint(query, clients) for query in request.queries))
    sys.stdout.write(response.model_dump_json())


def _lint(query: str, clients: dict[str, Linter]) -> SQLResult:
    # Embedded comments cannot replace the fixed dialect or select an executable templater.
    if _INLINE_CONFIG.search(query):
        return SQLResult(unsupported=True)
    style: Literal["percent", "pyformat"] = "pyformat" if _NAMED_PARAMETER.search(query) else "percent"
    client = clients.get(style)
    if client is None:
        config = FluffConfig(
            configs={
                "core": {
                    "dialect": "postgres",
                    "templater": "placeholder",
                    "rules": ",".join(sorted(RULES)),
                    "large_file_skip_byte_limit": 0,
                },
                "templater": {"placeholder": {"param_style": style}},
            }
        )
        client = Linter(config=config)
        clients[style] = client
    linted = client.lint_string(query, fix=False)
    found = linted.get_violations()
    if linted.tree is None or any(item.rule_code() in _PARSE_CODES for item in found):
        return SQLResult(unsupported=True)
    violations = tuple(_NativeViolation.model_validate(item.to_dict()) for item in found)
    return SQLResult(
        violations=tuple(
            SQLViolation(code=item.code, description=item.description, line=item.line, column=item.column)
            for item in violations
        )
    )


if __name__ == "__main__":
    main()
