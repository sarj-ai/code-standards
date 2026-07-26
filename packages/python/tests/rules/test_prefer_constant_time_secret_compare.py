from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rules.prefer_constant_time_secret_compare import (
    PreferConstantTimeSecretCompare,
)


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic


def _check(source: str) -> list[Diagnostic]:
    return PreferConstantTimeSecretCompare().check(Path("<test>.py"), source)


def _count(source: str) -> int:
    return len(_check(source))


# Every authenticator stem, exercised as a standalone identifier. Bare integrity
# hashes (`hash`, `digest`, `sha_digest`) are deliberately absent — they are not a
# timing-attack surface and live in the negative suite below.
_SECRET_NAMES = [
    "token",
    "access_token",
    "refresh_token",
    "auth_token",
    "secret",
    "client_secret",
    "apikey",
    "api_key",
    "hmac",
    "computed_hmac",
    "password",
    "passwd",
    "password_hash",
]

_OPERATORS = ["==", "!="]


# ---------------------------------------------------------------------------
# Positive: a secret-like identifier compared with `==` / `!=`.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", _SECRET_NAMES)
@pytest.mark.parametrize("op", _OPERATORS)
def test_flags_secret_name_left_operand(name: str, op: str):
    src = f"def f({name}, other):\n    return {name} {op} other\n"
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].code == "SARJ011"


@pytest.mark.parametrize("name", _SECRET_NAMES)
@pytest.mark.parametrize("op", _OPERATORS)
def test_flags_secret_name_right_operand_yoda(name: str, op: str):
    """Secret on the right-hand side (yoda-style) is flagged just the same."""
    src = f"def f({name}, other):\n    return other {op} {name}\n"
    assert _count(src) == 1


@pytest.mark.parametrize("op", _OPERATORS)
def test_flags_attribute_operand_left(op: str):
    src = f"def f(user, provided):\n    return user.password_hash {op} provided\n"
    assert _count(src) == 1


@pytest.mark.parametrize("op", _OPERATORS)
def test_flags_attribute_operand_right(op: str):
    src = f"def f(user, provided):\n    return provided {op} user.api_key\n"
    assert _count(src) == 1


def test_flags_nested_attribute_operand():
    src = "def f(req, expected):\n    return req.session.token == expected\n"
    assert _count(src) == 1


def test_flags_both_operands_secret_single_diagnostic():
    src = "def f(token, secret):\n    return token == secret\n"
    assert _count(src) == 1


def test_flags_secret_vs_runtime_operand():
    """Two runtime operands (secret vs another name) are a timing surface."""
    src = "def f(token, expected):\n    return token == expected\n"
    assert _count(src) == 1


def test_flags_comparison_inside_comprehension():
    src = "def f(items, token):\n    return [x for x in items if token == x]\n"
    assert _count(src) == 1


def test_flags_comparison_under_not():
    src = "def f(token, expected):\n    return not (token == expected)\n"
    assert _count(src) == 1


@pytest.mark.parametrize(
    "identifier",
    ["user_password_check", "the_signature_bytes", "x_hmac_y"],
)
def test_flags_secret_word_as_whole_token(identifier: str):
    """A secret word present as a whole snake/camel token is flagged."""
    src = f"import hmac\ndef f({identifier}, other):\n    return {identifier} == other\n"
    assert _count(src) == 1


# ---------------------------------------------------------------------------
# `signature` is crypto-gated: a MAC in crypto code, a *function* signature in
# reflection code (pydantic's `default_model_signature` sweep FP).
# ---------------------------------------------------------------------------

_SIGNATURE_NAMES = ["signature", "sig_signature", "webhook_signature"]


@pytest.mark.parametrize("name", _SIGNATURE_NAMES)
@pytest.mark.parametrize("crypto_import", ["import hmac", "import hashlib", "from jwt import decode"])
def test_flags_signature_when_module_imports_crypto(name: str, crypto_import: str):
    src = f"{crypto_import}\ndef f({name}, other):\n    return {name} == other\n"
    assert _count(src) == 1


