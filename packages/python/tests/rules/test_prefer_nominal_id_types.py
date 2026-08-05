from pathlib import Path

import pytest

from sarj_python_lint.rules.prefer_nominal_id_types import PreferNominalIdTypes


PATH = Path("app/services/files.py")


def _check(source: str, path: Path = PATH):
    return PreferNominalIdTypes().check(path, source)


@pytest.mark.parametrize(
    "source",
    [
        "def move(file_id: str, parent_folder_id: str) -> None: ...\n",
        "async def copy(source_id: str, target_id: str | None) -> None: ...\n",
        "def load(file_ids: list[str], drive_id: str) -> None: ...\n",
        "def load(file_id: str, drive_id: DriveId) -> None: ...\n",
        "class Link:\n    file_id: str\n    drive_id: str | None\n",
        "class Row:\n    id: str\n    parent_id: str\n",
        "class Row:\n    file_id: Mapped[str]\n    drive_id: Mapped[DriveId]\n",
        "class Service:\n    def __init__(self, user_id: str, organization_id: str) -> None: ...\n",
        "def load(file_id: Annotated[str, Path()], drive_id: str) -> None: ...\n",
        "def load(file_id: FileId | str, drive_id: DriveId) -> None: ...\n",
        "def get(file_id: UUID, drive_id: UUID) -> None: ...\n",
        "def get(execution_id: int, run_id: int) -> None: ...\n",
        'def get(file_id: "str", drive_id: "DriveId") -> None: ...\n',
        "def load(file_ids: set[str], drive_id: DriveId) -> None: ...\n",
        "def load(file_ids: frozenset[str], drive_id: DriveId) -> None: ...\n",
        "def share(org_id: str, *user_ids: str) -> None: ...\n",
        "def share(org_id: OrgId, user_ids: tuple[str, ...]) -> None: ...\n",
        "def cancel(task_id: str, owner_id: UserId) -> None: ...\n",
        "def load(message_id: UUID, conversation_id: ConversationId) -> None: ...\n",
    ],
    ids=[
        "parameters",
        "optional",
        "collection",
        "partial-migration",
        "model-fields",
        "model-id",
        "orm",
        "constructor",
        "annotated-parameter",
        "mixed-nominal-primitive-union",
        "uuid-primitives",
        "integer-primitives",
        "stringized-annotations",
        "set-collection",
        "frozen-set-collection",
        "variadic-role",
        "variadic-tuple-collection",
        "domain-task-id",
        "domain-message-id",
    ],
)
def test_flags_multiple_id_roles_sharing_a_boundary(source: str) -> None:
    diagnostics = _check(source)
    assert len(diagnostics) == 1
    assert diagnostics[0].code == "SARJ093"
    assert "NewType" in diagnostics[0].message


@pytest.mark.parametrize(
    "source",
    [
        "def get(file_id: str) -> None: ...\n",
        "def get(id: str, file_id: str) -> None: ...\n",
        "def get(file_id: FileId, drive_id: DriveId) -> None: ...\n",
        "def get(file_id: Annotated[FileId, Path()], drive_id: DriveId) -> None: ...\n",
        "def get(request_id: str, user_id: str) -> None: ...\n",
        "def get(file_id: str, count: int) -> None: ...\n",
        "def _provider_callback(file_id: str, drive_id: str) -> None: ...\n",
        "file_id: str\ndrive_id: str\n",
        "def get(file_id, drive_id: str) -> None: ...\n",
        "class Row:\n    id: str\n    name: str\n",
        "class ProviderSettings:\n    account_id: str\n    gateway_id: str\n",
        "class ProviderCredentials:\n    client_id: str\n    project_id: str\n",
        "class ProviderConfig:\n    account_id: str\n    gateway_id: str\n",
        "class RouteLike(Protocol):\n    operation_id: str\n    unique_id: str\n",
        "class ProviderSettings:\n    def __init__(self, account_id: str, gateway_id: str) -> None: ...\n",
        "def get(file_id: Union[FileId, None], drive_id: Optional[DriveId]) -> None: ...\n",
        "def get(file_ids: dict[str, str], drive_id: DriveId) -> None: ...\n",
        "def get(file_ids: tuple[str, int], drive_id: DriveId) -> None: ...\n",
        "def get(*args: str, drive_id: DriveId) -> None: ...\n",
        "def get(**kwargs: str) -> None: ...\n",
    ],
    ids=[
        "single-role",
        "bare-parameter-id",
        "nominal",
        "annotated-nominal",
        "operational",
        "non-id",
        "private-adapter",
        "module-locals",
        "unannotated",
        "generic-model-id",
        "raw-settings-schema",
        "raw-credentials-schema",
        "raw-config-schema",
        "structural-protocol",
        "raw-settings-constructor",
        "typing-union-nominal",
        "mapping-role-ambiguous",
        "heterogeneous-tuple-role-ambiguous",
        "generic-varargs",
        "generic-kwargs",
    ],
)
def test_ignores_ambiguous_or_already_distinct_boundaries(source: str) -> None:
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
    ],
    ids=[
        "test",
        "generated",
        "migration",
        "testing-helper",
        "fixture-helper",
        "test-fake",
        "script",
        "integration-adapter",
        "provider-adapter",
        "integration-runner",
    ],
)
def test_ignores_non_actionable_files(path: Path) -> None:
    assert _check("def move(file_id: str, drive_id: str) -> None: ...\n", path) == []


