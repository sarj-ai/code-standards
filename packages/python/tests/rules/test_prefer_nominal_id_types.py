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


@pytest.mark.parametrize(
    ("imports", "decorator"),
    [
        ("from typing import override", "override"),
        ("from typing import override as inherited", "inherited"),
        ("import typing as types", "types.override"),
        ("from typing_extensions import override", "override"),
    ],
)
def test_inherited_override_preserves_public_raw_id_contract(imports: str, decorator: str) -> None:
    source = (
        f"{imports}\nfrom external_api import TransportPort\n"
        "class Adapter(TransportPort):\n"
        f"    @{decorator}\n"
        "    def route(self, source_id: str, destination_id: str) -> str:\n"
        "        return source_id + destination_id\n"
    )

    assert _check(source) == []
    independent = source + "def internal(file_id: str, folder_id: str) -> None: ...\n"
    assert len(_check(independent)) == 1


@pytest.mark.parametrize(
    "source",
    [
        "from foreign import override\nclass Adapter:\n    @override\n    def route(self, source_id: str, destination_id: str) -> None: ...\n",
        "from typing import override\ndef override(value): return value\nclass Adapter:\n    @override\n    def route(self, source_id: str, destination_id: str) -> None: ...\n",
    ],
)
def test_noncanonical_or_noninherited_override_does_not_hide_owned_ids(source: str) -> None:
    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    "suffix",
    [
        "def unrelated(inherited: object) -> None: pass\n",
        "inherited = object()\n",
    ],
)
def test_declaration_time_override_alias_survives_later_or_unrelated_binding(suffix: str) -> None:
    source = (
        "from typing import override as inherited\n"
        "from external_api import TransportPort\n"
        "class Adapter(TransportPort):\n"
        "    @inherited\n"
        "    def route(self, source_id: str, destination_id: str) -> str:\n"
        "        return source_id + destination_id\n"
    )

    assert _check(source + suffix) == []


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


@pytest.mark.parametrize(
    ("definitions", "expected"),
    [
        (
            "import typing\nRoomName = typing.ＮｅｗＴｙｐｅ('RoomName', str)\nCallId = typing.ＮｅｗＴｙｐｅ('CallId', str)\n",
            1,
        ),
        (
            "import ｔｙｐｉｎｇ\nRoomName = ｔｙｐｉｎｇ.ＮｅｗＴｙｐｅ('RoomName', str)\nCallId = ｔｙｐｉｎｇ.ＮｅｗＴｙｐｅ('CallId', str)\n",
            1,
        ),
        ("import unrelated as typing\nRoomName = typing.ＮｅｗＴｙｐｅ('RoomName', str)\n", 0),
        ("import typing\nRoomName = typing.ＮｅｗＴｙｐｅ('RoomName', int)\n", 0),
        ("RoomName = 'ＮｅｗＴｙｐｅ'\nCallId = 'CallId'\n", 0),
        ("import typing\nRoomName = typing.ＮｅｗＴｙｐｅ('RoomName', str)\ntyping = unrelated\n", 0),
    ],
)
def test_native_normalized_nonfocus_factory_keeps_canonical_role_ownership(
    tmp_path: Path, definitions: str, expected: int
) -> None:
    diagnostics = _project_check(tmp_path, "def record(room_name: str, call_id: str) -> None: ...\n", definitions)
    assert len(diagnostics) == expected
    assert all(item.code == "SARJ093" and item.severity is Severity.WARNING for item in diagnostics)


@pytest.mark.parametrize(
    ("imports", "first", "second"),
    [
        ("", "int", "int"),
        ("from uuid import UUID as Key\n", "Key", "Key"),
        ("import uuid as identifiers\n", "identifiers.UUID", "identifiers.UUID"),
        ("import builtins as native\n", "native.str", "str"),
        ("from typing import List\n", "list[str]", "List[str]"),
        ("from typing import Optional\n", "Optional[str]", "str | None"),
        ("from typing import Annotated\n", "Annotated[str, 'wire']", "str"),
        ("from typing_extensions import Annotated as Meta\n", "Meta[str, 'wire']", "str"),
        ("from typing import Union\n", "Union[str, None]", "None | str"),
        ("from collections.abc import Sequence as Seq\n", "Seq[str]", "Seq[str]"),
        ("", "tuple[str, ...]", "tuple[str, ...]"),
        ("", "list[set[str]]", "list[set[str]]"),
    ],
)
def test_proven_carriers_preserve_aliases_and_container_shapes(imports: str, first: str, second: str) -> None:
    source = f"{imports}def move(left_id: {first}, right_id: {second}) -> None: ...\n"
    diagnostics = _check(source)
    assert len(diagnostics) == 1
    assert diagnostics[0].severity is Severity.ERROR


