from __future__ import annotations

from typing import TYPE_CHECKING

from sarj_python_lint.__main__ import (
    expand_paths,
)


if TYPE_CHECKING:
    from pathlib import Path


def testexpand_paths_skips_uv_cache(tmp_path: Path) -> None:
    source = tmp_path / "src" / "app.py"
    source.parent.mkdir()
    source.write_text("value = 1\n", encoding="utf-8")
    cached = tmp_path / ".uv-cache" / "archive" / "vendored.py"
    cached.parent.mkdir(parents=True)
    cached.write_text("value = 2\n", encoding="utf-8")

    assert expand_paths([tmp_path]) == [source]
