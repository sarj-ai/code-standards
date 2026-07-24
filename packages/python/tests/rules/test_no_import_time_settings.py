from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rules.no_import_time_settings import NoImportTimeSettings


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic


def _check(source: str, path: str = "python/voice/config.py") -> list[Diagnostic]:
    return NoImportTimeSettings().check(Path(path), source)


# --------------------------------------------------------------------------- #
# Positive: module-level Settings construction.                                #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "stmt",
    [
        "settings = Settings()",
        "settings = AppSettings()",
        "settings = VoiceSettings(env_file='.env')",
        "settings: Settings = Settings()",
        "settings = config.AppSettings()",
        "SETTINGS = GroqTTSSettings()",
    ],
)
def test_flags_module_level_settings(stmt: str):
    src = f"from app.config import Settings\n\n{stmt}\n"
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].code == "SARJ035"
    assert "import time" in diags[0].message


def test_message_names_the_class():
    diags = _check("settings = VoiceSettings()\n")
    assert "VoiceSettings" in diags[0].message


@pytest.mark.parametrize(
    "wrapper",
    [
        "try:\n    {stmt}\nexcept ValidationError:\n    raise",
        "if os.environ.get('ENV'):\n    {stmt}",
        "if flag:\n    pass\nelse:\n    {stmt}",
        "with warnings.catch_warnings():\n    {stmt}",
    ],
)
def test_flags_inside_module_level_blocks(wrapper: str):
    src = wrapper.format(stmt="settings = Settings()")
    assert len(_check(src)) == 1


def test_config_py_is_not_exempt():
    # The motivating incidents WERE module singletons in config.py files.
    src = "settings = Settings()\n"
    assert len(_check(src, "python/voice/config.py")) == 1
    assert len(_check(src, "app/settings.py")) == 1


@pytest.mark.parametrize(
    "path",
    [
        "tests/test_voice_migration_service.py",
        "python/bulbul/tests/store/test_voice_store.py",
        "agent/tests/conftest.py",
        "conftest.py",
        "bulbul/tests/settings.py",
        "voice_store_test.py",
    ],
)
def test_test_files_are_exempt(path: str):
    # Test-file module constants named *Settings are typically plain pydantic
    # models (TTS provider configs), not env-reading settings — and a test-local
    # singleton poisons no importer's import order.
    src = "DEFAULT_TTS = CartesiaTTSSettings(provider=p, voice='sonic')\n"
    assert _check(src, path) == []


# --------------------------------------------------------------------------- #
# Negative: deferred construction (the fix) is never flagged.                  #
# --------------------------------------------------------------------------- #


def test_allows_cached_factory():
    src = """
from functools import lru_cache

@lru_cache
def get_settings() -> Settings:
    return Settings()
"""
    assert _check(src) == []


def test_allows_construction_in_function_and_class_bodies():
    src = """
def build():
    return AppSettings()

class Container:
    settings = Settings()

    def make(self):
        s = Settings()
"""
    assert _check(src) == []


def test_allows_main_guard():
    src = """
if __name__ == "__main__":
    settings = Settings()
    run(settings)
"""
    assert _check(src) == []


def test_allows_type_checking_block():
    src = """
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    settings = Settings()
"""
    assert _check(src) == []


def test_allows_typing_dotted_type_checking_block():
    src = """
import typing

if typing.TYPE_CHECKING:
    settings = Settings()
"""
    assert _check(src) == []


# --------------------------------------------------------------------------- #
# Negative: callees that are not a Settings constructor.                       #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "stmt",
    [
        "settings = get_settings()",
        "settings = load_settings()",
        "config = SettingsConfigDict(env_prefix='APP_')",
        "settings = Settings",
        "settings = settings()",
        "model_config = ConfigDict(frozen=True)",
        "x = 1",
        "settings = Settings.model_validate(raw)",
    ],
)
def test_allows_non_constructor_values(stmt: str):
    assert _check(f"{stmt}\n") == []


def test_case_sensitive_suffix():
    assert _check("s = load_app_settings()\n") == []


# --------------------------------------------------------------------------- #
# Counts, ordering, edge cases.                                                #
# --------------------------------------------------------------------------- #


def test_multiple_hits_sorted():
    src = """
a = AppSettings()
b = DbSettings()
"""
    diags = _check(src)
    assert len(diags) == 2
    assert [(d.line, d.col) for d in diags] == sorted((d.line, d.col) for d in diags)


def test_line_col():
    diags = _check("settings = Settings()\n")
    assert (diags[0].line, diags[0].col) == (1, 1)


@pytest.mark.parametrize("source", ["", "  ", "# comment\n"])
def test_empty_or_trivial_source(source: str):
    assert _check(source) == []


def test_syntax_error_returns_empty():
    assert _check("def f(:\n    pass") == []