@pytest.mark.parametrize(
    ("imports", "first", "second"),
    [
        ("", "str", "int"),
        ("", "list[str]", "set[str]"),
        ("", "str", "list[str]"),
        ("", "tuple[str, str]", "tuple[str, str]"),
        ("", "dict[str, str]", "dict[str, str]"),
        ("", "str | int", "str"),
        ("from typing import Any\n", "str | Any", "str"),
        ("from typing import Literal\n", "Literal['dev']", "str"),
        ("from other import Sequence\n", "Sequence[str]", "Sequence[str]"),
        ("from other import UUID\n", "UUID", "UUID"),
        ("", "'invalid['", "str"),
        ("", "None", "None"),
    ],
)
def test_unlike_or_unknown_carriers_do_not_prove_swappability(imports: str, first: str, second: str) -> None:
    assert _check(f"{imports}def move(left_id: {first}, right_id: {second}) -> None: ...\n") == []


@pytest.mark.parametrize(
    "source",
    [
        "def move(left_id: str, /, right_id: str) -> None: ...\n",
        "def move(*, left_id: str, right_id: str) -> None: ...\n",
        "def move(left_id: str, *right_ids: str) -> None: ...\n",
        "async def move(left_id: str, right_id: str) -> None: ...\n",
        "class Store:\n    def move(self, left_id: str, right_id: str) -> None: ...\n",
    ],
)
def test_signature_forms_still_expose_role_confusion(source: str) -> None:
    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    "source",
    [
        "def configure(service_version: str = 'dev') -> None: ...\n",
        "def configure(service_version: str = 'dev', protocol_version: str = 'v1') -> None: ...\n",
        "def configure(service_version: str = 'dev', file_id: str = '') -> None: ...\n",
        "def configure(file_id: str, **values: str) -> None: ...\n",
        "def configure(file_id, folder_id) -> None: ...\n",
        "def outer():\n    def move(left_id: str, right_id: str) -> None: ...\n",
        "class WireSettings:\n    left_id: str\n    right_id: str\n",
        "from typing import TypedDict as Wire\nclass Payload(Wire):\n    left_id: str\n    right_id: str\n",
    ],
)
def test_defaults_and_unproven_roles_do_not_invent_domain_types(source: str) -> None:
    assert _check(source) == []


@pytest.mark.parametrize(
    "prefix",
    [
        "type Raw = str\nRaw = object\n",
        "type Raw = str\ndel Raw\n",
        "type Raw = str\nRaw += suffix\n",
        "type Raw = str\nif condition:\n    Raw = object\n",
        "type Raw = str\ndef other(Raw): ...\n",
        "type Raw = str\ntry: ...\nexcept Exception as Raw: ...\n",
        "type Raw = str\nmatch value:\n    case Raw: ...\n",
        "type Raw[str] = str\n",
    ],
)
def test_unstable_local_carrier_aliases_are_unknown(prefix: str) -> None:
    assert _check(f"{prefix}def move(left_id: Raw, right_id: str) -> None: ...\n") == []


@pytest.mark.parametrize(
    "source",
    [
        "def move[str](left_id: str, right_id: str) -> None: ...\n",
        "class Pair[str]:\n    left_id: str\n    right_id: str\n",
        "class Pair[str]:\n    def move(self, left_id: str, right_id: str) -> None: ...\n",
        "type Raw = str\ndef move[Raw](left_id: Raw, right_id: str) -> None: ...\n",
        "from uuid import UUID\ndef move[UUID](left_id: UUID, right_id: UUID) -> None: ...\n",
    ],
)
def test_type_parameters_do_not_resolve_to_outer_carriers(source: str) -> None:
    assert _check(source) == []


def test_unrelated_type_parameter_preserves_proven_ids() -> None:
    assert len(_check("def move[T](left_id: str, right_id: str, value: T) -> None: ...\n")) == 1


