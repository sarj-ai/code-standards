from typing import TYPE_CHECKING

import pytest

from sarj_python_lint._analysis_session import AnalysisSession
from sarj_python_lint._python_target import PythonTargetFacts
from sarj_python_lint.rules.prefer_match_type_dispatch import PreferMatchTypeDispatch
from sarj_python_lint.rules.prefer_match_value_dispatch import PreferMatchValueDispatch


if TYPE_CHECKING:
    from pathlib import Path


def _project(root: Path, specification: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "pyproject.toml").write_text(f'[project]\nrequires-python = "{specification}"\n')
    path = root / "module.py"
    path.touch()
    return path


@pytest.mark.parametrize(
    ("specification", "expected"),
    [
        (">=3.9", True),
        (">=3.9.12", True),
        (">3.9.12", True),
        (">=3.9.12rc1,<3.9.13", True),
        (">3.9.2.post1,<3.9.4", True),
        (">=3.9.12.dev1,<3.9.13", True),
        (">=3.9.12rc1,<3.9.12", False),
        (">3.9.2.post1,<3.9.3", False),
        ("~=3.8.1", True),
        ("==3.9.*", True),
        (">=3.9,!=3.9.0", True),
        (">=3.9,!=3.9.*", False),
        (">=3.10", False),
        (">=3.10,<3.9", False),
        (">=2.7,<3", True),
        ("===unknown", False),
        ("===3.9", False),
        (">=1!3.9", False),
        ("invalid", False),
        ("", False),
    ],
)
def test_complete_declaration_requires_a_legacy_witness(tmp_path: Path, specification: str, expected: bool) -> None:
    path = _project(tmp_path, specification)
    assert PythonTargetFacts().has_declared_support_before(path, (3, 10)) is expected


@pytest.mark.parametrize("boundary", ["pyproject.toml", "setup.py", "setup.cfg", ".git"])
def test_nearest_boundary_does_not_inherit_parent_support(tmp_path: Path, boundary: str) -> None:
    _project(tmp_path, ">=3.9")
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / boundary).touch()
    assert not PythonTargetFacts().has_declared_support_before(nested / "module.py", (3, 10))


def test_nearest_project_owns_its_target(tmp_path: Path) -> None:
    _project(tmp_path, ">=3.9")
    path = _project(tmp_path / "nested", ">=3.10")
    assert not PythonTargetFacts().has_declared_support_before(path, (3, 10))


@pytest.mark.parametrize(
    "metadata",
    [
        "[project",
        "[project]\nrequires-python = 39",
        '[project]\ndynamic = ["requires-python"]',
        '[project]\nrequires-python = ">=3.9"\ndynamic = "invalid"',
        '[project]\nrequires-python = ">=3.9"\ndynamic = [39]',
    ],
)
def test_invalid_or_dynamic_project_metadata_is_unknown(tmp_path: Path, metadata: str) -> None:
    path = _project(tmp_path, ">=3.9")
    (tmp_path / "pyproject.toml").write_text(metadata)
    assert not PythonTargetFacts().has_declared_support_before(path, (3, 10))


def _distribution(root: Path, name: str, specification: str, owned: str | None) -> None:
    metadata = root / f"{name}-1.0.dist-info"
    metadata.mkdir(parents=True)
    (metadata / "METADATA").write_text(
        f"Metadata-Version: 2.1\nName: {name}\nVersion: 1.0\nRequires-Python: {specification}\n"
    )
    if owned is not None:
        (metadata / "RECORD").write_text(f"{owned},,\n")


def test_installed_exact_owner_takes_precedence_over_enclosing_project(tmp_path: Path) -> None:
    _project(tmp_path, ">=3.14")
    root = tmp_path / "site-packages"
    path = root / "shared_namespace" / "module.py"
    path.parent.mkdir(parents=True)
    path.touch()
    _distribution(root, "different-distribution-name", ">=3.9", "shared_namespace/module.py")
    _distribution(root, "neighbor", ">=3.14", "neighbor.py")
    assert PythonTargetFacts().has_declared_support_before(path, (3, 10))
    assert not PythonTargetFacts().has_declared_support_before(root / "unowned.py", (3, 10))


@pytest.mark.parametrize("owned", [None, "neighbor.py"])
def test_missing_installed_ownership_does_not_inherit_project(tmp_path: Path, owned: str | None) -> None:
    _project(tmp_path, ">=3.9")
    root = tmp_path / "dist-packages"
    _distribution(root, "example", ">=3.9", owned)
    path = root / "module.py"
    path.touch()
    assert not PythonTargetFacts().has_declared_support_before(path, (3, 10))


def test_conflicting_installed_owners_are_unknown(tmp_path: Path) -> None:
    root = tmp_path / "site-packages"
    _distribution(root, "first", ">=3.9", "module.py")
    _distribution(root, "second", ">=3.14", "module.py")
    path = root / "module.py"
    path.touch()
    assert not PythonTargetFacts().has_declared_support_before(path, (3, 10))


