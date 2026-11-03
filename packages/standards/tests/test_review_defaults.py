from __future__ import annotations

import shutil
import subprocess
from typing import TYPE_CHECKING

import pytest

from sarj_standards.libs.adoption import review, scaffold


if TYPE_CHECKING:
    from pathlib import Path


def test_setup_preserves_attribute_overrides_and_converges(tmp_path: Path) -> None:
    attributes = tmp_path / ".gitattributes"
    original = "* text=auto\r\nspecial.test.ts -linguist-generated\r\n"
    attributes.write_bytes(original.encode())

    plan = scaffold.build_plan(tmp_path, force=False)
    updated = next(contents for path, contents in plan.writes if path == attributes)

    assert updated.endswith(original)
    assert review.attributes_with_review_defaults(updated) == updated
    assert updated.count(review.START) == 1
    assert "\n" not in updated.replace("\r\n", "")


@pytest.mark.parametrize("prefix", ["", "\ufeff"])
def test_git_collapses_test_paths_and_preserves_production_and_overrides(tmp_path: Path, prefix: str) -> None:
    attributes = review.attributes_with_review_defaults(f"{prefix}special.test.ts -linguist-generated\n")
    assert attributes.startswith(prefix + review.START)
    assert review.attributes_with_review_defaults(attributes) == attributes
    (tmp_path / ".gitattributes").write_text(attributes)
    git = shutil.which("git")
    assert git is not None
    subprocess.run([git, "-C", str(tmp_path), "init", "--quiet"], check=True)
    collapsed = (
        "test_reader.py",
        "src/test_reader.py",
        "src/reader_test.py",
        "conftest.py",
        "nested/tests/helper.py",
        "tests/fixture.json",
        "test/client.ts",
        "src/__tests__/client.ts",
        "src/__snapshots__/client.snap",
        "client.test.ts",
        "src/client.spec.tsx",
        "src/client.test.mts",
        "src/client.spec.cjs",
    )
    visible = ("src/reader.py", "src/test_adapter.ts", "src/contest.ts", "db/migrations/001.sql", "special.test.ts")
    completed = subprocess.run(
        [git, "-C", str(tmp_path), "check-attr", "-z", "linguist-generated", "--", *collapsed, *visible],
        check=True,
        capture_output=True,
    )
    fields = completed.stdout.decode().split("\0")[:-1]
    observed = dict(zip(fields[0::3], fields[2::3], strict=True))

    assert all(observed[path] == "true" for path in collapsed)
    assert all(observed[path] in {"unspecified", "unset"} for path in visible)


@pytest.mark.parametrize(
    "contents",
    [
        review.START,
        review.END,
        review.END + "\n" + review.START,
        review.START + "\n" + review.START + "\n" + review.END,
    ],
)
def test_malformed_owned_block_is_not_rewritten(contents: str) -> None:
    with pytest.raises(ValueError, match="malformed"):
        review.attributes_with_review_defaults(contents)


def test_owned_block_updates_without_touching_neighboring_attributes() -> None:
    contents = f"* text=auto\n{review.START}\nstale.test.ts linguist-generated=true\n{review.END}\ncustom.test.ts -linguist-generated\n"

    updated = review.attributes_with_review_defaults(contents)

    assert updated.startswith("* text=auto\n")
    assert updated.endswith("custom.test.ts -linguist-generated\n")
    assert "stale.test.ts" not in updated
    assert review.attributes_with_review_defaults(updated) == updated
