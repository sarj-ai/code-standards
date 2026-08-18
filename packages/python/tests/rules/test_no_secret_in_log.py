from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rule_base import is_suppressed
from sarj_python_lint.rules.no_secret_in_log import NoSecretInLog


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic, RuleExample


_PUBLIC_EXAMPLES = NoSecretInLog.public_examples()


def _check(source: str) -> list[Diagnostic]:
    return NoSecretInLog().check(Path("<test>.py"), source)


@pytest.mark.parametrize(
    "example",
    _PUBLIC_EXAMPLES,
    ids=tuple(example.example_id for example in _PUBLIC_EXAMPLES),
)
def test_public_documentation_examples_are_executable(example: RuleExample) -> None:
    focus = example.focus_file

    findings = NoSecretInLog().check(Path(focus.path), focus.source)

    assert len(findings) == example.expected_count


@pytest.mark.parametrize(
    "source",
    [
        "logger.info('order', payload=payload)",
        "logger.info('order', payload=payload.model_dump())",
        "logger.info(f'Request failed: {request_json}')",
        "logger.info(f'Response failed: {response_body}')",
        "logger.info('auth', value=access_token)",
    ],
)
def test_rejects_whole_payloads_and_direct_secrets(source: str) -> None:
    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    "source",
    [
        "logger.info('order', payload_id=payload.id)",
        "logger.info('order', payload_summary=summarize(payload))",
        "logger.info(f'Response status: {response_status}')",
    ],
)
def test_allows_payload_metadata_and_summaries(source: str) -> None:
    assert _check(source) == []


def _codes(source: str) -> list[str]:
    return [d.code for d in _check(source)]


# Family 1: every secret word is flagged as a logging keyword                  #

SECRET_KEYWORDS = [
    "token",
    "secret",
    "password",
    "passwd",
    "api_key",
    "apikey",
    "jwt",
    "credential",
    "credentials",
    "authorization",
    # compound / cased forms — whole-token + case-insensitive matching
    "access_token",
    "refresh_token",
    "auth_token",
    "AuthToken",
    "userPassword",
    "client_secret",
    "my_secret",
    "bearer_jwt",
    "APIKey",
    "user_credential",
    "authorization_header",
]


@pytest.mark.parametrize("kw", SECRET_KEYWORDS)
def test_flags_secret_keyword(kw: str):
    src = f'logger.info("msg", {kw}={kw})\n'
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].code == "SARJ012"
    assert kw in diags[0].message


# Family 2: every log-level method is a logging call                           #

LOG_METHODS = ["debug", "info", "warning", "warn", "error", "exception", "critical"]


@pytest.mark.parametrize("method", LOG_METHODS)
def test_flags_on_each_log_method(method: str):
    src = f'logger.{method}("m", token=token)\n'
    assert _codes(src) == ["SARJ012"]


# `log` and `trace` were here until the vocabulary unification.
NON_LOG_METHODS = ["send", "write", "emit", "handle", "flush", "notice"]


@pytest.mark.parametrize("method", NON_LOG_METHODS)
def test_skips_non_log_method(method: str):
    src = f'logger.{method}("m", token=token)\n'
    assert _check(src) == []


# Family 3: logger receiver resolution                                         #

LOGGER_RECEIVERS = [
    "logger",
    "log",
    "logging",
    "loguru",
    "_logger",
    "_log",
    "LOGGER",
    "Log",
    "self.logger",
    "self._log",
    "self.logging",
    "cls.logger",
    "app.log",
    "app.logging.getLogger('svc')",
    "logging.getLogger(__name__)",
    "logging.getLogger(__name__).getChild('x')",
    "logger.bind(request_id=rid)",
    "logger.opt(lazy=True)",
    "logger.bind(a=1).bind(b=2)",
    "logger.getChild('c')",
    # Bare-name factories, reached via `from structlog import get_logger` or `from logging import getLogger`.
    "get_logger()",
    "getLogger(__name__)",
    "get_logger().bind(request_id=rid)",
]


