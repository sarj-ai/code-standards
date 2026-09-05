from __future__ import annotations

from copy import deepcopy
import json
from typing import TYPE_CHECKING, TypeIs

from jsonschema import Draft202012Validator
from pydantic import TypeAdapter
import pytest

import sarj_standards.cli.main as cli
from sarj_standards.libs.catalogs import render_schema, validate_catalog
from sarj_standards.schemas._paths import SLACK_AUTOMATIONS_SCHEMA


if TYPE_CHECKING:
    from pathlib import Path


_JSON = TypeAdapter(object)


def _is_table(value: object) -> TypeIs[dict[str, object]]:
    return isinstance(value, dict) and all(
        isinstance(key, str)
        for key in value  # pyright: ignore[reportUnknownVariableType]
    )


def _is_list(value: object) -> TypeIs[list[object]]:
    return isinstance(value, list)


def _valid() -> dict[str, object]:
    parsed = _load_json(
        json.dumps(
            {
                "schemaVersion": 1,
                "repository": "owner/project",
                "systems": [{"id": "slack", "displayName": "Slack"}],
                "botApps": [
                    {
                        "kind": "bot-app",
                        "id": "sample-bot",
                        "displayName": "Sample Bot",
                        "summary": "Demonstrates a cataloged bot application.",
                        "status": "active",
                        "identityKind": "dedicated",
                        "configuration": {
                            "kind": "repository-manifest",
                            "manifestPath": "src/sample-bot/manifest.json",
                        },
                        "personas": [
                            {
                                "id": "sample",
                                "displayName": "Sample",
                                "summary": "Demonstrates a bot persona.",
                            }
                        ],
                        "capabilities": [
                            {
                                "id": "sample-action",
                                "displayName": "Sample action",
                                "summary": "Demonstrates a bot capability.",
                                "personaIds": ["sample"],
                                "connectedSystemIds": ["slack"],
                                "triggers": [
                                    {
                                        "id": "periodic-sample-run",
                                        "kind": "schedule",
                                        "displayName": "Periodic sample run",
                                        "cadence": {"kind": "periodic"},
                                    }
                                ],
                            }
                        ],
                        "sourcePaths": ["src/sample-bot"],
                    }
                ],
                "integrations": [
                    {
                        "kind": "integration",
                        "id": "sample-connector",
                        "displayName": "Sample connector",
                        "summary": "Demonstrates a cataloged integration.",
                        "status": "active",
                        "authorization": {
                            "kind": "user-token",
                            "authority": "write",
                            "privileges": ["profiles:write"],
                        },
                        "consumerBotAppIds": [],
                        "capabilities": [
                            {
                                "id": "sample-update",
                                "displayName": "Sample update",
                                "summary": "Demonstrates an integration capability.",
                                "connectedSystemIds": ["slack"],
                                "triggers": [
                                    {
                                        "id": "periodic-sample-update",
                                        "kind": "schedule",
                                        "displayName": "Periodic sample update",
                                        "cadence": {"kind": "periodic"},
                                    }
                                ],
                            }
                        ],
                        "sourcePaths": ["src/sample-connector"],
                    }
                ],
            }
        )
    )
    assert _is_table(parsed)
    return parsed


def _load_json(value: str) -> object:
    return _JSON.validate_json(value)


def _bot(document: dict[str, object]) -> dict[str, object]:
    bots = document["botApps"]
    assert _is_list(bots)
    assert bots
    assert _is_table(bots[0])
    return bots[0]


def _integration(document: dict[str, object]) -> dict[str, object]:
    integrations = document["integrations"]
    assert _is_list(integrations)
    assert integrations
    assert _is_table(integrations[0])
    return integrations[0]


def _write(path: Path, document: object) -> None:
    path.write_text(json.dumps(document), encoding="utf-8")


def _schema_accepts(schema: dict[str, object], document: object) -> bool:
    return Draft202012Validator(schema).is_valid(  # pyright: ignore[reportUnknownMemberType] -- jsonschema exposes an incomplete recursive JSON type.
        document  # pyright: ignore[reportArgumentType] -- mutable test documents contain only JSON values.
    )


