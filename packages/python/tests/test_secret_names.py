from __future__ import annotations

import pytest

from sarj_python_lint._secret_names import identifier_tokens, is_secret_name, leading_word


@pytest.mark.parametrize(
    ("identifier", "tokens"),
    [
        ("apiKey", ["apikey", "api", "key"]),
        ("API_KEY", ["api", "api", "key", "key"]),
        ("isTokenStrategy", ["istokenstrategy", "is", "token", "strategy"]),
        ("ToKeN", ["token", "to", "ke", "n"]),
    ],
)
def test_identifier_tokens_preserve_whole_segments_and_split_case(identifier: str, tokens: list[str]) -> None:
    assert identifier_tokens(identifier) == tokens


@pytest.mark.parametrize(
    ("identifier", "word"),
    [
        ("isToken", "is"),
        ("hasSecret", "has"),
        ("hash_secret", "hash"),
        ("issuer_token", "issuer"),
    ],
)
def test_leading_word_matches_words_not_prefixes(identifier: str, word: str) -> None:
    assert leading_word(identifier) == word


@pytest.mark.parametrize(
    "identifier",
    ["apiKey", "authToken", "SESSION_SECRET", "validToken", "presentToken"],
)
def test_secret_names_include_split_and_compound_credentials(identifier: str) -> None:
    assert is_secret_name(identifier)


@pytest.mark.parametrize(
    "identifier",
    [
        "token_count",
        "promptTokens",
        "apiKeyId",
        "passwordEnabled",
        "tokenPresent",
        "tokenType",
        "hasApiKey",
        "isTokenStrategy",
        "tokenize",
        "tokenizer",
        "secretary",
        "keyboardEvent",
    ],
)
def test_secret_names_exclude_metadata_flags_and_substrings(identifier: str) -> None:
    assert not is_secret_name(identifier)


@pytest.mark.parametrize("identifier", ["hash_secret", "issuer_token", "canary_token"])
def test_flag_prefix_guard_does_not_match_partial_words(identifier: str) -> None:
    assert is_secret_name(identifier)


@pytest.mark.parametrize("identifier", ["api_key", "public_api_key", "apiKey"])
def test_api_key_requires_adjacent_api_and_key_tokens(identifier: str) -> None:
    assert is_secret_name(identifier)


@pytest.mark.parametrize("identifier", ["api_public_key", "public_key", "keyboard"])
def test_nonadjacent_or_bare_key_is_not_an_api_key(identifier: str) -> None:
    assert not is_secret_name(identifier)
