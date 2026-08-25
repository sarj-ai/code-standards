from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import re
import shutil
import subprocess  # ruff: ignore[suspicious-subprocess-import] -- pinned local tools produce a committed projection.
import sys
import tempfile
from types import MappingProxyType
from typing import ClassVar, Final, Literal, NewType

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter


_DESTINATION: Final = Path("apps/docs/src/generated/third-party-rules.v1.json")
_NODE_PROJECTION: Final = Path("packages/typescript/scripts/project-third-party-rules.mjs")
_RUFF_CONFIGS: Final = MappingProxyType(
    {
        "application": Path("packages/standards/src/sarj_standards/configs/ruff.application.toml"),
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

type ProfileName = Literal["application", "standard"]
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
    engine: Literal["eslint", "ruff"]
    package: str
    version: str
    homepage: str


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

    code: str
    name: str
    summary: str
    linter: str
    fix_availability: str


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
        if inside and (match := _ENABLED_RULE_RE.match(line)) is not None:
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
    ruff_projection = _ruff_projection(resolved, ruff)
    rules = (*eslint.rules, *ruff_projection.rules)
    used_providers = {rule.provider for rule in rules}
    providers = (*eslint.providers, ruff_projection.provider)
    return _CatalogArtifact(
        schema_version=1,
        profiles=("application", "standard"),
        providers=tuple(
            sorted((provider for provider in providers if provider.id in used_providers), key=lambda item: item.id)
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
    parser = argparse.ArgumentParser(description="synchronize the generated third-party rule catalog")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--sync", action="store_true")
    args = parser.parse_args()
    result = sync(args.root, check=args.check)  # pyright: ignore[reportAny]
    sys.stdout.write(f"{result.message}\n")
    return result.status


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


def _ruff_projection(root: Path, ruff: str) -> _RuffProjection:
    output = _run((ruff, "rule", "--all", "--output-format", "json"), cwd=root)
    metadata_values = TypeAdapter(tuple[_RuffMetadata, ...]).validate_json(output)
    metadata = {value.code: value for value in metadata_values}
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
        if not item.linter:
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