@pytest.mark.parametrize("name", _SIGNATURE_NAMES)
def test_allows_signature_without_crypto_import(name: str):
    """No crypto machinery in the module — `signature` is a function signature."""
    src = f"import inspect\ndef f({name}, other):\n    return {name} == other\n"
    assert _check(src) == []


def test_allows_inspect_signature_comparison():
    # Minimized from pydantic _internal/_signature.py: comparing a computed
    # (name, kind) list against a default *function* signature.
    src = (
        "from inspect import Parameter\n"
        "def f(present_params):\n"
        "    default_model_signature = [('self', Parameter.POSITIONAL_ONLY)]\n"
        "    return [(p.name, p.kind) for p in present_params] == default_model_signature\n"
    )
    assert _check(src) == []


def test_token_still_fires_without_crypto_import():
    """Only the polysemous `signature` is crypto-gated — other auth words are not."""
    src = "def f(token, other):\n    return token == other\n"
    assert _count(src) == 1


@pytest.mark.parametrize("identifier", ["subtoken", "mytokenvalue"])
def test_allows_secret_word_only_as_substring(identifier: str):
    """A secret word buried mid-word (not a whole token) is NOT a secret."""
    src = f"def f({identifier}, other):\n    return {identifier} == other\n"
    assert _check(src) == []


def test_message_mentions_compare_digest():
    diags = _check("def f(token, e):\n    return token == e\n")
    assert len(diags) == 1
    assert "compare_digest" in diags[0].message


# ---------------------------------------------------------------------------
# Negative: comparisons that must NOT be flagged.
# ---------------------------------------------------------------------------


def test_allows_compare_digest_hmac():
    src = "import hmac\n\ndef f(token, expected):\n    return hmac.compare_digest(token, expected)\n"
    assert _check(src) == []


def test_allows_compare_digest_secrets():
    src = "import secrets\n\ndef f(token, expected):\n    return secrets.compare_digest(token, expected)\n"
    assert _check(src) == []


@pytest.mark.parametrize(
    "identifier",
    ["name", "count", "index", "status", "email", "user_id", "value"],
)
def test_allows_non_secret_name(identifier: str):
    src = f'def f({identifier}):\n    return {identifier} == "admin"\n'
    assert _check(src) == []


def test_allows_two_non_secret_names():
    src = "def f(a, b):\n    return a == b\n"
    assert _check(src) == []


@pytest.mark.parametrize("op", ["is", "is not", "<", ">", "<=", ">=", "in", "not in"])
def test_allows_non_eq_operators(op: str):
    """Identity, ordering, and membership operators are out of scope."""
    src = f"def f(token, other):\n    return token {op} other\n"
    assert _check(src) == []


def test_allows_secret_in_assignment():
    src = "def f():\n    token = compute()\n    return token\n"
    assert _check(src) == []


def test_allows_secret_in_call_argument():
    src = "def f(token):\n    return log(token)\n"
    assert _check(src) == []


def test_allows_secret_in_binop():
    src = "def f(token, salt):\n    return token + salt\n"
    assert _check(src) == []


def test_allows_secret_subscript_operand():
    """Subscripts are out of scope — only Name.id / Attribute.attr are matched."""
    src = 'def f(headers, expected):\n    return headers["token"] == expected\n'
    assert _check(src) == []


# ---------------------------------------------------------------------------
# Excluded operands: presence / identity-style comparisons.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "rhs",
    ["None", "True", "False", "0", "1", "0.0", "3.14", "1j", '""'],
)
@pytest.mark.parametrize("op", _OPERATORS)
def test_allows_secret_vs_excluded_operand(rhs: str, op: str):
    src = f"def f(token):\n    return token {op} {rhs}\n"
    assert _check(src) == []


@pytest.mark.parametrize("op", _OPERATORS)
def test_allows_excluded_operand_on_left(op: str):
    src = f"def f(token):\n    return None {op} token\n"
    assert _check(src) == []