def _materialize_valid_catalog(root: Path) -> Path:
    sample_bot = root / "src" / "sample-bot"
    sample_bot.mkdir(parents=True)
    (sample_bot / "manifest.json").write_text("{}\n", encoding="utf-8")
    (root / "src" / "sample-connector").mkdir()
    catalog = root / "catalog" / "slack-automations.v1.json"
    catalog.parent.mkdir()
    catalog.write_text(json.dumps(_valid()), encoding="utf-8")
    return catalog


def test_valid_catalog_and_repository_paths_pass(tmp_path: Path) -> None:
    catalog = _materialize_valid_catalog(tmp_path)

    assert validate_catalog(catalog, root=tmp_path) == ()


def test_shipped_json_schema_matches_the_runtime_contract() -> None:
    shipped = _load_json(SLACK_AUTOMATIONS_SCHEMA.read_text(encoding="utf-8"))
    rendered = _load_json(render_schema())

    assert shipped == rendered


def test_shipped_json_schema_is_valid_draft_2020_12() -> None:
    schema = _load_json(SLACK_AUTOMATIONS_SCHEMA.read_text(encoding="utf-8"))
    assert _is_table(schema)

    Draft202012Validator.check_schema(schema)


def _contract_corpus() -> tuple[tuple[str, dict[str, object], bool], ...]:  # ruff: ignore[too-many-locals]
    valid = _valid()

    invalid_slug = deepcopy(valid)
    _bot(invalid_slug)["id"] = "Reminder_Bot"

    invalid_repository = deepcopy(valid)
    invalid_repository["repository"] = "sarj-ai"

    invalid_path = deepcopy(valid)
    _bot(invalid_path)["sourcePaths"] = ["apps/../secrets"]

    empty_bots = deepcopy(valid)
    empty_bots["botApps"] = []

    empty_integrations = deepcopy(valid)
    empty_integrations["integrations"] = []

    empty_catalog = deepcopy(valid)
    empty_catalog["botApps"] = []
    empty_catalog["integrations"] = []

    empty_systems = deepcopy(valid)
    empty_systems["systems"] = []

    duplicate_system = deepcopy(valid)
    capability = _bot(duplicate_system)["capabilities"]
    assert _is_list(capability)
    assert capability
    assert _is_table(capability[0])
    capability[0]["connectedSystemIds"] = ["slack", "slack"]

    null_summary = deepcopy(valid)
    _bot(null_summary)["summary"] = None

    null_configuration = deepcopy(valid)
    _bot(null_configuration)["configuration"] = None

    invalid_cadence = deepcopy(valid)
    invalid_capabilities = _bot(invalid_cadence)["capabilities"]
    assert _is_list(invalid_capabilities)
    assert invalid_capabilities
    assert _is_table(invalid_capabilities[0])
    invalid_triggers = invalid_capabilities[0]["triggers"]
    assert _is_list(invalid_triggers)
    assert invalid_triggers
    assert _is_table(invalid_triggers[0])
    invalid_triggers[0]["cadence"] = None

    dedicated_with_two_personas = deepcopy(valid)
    dedicated_bot = _bot(dedicated_with_two_personas)
    personas = dedicated_bot["personas"]
    assert _is_list(personas)
    personas.append({"id": "second", "displayName": "Second", "summary": "A second persona."})
    dedicated_capabilities = dedicated_bot["capabilities"]
    assert _is_list(dedicated_capabilities)
    assert dedicated_capabilities
    assert _is_table(dedicated_capabilities[0])
    dedicated_capabilities[0]["personaIds"] = ["sample", "second"]

    shared_with_one_persona = deepcopy(valid)
    _bot(shared_with_one_persona)["identityKind"] = "shared"

    wrong_entry_kind = deepcopy(valid)
    _bot(wrong_entry_kind)["kind"] = "integration"

    null_authorization = deepcopy(valid)
    _integration(null_authorization)["authorization"] = None

    read_with_write_privilege = deepcopy(valid)
    _integration(read_with_write_privilege)["authorization"] = {
        "kind": "user-token",
        "authority": "read",
        "privileges": ["profiles:write"],
    }

    write_without_write_privilege = deepcopy(valid)
    _integration(write_without_write_privilege)["authorization"] = {
        "kind": "user-token",
        "authority": "write",
        "privileges": ["channels:read"],
    }

    csharp_boundary = deepcopy(valid)
    _bot(csharp_boundary)["summary"] = "Supports C#language tools."

    raw_team_id = deepcopy(valid)
    _bot(raw_team_id)["summary"] = "Coordinates workspace T12345678."

    untrimmed_text = deepcopy(valid)
    _bot(untrimmed_text)["displayName"] = " Reminder Bot"

    cases = [
        ("valid", valid, True),
        ("invalid slug", invalid_slug, False),
        ("invalid repository", invalid_repository, False),
        ("invalid path", invalid_path, False),
        ("bot only", empty_integrations, True),
        ("integration only", empty_bots, True),
        ("empty catalog", empty_catalog, False),
        ("empty systems", empty_systems, False),
        ("duplicate system", duplicate_system, False),
        ("null summary", null_summary, False),
        ("null configuration", null_configuration, False),
        ("invalid cadence", invalid_cadence, False),
        ("dedicated with two personas", dedicated_with_two_personas, False),
        ("shared with one persona", shared_with_one_persona, False),
        ("wrong entry kind", wrong_entry_kind, False),
        ("null authorization", null_authorization, False),
        ("read with write privilege", read_with_write_privilege, False),
        ("write without write privilege", write_without_write_privilege, False),
        ("C sharp boundary", csharp_boundary, True),
        ("raw team id", raw_team_id, False),
        ("untrimmed text", untrimmed_text, False),
    ]
    for name, unsafe_text in (
        ("credential", "Uses xoxb-not-a-real-token"),
        ("secret name", "Uses SLACK_BOT_TOKEN"),
        ("channel", "Posts to #leadership"),
        ("private channel", "Uses private-channel-id=leadership"),
        ("internal url", "Calls https://example.test/internal/run"),
    ):
        unsafe_document = deepcopy(valid)
        _bot(unsafe_document)["summary"] = unsafe_text
        cases.append((name, unsafe_document, False))
    return tuple(cases)


