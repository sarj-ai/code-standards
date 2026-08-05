"""Directory expansion must never lint dependency or tool caches."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sarj_python_lint.__main__ import _expand_paths  # pyright: ignore[reportPrivateUsage]


if TYPE_CHECKING:
    from pathlib import Path


def test_expand_paths_skips_uv_cache(tmp_path: Path) -> None:
    source = tmp_path / "src" / "app.py"
    source.parent.mkdir()
    source.write_text("value = 1\n", encoding="utf-8")
    cached = tmp_path / ".uv-cache" / "archive" / "vendored.py"
    cached.parent.mkdir(parents=True)
    cached.write_text("value = 2\n", encoding="utf-8")

    assert _expand_paths([tmp_path]) == [source]