def test_allows_secret_count_vs_zero():
    """`token_count == 0` is a count check — the numeric literal exempts it."""
    src = "def f(token_count):\n    return token_count == 0\n"
    assert _check(src) == []


# ---------------------------------------------------------------------------
# Literal-sentinel exemption: a secret compared to a compile-time str/bytes
# literal is a placeholder/state check, not a timing-attack surface.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("op", _OPERATORS)
@pytest.mark.parametrize(
    "literal",
    ['"PLACEHOLDER"', '"SENTINEL"', '"none"', "b'\\x00'", 'b"expected"', "'expected-value'"],
)
def test_allows_secret_vs_string_or_bytes_literal(op: str, literal: str):
    src = f"def f(password):\n    return password {op} {literal}\n"
    assert _check(src) == []


def test_allows_password_vs_placeholder_sentinel():
    """The real noura-be case: `password == "PLACEHOLDER"` is a sentinel check."""
    src = 'def f(password, password_confirmation):\n    return password == "PLACEHOLDER" or password_confirmation == "PLACEHOLDER"\n'
    assert _check(src) == []


def test_allows_token_vs_sentinel_literal():
    src = 'def f(token):\n    return token == "SENTINEL"\n'
    assert _check(src) == []


def test_allows_api_key_vs_bytes_literal():
    src = 'def f(api_key):\n    return api_key == b"\\x00\\x01"\n'
    assert _check(src) == []


def test_allows_secret_vs_string_literal_left_operand():
    src = 'def f(secret):\n    return "none" != secret\n'
    assert _check(src) == []


# ---------------------------------------------------------------------------
# Still fires: two runtime operands (Name/Attribute both sides).
# ---------------------------------------------------------------------------


def test_flags_two_runtime_hash_names():
    """`cached_hash != token_hash` still fires — `token_hash` carries the `token` authenticator.

    `cached_hash` alone is an integrity hash (not a timing surface); the diagnostic
    comes from the `token_hash` operand.
    """
    src = "def f(cached_hash, token_hash):\n    return cached_hash != token_hash\n"
    assert _count(src) == 1


def test_flags_secret_vs_stored_secret_name():
    src = "def f(password, stored_password):\n    return password == stored_password\n"
    assert _count(src) == 1


def test_flags_api_key_vs_request_key_name():
    src = "def f(api_key, req_key):\n    return api_key == req_key\n"
    assert _count(src) == 1


def test_flags_secret_vs_attribute_operand():
    src = "def f(secret, req):\n    return secret != req.stored_secret\n"
    assert _count(src) == 1


# ---------------------------------------------------------------------------
# Edge cases.
# ---------------------------------------------------------------------------


def test_empty_source():
    assert _check("") == []


def test_whitespace_only_source():
    assert _check("\n\n   \n") == []


def test_comment_only_source():
    assert _check("# just a comment\n") == []


def test_syntax_error_returns_empty():
    assert _check("def f(:\n    pass") == []


def test_syntax_error_unclosed_paren_returns_empty():
    assert _check("x = token == (\n") == []


def test_chained_comparison_not_flagged():
    """`a == token == b` has two operators, so the single-op guard skips it."""
    src = "def f(a, token, b):\n    return a == token == b\n"
    assert _check(src) == []


def test_chained_comparison_all_secrets_not_flagged():
    src = "def f(token, secret, digest):\n    return token == secret == digest\n"
    assert _check(src) == []


def test_secret_vs_secret_attribute_single_diag():
    src = "def f(token, obj):\n    return token == obj.secret\n"
    assert _count(src) == 1


# ---------------------------------------------------------------------------
# Line / column precision.
# ---------------------------------------------------------------------------


def test_line_and_col_module_level():
    diags = _check("token == expected\n")
    assert len(diags) == 1
    assert diags[0].line == 1
    assert diags[0].col == 1


def test_line_and_col_offset_within_statement():
    diags = _check("result = api_key != given\n")
    assert len(diags) == 1
    assert diags[0].line == 1
    assert diags[0].col == 10