@pytest.mark.parametrize(("name", "document", "is_valid"), _contract_corpus())
def test_runtime_and_json_schema_share_structural_contract(
    tmp_path: Path,
    name: str,
    document: dict[str, object],
    is_valid: bool,
) -> None:
    catalog = tmp_path / f"{name.replace(' ', '-')}.json"
    _write(catalog, document)
    schema = _load_json(SLACK_AUTOMATIONS_SCHEMA.read_text(encoding="utf-8"))
    assert _is_table(schema)
    assert (validate_catalog(catalog) == ()) is is_valid
    assert _schema_accepts(schema, document) is is_valid


@pytest.mark.parametrize("field", ["owner", "generatedAt"])
def test_catalog_rejects_unpublished_ownership_and_timestamp_fields(tmp_path: Path, field: str) -> None:
    document = _valid()
    _bot(document)[field] = "platform"
    catalog = tmp_path / "catalog.json"
    _write(catalog, document)

    findings = validate_catalog(catalog)

    assert any(field in finding.location and "Extra inputs" in finding.message for finding in findings)


@pytest.mark.parametrize(
    ("unsafe", "expected"),
    [
        ("Reads U012ABCDEF activity", "raw Slack IDs"),
        ("Uses SLACK_BOT_TOKEN", "secret environment-variable names"),
        ("Posts to #leadership", "Slack channel identifiers"),
        ("Uses private-channel-id=leadership", "private channel identifiers"),
        ("Calls https://example.test/internal/run", "admin or internal URLs"),
        ("Uses xoxb-not-a-real-token", "credentials"),
    ],
)
def test_catalog_rejects_unsafe_public_text(tmp_path: Path, unsafe: str, expected: str) -> None:
    document = _valid()
    _bot(document)["summary"] = unsafe
    catalog = tmp_path / "catalog.json"
    _write(catalog, document)

    findings = validate_catalog(catalog)

    assert any(expected in finding.message for finding in findings)


