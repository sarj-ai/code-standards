from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze
from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules.prefer_named_literal_alias import PreferNamedLiteralAlias


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic


_TRANSFER_LITERAL = 'Literal["domestic", "internal"]'
_CARD_LITERAL = 'Literal["charge", "debit", "prepaid"]'


def _lines(source: str) -> list[int]:
    return [item.line for item in PreferNamedLiteralAlias().check(Path("app/case.py"), source)]


def test_documented_examples() -> None:
    verify_native_rule(PreferNamedLiteralAlias, analyze)


@pytest.mark.parametrize(
    ("source", "line"),
    [
        ('from typing import Literal\ndef f() -> Literal["a", "b"] | None: ...\n', 2),
        ('import typing\ndef f(x: list[typing.Literal["a", "b"]]) -> None: ...\n', 2),
        ("from typing_extensions import Literal as L\nasync def f(*args: L[1, 2]) -> None: ...\n", 2),
        ('from typing import Literal\nstatus: Literal["played", "skipped"]\n', 2),
        ('from typing import Literal, Optional\nclass Event:\n    status: Optional[Literal["played", "skipped"]]\n', 3),
        ("from typing_extensions import Literal\ndef f(x: \"Literal['a', 'b']\") -> None: ...\n", 2),
        ("from typing import Literal, Optional\ndef f(x: Optional[\"Literal['a', 'b']\"]) -> None: ...\n", 2),
    ],
    ids=["nullable-return", "nested-parameter", "aliased-import-vararg", "variable", "field", "quoted", "nested-quote"],
)
def test_reports_inline_multi_member_literal(source: str, line: int) -> None:
    assert _lines(source) == [line]


@pytest.mark.parametrize(
    "source",
    [
        'from typing import Literal\ntype Kind = Literal["a", "b"]\ndef f(kind: Kind) -> None: ...\n',
        'from typing import Literal\nclass Event:\n    event: Literal["played"] = "played"\n',
        'from typing import Literal, cast\nvalue = cast(Literal["a", "b"], "a")\n',
        'from typing import Literal\nKind = Literal["a", "b"]\n',
        'from somewhere import Literal\ndef f(x: Literal["a", "b"]) -> None: ...\n',
        'from typing import Literal\ndef f(x: "Literal[") -> None: ...\n',
        'from typing import Literal\ndef f(x: Literal["Literal[1, 2]"]) -> None: ...\n',
        'from typing import Annotated, Literal\ndef f(x: Annotated[str, "Literal[1, 2]"]) -> None: ...\n',
        (
            'from typing import Literal\ndef f(x: Literal["a", "b"]) -> None: ...  '
            "# sarj-noqa: SARJ586 -- Wire contract mirrors an external schema.\n"
        ),
    ],
    ids=[
        "type-alias",
        "single-member-tag",
        "runtime-cast",
        "assigned-alias",
        "foreign-literal",
        "invalid-quote",
        "literal-string",
        "metadata-string",
        "suppressed",
    ],
)
def test_accepts_named_or_single_member_literal(source: str) -> None:
    assert _lines(source) == []


def _write(root: Path, files: dict[str, str]) -> list[Path]:
    paths: list[Path] = []
    for name, source in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
        paths.append(path)
    return paths


def _distribution(root: Path, files: dict[str, str]) -> list[Diagnostic]:
    _write(root, {"pyproject.toml": '[project]\nname = "example"\n'})
    return analyze(
        [PreferNamedLiteralAlias.id], [path for path in _write(root, files) if path.suffix in {".py", ".pyi"}]
    )


@pytest.mark.parametrize(
    ("canonical", "duplicate", "members"),
    [
        ("CardKind", "CardKindName", '"charge", "debit", "prepaid"'),
        ("MtdTenor", "MurabahaTenor", '"ONE_WEEK", "ONE_MONTH", "THREE_MONTHS", "SIX_MONTHS"'),
        ("TransferType", "TransferType", '"domestic", "internal"'),
    ],
)
def test_reports_duplicate_alias_once(tmp_path: Path, canonical: str, duplicate: str, members: str) -> None:
    items = _distribution(
        tmp_path,
        {
            "src/app/models.py": f"from typing import Literal\n{canonical} = Literal[{members}]\n",
            "src/app/settings.py": (
                f"from typing_extensions import Literal, TypeAlias\n{duplicate}: TypeAlias = Literal[{members}]\n"
            ),
        },
    )
    [item] = items
    assert item.path.name == "settings.py"
    assert item.severity is Severity.WARNING
    assert f"`{canonical}` from `app.models`" in item.message


def test_inline_literal_suggests_the_existing_alias(tmp_path: Path) -> None:
    [item] = _distribution(
        tmp_path,
        {
            "src/app/models.py": f"from typing import Literal\ntype TransferType = {_TRANSFER_LITERAL}\n",
            "src/app/agent.py": 'from typing import Literal\ndef transfer(kind: Literal["internal", "domestic"]): ...\n',
        },
    )
    assert "Reuse the existing Literal alias `TransferType` from `app.models`" in item.message


@pytest.mark.parametrize("declaration", ["type Source = {literal}", "def report(source: {literal}): ..."])
def test_literal_mirrors_the_unique_enum(tmp_path: Path, declaration: str) -> None:
    literal = 'Literal["collected_data", "standard", "variable"]'
    [item] = _distribution(
        tmp_path,
        {
            "src/app/message.py": "from typing import Literal\n" + declaration.format(literal=literal),
            "src/app/report_column.py": (
                "from enum import StrEnum\nclass ColumnSource(StrEnum):\n"
                '    STANDARD = "standard"\n    VARIABLE = "variable"\n    COLLECTED_DATA = "collected_data"\n'
            ),
        },
    )
    assert "mirrors `ColumnSource` from `app.report_column`" in item.message