@pytest.mark.parametrize(
    "definitions",
    [
        "from typing import NewType\nFolderId = NewType('WrongName', str)\n",
        "from typing import NewType\nFolderId = NewType('FolderId', str, extra)\n",
        "from typing import NewType\nFolderId = NewType('FolderId', str, extra=True)\n",
        "from typing import NewType\nFolderId = NewType(name, str)\n",
        "import typing\ntyping.NewType = other\nFolderId = typing.NewType('FolderId', str)\n",
        "import typing\ndel typing.NewType\nFolderId = typing.NewType('FolderId', str)\n",
        "import typing\nsetattr(typing, 'NewType', other)\nFolderId = typing.NewType('FolderId', str)\n",
        "import typing\ndelattr(typing, 'NewType')\nFolderId = typing.NewType('FolderId', str)\n",
        "import typing\nfrom builtins import setattr as change\nchange(typing, 'NewType', other)\nFolderId = typing.NewType('FolderId', str)\n",
        "import typing\ntyping.__dict__['NewType'] = other\nFolderId = typing.NewType('FolderId', str)\n",
        "import typing\ntyping.__setattr__('NewType', other)\nFolderId = typing.NewType('FolderId', str)\n",
    ],
)
def test_nominal_carriers_require_an_unmodified_valid_factory(definitions: str) -> None:
    assert _check(f"{definitions}def move(left_id: str, right_id: FolderId) -> None: ...\n") == []


@pytest.mark.parametrize(
    "definitions",
    [
        "from typing import NewType\ntype Raw = str\nFolderId = NewType('FolderId', Raw)\n",
        "from typing import NewType as Brand\nRaw = str\nFolderId = Brand('FolderId', Raw)\n",
        "from typing import NewType\nBaseId = NewType('BaseId', str)\nFolderId = NewType('FolderId', BaseId)\n",
        "from typing_extensions import TypeAliasType, NewType\nRaw = TypeAliasType('Raw', str)\nFolderId = NewType('FolderId', Raw)\n",
    ],
)
def test_nominal_carriers_resolve_proven_alias_chains(definitions: str) -> None:
    diagnostics = _check(f"{definitions}def move(left_id: str, right_id: FolderId) -> None: ...\n")
    assert len(diagnostics) == 1
    assert diagnostics[0].severity is Severity.ERROR


def test_multiple_shapes_produce_one_stable_boundary_diagnostic() -> None:
    source = "def move(file_id: str, folder_id: str, user_id: int, team_id: int) -> None: ...\n"
    diagnostics = _check(source)
    assert len(diagnostics) == 1
    assert diagnostics[0].line == 1
    assert diagnostics[0].col == source.index("str") + 1
    assert diagnostics[0].message == (
        "`file_id`, `folder_id`, `user_id`, `team_id` are swappable ID-shaped roles with the same carrier; "
        "introduce or reuse `typing.NewType` or nominal value-object identifiers and propagate them through this boundary."
    )


def test_class_constructor_and_independent_method_have_distinct_owners() -> None:
    diagnostics = _check(
        "class Pair:\n"
        "    left_id: str\n"
        "    right_id: str\n"
        "    def __init__(self, left_id: str, right_id: str) -> None: ...\n"
        "    def move(self, left_id: str, right_id: str) -> None: ...\n"
    )
    assert [(item.line, item.severity) for item in diagnostics] == [(2, Severity.ERROR), (5, Severity.ERROR)]


@pytest.mark.parametrize("code", ["SARJ0930", "SARJ094", "SARJ034"])
def test_other_suppression_codes_do_not_hide_nominal_diagnostic(code: str) -> None:
    source = f"def move(left_id: str, right_id: str) -> None: ...  # sarj-noqa: {code}\n"
    assert len(_check(source)) == 1


def test_repeated_rule_checks_refresh_project_sources(tmp_path: Path) -> None:
    rule = PreferNominalIdTypes()
    source = "from example.types import FolderId\ndef move(file_id: str, folder_id: FolderId) -> None: ...\n"
    _project_check(tmp_path, source, "from typing import NewType\nFolderId = NewType('FolderId', str)\n")
    path = tmp_path / "example" / "service.py"
    assert len(rule.check(path, source)) == 1
    (tmp_path / "example" / "types.py").write_text("class FolderId: ...\n")
    assert rule.check(path, source) == []


@pytest.mark.parametrize(
    "source",
    [
        "from .types import Raw\ndef move(file_id: Raw, folder_id: str) -> None: ...\n",
        "if condition:\n    from example.types import Raw\ndef move(file_id: Raw, folder_id: str) -> None: ...\n",
        "from example.types import *\ndef move(file_id: Raw, folder_id: str) -> None: ...\n",
    ],
)
def test_unproven_import_ownership_stays_unknown(tmp_path: Path, source: str) -> None:
    assert _project_check(tmp_path, source, "type Raw = str\n") == []


