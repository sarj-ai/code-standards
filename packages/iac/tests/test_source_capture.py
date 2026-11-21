from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sarj_rule_contracts import SourceCatalog

from sarj_iac_lint.__main__ import analyze


if TYPE_CHECKING:
    from pathlib import Path


def test_captured_analysis_preserves_utf8_and_newline_policy(tmp_path: Path) -> None:
    path = tmp_path / "main.tf"
    raw = b'# UTF-8: \xc3\xa9\r\nlocals {\r\n  tier = var.environment == "prod" ? "HA" : "BASIC"\r\n}\r\n'
    path.write_bytes(raw)
    legacy = analyze(["no-environment-conditional"], [path])
    sources = SourceCatalog()

    captured = analyze(["no-environment-conditional"], [path], sources=sources)

    assert captured == legacy
    assert len(captured) == 1
    snapshot = sources.get(path)
    assert snapshot is not None
    assert snapshot.raw == raw


@pytest.mark.parametrize("capture", [False, True])
def test_invalid_utf8_cannot_qualify(tmp_path: Path, capture: bool) -> None:
    path = tmp_path / "main.tf"
    path.write_bytes(b"# invalid UTF-8: \xff\nlocals {}\n")

    with pytest.raises(UnicodeDecodeError):
        analyze(["no-environment-conditional"], [path], sources=SourceCatalog() if capture else None)
