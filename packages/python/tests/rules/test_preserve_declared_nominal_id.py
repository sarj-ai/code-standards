from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.__main__ import analyze
from sarj_python_lint.rules.preserve_declared_nominal_id import PreserveDeclaredNominalId


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import RuleExample


def _check(source: str, path: str = "tests/fake.py"):
    return PreserveDeclaredNominalId().check(Path(path), source)


def test_flags_exact_declared_role_at_single_id_boundary() -> None:
    source = """
from typing import NewType, override
SipTrunkId = NewType("SipTrunkId", str)
class Fake:
    @override
    def format_phone(self, sip_trunk_id: str) -> str: ...
"""
    findings = _check(source)
    assert len(findings) == 1
    assert "SipTrunkId" in findings[0].message


def test_does_not_guess_unknown_or_nearby_roles() -> None:
    source = """
from typing import NewType, override
SipTrunkId = NewType("SipTrunkId", str)
class Fake:
    @override
    def format_phone(self, input_sip_trunk_id: str, provider_id: str) -> str: ...
"""
    assert _check(source) == []


def test_project_scan_catches_test_override_from_unchanged_type_module(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    package = tmp_path / "app"
    fake_dir = package / "tests" / "fakes"
    fake_dir.mkdir(parents=True)
    for directory in (package, package / "tests", fake_dir):
        (directory / "__init__.py").write_text("", encoding="utf-8")
    namespace = package / "calls"
    namespace.mkdir()
    (namespace / "types.py").write_text(
        'from typing import NewType\nSipTrunkId = NewType("SipTrunkId", str)\n', encoding="utf-8"
    )
    fake = fake_dir / "sip.py"
    fake.write_text(
        "from typing import override\nclass Fake:\n    @override\n    def format(self, sip_trunk_id: str): ...\n",
        encoding="utf-8",
    )
    findings = analyze(["preserve-declared-nominal-id"], [fake])
    assert len(findings) == 1


def test_ordinary_test_helper_remains_excluded() -> None:
    source = """
from typing import NewType
SipTrunkId = NewType("SipTrunkId", str)
def helper(sip_trunk_id: str): ...
"""
    assert _check(source, "tests/helpers.py") == []


def test_production_boundary_remains_owned_by_sarj093() -> None:
    source = """
from typing import NewType
SipTrunkId = NewType("SipTrunkId", str)
def format_phone(sip_trunk_id: str): ...
"""
    assert _check(source, "app/service.py") == []


@pytest.mark.parametrize("example", PreserveDeclaredNominalId.public_examples())
def test_public_examples(example: RuleExample) -> None:
    focus = example.focus_file
    assert len(_check(focus.source, str(focus.path))) == example.expected_count