@pytest.mark.parametrize(
    "definition",
    [
        "Raw = TypeAliasType('Raw', str)\n",
        "Raw = TypeAliasType('Raw', value=str)\n",
        "Raw = TypeAliasType(name='Raw', value=str)\n",
        "Raw = TypeAliasType('Raw', str, type_params=())\n",
    ],
)
def test_type_alias_factory_preserves_supported_argument_forms(definition: str) -> None:
    diagnostics = _check(
        f"from typing_extensions import TypeAliasType\n{definition}def move(left_id: Raw, right_id: str) -> None: ...\n"
    )
    assert len(diagnostics) == 1
    assert diagnostics[0].severity is Severity.ERROR


@pytest.mark.parametrize(
    "definition",
    [
        "Raw = TypeAliasType('Different', str)\n",
        "Raw = TypeAliasType('Raw', str, extra)\n",
        "Raw = TypeAliasType('Raw', str, value=int)\n",
        "Raw = TypeAliasType('Raw', str, **extra)\n",
        "Raw = TypeAliasType('Raw', str, unexpected=True)\n",
        "Raw = TypeAliasType(name, str)\n",
        "Raw = TypeAliasType(*arguments)\n",
        "Raw = TypeAliasType('Raw', str, type_params=(T,))\n",
    ],
)
def test_type_alias_factory_requires_proven_non_generic_signature(definition: str) -> None:
    assert (
        _check(
            f"from typing_extensions import TypeAliasType\n{definition}"
            "def move(left_id: Raw, right_id: str) -> None: ...\n"
        )
        == []
    )


def test_modified_type_alias_factory_is_unknown() -> None:
    assert (
        _check(
            "import typing_extensions as types\n"
            "types.TypeAliasType = other\n"
            "Raw = types.TypeAliasType('Raw', str)\n"
            "def move(left_id: Raw, right_id: str) -> None: ...\n"
        )
        == []
    )


@pytest.mark.parametrize("filename", ["test_models.py", "models_test.py", "conftest.py"])
def test_pytest_only_brand_does_not_establish_production_role(tmp_path: Path, filename: str) -> None:
    _project_check(tmp_path, "", "")
    (tmp_path / "example" / filename).write_text("from typing import NewType\nRoomName = NewType('RoomName', str)\n")
    assert _project_check(tmp_path, "def record(room_name: str, call_id: str) -> None: ...\n", "") == []


@pytest.mark.parametrize("role", ["service_version", "protocol_version", "room_names", "roomname"])
def test_non_id_roles_need_exact_established_brand_evidence(tmp_path: Path, role: str) -> None:
    assert (
        _project_check(
            tmp_path,
            f"def record({role}: str = 'dev', call_id: str = '') -> None: ...\n",
            "from typing import NewType\nRoomName = NewType('RoomName', str)\n",
        )
        == []
    )


def test_service_version_can_use_existing_nominal_domain_evidence(tmp_path: Path) -> None:
    diagnostics = _project_check(
        tmp_path,
        "def record(service_version: str = 'dev', call_id: str = '') -> None: ...\n",
        "from typing import NewType\nServiceVersion = NewType('ServiceVersion', str)\n",
    )
    assert len(diagnostics) == 1
    assert diagnostics[0].severity is Severity.WARNING


@pytest.mark.parametrize("schema", ["generated", "invalid", "wildcard", "shadowed", "nested"])
def test_unknown_definition_sources_cannot_establish_domain_roles(tmp_path: Path, schema: str) -> None:
    definition = "from typing import NewType\nRoomName = NewType('RoomName', str)\n"
    match schema:
        case "generated":
            definition = "# @generated\n" + definition
        case "invalid":
            definition += "def invalid(\n"
        case "wildcard":
            definition = "from foreign import *\n" + definition
        case "shadowed":
            definition += "def other(RoomName): ...\n"
        case _:
            definition = "def factory():\n" + "".join(f"    {line}\n" for line in definition.splitlines())
    assert _project_check(tmp_path, "def record(room_name: str, call_id: str) -> None: ...\n", definition) == []


