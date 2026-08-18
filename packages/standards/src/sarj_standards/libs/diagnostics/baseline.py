from __future__ import annotations

import json
from operator import itemgetter
from pathlib import Path
import re
from typing import TYPE_CHECKING, TypeIs

from sarj_standards.libs.filesystem import is_link_like


if TYPE_CHECKING:
    from collections.abc import Iterable

    from .models import Diagnostic


SCHEMA_VERSION = 1
_MAX_BYTES = 16 * 1024 * 1024
_FINGERPRINT = re.compile(r"[0-9a-f]{64}")
_NON_BASELINEABLE_SOURCES = frozenset({"react-doctor"})


def is_baselineable(diagnostic: Diagnostic) -> bool:
    return diagnostic.source not in _NON_BASELINEABLE_SOURCES


def load(path: Path) -> dict[str, int]:
    if not path.is_file() or is_link_like(path):
        msg = f"diagnostic baseline must be a regular file: {path}"
        raise ValueError(msg)
    if path.stat().st_size > _MAX_BYTES:
        msg = f"diagnostic baseline exceeds {_MAX_BYTES} bytes: {path}"
        raise ValueError(msg)
    try:
        parsed: object = json.loads(  # pyright: ignore[reportAny] -- untyped stdlib boundary narrowed below
            path.read_text(encoding="utf-8")
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        msg = f"cannot read diagnostic baseline {path}: {exc}"
        raise ValueError(msg) from exc
    root = _string_object_dict(parsed, label="diagnostic baseline")
    if root.get("schemaVersion") != SCHEMA_VERSION:
        msg = f"diagnostic baseline schemaVersion must equal {SCHEMA_VERSION}"
        raise ValueError(msg)
    entries = root.get("diagnostics")
    if not _is_object_list(entries):
        msg = "diagnostic baseline diagnostics must be a list"
        raise TypeError(msg)
    fingerprints: dict[str, int] = {}
    for index, value in enumerate(entries):
        entry = _string_object_dict(value, label=f"diagnostic baseline entry {index}")
        fingerprint = entry.get("fingerprint")
        if not isinstance(fingerprint, str) or _FINGERPRINT.fullmatch(fingerprint) is None:
            msg = f"diagnostic baseline entry {index} has an invalid fingerprint"
            raise ValueError(msg)
        _ = _required_text(entry, "source", index)
        _ = _required_text(entry, "ruleId", index)
        relative = _required_text(entry, "path", index)
        count = entry.get("count")
        if type(count) is not int or count < 1:
            msg = f"diagnostic baseline entry {index} count must be a positive integer"
            raise ValueError(msg)
        candidate = Path(relative)
        if candidate.is_absolute() or ".." in candidate.parts:
            msg = f"diagnostic baseline entry {index} path must be repository-relative"
            raise ValueError(msg)
        if fingerprint in fingerprints:
            msg = f"diagnostic baseline repeats fingerprint: {fingerprint}"
            raise ValueError(msg)
        fingerprints[fingerprint] = count
    return fingerprints


def _required_text(entry: dict[str, object], key: str, index: int) -> str:
    value = entry.get(key)
    if not isinstance(value, str) or not value:
        msg = f"diagnostic baseline entry {index} requires a non-empty {key}"
        raise TypeError(msg)
    return value


def render(diagnostics: Iterable[Diagnostic]) -> str:
    entries: dict[str, dict[str, object]] = {}
    for item in diagnostics:
        if item.fingerprint is None or not is_baselineable(item):
            continue
        entry = entries.setdefault(
            item.fingerprint,
            {
                "fingerprint": item.fingerprint,
                "source": item.source,
                "ruleId": item.rule_id or item.code,
                "path": item.location.path,
                "count": 0,
            },
        )
        count = entry["count"]
        if not isinstance(count, int):
            msg = "diagnostic baseline count has an invalid internal type"
            raise TypeError(msg)
        entry["count"] = count + 1
    ordered = sorted(
        entries.values(),
        key=itemgetter("source", "ruleId", "path", "fingerprint"),
    )
    return json.dumps({"schemaVersion": SCHEMA_VERSION, "diagnostics": ordered}, indent=2) + "\n"


def _string_object_dict(value: object, *, label: str) -> dict[str, object]:
    if not _is_object_dict(value):
        msg = f"{label} must be an object"
        raise TypeError(msg)
    result: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            msg = f"{label} contains a non-string key"
            raise TypeError(msg)
        result[key] = item
    return result


def _is_object_dict(value: object) -> TypeIs[dict[object, object]]:
    return isinstance(value, dict)


def _is_object_list(value: object) -> TypeIs[list[object]]:
    return isinstance(value, list)


__all__ = ["SCHEMA_VERSION", "load", "render"]
