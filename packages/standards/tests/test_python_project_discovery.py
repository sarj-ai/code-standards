from __future__ import annotations

from pathlib import Path

import pytest

from sarj_standards.libs.diagnostics import Completion, TrustMode
from sarj_standards.libs.linting.external import analyze_external


_PROJECT = '[project]\nname = "example"\nversion = "0.0.0"\ndependencies = []\n[tool.ruff]\n[tool.basedpyright]\n'


@pytest.mark.parametrize(
    ("capability", "outer", "inner"),
    [
        ("pyright", "basedpyright:.", "basedpyright:nested"),
        ("ruff", "ruff", "ruff:nested"),
        ("deptry", "deptry:.", "deptry:nested"),
    ],
    ids=("basedpyright", "ruff", "deptry"),
)
def test_grouping_observes_added_and_removed_nested_configuration(
    tmp_path: Path, capability: str, outer: str, inner: str
) -> None:
    root = tmp_path.resolve()
    (root / "pyproject.toml").write_text(_PROJECT, encoding="utf-8")
    nested = root / "nested"
    source = nested / "src"
    source.mkdir(parents=True)
    files = tuple(str(source / name) for name in ("a.py", "b.py"))
    for path in files:
        Path(path).write_text("value = 1\n", encoding="utf-8")

    def assert_group(invocation: str) -> None:
        (report,) = analyze_external(files, root=root, trust=TrustMode.SAFE, capabilities=frozenset({capability}))
        assert report.completion is Completion.COMPLETE, report.issues
        assert not report.diagnostics
        assert report.invocation_id == invocation
        assert report.file_count == len(files)

    assert_group(outer)
    configuration = nested / "pyproject.toml"
    configuration.write_text(_PROJECT, encoding="utf-8")
    assert_group(inner)
    configuration.unlink()
    assert_group(outer)


def test_deptry_observes_configuration_added_after_an_unowned_selection(tmp_path: Path) -> None:
    root = tmp_path.resolve()
    files = tuple(str(root / name) for name in ("a.py", "b.py"))
    for path in files:
        Path(path).write_text("value = 1\n", encoding="utf-8")
    capabilities = frozenset({"deptry"})
    assert analyze_external(files, root=root, trust=TrustMode.SAFE, capabilities=capabilities) == ()
    (root / "pyproject.toml").write_text(_PROJECT, encoding="utf-8")
    (report,) = analyze_external(files, root=root, trust=TrustMode.SAFE, capabilities=capabilities)
    assert report.completion is Completion.COMPLETE, report.issues
    assert not report.diagnostics
    assert report.file_count == len(files)
