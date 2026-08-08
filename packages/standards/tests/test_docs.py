from __future__ import annotations

import json
from pathlib import Path

import pytest

from sarj_standards.libs.repository import docs


REPO_ROOT = Path(__file__).resolve().parents[3]


def _repository(root: Path) -> None:
    packages = {
        "standards": ("pyproject.toml", '[project]\nname = "sarj-standards"\n'),
        "python": ("pyproject.toml", '[project]\nname = "sarj-python-lint"\n'),
        "sql": ("pyproject.toml", '[project]\nname = "sarj-sql-lint"\n'),
        "iac": ("pyproject.toml", '[project]\nname = "sarj-iac-lint"\n'),
        "typescript": ("package.json", '{"name":"@sarj/eslint-plugin"}\n'),
        "tsconfig": ("package.json", '{"name":"@sarj/tsconfig"}\n'),
    }
    for directory, (filename, content) in packages.items():
        path = root / "packages" / directory / filename
        path.parent.mkdir(parents=True)
        path.write_text(content, encoding="utf-8")
    ledger = root / "packages/standards/src/sarj_standards/configs/rule-ledger.json"
    ledger.parent.mkdir(parents=True)
    ledger.write_text(
        json.dumps({"rules": {"eslint": ["one", "two"], "python": ["one"], "sql": [], "iac": [], "text": []}}),
        encoding="utf-8",
    )
    (root / "README.md").write_text(
        "# Standards\n\n<!-- generated:packages:start -->\nstale\n<!-- generated:packages:end -->\n\n"
        "<!-- generated:rules:start -->\nstale\n<!-- generated:rules:end -->\n",
        encoding="utf-8",
    )
    for relative in (
        "CLAUDE.md",
        ".github/SECURITY.md",
        "packages/standards/README.md",
        "packages/python/README.md",
        "packages/sql/README.md",
        "packages/iac/README.md",
        "packages/typescript/README.md",
        "packages/tsconfig/README.md",
        "plugins/sarj-audit/README.md",
    ):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# {path.stem}\n", encoding="utf-8")


def test_check_reports_drift_without_writing(tmp_path: Path) -> None:
    _repository(tmp_path)
    before = (tmp_path / "README.md").read_bytes()

    result = docs.check(tmp_path)

    assert result.status == 1
    assert result.changed == (tmp_path / "README.md",)
    assert (tmp_path / "README.md").read_bytes() == before


def test_sync_is_deterministic_and_check_then_passes(tmp_path: Path) -> None:
    _repository(tmp_path)

    first = docs.sync(tmp_path)
    rendered = (tmp_path / "README.md").read_text(encoding="utf-8")
    second = docs.sync(tmp_path)

    assert first.status == 1
    assert second.status == 0
    assert docs.check(tmp_path).status == 0
    assert "| [`sarj-standards`](packages/standards/)" in rendered
    assert "| TypeScript | 2 |" in rendered


def test_missing_or_duplicated_markers_fail_loudly(tmp_path: Path) -> None:
    _repository(tmp_path)
    (tmp_path / "README.md").write_text("# no generated sections\n", encoding="utf-8")

    with pytest.raises(ValueError, match="exactly one"):
        docs.check(tmp_path)


def test_broken_local_link_fails_loudly(tmp_path: Path) -> None:
    _repository(tmp_path)
    (tmp_path / "CLAUDE.md").write_text("[missing](does-not-exist.md)\n", encoding="utf-8")

    with pytest.raises(ValueError, match="missing local target"):
        docs.check(tmp_path)


def test_broken_local_heading_link_fails_loudly(tmp_path: Path) -> None:
    _repository(tmp_path)
    (tmp_path / "CLAUDE.md").write_text("[missing](README.md#absent-heading)\n", encoding="utf-8")

    with pytest.raises(ValueError, match="missing Markdown heading"):
        docs.check(tmp_path)


def test_stale_command_example_fails_loudly(tmp_path: Path) -> None:
    _repository(tmp_path)
    (tmp_path / "packages/standards/README.md").write_text("```bash\nsarj-standards init\n```\n", encoding="utf-8")

    with pytest.raises(ValueError, match="invalid command example"):
        docs.check(tmp_path)


def test_repository_generated_documentation_has_no_drift() -> None:
    assert docs.check(REPO_ROOT).status == 0
