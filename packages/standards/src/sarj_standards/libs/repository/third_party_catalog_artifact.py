from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
import shutil
import subprocess  # ruff: ignore[suspicious-subprocess-import] -- pinned local tools produce a committed projection.
import sys
import tempfile
from types import MappingProxyType
from typing import Annotated, ClassVar, Final, Literal, NewType

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter
import typer


_DESTINATION: Final = Path("apps/docs/src/generated/third-party-rules.v1.json")
_NODE_PROJECTION: Final = Path("packages/typescript/scripts/project-third-party-rules.mjs")
_REACT_DOCTOR_PROJECTION: Final = Path("apps/docs/scripts/project-react-doctor-rules.mjs")
_MOBILE_CONFIG_ROOT: Final = Path("packages/standards/src/sarj_standards/configs")
_RUFF_CONFIGS: Final = MappingProxyType(
    {
        # Version-one catalog labels are compatibility aliases, not policy selectors.
        "application": Path("packages/standards/src/sarj_standards/configs/ruff.strict.toml"),
        "standard": Path("packages/standards/src/sarj_standards/configs/ruff.strict.toml"),
    }
)
_RUFF_CONTEXTS: Final = (
    ("source-python", "Python source", "src/example.py"),
    ("test-python", "Python tests", "tests/test_example.py"),
    ("script-python", "Python scripts", "scripts/example.py"),
    ("main-python", "Python CLI entry point", "src/__main__.py"),
    ("cli-python", "Python CLI modules", "src/cli/example.py"),
)
_ENABLED_RULE_RE: Final = re.compile(r"^\s*[^()]+\s\(([^()]+)\),$")
_ENABLED_NAMED_RULE_RE: Final = re.compile(r"^\s*([a-z][a-z0-9-]+),$")
_DETEKT_RULE_SETS: Final = frozenset(
    {
        "comments",
        "complexity",
        "coroutines",
        "empty-blocks",
        "exceptions",
        "naming",
        "performance",
        "potential-bugs",
        "style",
    }
)

type ProfileName = Literal["application", "standard"]
type ProviderEngine = Literal[
    "detekt", "eslint", "ktlint", "mobsfscan", "react-doctor", "ruff", "swiftformat", "swiftlint"
]
type ProjectionScope = Literal["complete", "config-explicit", "provider-only"]
RuleId = NewType("RuleId", str)
DisplayRuleId = NewType("DisplayRuleId", str)


class _FrozenModel(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
        strict=True,
    )


class _Context(_FrozenModel):
    id: str
    label: str
    level: Literal["error", "warning"]


class _Profile(_FrozenModel):
    name: ProfileName
    contexts: tuple[_Context, ...]


class _Provider(_FrozenModel):
    id: str
    label: str
    engine: ProviderEngine
    package: str
    version: str
    homepage: str
    projection_scope: ProjectionScope = Field(
        default="complete",
        validation_alias="projectionScope",
        serialization_alias="projectionScope",
    )


class _Rule(_FrozenModel):
    key: str
    provider: str
    id: RuleId
    display_id: DisplayRuleId = Field(
        validation_alias="displayId",
        serialization_alias="displayId",
    )
    summary: str
    docs_url: str = Field(validation_alias="docsUrl", serialization_alias="docsUrl")
    family: str | None
    autofix: Literal["always", "available", "none", "sometimes"]
    has_suggestions: bool = Field(
        validation_alias="hasSuggestions",
        serialization_alias="hasSuggestions",
    )
    profiles: tuple[_Profile, ...]


class _EslintProjection(_FrozenModel):
    providers: tuple[_Provider, ...]
    rules: tuple[_Rule, ...]


class _RuffMetadata(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True, strict=True)

    code: str | None
    name: str
    summary: str
    linter: str | None
    fix_availability: str


class _ReactDoctorProjection(_FrozenModel):
    rules: tuple[_Rule, ...]


class _Peers(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True, strict=True)

    peers: dict[str, str]


class _CatalogArtifact(_FrozenModel):
    schema_version: Literal[1] = Field(
        validation_alias="schemaVersion",
        serialization_alias="schemaVersion",
    )
    profiles: tuple[ProfileName, ProfileName]
    providers: tuple[_Provider, ...]
    rules: tuple[_Rule, ...]


@dataclass(frozen=True, slots=True)
class _RuffProjection:
    provider: _Provider
    rules: tuple[_Rule, ...]


@dataclass(frozen=True, slots=True)
class _MobileProviderSpec:
    id: str
    label: str
    engine: ProviderEngine
    package: str
    homepage: str
    projection_scope: ProjectionScope


