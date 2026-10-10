from pathlib import Path

import pytest

from sarj_sql_lint.rule_base import is_dump_file


@pytest.mark.parametrize("marker", ["postgresql database dump", "dumped by pg_dump", "dumped from database"])
@pytest.mark.parametrize("source_template", ["SELECT '{marker}';", 'SELECT "{marker}";', "SELECT $doc${marker}$doc$;"])
def test_dump_words_in_native_sql_data_do_not_exclude_source(marker: str, source_template: str) -> None:
    assert not is_dump_file(source_template.format(marker=marker), Path("queries/events.sql"))


@pytest.mark.parametrize(
    "prefix", ["-- PostgreSQL database dump\n", "/* Dumped by pg_dump */\n", "-- Dumped from database\n"]
)
def test_native_dump_headers_are_retained(prefix: str) -> None:
    assert is_dump_file(f"{prefix}SELECT 1;", Path("queries/events.sql"))


@pytest.mark.parametrize(
    "prefix",
    [
        "SELECT 'set statement_timeout = 0; set lock_timeout = 0;';",
        "-- set statement_timeout = 0; set lock_timeout = 0;\nSELECT 1;",
        "SELECT $doc$set statement_timeout = 0; set lock_timeout = 0;$doc$;",
    ],
)
def test_dump_session_settings_require_executable_source(prefix: str) -> None:
    assert not is_dump_file(prefix, Path("queries/events.sql"))


def test_native_dump_session_settings_remain_excluded() -> None:
    assert is_dump_file("SET statement_timeout = 0;\nSET lock_timeout = 0;\nSELECT 1;")


@pytest.mark.parametrize("path", ["schema.sql", "structure.sql", "events_dump.sql", "restore/events.sql"])
def test_explicit_dump_paths_remain_excluded(path: str) -> None:
    assert is_dump_file("SELECT 1;", Path(path))