@pytest.mark.parametrize(
    "neighbor",
    [
        'from typing import Literal\ntype Outcome = Literal["error", "success"]\n',
        (
            'from enum import StrEnum\nclass Transfer(StrEnum):\n    DOMESTIC = "domestic"\n    INTERNAL = "internal"\n'
            '    INTERNATIONAL = "international"\n'
        ),
        (
            'from enum import Enum\nclass Transfer(Enum):\n    DOMESTIC = "domestic"\n    INTERNAL = "internal"\n'
            "    OTHER = 1\n"
        ),
        (
            'from enum import StrEnum, auto\nclass Transfer(StrEnum):\n    DOMESTIC = "domestic"\n    INTERNAL = "internal"\n'
            "    UNKNOWN = auto()\n"
        ),
        f"# @generated\nfrom typing import Literal\ntype TransferType = {_TRANSFER_LITERAL}\n",
        f"from typing import Literal\ntype TransferType = {_TRANSFER_LITERAL}\nTransferType = str\n",
        "from .models import TransferType as TransferType\n",
        'from .models import TransferType\nfrom typing import Literal\ntype Transfer = Literal[TransferType, "internal"]\n',
    ],
    ids=[
        "different-values",
        "enum-superset",
        "mixed-enum",
        "computed-enum",
        "generated",
        "rebound",
        "reexport",
        "composite",
    ],
)
def test_does_not_suggest_unproven_declarations(tmp_path: Path, neighbor: str) -> None:
    assert (
        _distribution(
            tmp_path,
            {
                "src/app/models.py": f"from typing import Literal\ntype TransferType = {_TRANSFER_LITERAL}\n",
                "src/app/neighbor.py": neighbor,
            },
        )
        == []
    )


def test_abstains_on_unrelated_small_aliases(tmp_path: Path) -> None:
    assert (
        _distribution(
            tmp_path,
            {
                "src/app/models.py": 'from typing import Literal\ntype Outcome = Literal["error", "success"]\n',
                "src/app/settings.py": 'from typing import Literal\ntype Result = Literal["success", "error"]\n',
            },
        )
        == []
    )


def test_accepts_an_alias_in_the_modules_own_stub(tmp_path: Path) -> None:
    alias = f"from typing import Literal\ntype CardKind = {_CARD_LITERAL}\n"
    assert _distribution(tmp_path, {"src/app/cards.py": alias, "src/app/cards.pyi": alias}) == []


def test_ambiguous_aliases_keep_the_generic_inline_warning(tmp_path: Path) -> None:
    [item] = _distribution(
        tmp_path,
        {
            "src/app/cards.py": f"from typing import Literal\ntype CardKind = {_CARD_LITERAL}\n",
            "src/app/config.py": f"from typing import Literal\ntype CardKindName = {_CARD_LITERAL}\n",
            "src/app/names.py": f"from typing import Literal\ntype CardName = {_CARD_LITERAL}\n",
            "src/app/wire.py": f"from typing import Literal\ncard: {_CARD_LITERAL}\n",
        },
    )
    assert item.path.name == "wire.py"
    assert "Name this Literal domain" in item.message


def test_ambiguous_enums_do_not_match_an_alias(tmp_path: Path) -> None:
    enum_body = 'from enum import Enum\nclass Transfer(Enum):\n    DOMESTIC = "domestic"\n    INTERNAL = "internal"\n'
    assert (
        _distribution(
            tmp_path,
            {
                "src/app/first.py": enum_body,
                "src/app/second.py": enum_body,
                "src/app/types.py": f"from typing import Literal\ntype TransferType = {_TRANSFER_LITERAL}\n",
            },
        )
        == []
    )


def test_does_not_join_distributions_even_with_a_dependency(tmp_path: Path) -> None:
    module = 'from typing import Literal\ntype BeneficiaryStatus = Literal["active", "pending"]\n'
    paths = _write(
        tmp_path,
        {
            "bank_stub/pyproject.toml": '[project]\nname = "bank-stub"\n',
            "sidecar/pyproject.toml": '[project]\nname = "sidecar"\ndependencies = ["bank-stub"]\n',
            "bank_stub/src/bank_stub/domain.py": module,
            "sidecar/src/sidecar/domain.py": module,
        },
    )
    assert analyze([PreferNamedLiteralAlias.id], paths[2:]) == []


def test_excludes_nested_setup_distribution(tmp_path: Path) -> None:
    alias = f"from typing import Literal\ntype CardKind = {_CARD_LITERAL}\n"
    assert (
        _distribution(
            tmp_path,
            {
                "src/app/cards.py": alias,
                "legacy/setup.cfg": "[metadata]\nname = legacy\n",
                "legacy/cards.py": alias,
            },
        )
        == []
    )


def test_suppresses_a_duplicate_alias(tmp_path: Path) -> None:
    assert (
        _distribution(
            tmp_path,
            {
                "src/app/cards.py": f"from typing import Literal\ntype CardKind = {_CARD_LITERAL}\n",
                "src/app/config.py": (
                    f"from typing import Literal\ntype CardKindName = {_CARD_LITERAL}  "
                    "# sarj-noqa: SARJ586 -- Wire contract mirrors an external schema.\n"
                ),
            },
        )
        == []
    )