def test_line_reported_for_deeper_statement():
    src = "def f(token, e):\n    x = 1\n    return token == e\n"
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].line == 3


def test_col_for_indented_comparison():
    src = "def f(token, e):\n    return token == e\n"
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].col == 12


# ---------------------------------------------------------------------------
# Multiple diagnostics: count and ordering.
# ---------------------------------------------------------------------------


def test_multiple_secrets_each_flagged():
    src = "a = token == x\nb = secret == y\nc = password == z\n"
    diags = _check(src)
    assert len(diags) == 3


def test_multiple_diagnostics_in_source_order():
    src = "a = token == x\nb = secret == y\nc = password == z\n"
    lines = [d.line for d in _check(src)]
    assert lines == sorted(lines)
    assert lines == [1, 2, 3]


def test_mixed_flagged_and_clean_lines():
    src = (
        "import hmac\na = token == x\nb = count == 0\nc = hmac.compare_digest(sig, expected)\nd = signature != given\n"
    )
    diags = _check(src)
    assert [d.line for d in diags] == [2, 5]


# ---------------------------------------------------------------------------
# False-positive class: whole-token matching + innocuous-marker denylist.
# ---------------------------------------------------------------------------

_NON_SECRET_LOOKALIKES = [
    "token_count",
    "token_budget",
    "token_limit",
    "max_tokens",
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "n_tokens",
    "num_tokens",
    "tokenize",
    "tokenizer",
    "secretary",
    "api_key_id",
    "webhook_key_id",
    "password_enabled",
    "token_present",
    "secret_present",
    "password_set",
    "password_configured",
    "token_type",
    "credential_type",
]


@pytest.mark.parametrize("name", _NON_SECRET_LOOKALIKES)
def test_allows_non_secret_lookalike_vs_variable(name: str):
    """LLM counters, key-row ids, and feature flags are not secrets even vs a variable."""
    src = f"def f({name}, other):\n    return {name} == other\n"
    assert _check(src) == []


def test_still_flags_password_compound_label():
    """A real secret word as a whole token, vs a runtime value, is still flagged."""
    src = "def f(password_field, submitted):\n    return password_field == submitted\n"
    assert _count(src) == 1


# ---------------------------------------------------------------------------
# SARJ011-only narrowing: integrity hashes, category/handle descriptors, and
# ALL-CAPS sentinel constants are not a timing surface. (SARJ012
# `no-secret-in-log` keeps the broader shared secret set — these are suppressed
# inside this rule, not in `_secret_names`. The leading boolean-flag exemption
# below is the exception: it lives in the shared `_secret_names` predicate, so
# SARJ012 gets it too — a flag is neither a timing surface nor a leak.)
# ---------------------------------------------------------------------------

_INTEGRITY_HASH_NAMES = [
    "hash",
    "digest",
    "sha_digest",
    "content_hash",
    "metadata_hash",
    "hash_key",
    "existing_row_hash",
    "state_hash",
    "checksum",
    "file_checksum",
]


@pytest.mark.parametrize("name", _INTEGRITY_HASH_NAMES)
def test_allows_integrity_hash_operand(name: str):
    """A bare content/integrity hash is not an authenticator — no timing surface."""
    src = f"def f({name}, other):\n    return {name} == other\n"
    assert _check(src) == []


_AUTH_HASH_NAMES = ["password_hash", "token_hash", "jwt_hash", "computed_hmac", "signature_digest"]


@pytest.mark.parametrize("name", _AUTH_HASH_NAMES)
def test_flags_hash_carrying_authenticator(name: str):
    """A hash-bearing name that also carries an auth word gates access — still fires."""
    src = f"import hashlib\ndef f({name}, provided):\n    return {name} == provided\n"
    assert _count(src) == 1


_DESCRIPTOR_LOOKALIKES = [
    "token_name",
    "credential_name",
    "secret_kind",
    "token_kind",
    "credential_type",
    "grant_type",
    "auth_token_type",
]


