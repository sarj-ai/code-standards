from __future__ import annotations

from hmac import compare_digest
from inspect import currentframe
from pathlib import Path
from types import CodeType, FunctionType, SimpleNamespace
from typing import TYPE_CHECKING

import pytest
from sarj_rule_contracts import apply_edits

from sarj_python_lint._autofix_security import fixes
from sarj_python_lint._file_context import PythonFileContext
from sarj_python_lint.autofix import fix_source
from sarj_python_lint.rules.prefer_constant_time_secret_compare import PreferConstantTimeSecretCompare


if TYPE_CHECKING:
    from collections.abc import Callable


_RULE = "prefer-constant-time-secret-compare"
_PATH = Path("app/auth.py")
_SOURCE = (
    "from hmac import compare_digest\n"
    'compare_digest(b"a", b"b")\n'
    "def authenticate(provided_token, expected_token):\n"
    "    def _check(provided_token, expected_token, _compare=compare_digest, _type=type, _bytes=bytes):\n"
    "        if _type(provided_token) is _bytes and _type(expected_token) is _bytes:\n"
    "            return provided_token == expected_token\n"
    "        return False\n"
    "    return _check(provided_token, expected_token)\n"
)
_GETTER_SOURCE = (
    "from hmac import compare_digest\n"
    'compare_digest(b"a", b"b")\n'
    "def authenticate(request, settings):\n"
    "    def _check(_compare=compare_digest, _type=type, _bytes=bytes):\n"
    '        provided_token = request.headers["X-API-Key"]\n'
    "        expected_token = settings.api_key\n"
    "        if _type(provided_token) is _bytes and _type(expected_token) is _bytes:\n"
    "            return provided_token == expected_token\n"
    "        return False\n"
    "    return _check()\n"
)


def _fixed(source: str, path: Path = _PATH) -> str:
    context = PythonFileContext(path, source)
    edits = [
        edit
        for diagnostic in PreferConstantTimeSecretCompare().check_context(context)
        for edit in fixes(context, diagnostic)
    ]
    return apply_edits(source, edits)


def _function(source: str) -> FunctionType:
    code = compile(source, str(_PATH), "exec", dont_inherit=True)
    constants: tuple[object, ...] = code.co_consts
    function = next(value for value in constants if isinstance(value, CodeType) and value.co_name == "authenticate")
    return FunctionType(function, {"compare_digest": compare_digest})


def _reject_compare(_left: object, _right: object) -> bool:
    return False


def _object_type(_value: object) -> type[object]:
    return object


def _invoke(function: Callable[[object, object], object], request: object, settings: object) -> object:
    return function(request, settings)


@pytest.mark.parametrize("operator", ["==", "!="])
@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_security_autofix_exact_output_and_convergence(operator: str, newline: str) -> None:
    before = _SOURCE.replace(" == ", f" {operator} ").replace("\n", newline)
    prefix = "not " if operator == "!=" else ""
    expected = before.replace(
        f"provided_token {operator} expected_token", f"{prefix}_compare(provided_token, expected_token)"
    )
    assert len(PreferConstantTimeSecretCompare().check(_PATH, before)) == 1
    assert _fixed(before) == expected
    assert _fixed(expected) == expected
    assert not PreferConstantTimeSecretCompare().check(_PATH, expected)
    compile(expected, str(_PATH), "exec", dont_inherit=True)


def test_security_autofix_public_api_selection_suppression_and_unicode() -> None:
    source = "# Unicode 😀\n" + _SOURCE
    expected = source.replace("provided_token == expected_token", "_compare(provided_token, expected_token)")
    assert fix_source(_PATH, source, rule_ids=[_RULE]) == expected
    assert fix_source(_PATH, expected, rule_ids=[_RULE]) == expected
    assert fix_source(_PATH, source, rule_ids=[]) == source
    suppressed = source.replace(
        "return provided_token == expected_token", "return provided_token == expected_token  # sarj-noqa: SARJ011"
    )
    assert fix_source(_PATH, suppressed, rule_ids=[_RULE]) == suppressed
    assert fix_source(_PATH.with_suffix(".pyi"), source, rule_ids=[_RULE]) == source