@pytest.mark.parametrize("recv", LOGGER_RECEIVERS)
def test_flags_across_logger_receivers(recv: str):
    src = f'{recv}.error("m", secret=secret)\n'
    assert _codes(src) == ["SARJ012"]


NON_LOGGER_RECEIVERS = [
    "foo",
    "response",
    "resp",
    "client",
    "service",
    "db",
    "self.client",
    "self.db.session",
    "request",
    "metrics",
    "tracer",
    "obj.build()",
    "widget.getChild('c')",
]


@pytest.mark.parametrize("recv", NON_LOGGER_RECEIVERS)
def test_skips_non_logger_receiver(recv: str):
    src = f'{recv}.info("m", token=token)\n'
    assert _check(src) == []


# Family 4: case insensitivity of the secret word                             #


@pytest.mark.parametrize("kw", ["TOKEN", "Token", "ToKeN", "PASSWORD", "Secret", "Api_Key", "JWT", "Jwt"])
def test_flags_case_insensitive_secret(kw: str):
    src = f'logger.info("m", {kw}={kw})\n'
    assert _codes(src) == ["SARJ012"]


# Family 5: redaction markers exempt the keyword                              #

REDACTED_KEYWORDS = [
    "token_prefix",
    "token_suffix",
    "token_redacted",
    "secret_masked",
    "password_hash",
    "password_hint",
    "token_len",
    "token_length",
    "api_key_length",
    "secret_prefix",
    "jwt_hash",
    "authorization_length",
    "credential_mask",
    "PasswordHash",
    "tokenPrefix",
    # `tag` marks a redaction tag derived for logging, not the raw secret.
    "api_key_tag",
    "token_tag",
    "secret_tag",
]


@pytest.mark.parametrize("kw", REDACTED_KEYWORDS)
def test_allows_redacted_keyword(kw: str):
    src = f'logger.info("m", {kw}=v)\n'
    assert _check(src) == []


def test_redaction_wins_when_both_present():
    src = 'logger.info("m", token_prefix=token[:6], password_hash=h)\n'
    assert _check(src) == []


# Family 6: both keyword and value must prove raw secret material               #


def test_allows_secret_keyword_with_sliced_value():
    src = 'logger.info("m", token=token[:6])\n'
    assert _check(src) == []


def test_allows_secret_keyword_with_non_secret_attribute_value():
    src = 'logger.info("m", secret=obj.value)\n'
    assert _check(src) == []


def test_flags_secret_keyword_with_secret_attribute_value():
    src = 'logger.info("m", secret=obj.secret)\n'
    assert _codes(src) == ["SARJ012"]


@pytest.mark.parametrize(
    "source",
    [
        'logger.info("state", token_valid=token_valid)\n',
        'logger.info("state", token=token_valid)\n',
        'logger.info("state", password_present=password_present)\n',
        'logger.info("state", api_key_configured=api_key_configured)\n',
        'logger.info("state", secret=secret_enabled)\n',
    ],
)
def test_allows_derived_secret_state_references(source: str):
    assert _check(source) == []


def test_flags_valid_token_because_the_secret_word_is_terminal():
    assert _codes('logger.info("m", token=valid_token)\n') == ["SARJ012"]


def test_allows_unproven_alias_value():
    assert _check('logger.info("m", token=value)\n') == []


def test_flags_secret_attribute_even_under_generic_keyword():
    src = 'logger.info("m", data=obj.password)\n'
    assert _codes(src) == ["SARJ012"]


def test_allows_safe_name_with_secret_subscript_value():
    src = 'logger.info("m", value=d["token"])\n'
    assert _check(src) == []


# Family 7: forms the rule intentionally does NOT flag                         #


def test_skips_positional_secret_argument():
    src = 'logger.info("token=%s", token)\n'
    assert _check(src) == []