@pytest.mark.parametrize("name", _DESCRIPTOR_LOOKALIKES)
def test_allows_descriptor_and_category_lookalike(name: str):
    """`_type`/`_name`/`_kind` descriptors and `type`/`kind` discriminators are metadata."""
    src = f"def f({name}, other):\n    return {name} == other\n"
    assert _check(src) == []


_BOOLEAN_FLAG_NAMES = [
    # snake_case
    "is_token",
    "has_secret",
    "is_token_strategy",
    "was_password",
    "should_rotate_token",
    # camelCase — the leading word is only visible after camel splitting, so
    # these regressed when the check read the first token of the decomposition
    # (which is the whole segment `hassecret`, not `has`).
    "isToken",
    "hasSecret",
    "isTokenStrategy",
    "wasPassword",
]


@pytest.mark.parametrize("name", _BOOLEAN_FLAG_NAMES)
def test_allows_boolean_flag_prefix(name: str):
    """A leading `is`/`has`/`was` marks a boolean flag, not the credential itself."""
    src = f"def f({name}, other):\n    return {name} == other\n"
    assert _check(src) == []


_FLAG_PREFIX_LOOKALIKES = [
    # The leading WORD must match, never a prefix of one: `hash`/`issuer`/`canary`
    # merely start with the letters of `has`/`is`/`can` and stay credentials.
    "hash_secret",
    "issuer_token",
    "canary_token",
    "hashSecret",
    "issuerToken",
]


@pytest.mark.parametrize("name", _FLAG_PREFIX_LOOKALIKES)
def test_flags_credential_whose_leading_word_only_looks_like_a_flag(name: str):
    """A credential is not exempted just because its first word starts with `is`/`has`/`can`."""
    src = f"def f({name}, other):\n    return {name} == other\n"
    assert _count(src) == 1


_ALLCAPS_SENTINELS = [
    "models.TOKEN_TYPE_SYSTEM",
    "HTTP_DIGEST_AUTHENTICATION",
    "PASSWORD_NOT_CHANGED",
    "_WILDCARD_TOKEN",
    "CONF_API_KEY",
]


@pytest.mark.parametrize("sentinel", _ALLCAPS_SENTINELS)
def test_allows_compare_against_allcaps_constant(sentinel: str):
    """An ALL-CAPS constant is a compile-time sentinel/enum member, not a runtime secret."""
    src = f"def f(token_type):\n    return token_type == {sentinel}\n"
    assert _check(src) == []


def test_allows_secret_operand_vs_allcaps_constant():
    """Even a genuine secret vs an ALL-CAPS sentinel is a state check, not a timing surface."""
    src = "def f(password):\n    return password != PASSWORD_NOT_CHANGED\n"
    assert _check(src) == []


# Real-world FP shapes lifted from the corpus (HA auth, poetry lockfile, SQLAlchemy).


@pytest.mark.parametrize(
    "src",
    [
        "def f(token_type):\n    return token_type == models.TOKEN_TYPE_SYSTEM\n",
        "def f(self, metadata):\n    return self._content_hash == metadata\n",
        "def f(metadata_hash, expected):\n    return metadata_hash != expected\n",
        "def f(state, hash_key):\n    return state.session_id == hash_key\n",
    ],
)
def test_allows_corpus_false_positive_shapes(src: str):
    assert _check(src) == []


# Genuine authenticator compares from the corpus that MUST keep firing.


@pytest.mark.parametrize(
    "src",
    [
        "def f(secret_token, secret_token_header):\n    return secret_token != secret_token_header\n",
        "def f(data, session):\n    return data.access_token == session.access_token\n",
        "def f(push_secret, secret):\n    return push_secret != secret\n",
        "def f(api_key, provided):\n    return api_key == provided\n",
    ],
)
def test_flags_genuine_authenticator_compares(src: str):
    assert _count(src) == 1


