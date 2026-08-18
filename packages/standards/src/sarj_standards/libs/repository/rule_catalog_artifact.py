from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import json
from pathlib import Path, PurePosixPath
import shutil
import subprocess  # ruff: ignore[suspicious-subprocess-import] -- fixed local build commands generate the committed catalog.
from typing import Final, Protocol, TypeGuard

from sarj_standards.libs.repository import rule_inventory_artifact
from sarj_standards.libs.rules import (
    AutofixPolicy,
    DefaultLevel,
    DocumentedRule,
    ExampleFile,
    ExpectedOutcome,
    Language,
    MessageId,
    RuleCatalogDocument,
    RuleCategory,
    RuleEngine,
    RuleExample,
    RuleId,
    RuleSpec,
)
from sarj_standards.schemas import RULE_CATALOG


_CATALOG_PATH: Final = Path("packages/standards/src/sarj_standards/schemas/rule-catalog.v1.json")
_WARNING_LEVELS_PATH: Final = Path("packages/standards/src/sarj_standards/configs/rule-warning-levels.v1.json")
_TYPESCRIPT_PACKAGE: Final = Path("packages/typescript")
_NODE_PROJECTION: Final = (
    "import {publicDocumentation,rules} from './dist/index.js';"
    "process.stdout.write(JSON.stringify(publicDocumentation(rules)));"
)
_TYPESCRIPT_FIELDS: Final = frozenset(
    {
        "aliases",
        "autofix",
        "category",
        "code",
        "engine",
        "examples",
        "filePatterns",
        "languages",
        "limitations",
        "messageIds",
        "optionsSchema",
        "rationale",
        "references",
        "remediation",
        "ruleId",
        "since",
        "summary",
    }
)
_TYPESCRIPT_EXAMPLE_FIELDS: Final = frozenset(
    {"expectedCount", "files", "fixedFiles", "focusPath", "id", "outcome", "scenarioId", "title"}
)
_TYPESCRIPT_FILE_FIELDS: Final = frozenset({"path", "source"})
_PROCESS_TIMEOUT: Final = timedelta(seconds=120)


@dataclass(frozen=True, slots=True)
class CatalogSyncResult:
    status: int
    message: str


def load(path: Path = RULE_CATALOG) -> dict[str, object]:
    try:
        payload: object = json.loads(path.read_text(encoding="utf-8"))  # pyright: ignore[reportAny]
    except (OSError, json.JSONDecodeError) as exc:
        msg = f"cannot load shipped rule catalog {path}: {exc}"
        raise ValueError(msg) from exc
    if not _is_object(payload) or payload.get("schemaVersion") != 1 or not _is_array(payload.get("rules")):
        msg = "shipped rule catalog must contain schemaVersion 1 and a rules array"
        raise ValueError(msg)
    return payload


class _StringEnum(Protocol):
    @property
    def value(self) -> str: ...


class _NativeExampleFile(Protocol):
    @property
    def path(self) -> PurePosixPath: ...

    @property
    def source(self) -> str: ...


class _NativeExample(Protocol):
    @property
    def example_id(self) -> str: ...

    @property
    def title(self) -> str: ...

    @property
    def outcome(self) -> _StringEnum: ...

    @property
    def files(self) -> tuple[_NativeExampleFile, ...]: ...

    @property
    def fixed_files(self) -> tuple[_NativeExampleFile, ...]: ...

    @property
    def focus_path(self) -> PurePosixPath: ...

    @property
    def expected_count(self) -> int: ...

    @property
    def public(self) -> bool: ...

    @property
    def scenario(self) -> str: ...


class _NativeSpec(Protocol):
    @property
    def rule_id(self) -> str: ...

    @property
    def code(self) -> str: ...

    @property
    def summary(self) -> str: ...

    @property
    def rationale(self) -> str: ...

    @property
    def remediation(self) -> str: ...

    @property
    def category(self) -> _StringEnum: ...

    @property
    def autofix(self) -> _StringEnum: ...

    @property
    def aliases(self) -> tuple[str, ...]: ...

    @property
    def limitations(self) -> tuple[str, ...]: ...

    @property
    def examples(self) -> tuple[_NativeExample, ...]: ...


def _is_object(value: object) -> TypeGuard[dict[str, object]]:
    return isinstance(value, dict) and all(
        isinstance(key, str)
        for key in value  # pyright: ignore[reportUnknownVariableType]
    )


