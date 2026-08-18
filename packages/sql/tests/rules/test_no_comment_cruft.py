from pathlib import Path

import pytest

from sarj_sql_lint.rules.no_comment_cruft import NoCommentCruft


_DEBT_MARKER = "TO" + "DO"


def _check(source: str, name: str = "migration.sql"):
    return NoCommentCruft().check(Path(name), source)


@pytest.mark.parametrize(
    "source",
    [
        "-- DROP TABLE legacy;\nSELECT 1;",
        "/* CREATE TABLE old (id bigint); */\nSELECT 1;",
        "-- ===== legacy =====\nSELECT 1;",
        f"-- {_DEBT_MARKER} remove old rows\nSELECT 1;",
        "-- SELECT id\n-- FROM legacy\n-- WHERE active;\nSELECT 1;",
        "-- CREATE UNIQUE INDEX old_idx ON legacy (id);\nSELECT 1;",
        "/* DROP TABLE legacy;\n * sarj-noqa: SARJ999\n */\nSELECT 1;",
    ],
)
def test_flags_comment_cruft(source: str) -> None:
    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    "source",
    [
        "SELECT '-- DROP TABLE live';",
        "DO $$ BEGIN RAISE NOTICE '-- DROP TABLE live'; END $$;",
        "{% if enabled %}\nSELECT 1;\n{% endif %}\n{# ---------- section ---------- #}",
        "-- create or replace the table instead of dropping it\nSELECT 1;",
        "-- migrate:up\nSELECT 1;",
        "-- Roll back from snapshot OPS-812.\nSELECT 1;",
        f"-- {_DEBT_MARKER} tracked in DB-812\nSELECT 1;",
        "-- The replica must be updated before this statement.\nSELECT 1;",
        "-- CREATE TABLE statements must use bigint IDs.\nSELECT 1;",
        "-- ===== See RFC 9110 =====\nSELECT 1;",
    ],
)
def test_preserves_non_cruft_comments(source: str) -> None:
    assert _check(source) == []


def test_skips_dump_files() -> None:
    assert _check("-- PostgreSQL database dump\n-- DROP TABLE legacy;", "schema.sql") == []


def test_public_examples_execute() -> None:
    examples = NoCommentCruft.public_examples()
    assert [len(_check(example.focus_file.source)) for example in examples] == [1, 0]
