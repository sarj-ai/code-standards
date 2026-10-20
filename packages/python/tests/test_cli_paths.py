from __future__ import annotations

import cProfile
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.__main__ import (
    expand_paths,
    main,
)


if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("rule", ["prefer-match-exception-dispatch", "prefer-match-value-dispatch"])
def test_advisory_cli_rules_still_fail_unparseable_source(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], rule: str
) -> None:
    path = tmp_path / "broken.py"
    path.write_text("if value ==\n", encoding="utf-8")
    assert main(["check", "--rule", rule, str(path)]) == 2
    output = capsys.readouterr()
    assert not output.out
    assert "selected Python source could not be parsed" in output.err


@pytest.mark.parametrize("ignored", ["node_modules", ".venv", ".git", ".uv-cache", "build"])
def test_expand_paths_never_enters_ignored_directories(tmp_path: Path, ignored: str) -> None:
    source = tmp_path / "src" / "app.py"
    source.parent.mkdir()
    source.write_text("value = 1\n", encoding="utf-8")
    excluded = tmp_path / ignored
    excluded.mkdir()
    archive = excluded / "archive"
    archive.mkdir()
    (archive / "dependency.py").write_text("value = 2\n", encoding="utf-8")

    with cProfile.Profile() as profile:
        paths = expand_paths([tmp_path])
    assert paths == [source]
    scans = sum(
        entry.callcount for entry in profile.getstats() if isinstance(entry.code, str) and "scandir" in entry.code
    )
    assert scans == 2


def test_explicit_file_inside_ignored_directory_remains_supported(tmp_path: Path) -> None:
    ignored = tmp_path / "node_modules"
    ignored.mkdir()
    source = ignored / "requested.py"
    source.write_text("value = 1\n", encoding="utf-8")

    assert expand_paths([ignored]) == []
    assert expand_paths([source]) == [source]


def test_expand_paths_preserves_suffix_matching(tmp_path: Path) -> None:
    ordinary = tmp_path / "app.py"
    ordinary.write_text("value = 1\n", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("value = 2\n", encoding="utf-8")
    (tmp_path / "directory.py").mkdir()

    assert expand_paths([tmp_path]) == [ordinary]


@pytest.mark.parametrize("directory", [False, True])
def test_selected_oversized_file_cannot_silently_escape_analysis(tmp_path: Path, *, directory: bool) -> None:
    oversized = tmp_path / "service.py"
    oversized.write_bytes(b"# pyright: basic\n#" + b"x" * 500_001)
    with pytest.raises(ValueError, match="selected Python source exceeds"):
        expand_paths([tmp_path if directory else oversized])


def test_expand_paths_keeps_file_symlinks_without_following_directory_symlinks(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    external = tmp_path / "external"
    external.mkdir()
    source = external / "app.py"
    source.write_text("value = 1\n", encoding="utf-8")
    file_link = root / "linked.py"
    try:
        file_link.symlink_to(source)
        (root / "linked_directory").symlink_to(external, target_is_directory=True)
        (root / "loop").symlink_to(root, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")

    assert expand_paths([root]) == [file_link]


def test_directory_results_are_sorted_and_explicit_input_order_is_preserved(tmp_path: Path) -> None:
    paths = [tmp_path / relative for relative in ("z.py", "b/deep/c.py", "a/a.py", "b/b.py")]
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("value = 1\n", encoding="utf-8")

    assert expand_paths([tmp_path]) == sorted(paths)
    assert expand_paths(paths) == paths
