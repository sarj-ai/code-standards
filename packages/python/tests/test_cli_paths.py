from typing import TYPE_CHECKING

from sarj_python_lint.__main__ import main


if TYPE_CHECKING:
    from pathlib import Path


def test_expand_paths_skips_uv_cache(tmp_path: Path) -> None:
    source = tmp_path / "pkg" / "app.py"
    source.parent.mkdir()
    source.write_text("x = 1\n", encoding="utf-8")

    cached = tmp_path / "pkg" / ".uv-cache" / "archive-v0" / "dep.py"
    cached.parent.mkdir(parents=True)
    cached.write_text("x = f()  # type: ignore[reportCallIssue]\n", encoding="utf-8")

    assert (
        main(
            [
                "check",
                "--rule",
                "sarj-no-report-call-issue-ignore",
                str(tmp_path / "pkg"),
            ]
        )
        == 0
    )
