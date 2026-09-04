from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules.prefer_nominal_id_types import PreferNominalIdTypes


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic, RuleExample


PATH = Path("app/services/files.py")


def _check(source: str, path: Path = PATH) -> list[Diagnostic]:
    return PreferNominalIdTypes().check(path, source)


_PUBLIC_EXAMPLES = PreferNominalIdTypes.public_examples()


def _path_id(path: Path) -> str:
    return path.as_posix()


@pytest.mark.parametrize("example", _PUBLIC_EXAMPLES, ids=tuple(example.example_id for example in _PUBLIC_EXAMPLES))
def test_public_documentation_examples_are_executable(example: RuleExample) -> None:
    focus = example.focus_file
    assert len(_check(focus.source, Path(focus.path))) == example.expected_count
    compile(focus.source, str(focus.path), "exec")


def test_rule_identity_and_summary_match_swappability_boundary() -> None:
    rule = PreferNominalIdTypes()

    assert rule.code == "SARJ093"
    assert rule.id == "prefer-nominal-id-types"
    assert "swappable identifier roles" in rule.description


@pytest.mark.parametrize(
    "source",
    [
        "def move(file_id: str, parent_folder_id: str) -> None: ...\n",
        "async def copy(source_id: str, target_id: str | None) -> None: ...\n",
        "from typing import Optional\n\ndef copy(source_id: Optional[str], target_id: str) -> None: ...\n",
        "class Link:\n    file_id: str\n    drive_id: str | None\n",
        "class Row:\n    id: str\n    parent_id: str\n",
        "class Service:\n    def __init__(self, user_id: str, organization_id: str) -> None: ...\n",
        "from typing import Annotated\n\ndef load(file_id: Annotated[str, 'path'], drive_id: str) -> None: ...\n",
        "from uuid import UUID\n\ndef load(file_id: UUID, drive_id: UUID) -> None: ...\n",
        "import uuid\n\ndef load(file_id: uuid.UUID, drive_id: uuid.UUID) -> None: ...\n",
        "def load(execution_id: int, run_id: int) -> None: ...\n",
        "def load(file_id: 'str', drive_id: 'str') -> None: ...\n",
        "def share(org_id: str, *user_ids: str) -> None: ...\n",
        "def share(org_ids: list[str], user_ids: list[str]) -> None: ...\n",
        "from typing import Sequence\n\ndef share(org_ids: Sequence[str], user_ids: Sequence[str]) -> None: ...\n",
        "from typing import NewType\nUserId = NewType('UserId', str)\ndef share(user_id: UserId, org_id: str) -> None: ...\n",
        "UserId = str\ndef share(user_id: UserId, org_id: str) -> None: ...\n",
        "from typing_extensions import TypeAliasType\nUserId = TypeAliasType('UserId', str)\ndef share(user_id: UserId, org_id: str) -> None: ...\n",
        "from typing import Protocol\nclass Mover(Protocol):\n    def move(self, file_id: str, folder_id: str) -> None: ...\n",
        "def move(id: str, folder_id: str) -> None: ...\n",
    ],
)
def test_flags_proven_swappable_identifier_roles(source: str) -> None:
    diagnostics = _check(source)

    assert len(diagnostics) == 1
    assert diagnostics[0].code == "SARJ093"
    assert diagnostics[0].severity is Severity.WARNING
    assert "typing.NewType" in diagnostics[0].message


def test_reports_only_roles_in_a_matching_carrier_group() -> None:
    diagnostic = _check("def load(file_id: str, folder_id: str, shard_id: int) -> None: ...\n")[0]

    assert "`file_id`, `folder_id`" in diagnostic.message
    assert "shard_id" not in diagnostic.message