@pytest.mark.parametrize("prefix", tuple("ABCDEGTUVW"))
def test_catalog_rejects_every_recognized_raw_slack_id_prefix(tmp_path: Path, prefix: str) -> None:
    document = _valid()
    _bot(document)["summary"] = f"Coordinates workspace {prefix}12345678."
    catalog = tmp_path / "catalog.json"
    _write(catalog, document)

    findings = validate_catalog(catalog)

    assert any("raw Slack IDs" in finding.message for finding in findings)


def test_catalog_rejects_duplicate_ids_across_entry_kinds(tmp_path: Path) -> None:
    document = _valid()
    _integration(document)["id"] = _bot(document)["id"]
    catalog = tmp_path / "catalog.json"
    _write(catalog, document)

    findings = validate_catalog(catalog)

    assert any("must not reuse an id" in finding.message for finding in findings)


def test_catalog_accepts_shared_bot_personas_and_generic_private_channel_prose(tmp_path: Path) -> None:
    document = _valid()
    bot = _bot(document)
    bot["identityKind"] = "shared"
    bot["summary"] = "Coordinates workflows across private channels without exposing identifiers."
    personas = bot["personas"]
    assert _is_list(personas)
    personas.append({"id": "second", "displayName": "Second", "summary": "A second persona."})
    personas.sort(key=lambda persona: str(persona["id"]) if _is_table(persona) else "")
    capabilities = bot["capabilities"]
    assert _is_list(capabilities)
    assert capabilities
    assert _is_table(capabilities[0])
    capabilities[0]["personaIds"] = ["sample", "second"]
    catalog = tmp_path / "catalog.json"
    _write(catalog, document)

    assert validate_catalog(catalog) == ()


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ("unknown-persona", "unknown persona"),
        ("unused-persona", "must own at least one capability"),
        ("unknown-system", "unknown system"),
        ("unused-system", "must be referenced by a capability"),
        ("unknown-consumer", "unknown consumer bot app"),
    ],
)
def test_catalog_rejects_broken_domain_references(tmp_path: Path, mutation: str, expected: str) -> None:
    document = _valid()
    bot = _bot(document)
    capabilities = bot["capabilities"]
    assert _is_list(capabilities)
    assert capabilities
    assert _is_table(capabilities[0])
    match mutation:
        case "unknown-persona":
            capabilities[0]["personaIds"] = ["missing"]
        case "unused-persona":
            bot["identityKind"] = "shared"
            personas = bot["personas"]
            assert _is_list(personas)
            personas.append({"id": "unused", "displayName": "Unused", "summary": "An unused persona."})
        case "unknown-system":
            capabilities[0]["connectedSystemIds"] = ["missing"]
        case "unused-system":
            systems = document["systems"]
            assert _is_list(systems)
            systems.insert(0, {"id": "other", "displayName": "Other"})
        case _:
            _integration(document)["consumerBotAppIds"] = ["missing"]
    catalog = tmp_path / "catalog.json"
    _write(catalog, document)

    assert any(expected in finding.message for finding in validate_catalog(catalog))


def test_webhook_source_must_be_declared_and_connected(tmp_path: Path) -> None:
    document = _valid()
    capability = _bot(document)["capabilities"]
    assert _is_list(capability)
    assert capability
    assert _is_table(capability[0])
    capability[0]["triggers"] = [
        {
            "id": "incoming-record",
            "kind": "external-webhook",
            "displayName": "Incoming record",
            "sourceSystemId": "other",
        }
    ]
    systems = document["systems"]
    assert _is_list(systems)
    systems.insert(0, {"id": "other", "displayName": "Other"})
    catalog = tmp_path / "catalog.json"
    _write(catalog, document)

    assert any("webhook source must be a connected system" in finding.message for finding in validate_catalog(catalog))


