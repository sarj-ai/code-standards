from __future__ import annotations

import base64
from decimal import Decimal, InvalidOperation
import hashlib
import re
from typing import TYPE_CHECKING

from jsonschema import FormatChecker

from sarj_standards.libs.json_boundary import parse_json
from sarj_standards.libs.typed_containers import is_object_mapping


if TYPE_CHECKING:
    from pathlib import Path


_SHA256 = "3ebb9f46d87276b72793722c86605ed3afdd90e9cf877536958682d71a00f979"
_MAX_DURATION_SECONDS = 315_576_000_000
FORMATS = FormatChecker()
type JsonSchema = dict[str, object]


@FORMATS.checks("int64", raises=InvalidOperation)
def _int64(value: object) -> bool:
    return _integer_string(value, bits=64)


@FORMATS.checks("int32", raises=InvalidOperation)
def _int32(value: object) -> bool:
    return _integer_string(value, bits=32)


def _integer_string(value: object, *, bits: int) -> bool:
    if not isinstance(value, str):
        return True
    number = Decimal(value)
    return (
        number.is_finite() and -(2 ** (bits - 1)) <= number < 2 ** (bits - 1) and number == number.to_integral_value()
    )


@FORMATS.checks("byte", raises=ValueError)
def _base64(value: object) -> bool:
    if isinstance(value, str):
        compact = re.sub(r"[ \t\r\n\f\v]", "", value)
        base64.b64decode(compact + "=" * (-len(compact) % 4), altchars=b"-_", validate=True)
    return True


@FORMATS.checks("google-duration", raises=InvalidOperation)
def _duration(value: object) -> bool:
    if not isinstance(value, str):
        return True
    match = re.fullmatch(r"-?([0-9]+)(?:\.[0-9]{1,9})?s", value)
    return match is not None and Decimal(match[1]) <= _MAX_DURATION_SECONDS


def build_schema(directory: Path) -> JsonSchema:
    payload = (directory / "google-build-v1-schema.json").read_bytes()
    if hashlib.sha256(payload).hexdigest() != _SHA256:
        message = "Pinned upstream Cloud Build schema digest does not match"
        raise ValueError(message)
    schema = parse_json(payload.decode("utf-8"))
    if not is_object_mapping(schema):
        message = "Pinned Cloud Build schema must contain an object"
        raise ValueError(message)
    return {str(key): value for key, value in schema.items()}
