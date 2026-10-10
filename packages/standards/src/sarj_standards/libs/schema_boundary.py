from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING
from urllib.parse import unquote

from jsonschema import Draft4Validator, Draft6Validator, Draft7Validator, Draft201909Validator, Draft202012Validator
from jsonschema.exceptions import SchemaError
from jsonschema.protocols import Validator
from referencing import Registry, Resource
from referencing.exceptions import CannotDetermineSpecification, Unresolvable
from referencing.jsonschema import DRAFT7, Schema, UnknownDialect, specification_with

from sarj_standards.libs.json_boundary import normalize_json_value, parse_unique_json
from sarj_standards.libs.typed_containers import is_object_list, is_object_mapping


if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence
    from pathlib import Path

    from jsonschema.exceptions import ValidationError


_DIALECTS: Mapping[str, type[Validator]] = MappingProxyType(
    {
        "http://json-schema.org/draft-04/schema": Draft4Validator,
        "http://json-schema.org/draft-06/schema": Draft6Validator,
        "http://json-schema.org/draft-07/schema": Draft7Validator,
        "https://json-schema.org/draft/2019-09/schema": Draft201909Validator,
        "https://json-schema.org/draft/2020-12/schema": Draft202012Validator,
    }
)
HELM_SCHEMA_DIALECTS = frozenset(_DIALECTS)
HELM_DEFAULT_DIALECT = "https://json-schema.org/draft/2020-12/schema"
KUBERNETES_DEFAULT_DIALECT = "http://json-schema.org/draft-04/schema"
DEFAULT_DIALECT = "http://json-schema.org/draft-07/schema"
_MAX_SCHEMA_RESOURCES = 100_000


@dataclass(frozen=True, slots=True)
class SchemaReferenceProfile:
    default_dialect: str
    dialects: frozenset[str]
    extra_reference_keywords: tuple[tuple[str, str], ...] = ()
    extra_subschema_maps: tuple[tuple[str, str], ...] = ()


HELM_SCHEMA_PROFILE = SchemaReferenceProfile(
    default_dialect=HELM_DEFAULT_DIALECT,
    dialects=HELM_SCHEMA_DIALECTS,
    extra_reference_keywords=((HELM_DEFAULT_DIALECT, "$recursiveRef"),),
    extra_subschema_maps=tuple((dialect, "dependencies") for dialect in sorted(HELM_SCHEMA_DIALECTS)),
)


@dataclass(frozen=True, slots=True)
class _SchemaResource:
    resource: Resource[Schema]
    base: object
    validator: type[Validator]


@dataclass(slots=True)
class _ReferenceWalk:
    pending: list[_SchemaResource]
    visited: dict[tuple[int, int], object] = field(default_factory=dict)
    references: list[str] = field(default_factory=list)
    identifiers: list[str] = field(default_factory=list)


def _validator(*, schema: dict[str, object] | bool, default: type[Validator] = Draft7Validator) -> type[Validator]:
    dialect = schema.get("$schema") if not isinstance(schema, bool) else None
    if dialect is None:
        return default
    if not isinstance(dialect, str) or dialect.removesuffix("#") not in _DIALECTS:
        msg = "schema declares an unsupported JSON Schema dialect"
        raise ValueError(msg)
    return _DIALECTS[dialect.removesuffix("#")]


def schema_references(
    value: object,
    *,
    dialects: frozenset[str] | None = None,
    fragment: str = "",
    default_dialect: str = DEFAULT_DIALECT,
    legacy_identifiers: bool = False,
    profile: SchemaReferenceProfile | None = None,
) -> tuple[str, ...]:
    try:
        return _schema_references(
            value,
            dialects=dialects if profile is None else profile.dialects,
            fragment=fragment,
            default=_DIALECTS[default_dialect if profile is None else profile.default_dialect],
            legacy_identifiers=legacy_identifiers,
            profile=profile,
        )
    except (SchemaError, UnknownDialect, CannotDetermineSpecification) as error:
        msg = f"invalid or unsupported schema declaration: {error}"
        raise ValueError(msg) from error