def _is_array(value: object) -> TypeGuard[list[object]]:
    return isinstance(value, list)


def _native_spec(native: _NativeSpec, *, engine: RuleEngine, languages: frozenset[Language]) -> RuleSpec:
    return RuleSpec(
        engine=engine,
        rule_id=RuleId(native.rule_id),
        code=native.code,
        summary=native.summary,
        rationale=native.rationale,
        remediation=native.remediation,
        category=RuleCategory(native.category.value),
        languages=languages,
        autofix=AutofixPolicy(native.autofix.value),
        aliases=native.aliases,
        limitations=native.limitations,
        examples=tuple(_example(item) for item in native.examples),
    )


def _example(native: _NativeExample) -> RuleExample:
    return RuleExample(
        example_id=native.example_id,
        title=native.title,
        outcome=ExpectedOutcome(native.outcome.value),
        files=tuple(_example_file(item) for item in native.files),
        fixed_files=tuple(_example_file(item) for item in native.fixed_files),
        focus_path=native.focus_path,
        expected_count=native.expected_count,
        public=native.public,
        scenario=native.scenario,
    )


def _example_file(native: _NativeExampleFile) -> ExampleFile:
    return ExampleFile(path=native.path, source=native.source)


def parse_typescript_projection(payload: object) -> tuple[RuleSpec, ...]:
    if not _is_array(payload):
        msg = "TypeScript public metadata projection must be an array"
        raise TypeError(msg)
    return tuple(_typescript_spec(item) for item in payload)


def _typescript_spec(value: object) -> RuleSpec:
    if not _is_object(value):
        msg = "TypeScript public metadata entry must be an object"
        raise TypeError(msg)
    if frozenset(value) != _TYPESCRIPT_FIELDS:
        msg = "TypeScript public metadata entry has unexpected or missing fields"
        raise ValueError(msg)
    if value["engine"] != RuleEngine.ESLINT.value or value["code"] is not None:
        msg = "TypeScript public metadata has invalid engine or code"
        raise ValueError(msg)
    examples = value.get("examples")
    if not _is_array(examples):
        msg = "TypeScript public metadata examples must be an array"
        raise TypeError(msg)
    options = value.get("optionsSchema")
    if options is not None and not _is_object(options):
        msg = "TypeScript public metadata optionsSchema must be an object or null"
        raise TypeError(msg)
    since = value.get("since")
    if since is not None and not isinstance(since, str):
        msg = "TypeScript public metadata since must be a string or null"
        raise TypeError(msg)
    return RuleSpec(
        engine=RuleEngine.ESLINT,
        rule_id=RuleId(_value_from_dict(value, "ruleId")),
        code=None,
        summary=_value_from_dict(value, "summary"),
        rationale=_value_from_dict(value, "rationale"),
        remediation=_value_from_dict(value, "remediation"),
        category=RuleCategory(_value_from_dict(value, "category")),
        languages=frozenset(Language(item) for item in _string_list(value, "languages")),
        autofix=AutofixPolicy(_value_from_dict(value, "autofix")),
        aliases=tuple(_string_list(value, "aliases")),
        limitations=tuple(_string_list(value, "limitations")),
        file_patterns=tuple(_string_list(value, "filePatterns")),
        message_ids=tuple(MessageId(item) for item in _string_list(value, "messageIds")),
        options_schema=None if options is None else json.dumps(options, separators=(",", ":"), sort_keys=True),
        references=tuple(_string_list(value, "references")),
        since=since,
        examples=tuple(_typescript_example(item) for item in examples),
    )


def _value_from_dict(value: dict[str, object], name: str) -> str:
    item = value.get(name)
    if not isinstance(item, str) or not item:
        msg = f"TypeScript public metadata has invalid {name}"
        raise ValueError(msg)
    return item


def _string_list(value: dict[str, object], name: str) -> list[str]:
    item = value.get(name)
    if not _is_array(item) or not all(isinstance(entry, str) for entry in item):
        msg = f"TypeScript public metadata has invalid {name}"
        raise ValueError(msg)
    return [entry for entry in item if isinstance(entry, str)]