@dataclass(frozen=True, slots=True)
class _MobileProjection:
    providers: tuple[_Provider, ...]
    rules: tuple[_Rule, ...]


@dataclass(frozen=True, slots=True)
class SyncResult:
    status: int
    message: str


def parse_enabled_ruff_rules(settings: str) -> frozenset[str]:
    inside = False
    codes: set[str] = set()
    for line in settings.splitlines():
        if line == "linter.rules.enabled = [":
            inside = True
            continue
        if inside and line == "]":
            return frozenset(codes)
        match = (_ENABLED_RULE_RE.match(line) or _ENABLED_NAMED_RULE_RE.match(line)) if inside else None
        if match is not None:
            codes.add(match.group(1))
    msg = "Ruff settings omitted linter.rules.enabled"
    raise ValueError(msg)


def build(root: Path) -> _CatalogArtifact:
    resolved = root.resolve()
    node = shutil.which("node")
    npm = shutil.which("npm")
    ruff = shutil.which("ruff")
    if node is None or npm is None or ruff is None:
        missing = "node" if node is None else "npm" if npm is None else "ruff"
        msg = f"cannot generate third-party catalog: {missing} is not installed"
        raise RuntimeError(msg)
    _run((npm, "run", "build", "--silent"), cwd=resolved / "packages/typescript")
    eslint = _eslint_projection(resolved, node)
    react_doctor = _react_doctor_projection(resolved, node)
    ruff_projection = _ruff_projection(resolved, ruff)
    mobile = _mobile_projections(resolved)
    rules = (*eslint.rules, *react_doctor.rules, *ruff_projection.rules, *mobile.rules)
    providers = (*eslint.providers, _react_doctor_provider(resolved), ruff_projection.provider, *mobile.providers)
    included_providers = {rule.provider for rule in rules} | {provider.id for provider in mobile.providers}
    return _CatalogArtifact(
        schema_version=1,
        profiles=("application", "standard"),
        providers=tuple(
            sorted((provider for provider in providers if provider.id in included_providers), key=lambda item: item.id)
        ),
        rules=tuple(sorted(rules, key=lambda item: item.key)),
    )


def render(root: Path) -> str:
    payload = build(root).model_dump(mode="json", by_alias=True)
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n"


def sync(root: Path, *, check: bool) -> SyncResult:
    resolved = root.resolve()
    destination = resolved / _DESTINATION
    expected = render(resolved)
    current = destination.read_text(encoding="utf-8") if destination.is_file() else ""
    if current == expected:
        return SyncResult(0, "ok: third-party-rules.v1.json matches resolved tool policy")
    if check:
        return SyncResult(1, "drift: third-party-rules.v1.json differs; rerun with --sync")
    from sarj_standards.libs.adoption import transaction  # ruff: ignore[import-outside-top-level]

    transaction.atomic_write_text(resolved, destination, expected)
    return SyncResult(0, "updated: third-party-rules.v1.json")


def main() -> int:
    app = typer.Typer(add_completion=False, pretty_exceptions_enable=False)

    @app.command(help="synchronize the generated third-party rule catalog")
    def run(
        *,
        root: Annotated[Path, typer.Option("--root")] = Path(),
        check: Annotated[bool, typer.Option("--check")] = False,
        synchronize: Annotated[bool, typer.Option("--sync")] = False,
    ) -> None:
        if check == synchronize:
            msg = "choose exactly one of --check or --sync"
            raise typer.BadParameter(msg)
        result = sync(root, check=check)
        sys.stdout.write(f"{result.message}\n")
        raise typer.Exit(result.status)

    app()
    return 0


def _run(argv: tuple[str, ...], *, cwd: Path) -> str:
    completed = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true] -- resolved tools and fixed argv.
        argv,
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    return completed.stdout


def _eslint_projection(root: Path, node: str) -> _EslintProjection:
    output = _run((node, str(root / _NODE_PROJECTION)), cwd=root)
    return _EslintProjection.model_validate_json(output)


def _react_doctor_projection(root: Path, node: str) -> _ReactDoctorProjection:
    output = _run((node, str(root / _REACT_DOCTOR_PROJECTION)), cwd=root)
    return _ReactDoctorProjection.model_validate_json(output)


def _react_doctor_provider(root: Path) -> _Provider:
    peers = _Peers.model_validate_json(
        (root / "packages/standards/src/sarj_standards/configs/eslint.peers.json").read_text(encoding="utf-8")
    ).peers
    return _Provider(
        id="react-doctor",
        label="React Doctor",
        engine="react-doctor",
        package="react-doctor",
        version=peers["react-doctor"],
        homepage="https://react.doctor/",
    )