@pytest.mark.parametrize(
    "source",
    [
        "def load(file_id: str) -> None: ...\n",
        "def load(file_id: str, shard_id: int) -> None: ...\n",
        "def load(file_ids: list[str], tenant_id: str) -> None: ...\n",
        "from typing import NewType\nUserId = NewType('UserId', str)\nOrgId = NewType('OrgId', str)\ndef load(user_id: UserId, org_id: OrgId) -> None: ...\n",
        "def load(user_id: UserId, org_id: OrgId) -> None: ...\n",
        "def load(request_id: str, user_id: str) -> None: ...\n",
        "def correlate(trace_ids: list[str], span_ids: list[str]) -> None: ...\n",
        "def _load(file_id: str, folder_id: str) -> None: ...\n",
        "class _Link:\n    file_id: str\n    folder_id: str\n    def __init__(self, file_id: str, folder_id: str) -> None: ...\n",
        "class Service:\n    def _load(self, file_id: str, folder_id: str) -> None: ...\n",
        "@app.route('/')\ndef load(file_id: str, folder_id: str) -> None: ...\n",
        "from typing import override\nclass Service:\n    @override\n    def load(self, file_id: str, folder_id: str) -> None: ...\n",
        "from typing import TypedDict\nclass WireRow(TypedDict):\n    file_id: str\n    folder_id: str\n",
        "class ProviderSettings:\n    account_id: str\n    gateway_id: str\n",
        "from sqlalchemy.orm import Mapped\nclass Row:\n    file_id: Mapped[str]\n    folder_id: Mapped[str]\n",
        "from pydantic import BaseModel, Field\nclass VendorPayload(BaseModel):\n    call_id: str = Field(alias='sip.callID')\n    account_id: str = Field(validation_alias='sip.accountID')\n",
        "from typing import Annotated\nfrom pydantic import BaseModel, Field\nclass VendorPayload(BaseModel):\n    call_id: Annotated[str, Field(alias='sip.callID')]\n    account_id: Annotated[str, Field(validation_alias='sip.accountID')]\n",
        "from typing import Annotated\nimport pydantic\nclass VendorPayload(pydantic.BaseModel):\n    call_id: Annotated[str, pydantic.Field(alias='sip.callID')]\n    account_id: Annotated[str, pydantic.Field(serialization_alias='sip.accountID')]\n",
        "from typing import Annotated\nfrom pydantic.v1 import BaseModel, Field\nclass VendorPayload(BaseModel):\n    call_id: Annotated[str, Field(alias='sip.callID')]\n    account_id: Annotated[str, Field(alias='sip.accountID')]\n",
        "from vendor import UUID\ndef load(file_id: UUID, folder_id: UUID) -> None: ...\n",
        "class str: ...\ndef load(file_id: str, folder_id: str) -> None: ...\n",
        "class Optional: ...\ndef load(file_id: Optional[str], folder_id: Optional[str]) -> None: ...\n",
        "def NewType(name: str, base: object) -> object: ...\nUserId = NewType('UserId', str)\nOrgId = NewType('OrgId', str)\ndef load(user_id: UserId, org_id: OrgId) -> None: ...\n",
        "from fake import *\ndef load(file_id: str, folder_id: str) -> None: ...\n",
        "def load(file_ids: dict[str, str], folder_ids: dict[str, str]) -> None: ...\n",
        "def load(file_ids: tuple[str, int], folder_ids: tuple[str, int]) -> None: ...\n",
        "def set_log_context(session_id: str, participant_id: str) -> None: ...\n",
        "def load(file_id, folder_id: str) -> None: ...\n",
        "def load(**resource_ids: str) -> None: ...\n",
    ],
)
def test_allows_distinct_ambiguous_external_or_nonpublic_boundaries(source: str) -> None:
    assert _check(source) == []


@pytest.mark.parametrize(
    "path",
    [
        Path("tests/test_files.py"),
        Path("app/generated/client.py"),
        Path("app/migrations/versions/001_ids.py"),
        Path("app/testing/builders.py"),
        Path("app/fixtures/builders.py"),
        Path("app/test_fakes/provider.py"),
        Path("scripts/provider_sync.py"),
        Path("app/integrations/github/models.py"),
        Path("app/providers/github/client.py"),
        Path("integration/client.py"),
        Path("app/observability/context.py"),
        Path("webserver/audit/audit_log_entry.py"),
    ],
    ids=_path_id,
)
def test_skips_non_domain_paths(path: Path) -> None:
    assert _check("def move(file_id: str, folder_id: str) -> None: ...\n", path) == []


@pytest.mark.parametrize(
    "header",
    [
        "# Generated by protoc. Do not edit.\n",
        '"""Code generated by Speakeasy. DO NOT EDIT."""\n',
    ],
)
def test_skips_generated_source(header: str) -> None:
    assert _check(header + "def move(file_id: str, folder_id: str) -> None: ...\n") == []


def test_import_aliases_preserve_provenance() -> None:
    source = (
        "from builtins import str as Text\n"
        "from typing import Optional as Maybe\n"
        "from uuid import UUID as Identifier\n\n"
        "def text(file_id: Maybe[Text], folder_id: Text) -> None: ...\n"
        "def uuid(file_id: Identifier, folder_id: Identifier) -> None: ...\n"
    )

    assert len(_check(source)) == 2


def test_rebound_import_abstains() -> None:
    source = "from uuid import UUID\nUUID = vendor.UUID\ndef load(file_id: UUID, folder_id: UUID) -> None: ...\n"

    assert _check(source) == []


def test_class_fields_and_matching_constructor_report_once() -> None:
    source = (
        "class Link:\n"
        "    file_id: str\n"
        "    owner_id: str\n"
        "    def __init__(self, file_id: str, owner_id: str) -> None: ...\n"
    )

    assert len(_check(source)) == 1


def test_class_fields_and_constructor_superset_report_once() -> None:
    source = (
        "class Link:\n"
        "    file_id: str\n"
        "    owner_id: str\n"
        "    def __init__(self, file_id: str, owner_id: str, folder_id: str) -> None: ...\n"
    )

    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    ("source", "path"),
    [
        (
            ("class VoiceEventLogger:\n    def __init__(self, session_id: str, room_id: str) -> None: ...\n"),
            Path("app/events.py"),
        ),
        (
            "def create_voice_logger(session_id: str, room_id: str) -> object: ...\n",
            PATH,
        ),
        (
            "def emit(session_id: str, room_id: str) -> None: ...\n",
            Path("common/events/voice_logger.py"),
        ),
        (
            "def emit(session_id: str, room_id: str) -> None: ...\n",
            Path("common/logging.py"),
        ),
    ],
)
def test_skips_operational_logger_boundaries(source: str, path: Path) -> None:
    assert _check(source, path) == []


def test_suppression_is_recognized() -> None:
    source = (
        "def bridge(\n"
        "    legacy_id: str,  # sarj-noqa: SARJ093 — provider contract is raw\n"
        "    file_id: str,\n"
        ") -> None: ...\n"
    )
    assert _check(source) == []


@pytest.mark.parametrize("source", ["", "# comment\n", "def broken( -> None:\n"])
def test_allows_empty_or_invalid_source(source: str) -> None:
    assert _check(source) == []