def test_supports_inline_suppression_on_the_first_raw_annotation() -> None:
    source = (
        "def bridge(\n"
        "    legacy_id: str,  # sarj-noqa: SARJ093 — provider contract is raw\n"
        "    file_id: FileId,\n"
        ") -> None: ...\n"
    )
    assert _check(source) == []


def test_reports_once_per_boundary_and_names_every_role() -> None:
    diagnostics = _check("def move(file_id: str, drive_id: str, owner_id: str) -> None: ...\n")
    assert len(diagnostics) == 1
    assert "`file_id`, `drive_id`, `owner_id`" in diagnostics[0].message


def test_malformed_annotated_annotation_does_not_crash() -> None:
    assert _check("def load(file_id: Annotated[()], drive_id: str) -> None: ...\n") == []


def test_malformed_stringized_annotation_does_not_crash() -> None:
    assert _check('def load(file_id: "list[", drive_id: str) -> None: ...\n') == []


def test_keeps_owned_integration_service_boundaries_in_scope() -> None:
    path = Path("app/integrations/github/service.py")
    assert len(_check("def sync(file_id: str, drive_id: str) -> None: ...\n", path)) == 1


def test_nested_local_function_is_not_treated_as_a_public_boundary():
    src = """
def outer() -> None:
    def local(user_id: str, org_id: str) -> None:
        pass
    local("u", "o")
"""
    assert _check(src) == []


@pytest.mark.parametrize("wrapper", ["Iterator", "AsyncIterator", "AsyncIterable"])
def test_additional_id_collection_wrappers_are_detected(wrapper: str):
    src = f"def sync(user_ids: {wrapper}[str], org_ids: {wrapper}[OrgId]) -> None: ...\n"
    assert len(_check(src)) == 1


def test_adapter_models_path_is_exempt():
    src = "def map_ids(user_id: str, org_id: str) -> None: ...\n"
    assert _check(src, Path("app/adapters/vendor/models.py")) == []


@pytest.mark.parametrize("declaration", ["UserId = str", "type UserId = str"])
def test_structural_primitive_alias_is_not_mistaken_for_nominal_id(declaration: str):
    src = f"{declaration}\n\ndef sync(user_id: UserId, org_id: OrgId) -> None: ...\n"
    assert len(_check(src)) == 1


def test_newtype_alias_without_id_suffix_still_counts_as_nominal_role():
    src = "UserKey = NewType('UserKey', str)\n\ndef sync(user_id: UserKey, org_id: str) -> None: ...\n"
    assert len(_check(src)) == 1


def test_type_alias_type_primitive_is_not_mistaken_for_nominal_id():
    src = "UserId = TypeAliasType('UserId', str)\nOrgId = TypeAliasType('OrgId', str)\n\ndef sync(user_id: UserId, org_id: OrgId) -> None: ...\n"
    assert len(_check(src)) == 1


@pytest.mark.parametrize(
    "declaration",
    [
        "from typing import NewType as NT\nUserKey = NT('UserKey', str)",
        "UserKey: TypeAlias = NewType('UserKey', str)",
    ],
)
def test_suffixless_newtype_alias_spellings_count_as_nominal(declaration: str):
    src = f"{declaration}\n\ndef sync(user_id: UserKey, org_id: str) -> None: ...\n"
    assert len(_check(src)) == 1