def _mobile_projections(root: Path) -> _MobileProjection:
    config_root = root / _MOBILE_CONFIG_ROOT
    versions = TypeAdapter(dict[str, str]).validate_json(
        (config_root / "mobile-tools.versions.json").read_text(encoding="utf-8"), strict=True
    )
    provider_specs = (
        _MobileProviderSpec("detekt", "Detekt", "detekt", "detekt", "https://detekt.dev/", "config-explicit"),
        _MobileProviderSpec(
            "ktlint", "ktlint", "ktlint", "ktlint", "https://pinterest.github.io/ktlint/", "config-explicit"
        ),
        _MobileProviderSpec(
            "mobsfscan", "mobsfscan", "mobsfscan", "mobsfscan", "https://github.com/MobSF/mobsfscan", "provider-only"
        ),
        _MobileProviderSpec(
            "swiftformat",
            "SwiftFormat",
            "swiftformat",
            "swiftformat",
            "https://github.com/nicklockwood/SwiftFormat",
            "provider-only",
        ),
        _MobileProviderSpec(
            "swiftlint", "SwiftLint", "swiftlint", "swiftlint", "https://realm.github.io/SwiftLint/", "config-explicit"
        ),
    )
    providers = tuple(
        _Provider(
            id=spec.id,
            label=spec.label,
            engine=spec.engine,
            package=spec.package,
            version=versions[spec.package],
            homepage=spec.homepage,
            projection_scope=spec.projection_scope,
        )
        for spec in provider_specs
    )
    swiftlint_ids = _yaml_list_values(config_root / "swiftlint.strict.yml", ("opt_in_rules", "analyzer_rules"))
    ktlint_ids = _enabled_ktlint_rules(config_root / "ktlint.strict.editorconfig")
    detekt_ids = _enabled_detekt_rules(config_root / "detekt.strict.yml")
    rules = (
        *(
            _mobile_rule(provider="swiftlint", rule_id=rule_id, context_label="Swift source", context_id="swift-source")
            for rule_id in swiftlint_ids
        ),
        *(
            _mobile_rule(provider="ktlint", rule_id=rule_id, context_label="Kotlin source", context_id="kotlin-source")
            for rule_id in ktlint_ids
        ),
        *(
            _mobile_rule(provider="detekt", rule_id=rule_id, context_label="Kotlin source", context_id="kotlin-source")
            for rule_id in detekt_ids
        ),
    )
    return _MobileProjection(providers, tuple(rules))


def _mobile_rule(*, provider: str, rule_id: str, context_label: str, context_id: str) -> _Rule:
    match provider:
        case "detekt":
            family, name = rule_id.split(":", maxsplit=1)
            docs_url = f"https://detekt.dev/docs/1.23.8/rules/{family}/#{name.lower()}"
        case "ktlint":
            docs_url = "https://pinterest.github.io/ktlint/1.8.0/rules/standard/"
        case _:
            docs_url = f"https://realm.github.io/SwiftLint/{rule_id}.html"
    context = _Context(id=context_id, label=context_label, level="error")
    return _Rule(
        key=f"{provider}:{rule_id}",
        provider=provider,
        id=RuleId(rule_id),
        display_id=DisplayRuleId(rule_id),
        summary="Explicitly enabled by the canonical strict mobile configuration.",
        docs_url=docs_url,
        family=rule_id.split(":", maxsplit=1)[0] if ":" in rule_id else None,
        autofix="available" if provider == "ktlint" else "none",
        has_suggestions=False,
        profiles=tuple(_Profile(name=profile, contexts=(context,)) for profile in ("application", "standard")),
    )


def _yaml_list_values(path: Path, keys: tuple[str, ...]) -> tuple[str, ...]:
    selected: set[str] = set()
    active = False
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.partition("#")[0].rstrip()
        if line and not line.startswith(" "):
            active = line.removesuffix(":") in keys
            continue
        if active and (match := re.match(r"^\s+-\s+([a-z0-9_]+)\s*$", line)) is not None:
            selected.add(match.group(1))
    return tuple(sorted(selected))


def _enabled_ktlint_rules(path: Path) -> tuple[str, ...]:
    enabled: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if (match := re.match(r"^ktlint_standard_([^= ]+)\s*=\s*enabled\s*$", line)) is not None:
            enabled.add(f"standard:{match.group(1)}")
    return tuple(sorted(enabled))


