from __future__ import annotations

from typing import TYPE_CHECKING

from sarj_rule_contracts import SourceCatalog

from sarj_sql_lint.__main__ import analyze


if TYPE_CHECKING:
    from pathlib import Path


def test_captured_analysis_preserves_replacement_decoding_and_newline_policy(tmp_path: Path) -> None:
    path = tmp_path / "supabase" / "migration.sql"
    path.parent.mkdir()
    raw = b"-- invalid UTF-8: \xff\r\nCREATE TABLE document (metadata json);\r\n"
    path.write_bytes(raw)
    legacy = analyze(["prefer-jsonb"], [path])
    sources = SourceCatalog()

    captured = analyze(["prefer-jsonb"], [path], sources=sources)

    assert captured == legacy
    assert len(captured) == 1
    snapshot = sources.get(path)
    assert snapshot is not None
    assert snapshot.raw == raw
