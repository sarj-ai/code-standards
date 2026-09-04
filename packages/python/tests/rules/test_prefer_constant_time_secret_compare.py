from pathlib import Path
import textwrap
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rule_base import RuleExample, Severity
from sarj_python_lint.rules.prefer_constant_time_secret_compare import PreferConstantTimeSecretCompare


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic


_PATH = Path("app/auth.py")


def _check(source: str, path: Path = _PATH) -> list[Diagnostic]:
    return PreferConstantTimeSecretCompare().check(path, textwrap.dedent(source))


_PUBLIC_EXAMPLES = PreferConstantTimeSecretCompare.public_examples()


@pytest.mark.parametrize("example", _PUBLIC_EXAMPLES, ids=tuple(e.example_id for e in _PUBLIC_EXAMPLES))
def test_public_documentation_examples_are_executable(example: RuleExample) -> None:
    focus = example.focus_file
    assert len(PreferConstantTimeSecretCompare().check(Path(focus.path), focus.source)) == example.expected_count


@pytest.mark.parametrize("operator", ["==", "!="])
def test_request_header_compared_to_settings_secret_fires(operator: str) -> None:
    source = f'def auth(request, settings):\n    return request.headers["X-API-Key"] {operator} settings.api_key\n'
    [diagnostic] = _check(source)
    assert diagnostic.code == "SARJ011"
    assert diagnostic.severity is Severity.WARNING
    assert "compare_digest" in diagnostic.message


@pytest.mark.parametrize(
    "lookup",
    [
        'request.headers.get("Authorization")',
        'request.cookies.get("access_token")',
        'request.query_params.get("api_key")',
        'request.path_params.get("token")',
        'headers["X-Secret-Key"]',
    ],
)
def test_external_authentication_lookups_fire(lookup: str) -> None:
    source = f"def auth(request, headers, expected_token):\n    return {lookup} == expected_token\n"
    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    "source",
    [
        "def auth(provided_token, expected_token):\n    return provided_token == expected_token\n",
        "def auth(presented_api_key, stored_api_key):\n    return presented_api_key == stored_api_key\n",
        "def auth(submitted_password, self):\n    return submitted_password == self.password\n",
        'def auth(auth_header, configured_token):\n    return auth_header == f"Bearer {configured_token}"\n',
    ],
)
def test_role_shaped_names_fire(source: str) -> None:
    assert len(_check(source)) == 1


def test_header_and_settings_aliases_fire() -> None:
    source = """
        def auth(request, settings):
            provided = request.headers.get("X-API-Key")
            expected = settings.api_key
            return provided == expected
    """
    assert len(_check(source)) == 1


def test_settings_call_assignment_keeps_expected_name_role() -> None:
    source = """
        def auth(auth_header):
            expected_token = InstrumentationSettings().metrics.bearer_token
            return auth_header == f"Bearer {expected_token}"
    """
    assert len(_check(source)) == 1


def test_external_path_token_compared_to_uppercase_token_fires() -> None:
    source = """
        import os

        TOKEN = os.environ.get("SARJ_WEBHOOK_TOKEN", "").strip()

        def auth(request):
            return request.path_params.get("token") != TOKEN
    """
    assert len(_check(source)) == 1


def test_dominating_walrus_alias_fires() -> None:
    source = """
        def auth(request, self):
            if secret_key := request.headers.get("X-Secret-Key"):
                if secret_key == self.secret_key:
                    return True
            return False
    """
    assert len(_check(source)) == 1


def test_camel_case_roles_fire() -> None:
    assert len(_check("def auth(providedToken, expectedToken):\n    return providedToken == expectedToken\n")) == 1


@pytest.mark.parametrize(
    "source",
    [
        "def auth(x):\n    return REQUEST_TOKEN == x\n",
        'def auth(combined, provided_token, expected_token):\n    return f"{provided_token}:{expected_token}" == combined\n',
    ],
)
def test_roles_must_be_on_opposite_operands(source: str) -> None:
    assert _check(source) == []


@pytest.mark.parametrize(
    "source",
    [
        'def auth(request, settings, public_value):\n    provided = request.headers["X-API-Key"]\n    provided = public_value\n    return provided == settings.api_key\n',
        'def auth(request, settings, public_value):\n    expected = settings.api_key\n    expected = public_value\n    return request.headers["X-API-Key"] == expected\n',
        'def auth(request, settings):\n    if False:\n        provided = request.headers["X-API-Key"]\n    return provided == settings.api_key\n',
    ],
)
def test_non_dominating_or_rebound_aliases_are_clean(source: str) -> None:
    assert _check(source) == []


def test_same_line_later_assignment_does_not_flow_backward() -> None:
    source = 'def auth(request, settings):\n    result = provided == settings.api_key; provided = request.headers["X-API-Key"]\n    return result\n'
    assert _check(source) == []


@pytest.mark.parametrize(
    "assignment",
    [
        'EXPECTED_TOKEN = os.environ["TOKEN"]',
        'EXPECTED_TOKEN = os.getenv("TOKEN")',
        'EXPECTED_TOKEN = os.environ.get("TOKEN")',
    ],
)
def test_environment_backed_uppercase_secret_fires(assignment: str) -> None:
    source = f"import os\n{assignment}\n\ndef auth(provided_token):\n    return provided_token == EXPECTED_TOKEN\n"
    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    "source",
    [
        'def auth(provided_token, os):\n    return provided_token == os.getenv("TOKEN")\n',
        'def auth(provided_token, request):\n    return provided_token == request.environ.get("TOKEN")\n',
    ],
)
def test_unproven_environment_sources_are_clean(source: str) -> None:
    assert _check(source) == []