@pytest.mark.parametrize(
    ("global_alias", "capture_alias"), [("constant_compare", "_constant_compare"), ("compare_digest", "_比較")]
)
def test_security_autofix_preserves_existing_aliases_unicode_and_comparison_newlines(
    global_alias: str, capture_alias: str
) -> None:
    source = (
        _SOURCE.replace("compare_digest", global_alias)
        .replace(f"from hmac import {global_alias}", f"from hmac import compare_digest as {global_alias}")
        .replace("_compare", capture_alias)
    )
    source = source.replace(
        "return provided_token == expected_token", "return (provided_token\n                    == expected_token)"
    )
    expected = source.replace(
        "provided_token\n                    == expected_token", f"{capture_alias}(provided_token, expected_token)\n"
    )
    assert _fixed(source) == expected
    assert _fixed(expected) == expected
    compile(expected, str(_PATH), "exec", dont_inherit=True)


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("from hmac import compare_digest\n", ""),
        ('compare_digest(b"a", b"b")\n', ""),
        ("from hmac import compare_digest", "import hmac\nfrom hmac import compare_digest"),
        ("from hmac import compare_digest", "from other import compare_digest"),
        ("from hmac import compare_digest", "from unittest.mock import patch\nfrom hmac import compare_digest"),
        ("from hmac import compare_digest", "from .hmac import compare_digest"),
        ("from hmac import compare_digest", "from hmac import compare_digest, digest"),
        ('compare_digest(b"a", b"b")', 'compare_digest(b"a", b"b")\ncompare_digest = replacement'),
        ('compare_digest(b"a", b"b")', 'compare_digest(b"a", b"b")\nalias = compare_digest'),
        ('compare_digest(b"a", b"b")', 'compare_digest(b"a", b"b")\ncompare_digest.__name__'),
        ('compare_digest(b"a", b"b")', 'compare_digest(b"a", b"b")\ncallback()'),
        ('compare_digest(b"a", b"b")', 'compare_digest(b"a", b"b")\nsettings.api_key = b"x"'),
        ("_type(provided_token) is _bytes", "isinstance(provided_token, _bytes)"),
        ("_type(expected_token) is _bytes", "_type(expected_token) is str"),
        (" and _type(expected_token) is _bytes", ""),
        ("_type(expected_token) is _bytes", "_type(provided_token) is _bytes"),
        ("_type(provided_token) is _bytes", "_type(provided_token) == _bytes"),
        ("_type(provided_token) is _bytes", "_type(provided_token) is _bytes or accepted"),
        (
            "def authenticate(provided_token, expected_token):",
            "def authenticate(provided_token, expected_token, type):",
        ),
        (
            "def authenticate(provided_token, expected_token):",
            "def authenticate(provided_token, expected_token, bytes):",
        ),
        (
            "def authenticate(provided_token, expected_token):",
            "def authenticate[bytes](provided_token, expected_token):",
        ),
        ("def _check(provided_token", "def _check[type](provided_token"),
        ("def _check(provided_token", "def check(provided_token"),
        ("def _check(provided_token", "async def _check(provided_token"),
        ("_compare=compare_digest, _type=type, _bytes=bytes", "_compare=compare_digest"),
        ("_compare=compare_digest, _type=type, _bytes=bytes", "_compare=other, _type=type, _bytes=bytes"),
        ("_type=type", "_type=bytes"),
        ("_bytes=bytes", "_bytes=object"),
        ("_compare=compare_digest", "_compare: object=compare_digest"),
        ("_compare=compare_digest", "_compare=compare_digest, unrelated=None"),
        (
            "return provided_token == expected_token",
            "_compare = replacement\n            return provided_token == expected_token",
        ),
        ("return provided_token == expected_token", "return provided_token == expected_token == other"),
        ("return provided_token == expected_token", "return provided_token == expected_token  # retained rationale"),
        ("return False", "return True"),
        ("return _check(provided_token, expected_token)", "return _check"),
        ("return _check(provided_token, expected_token)", "return _check(provided_token, expected_token, replacement)"),
        (
            "return _check(provided_token, expected_token)",
            "return _check(provided_token, expected_token, _compare=replacement)",
        ),
        ("return _check(provided_token, expected_token)", "return _check(callback(), expected_token)"),
        ("return _check(provided_token, expected_token)", "return _check(request.token, expected_token)"),
        ("return _check(provided_token, expected_token)", "return _check(expected_token, provided_token)"),
        (
            "return _check(provided_token, expected_token)",
            "callback()\n    return _check(provided_token, expected_token)",
        ),
        ("return _check(provided_token, expected_token)", "yield _check(provided_token, expected_token)"),
        (
            "return _check(provided_token, expected_token)",
            "return (_check(provided_token, expected_token) for unused in (0,))",
        ),
        ("return _check(provided_token, expected_token)", "return (_check(provided_token, expected_token), globals())"),
        (
            "return _check(provided_token, expected_token)",
            "return (_check(provided_token, expected_token), request.currentframe)",
        ),
    ],
)
def test_security_autofix_refuses_unproved_type_source_capture_or_import_authority(old: str, new: str) -> None:
    assert old in _SOURCE
    source = _SOURCE.replace(old, new)
    assert _fixed(source) == source