def _schema_references(
    value: object,
    *,
    dialects: frozenset[str] | None,
    fragment: str,
    default: type[Validator],
    legacy_identifiers: bool,
    profile: SchemaReferenceProfile | None,
) -> tuple[str, ...]:
    root = _schema(value)
    validator = _validator(schema=root, default=default)
    walk = _ReferenceWalk([_SchemaResource(_resource(root, default=validator), root, validator)])
    if fragment:
        walk.pending.append(_SchemaResource(_resource(_pointer(root, fragment), default=validator), root, validator))
    while walk.pending:
        _visit_resource(
            walk, walk.pending.pop(), dialects=dialects, legacy_identifiers=legacy_identifiers, profile=profile
        )
    if any(reference.split("#", 1)[0] for reference in walk.references) and any(
        identifier.split("#", 1)[0] for identifier in walk.identifiers
    ):
        msg = "schema base-changing identifiers with external-file references require an explicit resolver"
        raise ValueError(msg)
    return tuple(walk.references)


def _visit_resource(
    walk: _ReferenceWalk,
    item: _SchemaResource,
    *,
    dialects: frozenset[str] | None,
    legacy_identifiers: bool,
    profile: SchemaReferenceProfile | None,
) -> None:
    resource, base = item.resource, item.base
    identity = (id(resource.contents), id(base))
    if identity in walk.visited:
        return
    walk.visited[identity] = resource.contents
    if len(walk.visited) > _MAX_SCHEMA_RESOURCES:
        msg = "schema semantic resource closure exceeds the analysis bound"
        raise ValueError(msg)
    content = _schema(resource.contents)
    validator = _validator(schema=content, default=item.validator)
    if not isinstance(content, bool):
        _native_dialect(content, dialects)
        references = _own_references(content, validator, profile=profile)
        walk.references.extend(references)
        identifier = _resource_identifier(resource, content, validator=validator, legacy_identifiers=legacy_identifiers)
        if identifier:
            walk.identifiers.append(identifier)
            if identifier.split("#", 1)[0]:
                base = resource.contents
        _queue_pointer_targets(walk, references, base=base, validator=validator)
    validator.check_schema(content)  # pyright: ignore[reportArgumentType] -- upstream protocol stub excludes valid modern boolean schemas.
    walk.pending.extend(
        _SchemaResource(child, base, validator)
        for child in _native_subresources(resource=resource, content=content, validator=validator)
    )
    walk.pending.extend(
        _SchemaResource(child, base, validator)
        for child in _profile_subresources(content=content, validator=validator, profile=profile)
    )


def _native_subresources(
    *, resource: Resource[Schema], content: dict[str, object] | bool, validator: type[Validator]
) -> Iterable[Resource[Schema]]:
    if (
        not isinstance(content, bool)
        and "dependencies" in content
        and validator in {Draft4Validator, Draft6Validator, Draft7Validator}
    ):
        # referencing 0.37.0 classifies every dependency from the first entry.
        # Traverse that mixed keyword separately; retain upstream ownership of others.
        resource = _resource({key: value for key, value in content.items() if key != "dependencies"}, default=validator)
    return resource.subresources()


def _profile_subresources(
    *,
    content: dict[str, object] | bool,
    validator: type[Validator],
    profile: SchemaReferenceProfile | None,
) -> Iterable[Resource[Schema]]:
    if isinstance(content, bool):
        return
    keywords: set[str] = {"dependencies"} if validator in {Draft4Validator, Draft6Validator, Draft7Validator} else set()
    if profile is not None:
        keywords.update(keyword for dialect, keyword in profile.extra_subschema_maps if _DIALECTS[dialect] is validator)
    for keyword in sorted(keywords):
        container = content.get(keyword)
        if is_object_mapping(container):
            for child in container.values():
                if not is_object_list(child):
                    yield _resource(child, default=validator)


def _native_dialect(content: dict[str, object], dialects: frozenset[str] | None) -> None:
    dialect = content.get("$schema")
    if dialects is not None and isinstance(dialect, str) and dialect.removesuffix("#") not in dialects:
        msg = "schema dialect is unsupported by the selected native validator"
        raise ValueError(msg)