@pytest.mark.parametrize("path", ["app/logging.py", "app/telemetry/service.py", "app/audit/models.py"])
def test_operational_paths_exclude_domain_role_diagnostics(path: str) -> None:
    assert _check("def move(file_id: str, folder_id: str) -> None: ...\n", path) == []


def test_operational_name_substrings_do_not_hide_unrelated_domain_functions() -> None:
    assert len(_check("def catalog(file_id: str, folder_id: str) -> None: ...\n")) == 1


@pytest.mark.parametrize("brand_on_disk", [True, False])
def test_current_focus_source_controls_canonical_role_evidence(tmp_path: Path, *, brand_on_disk: bool) -> None:
    brand = "from typing import NewType\nRoomName = NewType('RoomName', str)\n"
    boundary = "def record(room_name: str, call_id: str) -> None: ...\n"
    _project_check(tmp_path, brand + boundary if brand_on_disk else boundary, "")
    current_source = boundary if brand_on_disk else brand + boundary
    diagnostics = PreferNominalIdTypes().check(tmp_path / "example" / "service.py", current_source)
    assert len(diagnostics) == int(not brand_on_disk)
    assert all(item.severity is Severity.WARNING for item in diagnostics)


def test_distinct_class_and_constructor_roles_retain_both_diagnostics() -> None:
    diagnostics = _check(
        "class Move:\n"
        "    file_id: str\n"
        "    folder_id: str\n"
        "    def __init__(self, user_id: int, team_id: int) -> None: ...\n"
    )
    assert [(item.line, item.severity) for item in diagnostics] == [(2, Severity.ERROR), (4, Severity.ERROR)]


def test_distinct_class_and_constructor_carriers_retain_both_diagnostics() -> None:
    diagnostics = _check(
        "class Move:\n"
        "    file_id: str\n"
        "    folder_id: str\n"
        "    def __init__(self, file_id: int, folder_id: int) -> None: ...\n"
    )
    assert [(item.line, item.severity) for item in diagnostics] == [(2, Severity.ERROR), (4, Severity.ERROR)]


def test_distinct_expanded_class_roles_do_not_disappear_behind_constructor(tmp_path: Path) -> None:
    diagnostics = _project_check(
        tmp_path,
        "class Move:\n"
        "    room_name: str\n"
        "    call_id: str\n"
        "    def __init__(self, file_id: str, folder_id: str) -> None: ...\n",
        "from typing import NewType\nRoomName = NewType('RoomName', str)\n",
    )
    assert [(item.line, item.severity) for item in diagnostics] == [(2, Severity.WARNING), (4, Severity.ERROR)]


@pytest.mark.parametrize("quote_annotation", [True, False])
def test_wire_alias_metadata_survives_forward_annotation_strings(*, quote_annotation: bool) -> None:
    field = "Annotated[str, Field(alias='fileId')]"
    folder = "Annotated[str, Field(serialization_alias='folderId')]"
    if quote_annotation:
        field, folder = repr(field), repr(folder)
    assert (
        _check(
            "from typing import Annotated\nfrom pydantic import Field\n"
            f"class Payload:\n    file_id: {field}\n    folder_id: {folder}\n"
        )
        == []
    )


@pytest.mark.parametrize(
    "source",
    [
        "class Pair:\n    file_id: str\n    file_id: str\n",
        "type Raw = str\nclass Pair:\n    file_id: Raw\n    file_id: str\n",
        "class Pair:\n    file_id: str\n    ｆｉｌｅ＿ｉｄ: str\n",
        "class Pair:\n    file_id: str\n    file_id: str\n    def __init__(self, file_id: str) -> None: ...\n",
    ],
)
def test_repeated_declarations_do_not_create_a_second_role(source: str) -> None:
    assert _check(source) == []


@pytest.mark.parametrize(
    ("source", "line"),
    [
        ("class Pair:\n    file_id: str\n    file_id: str\n    folder_id: str\n", 2),
        (
            (
                "class Pair:\n    file_id: str\n    file_id: str\n"
                "    def __init__(self, file_id: str, folder_id: str) -> None: ...\n"
            ),
            4,
        ),
        (
            ("class Pair:\n    file_id: str\n    folder_id: str\n    def __init__(self, file_id: str) -> None: ...\n"),
            2,
        ),
    ],
)
def test_distinct_roles_survive_repeated_class_or_single_constructor_declarations(source: str, line: int) -> None:
    diagnostics = _check(source)
    assert len(diagnostics) == 1
    assert diagnostics[0].line == line
    assert diagnostics[0].message.count("`file_id`") == 1
    assert "`folder_id`" in diagnostics[0].message