def test_flags_fstring_with_secret():
    src = 'logger.info(f"token={token}")\n'
    assert _codes(src) == ["SARJ012"]


def test_skips_secret_word_in_message_literal():
    src = 'logger.info("the password was rejected")\n'
    assert _check(src) == []


def test_skips_double_star_kwargs():
    src = 'logger.info("m", **secrets)\n'
    assert _check(src) == []


def test_skips_double_star_alongside_flagged_keyword():
    src = 'logger.info("m", **extra, token=token)\n'
    assert _codes(src) == ["SARJ012"]


NON_SECRET_KEYWORDS = [
    "user_id",
    "count",
    "duration_ms",
    "request_id",
    "status",
    "correlation_id",
    "org_id",
    "call_id",
    "latency",
    "attempt",
    "level",
    "name",
]


@pytest.mark.parametrize("kw", NON_SECRET_KEYWORDS)
def test_allows_ordinary_keyword(kw: str):
    src = f'logger.info("done", {kw}=v)\n'
    assert _check(src) == []


def test_comment_mentioning_secret_is_ignored():
    src = 'logger.info("ok")  # do not log the password here\n'
    assert _check(src) == []


# Family 8: nested / multiple calls                                            #


def test_two_secret_keywords_in_one_call():
    src = 'logger.warning("auth", token=token, password=password)\n'
    assert _codes(src) == ["SARJ012", "SARJ012"]


def test_mixed_secret_and_redacted_keywords():
    src = 'logger.info("auth", token=token, token_prefix=token[:6])\n'
    assert _codes(src) == ["SARJ012"]


def test_multiple_calls_each_flagged():
    src = 'logger.info("a", token=token)\nlog.error("b", secret=secret)\nlogger.debug("c", api_key=api_key)\n'
    assert _codes(src) == ["SARJ012", "SARJ012", "SARJ012"]


def test_nested_logging_call_is_flagged():
    src = 'logger.info("outer", data=log.error("inner", token=token))\n'
    assert _codes(src) == ["SARJ012"]


def test_nested_non_logger_keyword_not_flagged():
    src = 'logger.info("m", data=wrap(token=t))\n'
    assert _check(src) == []


def test_secret_keyword_on_outer_with_nested_non_logger_is_unproven():
    src = 'logger.info("m", token=other.build(secret=s))\n'
    assert _check(src) == []


# Family 9: diagnostic location points at the value                           #


def test_diagnostic_line_col_single_line():
    src = 'logger.info("auth", token=token)\n'
    diag = _check(src)[0]
    assert (diag.line, diag.col) == (1, 27)


def test_diagnostic_line_col_multiline_call():
    src = 'logger.info(\n    "auth",\n    password=password,\n)\n'
    diag = _check(src)[0]
    assert (diag.line, diag.col) == (3, 14)


def test_diagnostics_ordered_by_source_position():
    src = 'logger.info("a", token=token)\nlog.error("b", secret=secret)\n'
    diags = _check(src)
    assert [(d.line, d.col) for d in diags] == [(1, 24), (2, 23)]


# Family 10: parse edge cases                                                  #


@pytest.mark.parametrize(
    "src",
    ["", "\n", "   \n\t\n", "# only a comment\n", "x = 1\n", '"""module docstring"""\n'],
)
def test_no_findings_on_trivial_sources(src: str):
    assert _check(src) == []


@pytest.mark.parametrize("src", ["def broken(:\n", "logger.info('x',\n", "class C(:\n", "  return =\n"])
def test_handles_syntax_error(src: str):
    assert _check(src) == []


# Family 11: FALSE-POSITIVE guards — non-secret lookalikes                     # These names embed a secret *substring* but are NOT secrets: LLM usage metrics (`*tokens*` counts, `token_count`), innocent words that merely embed a secret word (`secretary`), and boolean presence / state flags that answer "is it there / was it set" (`token_present`, `password_set`) rather than carrying the credential.

