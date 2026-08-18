from __future__ import annotations

from itertools import pairwise
import re


SECRET_WORDS = frozenset(
    {
        "token",
        "secret",
        "password",
        "passwd",
        "jwt",
        "secrets",
        "passwords",
        "credential",
        "credentials",
        "authorization",
        "signature",
        "hmac",
        "digest",
        "hash",
        "apikey",
        # Keep this vocabulary aligned with the TypeScript helper.
        "bearer",
    }
)

_SECRET_WORDS = SECRET_WORDS

# A trailing word in this set makes the identifier metadata, not a credential.
_INNOCUOUS_WORDS = frozenset(
    {
        "count",
        "counts",
        "budget",
        "limit",
        "limits",
        "id",
        "ids",
        "enabled",
        "disabled",
        "flag",
        "flags",
        "present",
        "set",
        "unset",
        "configured",
        "missing",
        "required",
        "valid",
        "invalid",
        "exists",
        "type",
        "types",
    }
)

# A leading predicate makes the identifier a boolean flag, not a credential.
_FLAG_PREFIXES = frozenset({"is", "has", "was", "are", "can", "should"})

# Split camel case, capitals, and digit runs within each underscore-delimited component.
_CAMEL_RE = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+")
_SEGMENT_RE = re.compile(r"[^A-Za-z0-9]+")


def identifier_tokens(identifier: str) -> list[str]:
    tokens: list[str] = []
    for segment in _SEGMENT_RE.split(identifier):
        if not segment:
            continue
        tokens.append(segment.lower())
        camel_parts: list[str] = _CAMEL_RE.findall(segment)
        tokens.extend(part.lower() for part in camel_parts)
    return tokens


def leading_word(identifier: str) -> str | None:
    for segment in _SEGMENT_RE.split(identifier):
        if not segment:
            continue
        parts: list[str] = _CAMEL_RE.findall(segment)
        return parts[0].lower() if parts else segment.lower()
    return None


def is_secret_name(identifier: str) -> bool:
    tokens = identifier_tokens(identifier)
    if tokens and tokens[-1] in _INNOCUOUS_WORDS:
        return False
    if leading_word(identifier) in _FLAG_PREFIXES:
        return False
    if any(tok in SECRET_WORDS for tok in tokens):
        return True
    return _has_api_key(tokens)


def _has_api_key(tokens: list[str]) -> bool:
    return any(a == "api" and b == "key" for a, b in pairwise(tokens))