def test_response_headers_are_not_request_input() -> None:
    source = 'def inspect(response, settings):\n    return response.headers["X-API-Key"] == settings.api_key\n'
    assert _check(source) == []


def test_hardcoded_non_sentinel_secret_fires() -> None:
    source = 'def auth(provided_token):\n    return provided_token == "production-secret-value"\n'
    assert len(_check(source)) == 1


@pytest.mark.parametrize("sentinel", ['""', '"PLACEHOLDER"', '"UNSET"', '"MISSING"'])
def test_public_sentinel_literals_are_clean(sentinel: str) -> None:
    source = f"def auth(provided_token):\n    return provided_token == {sentinel}\n"
    assert _check(source) == []


def test_password_comparison_recommends_password_verifier() -> None:
    [diagnostic] = _check("def auth(provided_password, self):\n    return provided_password == self.password\n")
    assert "password-hashing library's verification API" in diagnostic.message
    assert "compare_digest" not in diagnostic.message


def test_aliased_password_recommends_password_verifier() -> None:
    source = """
        def auth(request, settings):
            provided = request.headers["X-Password"]
            expected = settings.password
            return provided == expected
    """
    [diagnostic] = _check(source)
    assert "password-hashing library's verification API" in diagnostic.message


def test_sentinel_word_inside_real_secret_is_not_exempt() -> None:
    assert len(_check('def auth(provided_token):\n    return provided_token == "real-not-secret-value"\n')) == 1


@pytest.mark.parametrize("scheme", ['"Bearer"', '"Basic"', '"Digest"'])
def test_authorization_scheme_literals_are_clean(scheme: str) -> None:
    source = f'def auth(request):\n    return request.headers.get("Authorization") == {scheme}\n'
    assert _check(source) == []


@pytest.mark.parametrize(
    "source",
    [
        "def lex(token, kind):\n    return token == kind\n",
        "def stale(cached_hash, token_hash):\n    return cached_hash != token_hash\n",
        "def group(secret, expected):\n    return secret == expected\n",
        "def query(User, password):\n    return User.password == password\n",
        "def compare(secret_wrapper, expected_wrapper):\n    return secret_wrapper == expected_wrapper\n",
        "def payload(token_payload, expected_payload):\n    return token_payload == expected_payload\n",
    ],
)
def test_unproven_authentication_roles_are_clean(source: str) -> None:
    assert _check(source) == []


@pytest.mark.parametrize(
    "source",
    [
        "def parse(token):\n    return token == Punctuation\n",
        "def parse(token):\n    return token == Literal\n",
        "def parse(token):\n    return token == Keyword\n",
    ],
)
def test_lexer_tokens_are_clean(source: str) -> None:
    assert _check(source) == []


@pytest.mark.parametrize(
    "comparison",
    [
        "password == password_confirmation",
        "pending_password != confirm_password",
        "self.password == request.password_confirmation",
    ],
)
def test_password_confirmation_is_clean(comparison: str) -> None:
    source = f"def validate(password, password_confirmation, pending_password, confirm_password, self, request):\n    return {comparison}\n"
    assert _check(source) == []


def test_equality_dunder_is_clean() -> None:
    source = """
        class Credential:
            def __eq__(self, other):
                return self.secret == other.secret
    """
    assert _check(source) == []


def test_nested_auth_function_inside_equality_dunder_still_fires() -> None:
    source = """
        class Credential:
            def __eq__(self, other):
                def authenticate(provided_token, expected_token):
                    return provided_token == expected_token
                return authenticate(self.token, other.token)
    """
    assert len(_check(source)) == 1


def test_chained_equality_is_conservatively_ignored() -> None:
    assert _check("def auth(provided_token, expected_token, other):\n    return provided_token == expected_token == other\n") == []


@pytest.mark.parametrize(
    "path",
    [
        Path("test_auth.py"),
        Path("auth_test.py"),
        Path("tests/auth.py"),
        Path("test/auth.py"),
        Path("conftest.py"),
        Path("app/mocks/auth.py"),
        Path("app/fakes/auth.py"),
        Path("app/generated/auth.py"),
        Path("vendor/auth.py"),
    ],
    ids=["prefix-test", "suffix-test", "tests-dir", "test-dir", "conftest", "mocks", "fakes", "generated", "vendor"],
)
def test_excluded_paths_are_clean(path: Path) -> None:
    source = 'def auth(request, settings):\n    return request.headers["X-API-Key"] == settings.api_key\n'
    assert _check(source, path) == []


def test_generated_header_is_clean() -> None:
    source = '# This file is generated. Do not edit.\ndef auth(request, settings):\n    return request.headers["X-API-Key"] == settings.api_key\n'
    assert _check(source) == []


@pytest.mark.parametrize(
    "source",
    [
        'import hmac\ndef auth(request, settings):\n    return hmac.compare_digest(request.headers["X-API-Key"], settings.api_key)\n',
        'import secrets\ndef auth(request, settings):\n    return secrets.compare_digest(request.headers["X-API-Key"], settings.api_key)\n',
    ],
)
def test_constant_time_comparisons_are_clean(source: str) -> None:
    assert _check(source) == []


@pytest.mark.parametrize("source", ["", "# comment\n", "def broken(:\n"])
def test_empty_or_invalid_source_is_clean(source: str) -> None:
    assert _check(source) == []