FALSE_POSITIVE_KEYWORDS = [
    "token_count",
    "token_budget",
    "token_limit",
    "max_tokens",
    "prompt_tokens",
    "completion_tokens",
    "n_tokens",
    "total_tokens",
    "num_tokens",
    "tokenize",
    "tokenizer",
    "secretary",
    "api_key_id",
    "password_enabled",
    "token_present",
    "secret_present",
    "password_set",
    "password_unset",
    "password_configured",
    "token_missing",
    "password_required",
    "token_valid",
    "secret_invalid",
    "secret_exists",
    "token_type",
    "credential_type",
]


@pytest.mark.parametrize("kw", FALSE_POSITIVE_KEYWORDS)
def test_does_not_flag_non_secret_lookalike(kw: str):
    src = f'logger.info("usage", {kw}=n)\n'
    assert _check(src) == []


# Family 12: suppression via the shared is_suppressed helper                   #


def _unsuppressed(source: str) -> list[Diagnostic]:
    lines = source.splitlines()
    return [d for d in _check(source) if not is_suppressed(lines, d.line, d.code)]


def test_sarj_noqa_with_code_suppresses():
    src = 'logger.info("auth", token=token)  # sarj-noqa: SARJ012 — redacted downstream\n'
    assert _check(src)  # rule still reports
    assert _unsuppressed(src) == []  # helper filters it


def test_bare_sarj_noqa_suppresses():
    src = 'logger.info("auth", token=token)  # sarj-noqa\n'
    assert _unsuppressed(src) == []


def test_sarj_noqa_for_other_code_does_not_suppress():
    src = 'logger.info("auth", token=token)  # sarj-noqa: SARJ099\n'
    assert len(_unsuppressed(src)) == 1


def test_sarj_noqa_only_affects_its_own_line():
    src = 'logger.info("a", token=token)  # sarj-noqa: SARJ012\nlogger.info("b", secret=secret)\n'
    kept = _unsuppressed(src)
    assert len(kept) == 1
    assert kept[0].line == 2


# Family 13: additional shared secret words (signature / hmac / digest)        # `_SECRET_WORDS` carries more than the human-facing set in Family 1 — it also holds the crypto-material words shared with SARJ011.


@pytest.mark.parametrize("kw", ["signature", "hmac", "digest", "api_secret"])
def test_flags_additional_secret_words(kw: str):
    assert _codes(f'logger.info("m", {kw}={kw})\n') == ["SARJ012"]


def test_hash_keyword_is_exempted_by_redaction_marker():
    assert _check('logger.info("m", hash=h)\n') == []


# Family 14: camelCase decomposition of the keyword name                       #


def test_flags_camelcase_apikey():
    assert _codes('logger.info("m", apiKey=apiKey)\n') == ["SARJ012"]


@pytest.mark.parametrize("kw", ["tokenCount", "apiKeyId", "tokenPresent", "promptTokens"])
def test_allows_camelcase_innocuous(kw: str):
    assert _check(f'logger.info("m", {kw}=n)\n') == []


# Family 15: whole-token matching, not substring                               #


def test_flags_reset_token_whole_token_matching():
    assert _codes('logger.info("m", reset_token=reset_token)\n') == ["SARJ012"]


def test_allows_plural_tokens_counter():
    assert _check('logger.info("usage", tokens=n)\n') == []


# Family 16: extra receiver / method variants                                  #


def test_flags_bind_chain_on_self_logger():
    assert _codes('self.logger.bind(request_id=rid).info("m", secret=secret)\n') == ["SARJ012"]


def test_flags_logger_log_with_positional_level():
    assert _codes('logger.log(logging.INFO, "m", token=token)\n') == ["SARJ012"]


# Family 17: call results are not proven raw secret references                  #


