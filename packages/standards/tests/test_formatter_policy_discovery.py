from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from sarj_standards.libs.adoption import formatting


if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("name", [".prettierrc.json5", ".prettierrc.toml"])
def test_unsupported_standard_format_cannot_silently_reset_policy(tmp_path: Path, name: str) -> None:
    (tmp_path / name).write_text("{printWidth:120}", encoding="utf-8")

    with pytest.raises(ValueError, match="explicit formatter policy migration"):
        formatting.oxfmt_policy(tmp_path)


@pytest.mark.parametrize("name", [".prettierrc.ts", ".prettierrc.mts", ".prettierrc.cts", "prettier.config.cts"])
def test_typescript_policy_requires_pinned_migration_before_adoption(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    monkeypatch.setenv("PATH", str(tmp_path))
    (tmp_path / name).write_text("export default {printWidth:120};", encoding="utf-8")

    with pytest.raises(ValueError, match="pinned Oxfmt dependency"):
        formatting.oxfmt_policy(tmp_path)


@pytest.mark.parametrize(
    ("name", "source"),
    [
        ("package.yaml", "prettier:\n  printWidth: 120\n"),
        ("nested/.prettierrc.json", '{"printWidth":120}'),
        ("nested/.prettierignore", "generated/**\n"),
        ("nested/package.json", '{"prettier":{"printWidth":120}}'),
        ("nested/package.yaml", "prettier:\n  printWidth: 120\n"),
    ],
)
def test_root_formatter_does_not_silently_replace_unsupported_policy_scopes(
    tmp_path: Path, name: str, source: str
) -> None:
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")

    with pytest.raises(ValueError, match="requires explicit migration"):
        formatting.oxfmt_policy(tmp_path)


def test_formatter_dependency_policies_do_not_block_consumer_migration(tmp_path: Path) -> None:
    dependency = tmp_path / "node_modules" / "dependency"
    dependency.mkdir(parents=True)
    (dependency / "prettier.config.cts").write_text("module.exports={printWidth:120};", encoding="utf-8")

    assert formatting.oxfmt_policy(tmp_path)["printWidth"] == 80