def test_catalog_rejects_nondeterministic_collection_order(tmp_path: Path) -> None:
    document = _valid()
    second = deepcopy(_bot(document))
    second["id"] = "alpha-bot"
    bots = document["botApps"]
    assert _is_list(bots)
    bots.append(second)
    catalog = tmp_path / "catalog.json"
    _write(catalog, document)

    findings = validate_catalog(catalog)

    assert any("botApps must be sorted" in finding.message for finding in findings)


def test_sorting_remains_a_runtime_only_invariant(tmp_path: Path) -> None:
    document = _valid()
    second = deepcopy(_bot(document))
    second["id"] = "alpha-bot"
    bots = document["botApps"]
    assert _is_list(bots)
    bots.append(second)
    catalog = tmp_path / "catalog.json"
    _write(catalog, document)
    schema = _load_json(SLACK_AUTOMATIONS_SCHEMA.read_text(encoding="utf-8"))
    assert _is_table(schema)

    assert _schema_accepts(schema, document)
    assert any("botApps must be sorted" in finding.message for finding in validate_catalog(catalog))


def test_cross_entry_id_uniqueness_remains_a_runtime_only_invariant(tmp_path: Path) -> None:
    document = _valid()
    _integration(document)["id"] = _bot(document)["id"]
    catalog = tmp_path / "catalog.json"
    _write(catalog, document)
    schema = _load_json(SLACK_AUTOMATIONS_SCHEMA.read_text(encoding="utf-8"))
    assert _is_table(schema)

    assert _schema_accepts(schema, document)
    assert any("must not reuse an id" in finding.message for finding in validate_catalog(catalog))


def test_catalog_rejects_duplicate_json_keys(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog.json"
    catalog.write_text('{"schemaVersion":1,"schemaVersion":1}\n', encoding="utf-8")

    assert validate_catalog(catalog)[0].message == "duplicate JSON key: schemaVersion"


def test_catalog_rejects_missing_or_escaping_repository_paths(tmp_path: Path) -> None:
    catalog = _materialize_valid_catalog(tmp_path)
    document = _valid()
    _integration(document)["sourcePaths"] = ["apps/missing"]
    _write(catalog, document)

    findings = validate_catalog(catalog, root=tmp_path)
    schema = _load_json(SLACK_AUTOMATIONS_SCHEMA.read_text(encoding="utf-8"))
    assert _is_table(schema)

    assert _schema_accepts(schema, document)
    assert any("repository path does not exist" in finding.message for finding in findings)


def test_repository_manifest_path_must_resolve_to_a_file(tmp_path: Path) -> None:
    catalog = _materialize_valid_catalog(tmp_path)
    document = _valid()
    configuration = _bot(document)["configuration"]
    assert _is_table(configuration)
    configuration["manifestPath"] = "src/sample-bot"
    _write(catalog, document)

    findings = validate_catalog(catalog, root=tmp_path)

    assert any("repository manifest path must be a file" in finding.message for finding in findings)


def test_repository_path_rejects_an_in_root_symlink_to_an_outside_target(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    catalog = _materialize_valid_catalog(root)
    outside = tmp_path / "outside"
    outside.mkdir()
    escape = root / "src" / "escape"
    escape.symlink_to(outside, target_is_directory=True)
    document = _valid()
    _integration(document)["sourcePaths"] = ["src/escape"]
    _write(catalog, document)

    findings = validate_catalog(catalog, root=root)

    assert any("escapes through a symlink" in finding.message for finding in findings)


def test_explicit_cli_command_validates_a_catalog(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    catalog = _materialize_valid_catalog(tmp_path)

    status = cli.main(["--root", str(tmp_path), "validate-slack-automations", str(catalog)])

    assert status == 0
    assert "Slack automation catalog ✓" in capsys.readouterr().out


def test_check_automatically_rejects_an_invalid_conventional_catalog(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    catalog = _materialize_valid_catalog(tmp_path)
    document = _valid()
    document["generatedAt"] = "2026-08-19T12:00:00Z"
    _write(catalog, document)

    status = cli.main(["--root", str(tmp_path), "check"])

    assert status == 1
    assert "generatedAt" in capsys.readouterr().out