def test_allows_secret_name_with_redacting_call_value():
    assert _check('logger.info("m", token=mask(token))\n') == []


def test_flags_fstring_secret_with_safe_keyword():
    assert _codes('logger.info(f"key={api_key}", user_id=u)\n') == ["SARJ012"]


# Family 18: KNOWN DEFECTS (xfail strict)                                       #


@pytest.mark.parametrize("kw", ["staging_secret", "staging_token"])
def test_staging_secret_should_be_flagged(kw: str):
    assert _codes(f'logger.info("boot", {kw}={kw})\n') == ["SARJ012"]


@pytest.mark.parametrize("kw", ["secrets", "passwords"])
def test_plural_secret_bundle_should_be_flagged(kw: str):
    assert _codes(f'logger.info("loaded", {kw}={kw})\n') == ["SARJ012"]


# Family 19: LEADING boolean-flag prefixes (`has_secret`, `isToken`)           # The mirror image of the trailing flag markers in Family 11: a name whose leading WORD is a boolean predicate answers "does a secret exist?" and carries no credential, so logging it leaks nothing.

_LEADING_FLAG_KEYWORDS = [
    "has_secret",
    "hasSecret",
    "is_token",
    "isToken",
    "was_password",
    "wasPassword",
    "should_rotate_token",
    "can_use_api_key",
    "are_credentials_loaded",
]


@pytest.mark.parametrize("kw", _LEADING_FLAG_KEYWORDS)
def test_does_not_flag_leading_boolean_flag(kw: str):
    assert _check(f'logger.info("state", {kw}=flag)\n') == []


@pytest.mark.parametrize("kw", ["token_present", "password_enabled"])
def test_trailing_flag_markers_still_exempt(kw: str):
    assert _check(f'logger.info("state", {kw}=flag)\n') == []


@pytest.mark.parametrize(
    "kw",
    ["api_key", "INTERNAL_ADMIN_TOKEN", "slack_signing_secret", "auth_token"],
)
def test_genuine_secret_still_flagged_alongside_flag_exemption(kw: str):
    assert _codes(f'logger.info("boot", {kw}={kw})\n') == ["SARJ012"]


@pytest.mark.parametrize("kw", ["issuer_token", "canary_token", "issuerToken"])
def test_flags_credential_whose_leading_word_only_looks_like_a_flag(kw: str):
    assert _codes(f'logger.info("boot", {kw}={kw})\n') == ["SARJ012"]


# Family 20: LIVENESS CANARY                                                   # This rule reports ZERO hits across 2,657 files of popular third-party Python (fastapi, pydantic, black, sqlmodel, rich, flask, httpx, requests, anyio).

_SERVICE_MODULE = """
import logging

from loguru import logger

log = logging.getLogger(__name__)


def authenticate(token, password, api_key, jwt, secret):
    logger.info("auth ok", token=token)
    logger.error("bad creds", password=password)
    logger.debug("outbound call", api_key=api_key)
    logger.warning("expiring soon", jwt=jwt)
    self.logger.info("nested receiver", credentials=secret)
    logging.getLogger("audit").info("factory chain", authorization=secret)
    logger.bind(request_id=rid).info("builder chain", signature=secret)


def safely(token, api_key):
    logger.info("auth ok", token_prefix=token[:6], api_key_tag=tag(api_key))
    logger.info("usage", token_count=n, has_secret=True, api_key_id=row_id)
    log.info("stdlib", extra={"token": token})
    audit.record("stored", token=token)
"""


def test_liveness_every_leak_shape_still_fires():
    diags = _check(_SERVICE_MODULE)
    assert [d.line for d in diags] == [10, 11, 12, 13, 14, 15, 16]
    assert {d.code for d in diags} == {"SARJ012"}


def test_liveness_no_safe_shape_fires():
    safe = _SERVICE_MODULE.split("def safely")[1]
    assert _check(f"def safely{safe}") == []
