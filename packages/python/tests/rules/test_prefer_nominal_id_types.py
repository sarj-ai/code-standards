from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.__main__ import check_source, main
from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules.prefer_nominal_id_types import PreferNominalIdTypes
from sarj_python_lint.rules.require_keyword_only_swap_prone_params import RequireKeywordOnlySwapProneParams


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic, RuleExample


def _check(source: str, path: str = "app/services/files.py") -> list[Diagnostic]:
    return PreferNominalIdTypes().check(Path(path), source)


@pytest.mark.parametrize(
    "example",
    PreferNominalIdTypes.public_examples(),
    ids=[example.example_id for example in PreferNominalIdTypes.public_examples()],
)
def test_public_documentation_examples_are_executable(example: RuleExample) -> None:
    assert len(_check(example.focus_file.source, str(example.focus_file.path))) == example.expected_count


@pytest.mark.parametrize(
    ("source", "path"),
    [
        ("def move(file_id: str, folder_id: str) -> None: ...\n", "app/service.py"),
        ("def _move(file_id: str, folder_id: str) -> None: ...\n", "app/service.py"),
        ("@app.post('/')\ndef move(file_id: str, folder_id: str) -> None: ...\n", "app/routes.py"),
        (
            "from typing import override\nclass Store:\n    @override\n    def put(self, session_id: str, scenario_id: str) -> None: ...\n",
            "tests/fakes/store.py",
        ),
        ("class _Pair:\n    left_id: str\n    right_id: str\n", "tests/fakes/models.py"),
    ],
)
def test_flags_swappable_ids_in_private_decorated_and_test_boundaries(source: str, path: str) -> None:
    findings = _check(source, path)

    assert len(findings) == 1
    assert findings[0].code == "SARJ093"
    assert findings[0].severity is Severity.ERROR


@pytest.mark.parametrize(
    "source",
    [
        "def load(file_id: str) -> None: ...\n",
        "def load(file_id: str, shard_id: int) -> None: ...\n",
        "from typing import NewType\nFileId = NewType('FileId', str)\nFolderId = NewType('FolderId', str)\ndef load(file_id: FileId, folder_id: FolderId) -> None: ...\n",
        "def load(request_id: str, file_id: str) -> None: ...\n",
        "from sqlalchemy.orm import Mapped\nclass Row:\n    file_id: Mapped[str]\n    folder_id: Mapped[str]\n",
        "from pydantic import BaseModel, Field\nclass Wire(BaseModel):\n    file_id: str = Field(alias='fileId')\n    folder_id: str = Field(alias='folderId')\n",
    ],
)
def test_allows_distinct_nominal_operational_and_wire_ids(source: str) -> None:
    assert _check(source) == []


@pytest.mark.parametrize(
    "path",
    ["app/generated/client.py", "app/migrations/versions/001.py", "app/providers/github/client.py"],
)
def test_skips_generated_migrations_and_external_adapters(path: str) -> None:
    assert _check("def move(file_id: str, folder_id: str) -> None: ...\n", path) == []


def test_exact_suppression_is_recognized() -> None:
    source = (
        "def bridge(\n"
        "    legacy_id: str,  # sarj-noqa: SARJ093 — provider contract is raw\n"
        "    file_id: str,\n"
        ") -> None: ...\n"
    )
    assert _check(source) == []


def test_invalid_source_is_ignored() -> None:
    assert _check("def broken( -> None:\n") == []


def _project_check(tmp_path: Path, source: str, definitions: str) -> list[Diagnostic]:
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "example"\nversion = "0.1.0"\n')
    package = tmp_path / "example"
    package.mkdir(exist_ok=True)
    (package / "__init__.py").write_text("")
    (package / "types.py").write_text(definitions)
    path = package / "service.py"
    path.write_text(source)
    return PreferNominalIdTypes().check(path, source)


@pytest.mark.parametrize(
    "source",
    [
        "from example.types import FolderId\ndef move(file_id: str, folder_id: FolderId) -> None: ...\n",
        "from example.types import FolderId as Parent\ndef move(file_id: str, folder_id: Parent) -> None: ...\n",
        "import example.types as ids\ndef move(file_id: str, folder_id: ids.FolderId) -> None: ...\n",
        "from example.types import Raw\ndef move(file_id: Raw, folder_id: str) -> None: ...\n",
    ],
)
def test_imported_carriers_are_advisory(tmp_path: Path, source: str) -> None:
    findings = _project_check(
        tmp_path, source, "from typing import NewType\nFolderId = NewType('FolderId', str)\ntype Raw = str\n"
    )
    assert len(findings) == 1
    assert findings[0].severity is Severity.WARNING