def test_installed_record_cannot_claim_external_source(tmp_path: Path) -> None:
    path = _project(tmp_path / "source", ">=3.14")
    root = tmp_path / "site-packages"
    _distribution(root, "example", ">=3.9", "../source/module.py")
    (root / "module.py").symlink_to(path)
    assert not PythonTargetFacts().has_declared_support_before(root / "module.py", (3, 10))


def test_symlink_to_installed_file_uses_installed_target(tmp_path: Path) -> None:
    _project(tmp_path, ">=3.9")
    root = tmp_path / "site-packages"
    _distribution(root, "example", ">=3.14", "module.py")
    installed = root / "module.py"
    installed.touch()
    link = tmp_path / "linked.py"
    link.symlink_to(installed)
    assert not PythonTargetFacts().has_declared_support_before(link, (3, 10))


@pytest.mark.parametrize("record", ["module.py,,,extra\n", '"module.py,,\n'])
def test_malformed_installed_record_is_unknown(tmp_path: Path, record: str) -> None:
    root = tmp_path / "site-packages"
    _distribution(root, "example", ">=3.9", "module.py")
    (root / "example-1.0.dist-info" / "RECORD").write_text(record)
    path = root / "module.py"
    path.touch()
    assert not PythonTargetFacts().has_declared_support_before(path, (3, 10))


def test_duplicate_installed_declarations_are_unknown(tmp_path: Path) -> None:
    root = tmp_path / "site-packages"
    _distribution(root, "example", ">=3.9\nRequires-Python: >=3.14", "module.py")
    path = root / "module.py"
    path.touch()
    assert not PythonTargetFacts().has_declared_support_before(path, (3, 10))


def test_unreadable_project_metadata_is_unknown(tmp_path: Path) -> None:
    path = _project(tmp_path, ">=3.9")
    (tmp_path / "pyproject.toml").write_bytes(b"\xff\xfe")
    assert not PythonTargetFacts().has_declared_support_before(path, (3, 10))


def test_facts_are_cached_only_within_one_session(tmp_path: Path) -> None:
    path = _project(tmp_path, ">=3.9")
    facts = PythonTargetFacts()
    assert facts.has_declared_support_before(path, (3, 10))
    _project(tmp_path, ">=3.14")
    assert facts.has_declared_support_before(path, (3, 10))
    assert not PythonTargetFacts().has_declared_support_before(path, (3, 10))


_VALUE_SOURCE = "if value == 'a':\n    first()\nelif value == 'b':\n    second()\nelse:\n    fallback()\n"
_TYPE_SOURCE = (
    "def parse(value):\n    if isinstance(value, str):\n        return 1\n"
    "    elif isinstance(value, bytes):\n        return 2\n"
    "    elif isinstance(value, dict):\n        return 3\n"
)


@pytest.mark.parametrize("with_session", [False, True])
def test_both_match_rules_respect_declared_target(tmp_path: Path, *, with_session: bool) -> None:
    path = _project(tmp_path, ">=3.9")
    for rule, source in [(PreferMatchValueDispatch(), _VALUE_SOURCE), (PreferMatchTypeDispatch(), _TYPE_SOURCE)]:
        if with_session:
            rule.prepare_session(AnalysisSession())
        assert rule.check(path, source) == []
    _project(tmp_path, ">=3.10")
    assert len(PreferMatchValueDispatch().check(path, _VALUE_SOURCE)) == 1
    assert len(PreferMatchTypeDispatch().check(path, _TYPE_SOURCE)) == 1


def test_same_rule_instance_without_session_refreshes_target(tmp_path: Path) -> None:
    rule = PreferMatchValueDispatch()
    path = _project(tmp_path, ">=3.9")
    assert rule.check(path, _VALUE_SOURCE) == []
    _project(tmp_path, ">=3.10")
    assert len(rule.check(path, _VALUE_SOURCE)) == 1


def test_preparing_new_session_refreshes_target(tmp_path: Path) -> None:
    rule = PreferMatchValueDispatch()
    path = _project(tmp_path, ">=3.9")
    rule.prepare_session(AnalysisSession())
    assert rule.check(path, _VALUE_SOURCE) == []
    _project(tmp_path, ">=3.10")
    assert rule.check(path, _VALUE_SOURCE) == []
    rule.prepare_session(AnalysisSession())
    assert len(rule.check(path, _VALUE_SOURCE)) == 1


@pytest.mark.parametrize("source", ["value = 1\n", "if:", "# Generated file; do not edit\n" + _VALUE_SOURCE])
def test_no_target_lookup_without_candidate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, source: str) -> None:
    def unexpected_lookup(_facts: PythonTargetFacts, _path: Path, _minimum: tuple[int, int]) -> bool:
        pytest.fail("Target metadata must not be queried without a syntactic candidate")

    monkeypatch.setattr(PythonTargetFacts, "has_declared_support_before", unexpected_lookup)
    for rule in (PreferMatchValueDispatch(), PreferMatchTypeDispatch()):
        rule.prepare_session(AnalysisSession())
        assert rule.check(tmp_path / "module.py", source) == []