def _enabled_detekt_rules(path: Path) -> tuple[str, ...]:
    selected: set[str] = set()
    current_set: str | None = None
    set_active = False
    current_rule: str | None = None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.partition("#")[0].rstrip()
        if (match := re.match(r"^([a-z][a-z-]+):\s*$", line)) is not None:
            current_set = match.group(1) if match.group(1) in _DETEKT_RULE_SETS else None
            set_active = False
            current_rule = None
        elif current_set is not None and (match := re.match(r"^  ([A-Z][A-Za-z0-9]+):\s*$", line)) is not None:
            current_rule = match.group(1)
        elif current_set is not None and current_rule is None and re.match(r"^  active:\s*true\s*$", line):
            set_active = True
        elif current_set is not None and current_rule is not None and re.match(r"^    active:\s*true\s*$", line):
            if set_active:
                selected.add(f"{current_set}:{current_rule}")
    return tuple(sorted(selected))


def _ruff_projection(root: Path, ruff: str) -> _RuffProjection:
    output = _run((ruff, "rule", "--all", "--output-format", "json"), cwd=root)
    metadata = parse_ruff_metadata(output)

    contexts_by_rule = _resolved_ruff_contexts(root, ruff)

    rules: list[_Rule] = []
    for code, profile_contexts in sorted(contexts_by_rule.items()):
        try:
            item = metadata[code]
        except KeyError as exc:
            msg = f"enabled Ruff rule {code} is absent from installed metadata"
            raise ValueError(msg) from exc
        if not item.name:
            msg = f"Ruff metadata for {code} lacks a rule name"
            raise ValueError(msg)
        if not item.summary:
            msg = f"Ruff metadata for {code} lacks a summary"
            raise ValueError(msg)
        if item.code is not None and not item.linter:
            msg = f"Ruff metadata for {code} lacks a linter family"
            raise ValueError(msg)
        if not item.fix_availability:
            msg = f"Ruff metadata for {code} lacks required public fields"
            raise ValueError(msg)
        rules.append(
            _Rule(
                key=f"ruff:{code}",
                provider="ruff",
                id=RuleId(code),
                display_id=DisplayRuleId(code),
                summary=item.summary,
                docs_url=f"https://docs.astral.sh/ruff/rules/{item.name}/",
                family=item.linter,
                autofix=_ruff_autofix(item.fix_availability),
                has_suggestions=False,
                profiles=tuple(
                    _Profile(name=_profile_name(profile), contexts=tuple(contexts))
                    for profile, contexts in sorted(profile_contexts.items())
                ),
            )
        )
    version = _run((ruff, "--version"), cwd=root).strip().removeprefix("ruff ")
    provider = _Provider(
        id="ruff",
        label="Ruff",
        engine="ruff",
        package="ruff",
        version=version,
        homepage="https://docs.astral.sh/ruff/",
    )
    return _RuffProjection(provider, tuple(rules))


def parse_ruff_metadata(output: str) -> dict[str, _RuffMetadata]:
    metadata_values = TypeAdapter(tuple[_RuffMetadata, ...]).validate_json(output)
    # Ruff may expose preview rules by name before assigning a stable code or
    # linter family. The name is the stable selector Ruff accepts until a code
    # exists, so it remains part of the effective public inventory.
    return {value.code or value.name: value for value in metadata_values}


def _resolved_ruff_contexts(root: Path, ruff: str) -> dict[str, dict[str, list[_Context]]]:
    contexts_by_rule: dict[str, dict[str, list[_Context]]] = {}
    with tempfile.TemporaryDirectory(prefix="sarj-third-party-") as temporary:
        temporary_root = Path(temporary)
        for _, _, relative in _RUFF_CONTEXTS:
            path = temporary_root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("", encoding="utf-8")
        for profile, relative_config in sorted(_RUFF_CONFIGS.items()):
            config = root / relative_config
            for context_id, context_label, relative in _RUFF_CONTEXTS:
                settings = _run(
                    (ruff, "check", "--show-settings", "--config", str(config), str(temporary_root / relative)),
                    cwd=root,
                )
                for code in parse_enabled_ruff_rules(settings):
                    contexts_by_rule.setdefault(code, {}).setdefault(profile, []).append(
                        _Context(id=context_id, label=context_label, level="error")
                    )
    return contexts_by_rule


def _ruff_autofix(availability: str) -> Literal["always", "available", "none", "sometimes"]:
    normalized = availability.lower()
    match normalized:
        case "always" | "available" | "none" | "sometimes":
            return normalized
        case _:
            msg = f"unknown Ruff fix availability: {availability}"
            raise ValueError(msg)


def _profile_name(value: str) -> ProfileName:
    if value == "application":
        return "application"
    if value == "standard":
        return "standard"
    msg = f"unknown profile name: {value}"
    raise ValueError(msg)


if __name__ == "__main__":
    raise SystemExit(main())