def test_existing_domain_brands_admit_non_id_roles(tmp_path: Path) -> None:
    findings = _project_check(
        tmp_path,
        "def record(room_name: str, call_id: str) -> None: ...\n",
        "from typing import NewType\nRoomName = NewType('RoomName', str)\nCallId = NewType('CallId', str)\n",
    )
    assert len(findings) == 1
    assert findings[0].severity is Severity.WARNING


@pytest.mark.parametrize(
    "definitions",
    [
        "from unrelated import NewType\nRoomName = NewType('RoomName', str)\n",
        "from typing import NewType\nRoomName = NewType('RoomName', int)\n",
        "from typing import NewType\nRoomName = NewType('RoomName', str)\nRoomName = str\n",
        "type RoomName = str\n",
        "",
    ],
)
def test_non_id_roles_require_proven_matching_nominals(tmp_path: Path, definitions: str) -> None:
    assert _project_check(tmp_path, "def record(room_name: str, call_id: str) -> None: ...\n", definitions) == []


def test_imported_carrier_cycles_are_unknown(tmp_path: Path) -> None:
    assert (
        _project_check(
            tmp_path,
            "from example.types import Raw\ndef move(file_id: Raw, folder_id: str) -> None: ...\n",
            "type Raw = Other\ntype Other = Raw\n",
        )
        == []
    )


def test_old_errors_remain_errors_with_project_context(tmp_path: Path) -> None:
    findings = _project_check(tmp_path, "def move(file_id: str, folder_id: str) -> None: ...\n", "")
    assert len(findings) == 1
    assert findings[0].severity is Severity.ERROR


@pytest.mark.parametrize(
    "source",
    [
        "from example.types import FolderId\nFolderId = object\ndef move(file_id: str, folder_id: FolderId) -> None: ...\n",
        "import example.types as ids\nids.FolderId = object\ndef move(file_id: str, folder_id: ids.FolderId) -> None: ...\n",
        "from example.types import FolderId\ndef move(file_id: str, folder_id: FolderId) -> None: ...\ndef other(FolderId): ...\n",
        "from example.types import FolderId\ndef move(file_id: str, folder_id: FolderId) -> None: ...  # sarj-noqa: SARJ093\n",
        "from example.types import FolderId\nfrom typing import TypedDict\nclass Wire(TypedDict):\n    file_id: str\n    folder_id: FolderId\n",
    ],
)
def test_imported_expansion_preserves_shadowing_and_exclusions(tmp_path: Path, source: str) -> None:
    assert _project_check(tmp_path, source, "from typing import NewType\nFolderId = NewType('FolderId', str)\n") == []


@pytest.mark.parametrize("depends", [False, True])
def test_domain_brands_require_declared_dependency(tmp_path: Path, *, depends: bool) -> None:
    (tmp_path / ".git").mkdir()
    consumer = tmp_path / "consumer"
    consumer.mkdir()
    dependencies = '["shared-domain"]' if depends else "[]"
    (consumer / "pyproject.toml").write_text(f'[project]\nname = "consumer"\ndependencies = {dependencies}\n')
    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / "pyproject.toml").write_text('[project]\nname = "shared-domain"\n')
    (shared / "types.py").write_text("from typing import NewType\nRoomName = NewType('RoomName', str)\n")
    path = consumer / "service.py"
    source = "def record(room_name: str, call_id: str) -> None: ...\n"
    path.write_text(source)
    findings = PreferNominalIdTypes().check(path, source)
    assert len(findings) == int(depends)


def test_duplicate_domain_brand_definitions_are_unknown(tmp_path: Path) -> None:
    definitions = "from typing import NewType\nRoomName = NewType('RoomName', str)\n"
    _project_check(tmp_path, "", definitions)
    (tmp_path / "example" / "more.py").write_text(definitions)
    assert _project_check(tmp_path, "def record(room_name: str, call_id: str) -> None: ...\n", definitions) == []


def test_explicit_first_party_reexport_chain(tmp_path: Path) -> None:
    _project_check(tmp_path, "", "type Raw = str\n")
    (tmp_path / "example" / "exports.py").write_text(
        "from example.types import Raw as Carrier\ntype Export = Carrier\n"
    )
    source = "from example.exports import Export\ndef move(file_id: Export, folder_id: str) -> None: ...\n"
    findings = _project_check(tmp_path, source, "type Raw = str\n")
    assert len(findings) == 1
    assert findings[0].severity is Severity.WARNING


def test_local_established_non_id_brand_is_advisory() -> None:
    findings = _check(
        "from typing import NewType\nRoomName = NewType('RoomName', str)\ndef record(room_name: str, call_id: str) -> None: ...\n"
    )
    assert len(findings) == 1
    assert findings[0].severity is Severity.WARNING