# ---------------------------------------------------------------------------
# Test-path scope: fixture equality assertions are not a timing surface.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("test_path", ["test_auth.py", "svc/tests/test_auth.py", "tests/conftest.py"])
def test_skips_test_paths(test_path: str):
    src = "def f(api_key, fixture_key):\n    return api_key == fixture_key\n"
    assert PreferConstantTimeSecretCompare().check(Path(test_path), src) == []


def test_flags_same_compare_in_production_path():
    """The identical runtime compare in a non-test module is still flagged."""
    src = "def f(api_key, provided):\n    return api_key == provided\n"
    assert len(PreferConstantTimeSecretCompare().check(Path("svc/auth.py"), src)) == 1


# ---------------------------------------------------------------------------
# Adversarial edge-case hunt (2026-07): camelCase, attribute/attribute,
# lambda/f-string operands, innocuous-boundary probing.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["apiKey", "accessToken", "clientSecret", "authToken"])
def test_flags_camelcase_secret_name(name: str):
    """A secret word surfaced only by camelCase splitting is still flagged."""
    src = f"def f({name}, provided):\n    return {name} == provided\n"
    assert _count(src) == 1


def test_flags_attribute_vs_attribute():
    """`self.token == other.token` — both operands secret attrs, one diagnostic."""
    src = "def f(self, other):\n    return self.token == other.token\n"
    assert _count(src) == 1


def test_flags_comparison_inside_lambda():
    src = "g = lambda token, e: token == e\n"
    assert _count(src) == 1


def test_flags_secret_vs_fstring_rhs():
    """An f-string RHS is not a compile-time Constant, so it does not exempt."""
    src = 'def f(token, expected):\n    return token == f"{expected}"\n'
    assert _count(src) == 1


def test_allows_fstring_lhs_not_inspected():
    """A JoinedStr operand is neither Name nor Attribute — out of scope (no fire)."""
    src = 'def f(token, expected):\n    return f"{token}" == expected\n'
    assert _check(src) == []


def test_token_fires_but_token_type_stays_exempt():
    """`token` is a secret; `token_type` (innocuous `type`) is metadata."""
    assert _count("def f(token, o):\n    return token == o\n") == 1
    assert _check("def f(token_type, o):\n    return token_type == o\n") == []


def test_flags_token_tag_tag_absent_from_denylist():
    """`tag` is NOT in the innocuous denylist, so `token_tag` still fires."""
    src = "def f(token_tag, other):\n    return token_tag == other\n"
    assert _count(src) == 1


# --- Genuine defects: xfail(strict=True) ----------------------------------


def test_flags_secret_in_walrus_operand():
    src = "def f(expected):\n    return (secret := load()) == expected\n"
    assert _count(src) == 1


def test_flags_valid_token_credential():
    src = "def f(valid_token, provided):\n    return valid_token == provided\n"
    assert _count(src) == 1


@pytest.mark.xfail(
    strict=True,
    reason="Literal-sentinel exemption doesn't follow a Name bound to a str literal one line up — false positive on equivalent code",
)
def test_allows_secret_vs_name_bound_to_literal():
    src = 'def f(token):\n    expected = "PLACEHOLDER"\n    return token == expected\n'
    assert _check(src) == []


# --- Value-equality dunders are not an auth gate --------------------------


def test_allows_secret_compare_in_eq_dunder():
    src = """
class HTTPBasicAuth:
    def __eq__(self, other):
        return self.password == getattr(other, "password", None)
"""
    assert _check(src) == []


def test_allows_secret_compare_in_ne_dunder():
    src = """
class HTTPBasicAuth:
    def __ne__(self, other):
        return self.api_key != getattr(other, "api_key", None)
"""
    assert _check(src) == []


def test_flags_secret_compare_in_ordinary_method_of_same_class():
    src = """
class HTTPBasicAuth:
    def authenticate(self, other):
        return self.password == other.password
"""
    assert _count(src) == 1


def test_flags_secret_compare_in_nested_def_inside_eq_dunder():
    src = """
class Auth:
    def __eq__(self, other):
        def check(provided):
            return self.token == provided
        return check(other.token)
"""
    assert _count(src) == 1