def _resource_identifier(
    resource: Resource[Schema], content: dict[str, object], *, validator: type[Validator], legacy_identifiers: bool
) -> str | None:
    identifier = resource.id()
    uses_legacy_id = "id" in content and (content.get("$schema") is None or validator is Draft4Validator)
    if legacy_identifiers and (uses_legacy_id or "$id" in content):
        identifier = content["id"] if uses_legacy_id else content["$id"]
        if not isinstance(identifier, str):
            msg = "legacy schema id must be a string"
            raise TypeError(msg)
    return identifier


def _queue_pointer_targets(
    walk: _ReferenceWalk, references: tuple[str, ...], *, base: object, validator: type[Validator]
) -> None:
    for reference in references:
        if not reference.startswith("#") or not unquote(reference[1:]).startswith("/"):
            continue
        target = _pointer(base, reference[1:])
        identity = (id(target), id(base))
        if identity not in walk.visited:
            walk.visited[identity] = target
            walk.pending.append(_SchemaResource(_resource(target, default=validator), base, validator))


def _pointer(value: object, fragment: str) -> object:
    pointer = unquote(fragment)
    if not pointer.startswith("/"):
        return value  # Named anchors are covered by upstream semantic subresources.
    current = value
    for part in pointer[1:].split("/"):
        key = part.replace("~1", "/").replace("~0", "~")
        if is_object_mapping(current) and key in current:
            current = current[key]
        elif is_object_list(current) and key.isdecimal() and str(int(key)) == key and int(key) < len(current):
            current = current[int(key)]
        else:
            msg = "schema JSON Pointer does not resolve inside its closed document"
            raise ValueError(msg)
    return current


def _resource(value: object, *, default: type[Validator]) -> Resource[Schema]:
    dialect = next(uri for uri, validator in _DIALECTS.items() if validator is default)
    return Resource.from_contents(_schema(value), default_specification=specification_with(dialect))


def _own_references(
    content: dict[str, object], validator: type[Validator], *, profile: SchemaReferenceProfile | None
) -> tuple[str, ...]:
    references: list[str] = []
    additional: frozenset[str] = (
        frozenset(keyword for dialect, keyword in profile.extra_reference_keywords if _DIALECTS[dialect] is validator)
        if profile is not None
        else frozenset()
    )
    for keyword in ("$ref", "$dynamicRef", "$recursiveRef"):
        if keyword not in content or (keyword not in validator.VALIDATORS and keyword not in additional):
            continue
        reference = content[keyword]
        if not isinstance(reference, str):
            msg = f"schema {keyword} must be a string"
            raise TypeError(msg)
        references.append(reference)
    return tuple(references)


def validate_local_schema(instance: object, schema: Path, closure: Sequence[Path]) -> tuple[str, ...]:
    try:
        return _validate(instance, schema, closure)
    except (SchemaError, Unresolvable) as error:
        msg = f"local schema is invalid or lacks a closed reference: {error}"
        raise ValueError(msg) from error


def _validate(instance: object, schema: Path, closure: Sequence[Path]) -> tuple[str, ...]:
    registry: Registry[Schema] = Registry()
    for path in closure:
        content = _schema(parse_unique_json(path.read_text(encoding="utf-8")))
        schema_references(content)
        resource = Resource.from_contents(content, default_specification=DRAFT7)
        registry = registry.with_resource(path.as_uri(), resource)
    content = _schema(parse_unique_json(schema.read_text(encoding="utf-8")))
    validator = _validator(schema=content)({"$ref": schema.as_uri()}, registry=registry)
    normalized = normalize_json_value(instance)
    errors: Iterable[ValidationError] = validator.iter_errors(normalized)
    return tuple(str(error.message) for error in errors)


def _schema(value: object) -> dict[str, object] | bool:
    if isinstance(value, bool):
        return value
    if is_object_mapping(value) and all(isinstance(key, str) for key in value):
        return {key: item for key, item in value.items() if isinstance(key, str)}
    msg = "JSON schema must be a boolean or object"
    raise ValueError(msg)