def test_local_unrelated_newtype_factory_does_not_establish_domain() -> None:
    assert (
        _check(
            "from unrelated import NewType\nRoomName = NewType('RoomName', str)\ndef record(room_name: str, call_id: str) -> None: ...\n"
        )
        == []
    )


def test_mutated_typing_namespace_does_not_establish_brand(tmp_path: Path) -> None:
    assert (
        _project_check(
            tmp_path,
            "def record(room_name: str, call_id: str) -> None: ...\n",
            "import typing\ntyping.NewType = other_factory\nRoomName = typing.NewType('RoomName', str)\n",
        )
        == []
    )


def test_test_only_brand_does_not_prescribe_production_type(tmp_path: Path) -> None:
    _project_check(tmp_path, "", "")
    (tmp_path / "example" / "test_models.py").write_text(
        "from typing import NewType\nRoomName = NewType('RoomName', str)\n"
    )
    assert _project_check(tmp_path, "def record(room_name: str, call_id: str) -> None: ...\n", "") == []


def test_expanded_class_does_not_hide_existing_constructor_error(tmp_path: Path) -> None:
    findings = _project_check(
        tmp_path,
        "from example.types import FolderId\nclass Move:\n    file_id: str\n    folder_id: FolderId\n    def __init__(self, file_id: str, folder_id: str) -> None: ...\n",
        "from typing import NewType\nFolderId = NewType('FolderId', str)\n",
    )
    assert len(findings) == 1
    assert findings[0].severity is Severity.ERROR
    assert findings[0].line == 5


@pytest.mark.parametrize(("carrier", "exit_code"), [("FolderId", 0), ("str", 1)])
def test_native_cli_keeps_expanded_warnings_nonblocking(tmp_path: Path, carrier: str, exit_code: int) -> None:
    source = f"from example.types import FolderId\ndef move(file_id: str, folder_id: {carrier}) -> None: ...\n"
    _project_check(tmp_path, source, "from typing import NewType\nFolderId = NewType('FolderId', str)\n")
    path = tmp_path / "example" / "service.py"
    assert main(["check", "--rule", PreferNominalIdTypes.id, str(path)]) == exit_code


def test_expanded_warning_owns_generic_keyword_only_warning() -> None:
    source = "from typing import NewType\nApiKey = NewType('ApiKey', str)\ndef record(api_key: str, call_id: str) -> None: ...\n"
    findings = check_source(
        [RequireKeywordOnlySwapProneParams(), PreferNominalIdTypes()],
        Path("app/service.py"),
        source,
    )
    assert {(finding.code, finding.severity) for finding in findings} == {
        ("SARJ093", Severity.WARNING),
    }


@pytest.mark.parametrize(
    "source",
    [
        "from example.types import FolderId\ndef move(file_id: str, folder_id: 'FolderId') -> None: ...\n",
        "from example.types import Raw\ntype Local = Raw\ndef move(file_id: Local, folder_id: str) -> None: ...\n",
        "from example.types import Raw\ntype Local = Raw\ntype Next = Local\ndef move(file_id: Next, folder_id: str) -> None: ...\n",
    ],
)
def test_demanded_annotations_preserve_quotes_and_local_aliases(tmp_path: Path, source: str) -> None:
    findings = _project_check(
        tmp_path, source, "from typing import NewType\nFolderId = NewType('FolderId', str)\ntype Raw = str\n"
    )
    assert len(findings) == 1
    assert findings[0].severity is Severity.WARNING


@pytest.mark.parametrize("include_brand", [True, False])
@pytest.mark.parametrize("excluded", [True, False])
@pytest.mark.parametrize("globs", [True, False])
def test_duplicate_distribution_names_are_scoped_by_declared_workspace(
    tmp_path: Path, *, include_brand: bool, excluded: bool, globs: bool
) -> None:
    (tmp_path / ".git").mkdir()
    for product, brand in (("first", include_brand), ("second", True)):
        root = tmp_path / product
        root.mkdir()
        members = '["*"]' if globs else '["consumer", "shared"]'
        exclusions = '["shared"]' if excluded else "[]"
        (root / "pyproject.toml").write_text(f"[tool.uv.workspace]\nmembers = {members}\nexclude = {exclusions}\n")
        for member in ("consumer", "shared"):
            package = root / member
            package.mkdir()
            dependencies = '["shared"]' if member == "consumer" else "[]"
            (package / "pyproject.toml").write_text(f'[project]\nname = "{member}"\ndependencies = {dependencies}\n')
        if brand:
            (root / "shared" / "ids.py").write_text("from typing import NewType\nRoomName = NewType('RoomName', str)\n")
    path = tmp_path / "first" / "consumer" / "service.py"
    source = "def record(room_name: str, call_id: str) -> None: ...\n"
    path.write_text(source)
    findings = PreferNominalIdTypes().check(path, source)
    assert len(findings) == int(include_brand and not excluded)
