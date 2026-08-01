"""Shared predicate for deciding whether an identifier names secret material.

Used by both SARJ011 (`prefer-constant-time-secret-compare`) and SARJ012
(`no-secret-in-log`) so the two rules never diverge on what counts as a secret.

The historical implementation matched a secret word as a bare *substring*, which
misfired on a large false-positive class observed in a real audit:

- LLM usage counters that merely embed `token`: `token_count`, `prompt_tokens`,
  `completion_tokens`, `total_tokens`, `max_tokens`, `n_tokens`, `num_tokens`,
  `tokenize`, `tokenizer`, `token_budget`.
- Row-id / handle names: `api_key_id`, `*_key_id` — the id of a key row, not the
  key material.
- Boolean feature / presence / state flags, in both word orders: trailing
  (`password_enabled`, `token_present`, `password_set`, `password_configured`)
  and leading (`has_secret`, `hasSecret`, `is_token`, `isToken`) — a boolean
  answering "is it there / was it set", not the credential itself. A `type`
  discriminator is the same: `token_type` is `"Bearer"`, `credential_type` is a
  class name.
- Innocent words embedding a secret word: `secretary` (embeds `secret`).

We fix this with three changes:

1. Match a secret word only as a WHOLE token (after snake_case / camelCase
   splitting), never a substring. This alone clears `tokenize`, `tokenizer`,
   `secretary`, and every *pluralized* `tokens` counter (plural `tokens` is not
   the singular secret word `token`).
2. Disqualify an identifier whose TRAILING token is a counter / row-id / flag
   marker (`count`, `budget`, `id`, `enabled`, ...) even when a secret word is
   also present — this clears `token_count`, `api_key_id`, `password_enabled`,
   while still catching a credential that merely leads with such a word
   (`valid_token`, `present_token` are secrets, not flags).
3. Disqualify an identifier whose LEADING WORD is a boolean predicate (`is`,
   `has`, `was`, ...) — the mirror image of (2), clearing `has_secret` /
   `hasSecret` / `is_token` / `isToken`, which name a boolean answering "does a
   secret exist?" and are neither a leak nor a timing surface.
"""

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
        # `bearer` is in the TypeScript twin's SECRET_WORDS and was in neither
        # Python set, so `bearer == provided` was a flagged timing attack in one
        # engine and silent in the other. The lists are otherwise identical,
        # which is exactly what made the gap invisible.
        "bearer",
    }
)

_SECRET_WORDS = SECRET_WORDS

# Tokens that mark a counter, row-id, feature flag, or boolean presence/state
# marker. As the TRAILING token they mean the identifier is metadata *about* a
# secret, not the secret itself, so it is not a leak / timing surface even when a
# secret word is also present: `token_present`, `password_set`, and
# `password_configured` are booleans, not credentials. Leading such a word does
# not disqualify — `valid_token` / `present_token` are credentials.
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

# A LEADING boolean-predicate word marks a flag, not the credential itself:
# `has_secret`, `hasSecret`, `is_token`, `isToken`, `should_rotate_token`.
#
# WHY THE SHARED PREDICATE (both SARJ011 and SARJ012), not just the SARJ011-only
# auth narrowing the TS port uses: this is the exact mirror of the TRAILING
# `_INNOCUOUS_WORDS` check above, which already exempts both rules. `has_token`
# and `token_present` are the same boolean; word order must not decide whether a
# name counts as a credential. And the SARJ012 case stands on its own — a boolean
# answering "does a secret exist?" leaks nothing when logged, so the rule was
# reporting a pure false positive. (As with the trailing form, the exemption keys
# on the NAME: someone who writes `has_secret=the_actual_secret` still leaks, but
# that hole predates this and is inherent to a name-only rule.)
#
# WHY IT IS SAFE IN THE PERMISSIVE DIRECTION: every member is a copula/auxiliary
# verb that is never the head noun of a credential. Real secret names are noun
# phrases — `auth_token`, `api_key`, `signing_secret`, `INTERNAL_ADMIN_TOKEN` —
# and none begins with `is`/`has`/`was`/`are`/`can`/`should`. Matching is on the
# whole leading WORD, never a prefix of one, so names that merely start with
# those letters keep firing: `hash_secret` (`hash` != `has`), `issuer_token`
# (`issuer` != `is`), `canary_token` (`canary` != `can`).
_FLAG_PREFIXES = frozenset({"is", "has", "was", "are", "can", "should"})

# camelCase / PascalCase / ALLCAPS / digit run splitter, applied to each
# snake/kebab segment. `APIKey` -> ["API", "Key"], `authToken` -> ["auth", "Token"].
_CAMEL_RE = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+")
_SEGMENT_RE = re.compile(r"[^A-Za-z0-9]+")


def identifier_tokens(identifier: str) -> list[str]:
    """Return ordered lowercase tokens from snake_case + camelCase decomposition.

    Also yields each whole snake/kebab segment lowercased, so a pathological
    mixed-case single word like `ToKeN` (which camel-splitting shreds into
    `to`/`ke`/`n`) still surfaces its intended `token` form.

    """
    tokens: list[str] = []
    for segment in _SEGMENT_RE.split(identifier):
        if not segment:
            continue
        tokens.append(segment.lower())
        camel_parts: list[str] = _CAMEL_RE.findall(segment)
        tokens.extend(part.lower() for part in camel_parts)
    return tokens


def leading_word(identifier: str) -> str | None:
    """Return the first *word* of `identifier`, lowercased, or None if it has none.

    `identifier_tokens` deliberately emits each whole snake/kebab segment before
    its camel parts, so its first entry for the camelCase `hasSecret` is the
    useless `hassecret` rather than `has`. Splitting the leading segment with the
    same camel regex makes `has_secret` and `hasSecret` both yield `has`.

    """
    for segment in _SEGMENT_RE.split(identifier):
        if not segment:
            continue
        parts: list[str] = _CAMEL_RE.findall(segment)
        return parts[0].lower() if parts else segment.lower()
    return None


def is_secret_name(identifier: str) -> bool:
    """Report whether `identifier` names raw secret material (a credential, not metadata)."""
    tokens = identifier_tokens(identifier)
    if tokens and tokens[-1] in _INNOCUOUS_WORDS:
        return False
    if leading_word(identifier) in _FLAG_PREFIXES:
        return False
    if any(tok in SECRET_WORDS for tok in tokens):
        return True
    return _has_api_key(tokens)


def _has_api_key(tokens: list[str]) -> bool:
    """Report whether `api` is immediately followed by `key` (the split form of `api_key`)."""
    return any(a == "api" and b == "key" for a, b in pairwise(tokens))
