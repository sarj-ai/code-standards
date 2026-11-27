from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.__main__ import analyze
from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules.no_nominal_rebrand import NoNominalRebrand


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import RuleExample


_DECLARATIONS = 'from typing import NewType\nUserId = NewType("UserId", str)\nOrgId = NewType("OrgId", str)\n'
_REBRAND = "def rebrand(organization: OrgId) -> UserId:\n    return UserId(organization)\n"


@pytest.mark.parametrize(
    ("declarations", "source", "expected"),
    [
        (_DECLARATIONS, _REBRAND, 1),
        (_DECLARATIONS.replace("from typing", "from typing_extensions"), _REBRAND, 1),
        (
            _DECLARATIONS.replace("import NewType", "import NewType as Brand").replace("= NewType(", "= Brand("),
            _REBRAND,
            1,
        ),
        (_DECLARATIONS, 'def rebrand():\n    organization: OrgId = OrgId("org")\n    return UserId(organization)\n', 1),
        (
            _DECLARATIONS,
            "class Record:\n    organization: OrgId\n\ndef rebrand(record: Record):\n    return UserId(record.organization)\n",
            1,
        ),
        (
            _DECLARATIONS,
            "class Record:\n    organization: OrgId\n\n    def rebrand(self):\n        return UserId(self.organization)\n",
            1,
        ),
        ("class Carrier: pass\n" + _DECLARATIONS.replace(", str)", ", Carrier)"), _REBRAND, 1),
        (_DECLARATIONS, _REBRAND.replace("OrgId)", "str)"), 0),
        (_DECLARATIONS, _REBRAND.replace("OrgId)", "UserId)"), 0),
        (_DECLARATIONS.replace('OrgId", str', 'OrgId", bytes'), _REBRAND, 0),
        (_DECLARATIONS, _REBRAND + "UserId = alternate\n", 0),
        (_DECLARATIONS, _REBRAND.replace("    return", "    UserId = alternate\n    return"), 0),
        (_DECLARATIONS, _REBRAND.replace("    return", '    organization = "validated"\n    return'), 0),
        (_DECLARATIONS.replace('UserId = NewType("UserId", str)', "class UserId(str): pass"), _REBRAND, 0),
        (_DECLARATIONS.replace("from typing", "from unavailable"), _REBRAND, 0),
        (
            _DECLARATIONS,
            _REBRAND.replace(
                "UserId(organization)",
                "UserId(organization)  # sarj-noqa: " + NoNominalRebrand.code + " -- explicit fixture",
            ),
            0,
        ),
        ("# @generated\n" + _DECLARATIONS, _REBRAND, 0),
        (_DECLARATIONS, "def invalid(", 0),
    ],
)
def test_source_proven_rebrands(declarations: str, source: str, expected: int) -> None:
    findings = NoNominalRebrand().check(Path("app/work.py"), declarations + source)
    assert len(findings) == expected
    assert all(finding.code == NoNominalRebrand.code and finding.severity is Severity.WARNING for finding in findings)


@pytest.mark.parametrize(
    ("imports", "annotation", "constructor", "expected"),
    [
        ("from app.ids import OrgId as Organization, UserId", "Organization", "UserId", 1),
        ("from app.ids import OrgId as Organization, UserId as User", "Organization", "User", 1),
        ("import app.ids as ids", "ids.OrgId", "ids.UserId", 1),
        ("from .ids import OrgId, UserId", "OrgId", "UserId", 1),
        ("try:\n    load_ids()\nexcept ImportError:\n    from .ids import OrgId, UserId", "OrgId", "UserId", 1),
        ("from app.ids import OrgId\nfrom elsewhere import UserId", "OrgId", "UserId", 0),
        ("from app.ids import UserId as Origin, UserId as Target", "Origin", "Target", 0),
    ],
)
def test_first_party_nominal_identity(
    tmp_path: Path, imports: str, annotation: str, constructor: str, expected: int
) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "fixture"\n', encoding="utf-8")
    package = tmp_path / "src" / "app"
    package.mkdir(parents=True)
    (package / "__init__.py").touch()
    (package / "ids.py").write_text(_DECLARATIONS, encoding="utf-8")
    target = package / "consumer.py"
    target.write_text(
        f"{imports}\ndef rebrand(organization: {annotation}):\n    return {constructor}(organization)\n",
        encoding="utf-8",
    )
    findings = analyze([NoNominalRebrand.id], [target])
    assert [(finding.code, finding.line) for finding in findings] == [
        (NoNominalRebrand.code, len(imports.splitlines()) + 2)
    ] * expected


def test_first_party_module_at_distribution_root(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "fixture"\n', encoding="utf-8")
    (tmp_path / "ids.py").write_text(_DECLARATIONS, encoding="utf-8")
    consumer = tmp_path / "consumer.py"
    consumer.write_text("from ids import OrgId, UserId\n" + _REBRAND, encoding="utf-8")
    assert [finding.code for finding in analyze([NoNominalRebrand.id], [consumer])] == [NoNominalRebrand.code]


def test_ordinary_module_can_make_a_nominal_provider_ambiguous(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "fixture"\n', encoding="utf-8")
    (tmp_path / "ids.py").write_text(_DECLARATIONS, encoding="utf-8")
    (tmp_path / "ids").mkdir()
    (tmp_path / "ids" / "__init__.py").write_text('version = "1"\n', encoding="utf-8")
    consumer = tmp_path / "consumer.py"
    consumer.write_text("from ids import OrgId, UserId\n" + _REBRAND, encoding="utf-8")

    assert analyze([NoNominalRebrand.id], [consumer]) == []


def test_next_scan_observes_new_codegen_marker(tmp_path: Path) -> None:
    client = tmp_path / "sdk" / "models" / "client.py"
    client.parent.mkdir(parents=True)
    client.write_text(_DECLARATIONS + _REBRAND, encoding="utf-8")
    assert [finding.code for finding in analyze([NoNominalRebrand.id], [client])] == [NoNominalRebrand.code]

    (tmp_path / "sdk" / "codegen.yml").touch()
    assert analyze([NoNominalRebrand.id], [client]) == []


@pytest.mark.parametrize("example", NoNominalRebrand.public_examples())
def test_public_examples(example: RuleExample) -> None:
    assert len(NoNominalRebrand().check(Path(example.focus_path), example.focus_file.source)) == example.expected_count
