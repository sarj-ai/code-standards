from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Annotated, ClassVar, Final, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError, field_validator, model_validator


CONVENTIONAL_PATH: Final = Path("catalog/slack-automations.v1.json")
_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_REPOSITORY = re.compile(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?/[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?$")
_SLASH_COMMAND = re.compile(r"^/[a-z0-9]+(?:-[a-z0-9]+)*$")
_RAW_SLACK_ID = re.compile(r"(?<![A-Z0-9])[ABCDEGTUVW][A-Z0-9]{8,}(?![A-Z0-9])")
_SECRET_VALUE = re.compile(r"(?i)(?:xox[baprs]-|bearer\s+[a-z0-9._-]+|-----BEGIN [A-Z ]+PRIVATE KEY-----)")
_SECRET_NAME = re.compile(r"\b[A-Z][A-Z0-9_]*(?:TOKEN|SECRET|PASSWORD|CREDENTIALS?|API_KEY)\b")
_CHANNEL_IDENTIFIER = re.compile(r"(?:^|[^A-Za-z0-9_])#[a-z0-9][a-z0-9_-]*|/archives/[CG][A-Z0-9]+", re.IGNORECASE)
_PRIVATE_CHANNEL_IDENTIFIER = re.compile(r"(?i)\bprivate[-_ ]channel[-_ ](?:id|name)\s*[:=]\s*[a-z0-9_-]+")
_INTERNAL_URL = re.compile(r"(?i)https?://[^\s]+/(?:admin|internal)(?:[/#?]|\b)")
_PATH_SCHEMA_PATTERN: Final = r"^(?!\.?\.?$)(?!\.?\.?/)(?!.*//)(?!.*(?:/\.?\.?)(?:/|$))[^/]+(?:/[^/]+)*$"
_PUBLIC_TEXT_SCHEMA: Final[dict[str, JsonValue]] = {
    "allOf": [
        {"pattern": r"^(?!\s)(?:[^\r\n]*\S)$|^\S$"},
        {"not": {"pattern": r"(?:^|[^A-Z0-9])[ABCDEGTUVW][A-Z0-9]{8,}(?:$|[^A-Z0-9])"}},
        {
            "not": {
                "pattern": (
                    r"[xX][oO][xX][bBaApPrRsS]-|"
                    r"[bB][eE][aA][rR][eE][rR]\s+[A-Za-z0-9._-]+|"
                    r"-----BEGIN [A-Z ]+PRIVATE KEY-----"
                )
            }
        },
        {"not": {"pattern": r"\b[A-Z][A-Z0-9_]*(?:TOKEN|SECRET|PASSWORD|CREDENTIALS?|API_KEY)\b"}},
        {"not": {"pattern": r"(?:^|[^A-Za-z0-9_])#[A-Za-z0-9][A-Za-z0-9_-]*|/archives/[CGcg][A-Za-z0-9]+"}},
        {
            "not": {
                "pattern": (
                    r"[pP][rR][iI][vV][aA][tT][eE][-_ ][cC][hH][aA][nN][nN][eE][lL][-_ ]"
                    r"(?:[iI][dD]|[nN][aA][mM][eE])\s*[:=]\s*[A-Za-z0-9_-]+"
                )
            }
        },
        {
            "not": {
                "pattern": (
                    r"[hH][tT][tT][pP][sS]?://[^\s]+/"
                    r"(?:[aA][dD][mM][iI][nN]|[iI][nN][tT][eE][rR][nN][aA][lL])"
                    r"(?:[/#?]|[^A-Za-z0-9_]|$)"
                )
            }
        },
    ]
}
_PUBLIC_TEXT_ITEM_SCHEMA: Final[dict[str, JsonValue]] = {
    "type": "string",
    "minLength": 1,
    "maxLength": 160,
    **_PUBLIC_TEXT_SCHEMA,
}


@dataclass(frozen=True, slots=True, order=True)
class CatalogFinding:
    location: str
    message: str

    def render(self, path: Path) -> str:
        return f"{path.as_posix()}:{self.location}: {self.message}"


class _CatalogModel(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", strict=True, frozen=True, populate_by_name=True)


class _Named(_CatalogModel):
    id: str = Field(min_length=1, max_length=80, pattern=_SLUG.pattern)
    display_name: str = Field(alias="displayName", min_length=1, max_length=80, json_schema_extra=_PUBLIC_TEXT_SCHEMA)

    @field_validator("id")
    @classmethod
    def id_is_slug(cls, value: str) -> str:
        return _slug(value)

    @field_validator("display_name")
    @classmethod
    def display_name_is_public(cls, value: str) -> str:
        return _public_text(value)


class _Summarized(_Named):
    summary: str = Field(min_length=1, max_length=320, json_schema_extra=_PUBLIC_TEXT_SCHEMA)

    @field_validator("summary")
    @classmethod
    def summary_is_public(cls, value: str) -> str:
        return _public_text(value)


class SlackSystem(_Named):
    pass


class _Trigger(_Named):
    pass


class SlackEventTrigger(_Trigger):
    kind: Literal["slack-event"]
    event_types: tuple[str, ...] = Field(
        alias="eventTypes", min_length=1, json_schema_extra={"items": _PUBLIC_TEXT_ITEM_SCHEMA, "uniqueItems": True}
    )

    @field_validator("event_types")
    @classmethod
    def event_types_are_valid(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(_public_text(item) for item in value)
        _require_sorted_unique(normalized, "eventTypes")
        return normalized


class SlackInteractionTrigger(_Trigger):
    kind: Literal["slack-interaction"]
    interaction_types: tuple[Literal["action", "shortcut", "view-submission"], ...] = Field(
        alias="interactionTypes", min_length=1, json_schema_extra={"uniqueItems": True}
    )

    @field_validator("interaction_types")
    @classmethod
    def interaction_types_are_sorted(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        _require_sorted_unique(value, "interactionTypes")
        return value


class SlashCommandTrigger(_Trigger):
    kind: Literal["slash-command"]
    command: str = Field(min_length=2, max_length=82, pattern=_SLASH_COMMAND.pattern)

    @field_validator("command")
    @classmethod
    def command_is_valid(cls, value: str) -> str:
        if _SLASH_COMMAND.fullmatch(value) is None:
            msg = "command must be a lowercase slash-command"
            raise ValueError(msg)
        return value


class Cadence(_CatalogModel):
    kind: Literal["hourly", "daily", "weekly", "biweekly", "periodic"]


class ScheduleTrigger(_Trigger):
    kind: Literal["schedule"]
    cadence: Cadence


class ExternalWebhookTrigger(_Trigger):
    kind: Literal["external-webhook"]
    source_system_id: str = Field(alias="sourceSystemId", min_length=1, max_length=80, pattern=_SLUG.pattern)

    @field_validator("source_system_id")
    @classmethod
    def source_system_id_is_slug(cls, value: str) -> str:
        return _slug(value)


class InternalEventTrigger(_Trigger):
    kind: Literal["internal-event"]
    event_name: str = Field(alias="eventName", min_length=1, max_length=80, pattern=_SLUG.pattern)

    @field_validator("event_name")
    @classmethod
    def event_name_is_slug(cls, value: str) -> str:
        return _slug(value)


class ManualTrigger(_Trigger):
    kind: Literal["manual"]
    mode: Literal["operator", "test"]


type Trigger = Annotated[
    SlackEventTrigger
    | SlackInteractionTrigger
    | SlashCommandTrigger
    | ScheduleTrigger
    | ExternalWebhookTrigger
    | InternalEventTrigger
    | ManualTrigger,
    Field(discriminator="kind"),
]


class _Capability(_Summarized):
    connected_system_ids: tuple[str, ...] = Field(
        alias="connectedSystemIds",
        min_length=1,
        json_schema_extra={
            "items": {"type": "string", "minLength": 1, "maxLength": 80, "pattern": _SLUG.pattern},
            "uniqueItems": True,
        },
    )
    triggers: tuple[Trigger, ...] = Field(min_length=1, json_schema_extra={"uniqueItems": True})

    @field_validator("connected_system_ids")
    @classmethod
    def connected_system_ids_are_sorted(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(_slug(item) for item in value)
        _require_sorted_unique(normalized, "connectedSystemIds")
        return normalized

    @field_validator("triggers")
    @classmethod
    def triggers_are_sorted(cls, value: tuple[Trigger, ...]) -> tuple[Trigger, ...]:
        _require_sorted_unique(tuple(item.id for item in value), "triggers")
        return value


class BotCapability(_Capability):
    persona_ids: tuple[str, ...] = Field(
        alias="personaIds",
        min_length=1,
        json_schema_extra={
            "items": {"type": "string", "minLength": 1, "maxLength": 80, "pattern": _SLUG.pattern},
            "uniqueItems": True,
        },
    )

    @field_validator("persona_ids")
    @classmethod
    def persona_ids_are_sorted(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(_slug(item) for item in value)
        _require_sorted_unique(normalized, "personaIds")
        return normalized


class IntegrationCapability(_Capability):
    pass


class Persona(_Summarized):
    pass


class RepositoryManifestConfiguration(_CatalogModel):
    kind: Literal["repository-manifest"]
    manifest_path: str = Field(alias="manifestPath", json_schema_extra={"pattern": _PATH_SCHEMA_PATTERN})

    @field_validator("manifest_path")
    @classmethod
    def manifest_path_is_relative(cls, value: str) -> str:
        return _relative_path(value)


class ExternalConfiguration(_CatalogModel):
    kind: Literal["external"]


type AppConfiguration = Annotated[
    RepositoryManifestConfiguration | ExternalConfiguration,
    Field(discriminator="kind"),
]


class _Automation(_Summarized):
    status: Literal["active", "dark", "retired"]
    source_paths: tuple[str, ...] = Field(
        alias="sourcePaths",
        min_length=1,
        json_schema_extra={"items": {"type": "string", "pattern": _PATH_SCHEMA_PATTERN}, "uniqueItems": True},
    )

    @field_validator("source_paths")
    @classmethod
    def source_paths_are_sorted(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(_relative_path(item) for item in value)
        _require_sorted_unique(normalized, "sourcePaths")
        return normalized


class _BotApp(_Automation):
    kind: Literal["bot-app"]
    configuration: AppConfiguration
    capabilities: tuple[BotCapability, ...] = Field(min_length=1, json_schema_extra={"uniqueItems": True})
    personas: tuple[Persona, ...]

    @field_validator("capabilities")
    @classmethod
    def capabilities_are_sorted(cls, value: tuple[BotCapability, ...]) -> tuple[BotCapability, ...]:
        _require_sorted_unique(tuple(item.id for item in value), "capabilities")
        return value

    @field_validator("personas")
    @classmethod
    def personas_are_sorted(cls, value: tuple[Persona, ...]) -> tuple[Persona, ...]:
        _require_sorted_unique(tuple(item.id for item in value), "personas")
        return value

    @model_validator(mode="after")
    def persona_references_are_owned(self) -> Self:
        persona_ids = {persona.id for persona in self.personas}
        used_persona_ids: set[str] = set()
        for capability in self.capabilities:
            for persona_id in capability.persona_ids:
                if persona_id not in persona_ids:
                    msg = f"capability {capability.id} references unknown persona {persona_id}"
                    raise ValueError(msg)
                used_persona_ids.add(persona_id)
        unused = persona_ids - used_persona_ids
        if unused:
            msg = f"personas must own at least one capability: {', '.join(sorted(unused))}"
            raise ValueError(msg)
        return self


class DedicatedBotApp(_BotApp):
    identity_kind: Literal["dedicated"] = Field(alias="identityKind")
    personas: tuple[Persona] = Field(min_length=1, max_length=1)


class SharedBotApp(_BotApp):
    identity_kind: Literal["shared"] = Field(alias="identityKind")
    personas: tuple[Persona, ...] = Field(min_length=2)


type BotApp = Annotated[DedicatedBotApp | SharedBotApp, Field(discriminator="identity_kind")]


type ReadPrivilege = Literal["channels:read", "user-groups:read", "workspace-members:read"]
type IntegrationPrivilege = Literal[
    "channels:read",
    "channels:write",
    "profiles:write",
    "user-groups:read",
    "user-groups:write",
    "workspace-members:read",
]


class ReadUserTokenAuthorization(_CatalogModel):
    kind: Literal["user-token"]
    authority: Literal["read"]
    privileges: tuple[ReadPrivilege, ...] = Field(min_length=1, json_schema_extra={"uniqueItems": True})

    @field_validator("privileges")
    @classmethod
    def privileges_are_sorted(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        _require_sorted_unique(value, "privileges")
        return value


class WriteUserTokenAuthorization(_CatalogModel):
    kind: Literal["user-token"]
    authority: Literal["write"]
    privileges: tuple[IntegrationPrivilege, ...] = Field(
        min_length=1,
        json_schema_extra={
            "contains": {"enum": ["channels:write", "profiles:write", "user-groups:write"]},
            "minContains": 1,
            "uniqueItems": True,
        },
    )

    @field_validator("privileges")
    @classmethod
    def privileges_are_sorted_with_write_authority(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        _require_sorted_unique(value, "privileges")
        if all(privilege.endswith(":read") for privilege in value):
            msg = "write authority requires a write privilege"
            raise ValueError(msg)
        return value


type UserTokenAuthorization = Annotated[
    ReadUserTokenAuthorization | WriteUserTokenAuthorization,
    Field(discriminator="authority"),
]


class Integration(_Automation):
    kind: Literal["integration"]
    authorization: UserTokenAuthorization
    capabilities: tuple[IntegrationCapability, ...] = Field(min_length=1, json_schema_extra={"uniqueItems": True})
    consumer_bot_app_ids: tuple[str, ...] = Field(
        alias="consumerBotAppIds",
        json_schema_extra={
            "items": {"type": "string", "minLength": 1, "maxLength": 80, "pattern": _SLUG.pattern},
            "uniqueItems": True,
        },
    )

    @field_validator("capabilities")
    @classmethod
    def capabilities_are_sorted(cls, value: tuple[IntegrationCapability, ...]) -> tuple[IntegrationCapability, ...]:
        _require_sorted_unique(tuple(item.id for item in value), "capabilities")
        return value

    @field_validator("consumer_bot_app_ids")
    @classmethod
    def consumers_are_sorted(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(_slug(item) for item in value)
        _require_sorted_unique(normalized, "consumerBotAppIds")
        return normalized


class SlackAutomationCatalog(_CatalogModel):
    schema_version: Literal[1] = Field(alias="schemaVersion")
    repository: str = Field(min_length=3, max_length=160, pattern=_REPOSITORY.pattern)
    systems: tuple[SlackSystem, ...] = Field(min_length=1, json_schema_extra={"uniqueItems": True})
    bot_apps: tuple[BotApp, ...] = Field(alias="botApps", json_schema_extra={"uniqueItems": True})
    integrations: tuple[Integration, ...] = Field(json_schema_extra={"uniqueItems": True})

    @field_validator("repository")
    @classmethod
    def repository_is_slug_pair(cls, value: str) -> str:
        if _REPOSITORY.fullmatch(value) is None:
            msg = "repository must be an owner/name slug"
            raise ValueError(msg)
        return value

    @field_validator("systems")
    @classmethod
    def systems_are_sorted(cls, value: tuple[SlackSystem, ...]) -> tuple[SlackSystem, ...]:
        _require_sorted_unique(tuple(item.id for item in value), "systems")
        return value

    @field_validator("bot_apps")
    @classmethod
    def bot_apps_are_sorted(cls, value: tuple[BotApp, ...]) -> tuple[BotApp, ...]:
        _require_sorted_unique(tuple(item.id for item in value), "botApps")
        return value

    @field_validator("integrations")
    @classmethod
    def integrations_are_sorted(cls, value: tuple[Integration, ...]) -> tuple[Integration, ...]:
        _require_sorted_unique(tuple(item.id for item in value), "integrations")
        return value

    @model_validator(mode="after")
    def references_are_valid(self) -> Self:
        automation_ids = tuple(item.id for item in (*self.bot_apps, *self.integrations))
        if not automation_ids:
            msg = "catalog must contain at least one bot app or integration"
            raise ValueError(msg)
        if len(automation_ids) != len(set(automation_ids)):
            msg = "botApps and integrations must not reuse an id"
            raise ValueError(msg)
        system_ids = {system.id for system in self.systems}
        bot_ids = {bot.id for bot in self.bot_apps}
        used_system_ids: set[str] = set()
        for automation in (*self.bot_apps, *self.integrations):
            for capability in automation.capabilities:
                for system_id in capability.connected_system_ids:
                    if system_id not in system_ids:
                        msg = f"{automation.id}/{capability.id} references unknown system {system_id}"
                        raise ValueError(msg)
                    used_system_ids.add(system_id)
                for trigger in capability.triggers:
                    if isinstance(trigger, ExternalWebhookTrigger):
                        if trigger.source_system_id not in system_ids:
                            msg = f"{automation.id}/{capability.id} references unknown webhook system {trigger.source_system_id}"
                            raise ValueError(msg)
                        if trigger.source_system_id not in capability.connected_system_ids:
                            msg = f"{automation.id}/{capability.id} webhook source must be a connected system"
                            raise ValueError(msg)
        for integration in self.integrations:
            for consumer_id in integration.consumer_bot_app_ids:
                if consumer_id not in bot_ids:
                    msg = f"integration {integration.id} references unknown consumer bot app {consumer_id}"
                    raise ValueError(msg)
        unused_system_ids = system_ids - used_system_ids
        if unused_system_ids:
            msg = f"systems must be referenced by a capability: {', '.join(sorted(unused_system_ids))}"
            raise ValueError(msg)
        return self


class _DuplicateKeyError(ValueError):
    pass


def validate_catalog(path: Path, *, root: Path | None = None) -> tuple[CatalogFinding, ...]:
    resolved_root = root.resolve() if root is not None else None
    if resolved_root is not None:
        try:
            resolved_catalog = path.resolve(strict=True)
        except OSError as exc:
            return (CatalogFinding("$", f"cannot resolve catalog: {exc}"),)
        if path.is_symlink() or not resolved_catalog.is_relative_to(resolved_root):
            return (CatalogFinding("$", "catalog must be a regular file inside the repository"),)
    try:
        payload = path.read_text(encoding="utf-8")
    except OSError as exc:
        return (CatalogFinding("$", f"cannot read catalog: {exc}"),)
    try:
        json.loads(payload, object_pairs_hook=_object_without_duplicate_keys)
    except _DuplicateKeyError as exc:
        return (CatalogFinding("$", str(exc)),)
    except json.JSONDecodeError as exc:
        return (CatalogFinding(f"line {exc.lineno}, column {exc.colno}", exc.msg),)
    try:
        catalog = SlackAutomationCatalog.model_validate_json(payload)
    except ValidationError as exc:
        return tuple(
            sorted(
                CatalogFinding(_location(error["loc"]), str(error["msg"]))
                for error in exc.errors(include_url=False, include_context=False)
            )
        )
    return _path_findings(catalog, resolved_root) if resolved_root is not None else ()


def render_schema() -> str:
    document = SlackAutomationCatalog.model_json_schema(by_alias=True, mode="validation")
    document["anyOf"] = [
        {"properties": {"botApps": {"minItems": 1}}},
        {"properties": {"integrations": {"minItems": 1}}},
    ]
    document["$id"] = "https://standards.sarj.ai/schemas/slack-app-catalog/v1"
    document["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    return json.dumps(document, indent=2, sort_keys=True) + "\n"


def _object_without_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            msg = f"duplicate JSON key: {key}"
            raise _DuplicateKeyError(msg)
        result[key] = value
    return result


def _public_text(value: str) -> str:
    if not value or value != value.strip() or "\n" in value or "\r" in value:
        msg = "public text must be nonempty, trimmed, and single-line"
        raise ValueError(msg)
    forbidden = (
        (_RAW_SLACK_ID, "raw Slack IDs"),
        (_SECRET_VALUE, "credentials"),
        (_SECRET_NAME, "secret environment-variable names"),
        (_CHANNEL_IDENTIFIER, "Slack channel identifiers"),
        (_PRIVATE_CHANNEL_IDENTIFIER, "private channel identifiers"),
        (_INTERNAL_URL, "admin or internal URLs"),
    )
    for pattern, label in forbidden:
        if pattern.search(value) is not None:
            msg = f"public text must not contain {label}"
            raise ValueError(msg)
    return value


def _slug(value: str) -> str:
    if _SLUG.fullmatch(value) is None:
        msg = "id must be a lowercase kebab-case slug"
        raise ValueError(msg)
    return value


def _relative_path(value: str) -> str:
    candidate = Path(value)
    if (
        not value
        or value != candidate.as_posix()
        or candidate.is_absolute()
        or value.endswith("/")
        or any(part in {"", ".", ".."} for part in candidate.parts)
    ):
        msg = "source paths must be normalized repository-relative POSIX paths"
        raise ValueError(msg)
    return value


def _require_sorted_unique(values: tuple[str, ...], label: str) -> None:
    if tuple(sorted(values)) != values:
        msg = f"{label} must be sorted"
        raise ValueError(msg)
    if len(values) != len(set(values)):
        msg = f"{label} must not contain duplicates"
        raise ValueError(msg)


def _location(parts: tuple[int | str, ...]) -> str:
    rendered_parts = ["$"]
    rendered_parts.extend(f"[{part}]" if isinstance(part, int) else f".{part}" for part in parts)
    return "".join(rendered_parts)


def _path_findings(catalog: SlackAutomationCatalog, root: Path) -> tuple[CatalogFinding, ...]:
    findings: list[CatalogFinding] = []
    for collection_name, entries in (("botApps", catalog.bot_apps), ("integrations", catalog.integrations)):
        for entry_index, entry in enumerate(entries):
            for path_index, source_path in enumerate(entry.source_paths):
                _append_path_finding(
                    findings, root, source_path, f"$.{collection_name}[{entry_index}].sourcePaths[{path_index}]"
                )
            if isinstance(entry, _BotApp) and isinstance(entry.configuration, RepositoryManifestConfiguration):
                _append_path_finding(
                    findings,
                    root,
                    entry.configuration.manifest_path,
                    f"$.{collection_name}[{entry_index}].configuration.manifestPath",
                    require_file=True,
                )
    return tuple(sorted(findings))


def _append_path_finding(
    findings: list[CatalogFinding],
    root: Path,
    value: str,
    location: str,
    *,
    require_file: bool = False,
) -> None:
    candidate = root / value
    try:
        resolved = candidate.resolve(strict=True)
    except OSError:
        findings.append(CatalogFinding(location, f"repository path does not exist: {value}"))
        return
    if not resolved.is_relative_to(root):
        findings.append(CatalogFinding(location, f"repository path escapes through a symlink: {value}"))
    elif require_file and not resolved.is_file():
        findings.append(CatalogFinding(location, f"repository manifest path must be a file: {value}"))