def _typescript_example(value: object) -> RuleExample:
    if not _is_object(value):
        msg = "TypeScript public example must be an object"
        raise TypeError(msg)
    if frozenset(value) != _TYPESCRIPT_EXAMPLE_FIELDS:
        msg = "TypeScript public example has unexpected or missing fields"
        raise ValueError(msg)
    files = value.get("files")
    fixed_files = value.get("fixedFiles")
    if not _is_array(files) or not _is_array(fixed_files):
        msg = "TypeScript public example files must be arrays"
        raise TypeError(msg)
    focus_path = _value_from_dict(value, "focusPath")
    expected_count = value.get("expectedCount")
    if type(expected_count) is not int:
        msg = "TypeScript public example expectedCount must be an integer"
        raise TypeError(msg)
    return RuleExample(
        example_id=_value_from_dict(value, "id"),
        title=_value_from_dict(value, "title"),
        outcome=ExpectedOutcome(_value_from_dict(value, "outcome")),
        files=tuple(_typescript_file(item) for item in files),
        fixed_files=tuple(_typescript_file(item) for item in fixed_files),
        focus_path=PurePosixPath(focus_path),
        expected_count=expected_count,
        public=True,
        scenario=_value_from_dict(value, "scenarioId"),
    )


def _typescript_file(value: object) -> ExampleFile:
    if not _is_object(value):
        msg = "TypeScript public example file must be an object"
        raise TypeError(msg)
    if frozenset(value) != _TYPESCRIPT_FILE_FIELDS:
        msg = "TypeScript public example file has unexpected or missing fields"
        raise ValueError(msg)
    return ExampleFile(
        path=PurePosixPath(_value_from_dict(value, "path")),
        source=_value_from_dict(value, "source"),
    )


def build(  # ruff: ignore[too-many-locals] -- joins five engine registries with lifecycle metadata.
    root: Path,
) -> RuleCatalogDocument:
    from sarj_standards.libs.linting import textlint  # ruff: ignore[import-outside-top-level]

    resolved = root.resolve()
    warning_rules = _warning_rules(resolved)
    inventory = rule_inventory_artifact.build(resolved)
    raw_rules = inventory["rules"]
    if not _is_array(raw_rules):
        msg = "rule inventory rules must be an array"
        raise TypeError(msg)
    locations: dict[tuple[str, str], tuple[PurePosixPath, PurePosixPath]] = {}
    for value in raw_rules:
        if not _is_object(value):
            msg = "rule inventory entry must be an object"
            raise TypeError(msg)
        family = _value_from_dict(value, "family")
        rule_id = _value_from_dict(value, "id")
        locations[family, rule_id] = (
            PurePosixPath(_value_from_dict(value, "source")),
            PurePosixPath(_value_from_dict(value, "test")),
        )

    specs = (
        *_python_specs(),
        *_sql_specs(),
        *_iac_specs(),
        *(meta.native_spec(rule_id) for rule_id, meta in textlint.REGISTRY.items()),
        *_typescript_specs(resolved),
    )
    engine_family = {
        RuleEngine.ESLINT: "typescript",
        RuleEngine.IAC: "iac",
        RuleEngine.PYTHON: "python",
        RuleEngine.SQL: "sql",
        RuleEngine.TEXT: "text",
    }
    documented: list[DocumentedRule] = []
    for spec in specs:
        family = engine_family[spec.engine]
        try:
            source, test = locations.pop((family, spec.rule_id))
        except KeyError as exc:
            msg = f"{spec.key} is documented but absent from the live inventory"
            raise ValueError(msg) from exc
        documented.append(
            DocumentedRule(
                spec=spec,
                default_level=(DefaultLevel.WARNING if spec.key in warning_rules else DefaultLevel.ERROR),
                source=source,
                test=test,
            )
        )
    if locations:
        missing = ", ".join(f"{family}:{rule_id}" for family, rule_id in sorted(locations))
        msg = f"live rules missing source-owned documentation: {missing}"
        raise ValueError(msg)
    live_keys = {rule.spec.key for rule in documented}
    unknown_warning_rules = warning_rules - live_keys
    if unknown_warning_rules:
        msg = f"warning lifecycle names unknown rules: {', '.join(sorted(unknown_warning_rules))}"
        raise ValueError(msg)
    return RuleCatalogDocument(tuple(documented))