def test_duplicate_nominal_then_raw_role_keeps_the_raw_annotation() -> None:
    diagnostics = _check(
        "from typing import NewType\nFileId = NewType('FileId', str)\nFolderId = NewType('FolderId', str)\n"
        "class Pair:\n    file_id: FileId\n    file_id: str\n    folder_id: FolderId\n"
    )
    assert len(diagnostics) == 1
    assert diagnostics[0].line == 6
    assert diagnostics[0].message.count("`file_id`") == 1


@pytest.mark.parametrize(
    "final_annotation",
    ["FileId", "object", "int", "list[str]"],
)
def test_final_class_annotation_replaces_an_earlier_raw_id(final_annotation: str) -> None:
    source = (
        "from typing import NewType\nFileId = NewType('FileId', str)\n"
        f"class Pair:\n    file_id: str\n    file_id: {final_annotation}\n    folder_id: FileId\n"
    )
    assert _check(source) == []


def test_final_wire_alias_replaces_an_earlier_domain_field() -> None:
    source = (
        "from pydantic import Field\nclass Pair:\n    file_id: str\n"
        "    file_id: str = Field(alias='fileId')\n    folder_id: str\n"
    )
    assert _check(source) == []


def test_final_raw_carrier_keeps_its_own_location_after_a_different_declaration() -> None:
    source = "class Pair:\n    file_id: int\n    file_id: str\n    folder_id: str\n"
    [finding] = _check(source)
    assert finding.line == 3
    assert finding.message.count("`file_id`") == 1


def test_equivalent_raw_redeclaration_preserves_exact_suppression() -> None:
    source = (
        "class Pair:\n    file_id: str  # sarj-noqa: SARJ093 -- raw external contract\n"
        "    file_id: str\n    folder_id: str\n"
    )
    assert _check(source) == []


@pytest.mark.parametrize(
    "mutation",
    [
        "vars(typing)['NewType'] = other\n",
        "namespace = vars(typing)\nnamespace['NewType'] = other\n",
        "from builtins import vars as namespace\nnamespace(typing)['NewType'] = other\n",
        "import builtins as native\nnative.vars(typing)['NewType'] = other\n",
    ],
)
def test_builtin_vars_exposure_cannot_prove_factory_identity(mutation: str) -> None:
    assert (
        _check(
            f"import typing\n{mutation}FolderId = typing.NewType('FolderId', str)\n"
            "def move(file_id: str, folder_id: FolderId) -> None: ...\n"
        )
        == []
    )


@pytest.mark.parametrize(
    "unrelated",
    [
        "vars(other)['NewType'] = replacement\n",
        "from foreign import vars\nvars(typing)['NewType'] = replacement\n",
    ],
)
def test_unrelated_or_unproven_vars_calls_do_not_shadow_typing(unrelated: str) -> None:
    diagnostics = _check(
        f"import typing\n{unrelated}FolderId = typing.NewType('FolderId', str)\n"
        "def move(file_id: str, folder_id: FolderId) -> None: ...\n"
    )
    assert len(diagnostics) == 1
    assert diagnostics[0].severity is Severity.ERROR


@pytest.mark.parametrize(("leaf", "expected_count"), [("str", 1), ("Unknown", 0)])
def test_deep_forward_union_preserves_known_carriers_without_recursion(leaf: str, expected_count: int) -> None:
    annotation = " | ".join(["str", *(["None"] * 2_999), leaf])
    diagnostics = _check(f"def move(file_id: {annotation!r}, folder_id: str) -> None: ...\n")
    assert len(diagnostics) == expected_count
    assert all(item.severity is Severity.ERROR and item.line == 1 for item in diagnostics)


def test_unmarked_inherited_raw_id_contract_is_preserved() -> None:
    source = (
        "class Port:\n    def route(self, source_id: str, destination_id: str) -> str: ...\n"
        "class Adapter(Port):\n"
        "    def route(self, source_id: str, destination_id: str) -> str:\n        return source_id + destination_id\n"
        "    def internal(self, file_id: str, folder_id: str) -> None: ...\n"
    )
    assert [item.line for item in _check(source)] == [2]


def test_unencodable_forward_annotation_is_not_a_nominal_role() -> None:
    source = "def move(file_id: '\\ud800', folder_id: str) -> None: ...\n"
    assert _check(source) == []