@pytest.mark.parametrize("operator", ["==", "!="])
@pytest.mark.parametrize(
    ("provided", "expected"), [(b"a", b"a"), (b"a", b"b"), (b"", b""), (b"\0\xff", b"\0\xff"), ("a", b"a"), (1, b"a")]
)
def test_security_autofix_original_and_fixed_bytes_runtime(operator: str, provided: object, expected: object) -> None:
    original = _SOURCE.replace(" == ", f" {operator} ")
    fixed = _fixed(original)
    assert fixed != original
    assert _function(original)(provided, expected) is _function(fixed)(provided, expected)


def test_security_autofix_bytes_subclasses_keep_original_guard_fallback() -> None:
    class BytesSubclass(bytes):
        def __eq__(self, _other: object) -> bool:
            raise AssertionError

        def __hash__(self) -> int:
            return super().__hash__()

    value = BytesSubclass(b"a")
    assert _function(_SOURCE)(value, b"a") is False
    assert _function(_fixed(_SOURCE))(value, b"a") is False


@pytest.mark.parametrize(
    "captures", ["", "_compare=compare_digest", "_compare=compare_digest, _type=type, _bytes=bytes"]
)
def test_security_autofix_refuses_getters_and_preserves_simultaneous_global_mutation(captures: str) -> None:
    source = _GETTER_SOURCE.replace("_compare=compare_digest, _type=type, _bytes=bytes", captures)
    if "_type=type" not in captures:
        source = source.replace("_type(", "type(").replace(" is _bytes", " is bytes")
    fixed = _fixed(source)
    assert fixed == source
    for program in (source, fixed):
        authenticate = _function(program)

        class Settings:
            def __init__(self, target: FunctionType) -> None:
                self.target = target

            @property
            def api_key(self) -> bytes:
                self.target.__globals__.update(compare_digest=_reject_compare, type=_object_type, bytes=object)
                return b"value"

        assert authenticate(SimpleNamespace(headers={"X-API-Key": b"value"}), Settings(authenticate)) is True


def test_security_autofix_refuses_triple_capture_getter_that_mutates_live_helper_frame() -> None:
    assert _fixed(_GETTER_SOURCE) == _GETTER_SOURCE
    unsafe_design = _GETTER_SOURCE.replace(
        "provided_token == expected_token", "_compare(provided_token, expected_token)"
    )
    observed: list[object] = []
    for program in (_GETTER_SOURCE, unsafe_design):
        authenticate = _function(program)

        class Settings:
            @property
            def api_key(self) -> bytes:
                frame = currentframe()
                assert frame is not None
                caller = frame.f_back
                assert caller is not None
                caller.f_locals["_compare"] = _reject_compare
                return b"value"

        result = _invoke(authenticate, SimpleNamespace(headers={"X-API-Key": b"value"}), Settings())
        assert isinstance(result, bool)
        observed.append(result)
    assert observed == [True, False]


@pytest.mark.parametrize("nested_shadow", [False, True])
def test_security_autofix_refuses_a_local_hmac_module(tmp_path: Path, *, nested_shadow: bool) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "synthetic-auth"\n', encoding="utf-8")
    (tmp_path / "hmac.py").write_text("compare_digest = replacement\n", encoding="utf-8")
    app = tmp_path / "app"
    app.mkdir()
    if nested_shadow:
        (app / "hmac.py").write_text("compare_digest = other_replacement\n", encoding="utf-8")
    assert _fixed(_SOURCE, app / "auth.py") == _SOURCE