def _warning_rules(root: Path) -> frozenset[str]:
    path = root / _WARNING_LEVELS_PATH
    payload: object = json.loads(path.read_text(encoding="utf-8"))  # pyright: ignore[reportAny]
    if not _is_object(payload) or set(payload) != {"rules", "schemaVersion"}:
        msg = "rule warning lifecycle must contain exactly rules and schemaVersion"
        raise ValueError(msg)
    if payload["schemaVersion"] != 1 or not _is_array(payload["rules"]):
        msg = "rule warning lifecycle must use schemaVersion 1 and an array of rules"
        raise TypeError(msg)
    rules = payload["rules"]
    if any(not isinstance(value, str) for value in rules):
        msg = "rule warning lifecycle selectors must be strings"
        raise TypeError(msg)
    selected = frozenset(value for value in rules if isinstance(value, str))
    if len(selected) != len(rules):
        msg = "rule warning lifecycle repeats a selector"
        raise ValueError(msg)
    return selected


def _python_specs() -> tuple[RuleSpec, ...]:
    from sarj_python_lint.rules import REGISTRY  # ruff: ignore[import-outside-top-level]

    specs: list[RuleSpec] = []
    for rule_id, rule in REGISTRY.items():
        native = rule.native_spec()
        if native is None:
            msg = f"python:{rule_id} is missing source-owned documentation"
            raise ValueError(msg)
        specs.append(_native_spec(native, engine=RuleEngine.PYTHON, languages=frozenset({Language.PYTHON})))
    return tuple(specs)


def _sql_specs() -> tuple[RuleSpec, ...]:
    from sarj_sql_lint.rules import REGISTRY  # ruff: ignore[import-outside-top-level]

    specs: list[RuleSpec] = []
    for rule_id, rule in REGISTRY.items():
        native = rule.native_spec()
        if native is None:
            msg = f"sql:{rule_id} is missing source-owned documentation"
            raise ValueError(msg)
        specs.append(_native_spec(native, engine=RuleEngine.SQL, languages=frozenset({Language.SQL})))
    return tuple(specs)


def _iac_specs() -> tuple[RuleSpec, ...]:
    from sarj_iac_lint.rules import REGISTRY  # ruff: ignore[import-outside-top-level]

    specs: list[RuleSpec] = []
    for rule_id, rule in REGISTRY.items():
        native = rule.native_spec()
        if native is None:
            msg = f"iac:{rule_id} is missing source-owned documentation"
            raise ValueError(msg)
        specs.append(_native_spec(native, engine=RuleEngine.IAC, languages=frozenset({Language.IAC})))
    return tuple(specs)


def _typescript_specs(root: Path) -> tuple[RuleSpec, ...]:
    package = root / _TYPESCRIPT_PACKAGE
    npm = shutil.which("npm")
    node = shutil.which("node")
    if npm is None or node is None:
        missing = "npm" if npm is None else "node"
        msg = f"cannot generate the TypeScript rule catalog: {missing} is not installed"
        raise RuntimeError(msg)
    subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true] -- resolved executable and fixed argv.
        (npm, "run", "build", "--silent"),
        cwd=package,
        check=True,
        timeout=_PROCESS_TIMEOUT.total_seconds(),
    )
    completed = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true] -- resolved executable and fixed projection.
        (node, "--input-type=module", "--eval", _NODE_PROJECTION),
        cwd=package,
        check=True,
        capture_output=True,
        text=True,
        timeout=_PROCESS_TIMEOUT.total_seconds(),
    )
    payload: object = json.loads(completed.stdout)  # pyright: ignore[reportAny]
    return parse_typescript_projection(payload)


def render(root: Path) -> str:
    return json.dumps(build(root).as_public_dict(), ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n"


def sync(root: Path, *, check: bool) -> CatalogSyncResult:
    from sarj_standards.libs.adoption import transaction  # ruff: ignore[import-outside-top-level]

    resolved = root.resolve()
    destination = resolved / _CATALOG_PATH
    expected = render(resolved)
    current = destination.read_text(encoding="utf-8") if destination.is_file() else ""
    if current == expected:
        return CatalogSyncResult(0, "ok: rule-catalog.v1.json matches source-owned metadata")
    if check:
        return CatalogSyncResult(1, "drift: rule-catalog.v1.json differs; run `sarj-standards maintain catalog sync`")
    transaction.atomic_write_text(resolved, destination, expected)
    return CatalogSyncResult(0, "updated: rule-catalog.v1.json")
