from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from sarj_sql_lint.__main__ import analyze
from sarj_sql_lint.rule_base import dollar_quoted_spans, is_generated_migration
from sarj_sql_lint.rules import REGISTRY
from sarj_sql_lint.rules.no_offset_pagination import NoOffsetPagination


if TYPE_CHECKING:
    from pathlib import Path


_MIXED_PHASES = (
    "ALTER TABLE public_example ADD COLUMN note TEXT;\n"
    "UPDATE public_example SET note = legacy_note;\n"
    "ALTER TABLE public_example DROP COLUMN legacy_note;\n"
)
_GENERATED_FORMS = (
    ("", 1),
    ("SELECT '--> statement-breakpoint';\n", 1),
    ("SELECT $doc$--> statement-breakpoint$doc$;\n", 1),
    ('SELECT "--> statement-breakpoint";\n', 1),
    ("DO $body$ BEGIN\n-- --> statement-breakpoint\nNULL; END $body$;\n", 1),
    ("--> statement-breakpoint\n", 0),
    ("SELECT 1;--> statement-breakpoint\n", 0),
    ("-- docs mention --> statement-breakpoint\n", 0),
    ("/* --> statement-breakpoint */\n", 0),
    ("-- > statement-breakpoint\n", 1),
)


@pytest.mark.parametrize(("prefix", "expected"), _GENERATED_FORMS)
@pytest.mark.parametrize("crlf", [False, True])
def test_generated_migration_marker_requires_a_file_comment(
    prefix: str, expected: int, tmp_path: Path, *, crlf: bool
) -> None:
    path = tmp_path / "supabase/migrations/001.sql"
    path.parent.mkdir(parents=True)
    source = prefix + _MIXED_PHASES
    source = source.replace("\n", "\r\n") if crlf else source
    path.write_bytes(source.encode())
    findings = analyze(["mixed-migration-phases"], [path])
    assert len(findings) == expected
    assert findings == analyze(["mixed-migration-phases"], [path])
    assert is_generated_migration(path, source) == (expected == 0)


@pytest.mark.parametrize("tag", ["doc", "文", "e\u0301", "💡", "a\u00a0b", "a\u2003b"])
def test_native_dollar_tag_classes_keep_scalar_values_opaque(tag: str, tmp_path: Path) -> None:
    literal = f"${tag}$--> statement-breakpoint${tag}$"
    source = f"SELECT {literal};\n" + _MIXED_PHASES
    assert dollar_quoted_spans(source) == ((7, 7 + len(literal)),)
    path = tmp_path / "supabase/migrations/001.sql"
    path.parent.mkdir(parents=True)
    path.write_text(source)
    assert len(analyze(["mixed-migration-phases"], [path])) == 1


@pytest.mark.parametrize("marker", ["meta/_journal.json", "migration_lock.toml", "atlas.sum"])
def test_generated_tree_ownership_remains_independent_of_source_data(marker: str, tmp_path: Path) -> None:
    generated = tmp_path / marker
    generated.parent.mkdir(parents=True, exist_ok=True)
    generated.write_text("{}")
    path = tmp_path / "supabase/migrations/001.sql"
    path.parent.mkdir(parents=True)
    assert is_generated_migration(path, "SELECT '--> statement-breakpoint';\n" + _MIXED_PHASES)


_QUERY = "SELECT id FROM public_event ORDER BY id OFFSET $1;\n"
_QUERY_FORMS = (
    ("", 1),
    ("-- @generated\n", 0),
    ("\n\t\n-- @generated\n", 0),
    ("/* @generated */\n", 1),
    ("-- generated\n", 1),
    ("SELECT '\n-- @generated\n';\n", 1),
    ("SELECT $doc$\n-- @generated\n$doc$;\n", 1),
    ("SELECT $💡$\n-- @generated\n$💡$;\n", 1),
    ('SELECT "\n-- @generated\n";\n', 1),
    ("DO $x$ BEGIN\n-- @generated\nNULL; END $x$;\n", 1),
    ("SELECT '\n-- @generated\n';\n-- @generated\n", 0),
    ("\n" * 1024 + "-- @generated\n", 1),
)


@pytest.mark.parametrize(("prefix", "expected"), _QUERY_FORMS)
@pytest.mark.parametrize("crlf", [False, True])
def test_generated_query_header_requires_a_file_comment(
    prefix: str, expected: int, tmp_path: Path, *, crlf: bool
) -> None:
    source = prefix + _QUERY
    source = source.replace("\n", "\r\n") if crlf else source
    assert len(NoOffsetPagination().check(tmp_path / "events.sql", source)) == expected


@pytest.mark.parametrize("rule", ["no-offset-pagination", "index-concurrently", "mixed-migration-phases"])
@pytest.mark.parametrize("tag", ["doc", "💡", "a\u00a0b", "e\u0301"])
@pytest.mark.parametrize("following", ["", "💡", "\u00a0", "\u2003"])
@pytest.mark.parametrize("crlf", [False, True])
def test_dollar_values_cannot_hide_subsequent_query_index_or_migration(
    rule: str, tag: str, following: str, tmp_path: Path, *, crlf: bool
) -> None:
    spec = REGISTRY[rule].native_spec()
    assert spec is not None
    example = next(example for example in spec.examples if str(example.outcome) == "match")
    prefix = f"SELECT ${tag}$\n-- @generated\n--> statement-breakpoint\n${tag}${following};\n"
    paths: list[Path] = []
    for file in example.files:
        source = (prefix if file.path == example.focus_path else "") + file.source
        source = source.replace("\n", "\r\n") if crlf else source
        path = tmp_path / str(file.path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(source.encode())
        paths.append(path)
    findings = analyze([rule], paths)
    assert sum(finding.path == tmp_path / str(example.focus_path) for finding in findings) == example.expected_count
    assert findings == analyze([rule], paths)


@pytest.mark.parametrize("tag", ["doc", "💡", "a\u00a0b"])
def test_query_header_window_can_end_inside_an_opaque_value(tag: str, tmp_path: Path) -> None:
    prefix = f"SELECT ${tag}$\n-- @generated\n" + "opaque documentation " * 100 + f"${tag}$;\n"
    assert len(NoOffsetPagination().check(tmp_path / "events.sql", prefix + _QUERY)) == 1


def test_query_header_window_keeps_a_partial_true_comment(tmp_path: Path) -> None:
    source = "-- @generated " + "header " * 200 + "\n" + _QUERY
    assert not NoOffsetPagination().check(tmp_path / "events.sql", source)
