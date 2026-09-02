from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
import json
from pathlib import Path, PurePosixPath
import re
from types import MappingProxyType
from typing import TYPE_CHECKING, NamedTuple, final, override

from sarj_iac_lint._hcl import document
from sarj_iac_lint.rule_base import (
    AutofixPolicy,
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    Rule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
)


if TYPE_CHECKING:
    from collections.abc import Iterator


_TFVARS_SUFFIX = ".tfvars"
_TFVARS_JSON_SUFFIX = ".tfvars.json"
_AUTO_STEM_SUFFIX = ".auto"
_ENVS_MANIFEST = "envs.json"

# Directories that never hold a root's own inputs; `.terraform` carries vendored
# module copies whose tfvars belong to other repositories entirely.
_SKIP_DIR_NAMES = frozenset({".terraform", ".git", "node_modules", "__pycache__", ".venv", "venv"})

# A tfvars file sits at most two directories below its root (`env/<name>/x.tfvars`),
# so root resolution never needs to climb further than three levels.
_MAX_ANCESTOR_HOPS = 3

# Cross-environment findings need at least two environments to compare.
_MIN_ENVIRONMENTS = 2

_MAX_VALUE_DISPLAY = 48

# Value tags a diagnostic may print, and only from unquoted source text. A
# string in a tfvars file is routinely a password, token or connection URI, and
# lint output reaches CI logs and PR annotations — places the (often gitignored)
# tfvars file never reaches. A quoted account id canonicalizes to a number but was
# written as a string, so the quote, not the tag alone, is the gate.
_PRINTABLE_TAGS = frozenset({"bool", "num", "null"})

# Stems that name a copy, a specimen or a scratch file rather than a deployment.
# A `backup.tfvars` beside `production.tfvars` is that file's backup, so treating
# it as a second environment makes every shared line "constant everywhere" — a
# tautology comparing a file against its own copy.
_NON_ENVIRONMENT_STEMS = frozenset(
    {"backup", "bak", "backend", "backend-config", "example", "sample", "template", "old", "copy", "tmp"}
)

# Terraform's own filename: it names no environment, so it takes the name of the
# directory that holds it.
_CONVENTIONAL_STEM = "terraform"


class _ScalarType(StrEnum):
    BOOL = "bool"
    NUMBER = "number"
    STRING = "string"


# Every auto-loaded root var-file belongs to one plan, so they share one label
# rather than each inventing an environment named after its file.
_AUTO_ENVIRONMENT = "(auto-loaded)"

_NUMBER_RE = re.compile(r"-?(?:\d+(?:\.\d+)?|\.\d+)(?:[eE][+-]?\d+)?")
_IDENT_RE = re.compile(r"[A-Za-z_][\w-]*")
_GENERATED_RE = re.compile(r"generated.{0,80}(?:do not edit|don't edit)", re.IGNORECASE)


# One comparable value: a tagged record so `"false"` and `false` canonicalize
# identically while `true` and `1` stay distinct, mirroring HCL's conversions.
@dataclass(frozen=True, slots=True)
class _Canon:
    tag: str
    value: object


class _ValueParseResult(NamedTuple):
    value: _Canon | None
    next_index: int


class _MapKeyParseResult(NamedTuple):
    key: str | None
    next_index: int


_BOOL_SCALARS: Mapping[str, _Canon] = MappingProxyType(
    {
        "true": _Canon(tag="bool", value=True),
        "false": _Canon(tag="bool", value=False),
    }
)
_KEYWORD_SCALARS: Mapping[str, _Canon] = MappingProxyType({**_BOOL_SCALARS, "null": _Canon("null", None)})


@final
class NoDeadEnvironmentInput(Rule):
    id = "no-dead-environment-input"
    code = "SARJ205"
    documentation = RuleDocumentation(
        summary=(
            "Find undeclared tfvars assignments and potentially redundant scalar values across discovered Terraform "
            "environments."
        ),
        rationale=(
            "Undeclared assignments are stale configuration, while repeated scalar values can hide whether a setting "
            "is truly environment-specific or belongs in shared configuration."
        ),
        remediation=(
            "Remove assignments that have no parsed declaration. For repeated values, confirm the setting is not an "
            "intentional per-environment contract before moving it to a default or shared input source."
        ),
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Cross-environment comparisons require at least two discovered, readable HCL tfvars environments.",
            (
                "Only scalar variables declared exactly as bool, number, or string are compared; dynamic, collection, "
                "interpolated, heredoc, JSON, and incomplete roots are conservatively skipped."
            ),
            (
                "Named tfvars files are inferred as environments; repeated values are advisory because invocation "
                "order and intentional fail-closed contracts cannot be proven from filenames."
            ),
            (
                "Generated fixtures, testdata, backend configuration, backups, templates, and other specimen inputs "
                "are excluded."
            ),
            "Sensitive and non-primitive values are never printed in diagnostics.",
        ),
        examples=(
            RuleExample(
                example_id="flag-constant-in-every-environment",
                title="Boolean assigned the same semantic value in every environment",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.iac(
                        "variables.tf",
                        'variable "pagerduty_enabled" {\n  type    = bool\n  default = true\n}\n',
                    ),
                    ExampleFile.iac("env/dev/terraform.tfvars", "pagerduty_enabled = false\n"),
                    ExampleFile.iac("env/prod/terraform.tfvars", "pagerduty_enabled = false\n"),
                ),
                focus_path=PurePosixPath("env/dev/terraform.tfvars"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="input-that-actually-varies",
                title="Data input carrying a real per-environment difference",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.iac("variables.tf", 'variable "redis_tier" {\n  type = string\n}\n'),
                    ExampleFile.iac("env/dev/terraform.tfvars", 'redis_tier = "BASIC"\n'),
                    ExampleFile.iac("env/prod/terraform.tfvars", 'redis_tier = "STANDARD_HA"\n'),
                ),
                focus_path=PurePosixPath("env/dev/terraform.tfvars"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="sensitive-value-repeated-across-environments",
                title="Sensitive input duplicated instead of injected once",
                outcome=ExampleOutcome.MATCH,
                scenario="sensitive-shared-input",
                files=(
                    ExampleFile.iac(
                        "variables.tf",
                        'variable "api_token" {\n  type      = string\n  sensitive = true\n}\n',
                    ),
                    ExampleFile.iac("env/dev/terraform.tfvars", 'api_token = "same-placeholder"\n'),
                    ExampleFile.iac("env/prod/terraform.tfvars", 'api_token = "same-placeholder"\n'),
                ),
                focus_path=PurePosixPath("env/dev/terraform.tfvars"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="sensitive-input-that-varies-by-environment",
                title="Sensitive input carrying an actual environment decision",
                outcome=ExampleOutcome.NO_MATCH,
                scenario="sensitive-shared-input",
                files=(
                    ExampleFile.iac(
                        "variables.tf",
                        'variable "api_token" {\n  type      = string\n  sensitive = true\n}\n',
                    ),
                    ExampleFile.iac("env/dev/terraform.tfvars", 'api_token = "dev-placeholder"\n'),
                    ExampleFile.iac("env/prod/terraform.tfvars", 'api_token = "prod-placeholder"\n'),
                ),
                focus_path=PurePosixPath("env/dev/terraform.tfvars"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="assignment-equal-to-declared-default",
                title="Assignment restating the variable's declared default",
                outcome=ExampleOutcome.MATCH,
                scenario="equals-default",
                files=(
                    ExampleFile.iac(
                        "variables.tf",
                        'variable "text_llm_enable_thinking" {\n  type    = bool\n  default = true\n}\n',
                    ),
                    ExampleFile.iac("env/dev/terraform.tfvars", "text_llm_enable_thinking = true\n"),
                ),
                focus_path=PurePosixPath("env/dev/terraform.tfvars"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="default-is-an-active-environment-choice",
                title="A sibling environment overrides the declared default",
                outcome=ExampleOutcome.NO_MATCH,
                scenario="equals-default",
                files=(
                    ExampleFile.iac(
                        "variables.tf",
                        'variable "text_llm_enable_thinking" {\n  type    = bool\n  default = true\n}\n',
                    ),
                    ExampleFile.iac("env/dev/terraform.tfvars", "text_llm_enable_thinking = true\n"),
                    ExampleFile.iac("env/prod/terraform.tfvars", "text_llm_enable_thinking = false\n"),
                ),
                focus_path=PurePosixPath("env/dev/terraform.tfvars"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="orphaned-assignment-after-variable-deletion",
                title="Assignment surviving the deletion of its variable",
                outcome=ExampleOutcome.MATCH,
                scenario="orphaned-key",
                files=(
                    ExampleFile.iac("variables.tf", 'variable "region" {\n  type = string\n}\n'),
                    ExampleFile.iac("env/dev/terraform.tfvars", 'region = "me-central2"\ngke_enabled = true\n'),
                ),
                focus_path=PurePosixPath("env/dev/terraform.tfvars"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="declared-assignment",
                title="Every tfvars assignment has a parsed root declaration",
                outcome=ExampleOutcome.NO_MATCH,
                scenario="orphaned-key",
                files=(
                    ExampleFile.iac(
                        "variables.tf",
                        'variable "region" {\n  type = string\n}\nvariable "gke_enabled" {\n  type = bool\n}\n',
                    ),
                    ExampleFile.iac("env/dev/terraform.tfvars", 'region = "me-central2"\ngke_enabled = true\n'),
                ),
                focus_path=PurePosixPath("env/dev/terraform.tfvars"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if not path.name.endswith((_TFVARS_SUFFIX, _TFVARS_JSON_SUFFIX)):
            return []
        if (
            path.name.endswith(_TFVARS_JSON_SUFFIX)
            or any(part.lower() in {"fixture", "fixtures", "testdata"} for part in path.parts)
            or _generated_header(source)
        ):
            return []
        root = _find_root(path)
        if root is None:
            return []
        analysis = _analyze_root(root)
        resolved = path.resolve()
        environment = analysis.environment_of(resolved)
        if environment is None:
            return []
        diags = [
            Diagnostic(path=path, line=attr.line, col=attr.col, code=self.code, message=message)
            for attr in document(source).attributes
            if (message := _assignment_message(analysis, environment, attr.name, attr.value)) is not None
        ]
        return sorted(diags, key=lambda d: (d.line, d.col))


@dataclass(frozen=True, slots=True)
class _Declaration:
    has_default: bool
    default: _Canon | None
    scalar_type: _ScalarType | None
    sensitive: bool


@dataclass(frozen=True, slots=True)
class _AssignmentValue:
    text: str
    canon: _Canon | None
    file: Path


@dataclass(frozen=True, slots=True)
class _BlindEnvironment:
    name: str
    reason: str


@dataclass(frozen=True, slots=True)
class _RootAnalysis:
    root: Path
    files: Mapping[str, tuple[Path, ...]]
    declarations: Mapping[str, _Declaration]
    values: Mapping[str, Mapping[str, _AssignmentValue]]
    blind: tuple[_BlindEnvironment, ...]
    declarations_complete: bool

    def environment_of(self, resolved: Path) -> str | None:
        return next((env for env, paths in self.files.items() if any(resolved == p.resolve() for p in paths)), None)


def _assignment_message(analysis: _RootAnalysis, environment: str, name: str, value: str) -> str | None:
    declaration = analysis.declarations.get(name)
    if declaration is None:
        if not analysis.declarations_complete:
            return None
        return (
            f"orphaned-key: `{name}` has no declaration in the parsed root `{analysis.root.name}`; "
            "remove it if this is a variable file, or restore the missing declaration."
        )
    if declaration.scalar_type is None:
        return None
    canon = _canonical_for_type(value, declaration.scalar_type)
    display = _display(canon, value, sensitive=declaration.sensitive)
    if (
        canon is not None
        and declaration.default is not None
        and canon == declaration.default
        # A blind root cannot rule out a sibling override: the environment it
        # cannot read is exactly the one whose value would keep this line.
        and not analysis.blind
        and not _varies_elsewhere(analysis, name)
    ):
        return (
            f"equals-default: `{name}` is assigned its declared default{display} — "
            "consider removing it only if this environment should inherit future default changes."
        )
    if not _constant_everywhere(analysis, environment, name, canon):
        return None
    environments = ", ".join(sorted(analysis.files))
    if declaration.sensitive:
        return (
            f"sensitive-constant: `{name}` carries one sensitive value across every environment "
            f"({environments}) — inject it once through the shared secret source and delete the duplicate "
            "per-environment assignments; do not hard-code a default."
        )
    if declaration.has_default:
        return (
            f"constant-everywhere: `{name}` carries one value{display} across every environment "
            f"({environments}); consider using the shared default if the repetition is not an intentional contract."
        )
    return (
        f"required-but-constant: `{name}` has no default yet every environment ({environments}) assigns "
        f"one value{display}; consider a shared input source while preserving requiredness when it is intentional."
    )


def _varies_elsewhere(analysis: _RootAnalysis, name: str) -> bool:
    canons = {value.canon for value in analysis.values.get(name, {}).values()}
    # An opaque sibling (heredoc or interpolation) counts as variation, not as
    # agreement: `None` joins the set on its own. Advising deletion of a line a
    # sibling may override is the costly direction to be wrong in.
    return len(canons) > 1


def _constant_everywhere(analysis: _RootAnalysis, environment: str, name: str, canon: _Canon | None) -> bool:
    if analysis.blind or canon is None or len(analysis.files) < _MIN_ENVIRONMENTS:
        return False
    per_env = analysis.values.get(name, {})
    if set(per_env) != set(analysis.files):
        return False
    return all(
        env == environment or (other.canon is not None and other.canon == canon) for env, other in per_env.items()
    )


def _display(canon: _Canon | None, value: str, *, sensitive: bool) -> str:
    text = " ".join(value.split())
    if sensitive or canon is None or canon.tag not in _PRINTABLE_TAGS or text.startswith(('"', "'")):
        return ""
    return f" ({text})" if len(text) <= _MAX_VALUE_DISPLAY else ""


def _generated_header(source: str) -> bool:
    header = "\n".join(line for line in source.splitlines()[:20] if line.lstrip().startswith(("#", "//", "/*", "*")))
    return _GENERATED_RE.search(header) is not None


def _find_root(path: Path) -> Path | None:
    absolute = path if path.is_absolute() else Path.cwd() / path
    if any(part in _SKIP_DIR_NAMES for part in absolute.parts):
        return None
    directory = absolute.parent
    for _ in range(_MAX_ANCESTOR_HOPS):
        if _has_tf_files(directory):
            return directory if _declares_variables(directory) else None
        if directory.parent == directory:
            return None
        directory = directory.parent
    return None


def _has_tf_files(directory: Path) -> bool:
    return next(iter(directory.glob("*.tf")), None) is not None


def _declares_variables(directory: Path) -> bool:
    return next(_variable_blocks(directory), None) is not None


def _variable_blocks(directory: Path) -> Iterator[tuple[str, str | None, _ScalarType | None, bool]]:
    for tf in sorted(directory.glob("*.tf")):
        text = _read_text(tf)
        if text is None:
            continue
        for block in document(text).blocks:
            if block.type == "variable" and block.labels:
                default = block.attribute("default")
                declared = block.attribute("type")
                declared_type = None if declared is None else declared.value.strip()
                try:
                    scalar_type = None if declared_type is None else _ScalarType(declared_type)
                except ValueError:
                    scalar_type = None
                sensitive_attr = block.attribute("sensitive")
                sensitive = sensitive_attr is not None and _canonical(sensitive_attr.value) != _BOOL_SCALARS["false"]
                yield block.labels[0], None if default is None else default.value, scalar_type, sensitive


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _analyze_root(root: Path) -> _RootAnalysis:
    files = _environment_files(root)
    declarations = {
        name: _Declaration(
            default is not None,
            None if default is None or scalar_type is None else _canonical_for_type(default, scalar_type),
            scalar_type,
            sensitive,
        )
        for name, default, scalar_type, sensitive in _variable_blocks(root)
    }
    values: dict[str, dict[str, _AssignmentValue]] = {}
    blind = list(_structural_blind(root, files))
    # One report per ambiguous environment: every later conflict in it has the
    # same cause and the same fix, so naming the first is the whole message.
    conflicted: set[str] = set()
    blind.extend(_auto_loaded_blind(files))
    for env, paths in files.items():
        for file in paths:
            text = _read_text(file)
            if text is None:
                blind.append(_BlindEnvironment(env, f"`{file.name}` for environment `{env}` cannot be read"))
                continue
            for attr in document(text).attributes:
                declaration = declarations.get(attr.name)
                assignment = _AssignmentValue(
                    attr.value,
                    None
                    if declaration is None or declaration.scalar_type is None
                    else _canonical_for_type(attr.value, declaration.scalar_type),
                    file,
                )
                previous = values.setdefault(attr.name, {}).get(env)
                if previous is not None and env not in conflicted:
                    # Terraform rejects a key redefined inside one file, so that
                    # file's inputs are not a thing this rule can reason about;
                    # only a disagreement BETWEEN files is a var-file ordering
                    # question. Both leave the environment unknowable.
                    same_file = previous.file == file
                    if same_file or previous.canon != assignment.canon:
                        conflicted.add(env)
                        blind.append(
                            _BlindEnvironment(
                                env,
                                _redefinition_reason(env, attr.name, file)
                                if same_file
                                else _conflict_reason(env, attr.name, paths),
                            )
                        )
                values[attr.name][env] = assignment
    blind.extend(_manifest_blind(root, frozenset(files)))
    return _RootAnalysis(
        root=root,
        files={env: tuple(paths) for env, paths in files.items()},
        declarations=declarations,
        values=values,
        blind=tuple(sorted(blind, key=lambda item: (item.name, item.reason))),
        declarations_complete=next(iter(root.glob("*.tf.json")), None) is None,
    )


def _auto_loaded_blind(files: Mapping[str, Sequence[Path]]) -> Iterator[_BlindEnvironment]:
    auto = files.get(_AUTO_ENVIRONMENT, ())
    named = {env for env in files if env != _AUTO_ENVIRONMENT}
    if not auto or not named:
        return
    listed = ", ".join(f"`{file.name}`" for file in sorted(auto))
    yield _BlindEnvironment(
        min(named),
        f"{listed} is auto-loaded into every plan, so beside the named environment files "
        f"({', '.join(sorted(named))}) it is a baseline whose precedence this rule cannot model",
    )


def _redefinition_reason(environment: str, name: str, file: Path) -> str:
    return (
        f"`{file.name}` assigns `{name}` twice, which Terraform rejects as a redefined attribute, "
        f"so environment `{environment}` has no inputs this rule can read"
    )


def _conflict_reason(environment: str, name: str, paths: Sequence[Path]) -> str:
    named = ", ".join(f"`{path.name}`" for path in paths)
    return (
        f"environment `{environment}` is defined by more than one file ({named}) and they assign "
        f"`{name}` different values, so its effective inputs depend on var-file order"
    )


def _environment_files(root: Path) -> dict[str, list[Path]]:
    out: dict[str, list[Path]] = {}
    seen: set[Path] = set()
    for file, environment in _candidate_environments(root):
        if _is_non_environment(environment):
            continue
        resolved = file.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        out.setdefault(environment, []).append(file)
    return out


def _candidate_environments(root: Path) -> Iterator[tuple[Path, str]]:
    for file in sorted(root.glob(f"*{_TFVARS_SUFFIX}")):
        # Terraform loads every auto-loaded root var-file into the SAME plan, so
        # `a.auto.tfvars` and `b.auto.tfvars` are one environment, not two whose
        # shared lines would read as constant across it.
        yield file, _AUTO_ENVIRONMENT if _is_auto_loaded(file.name) else _stem_environment(file.name)
    for file, env_dir in _nested_tfvars(root, _TFVARS_SUFFIX):
        stem = _stem_environment(file.name)
        yield file, env_dir.name if stem == _CONVENTIONAL_STEM else stem


def _is_auto_loaded(name: str) -> bool:
    stem = name.removesuffix(_TFVARS_SUFFIX)
    return stem == _CONVENTIONAL_STEM or stem.endswith(_AUTO_STEM_SUFFIX)


def _is_non_environment(label: str) -> bool:
    lowered = label.lower()
    return lowered in _NON_ENVIRONMENT_STEMS or lowered.rsplit(".", 1)[-1] in _NON_ENVIRONMENT_STEMS


def _nested_tfvars(root: Path, suffix: str) -> Iterator[tuple[Path, Path]]:
    for pattern in (f"*/*{suffix}", f"*/*/*{suffix}"):
        for file in sorted(root.glob(pattern)):
            relative_dirs = file.relative_to(root).parts[:-1]
            if any(part in _SKIP_DIR_NAMES for part in relative_dirs):
                continue
            if any(_has_tf_files(root.joinpath(*relative_dirs[: index + 1])) for index in range(len(relative_dirs))):
                continue
            yield file, file.parent


def _stem_environment(name: str) -> str:
    stem = name.removesuffix(_TFVARS_SUFFIX)
    return stem.removesuffix(_AUTO_STEM_SUFFIX)


def _structural_blind(root: Path, files: dict[str, list[Path]]) -> Iterator[_BlindEnvironment]:
    for file, env_dir in _nested_tfvars(root, _TFVARS_JSON_SUFFIX):
        yield _BlindEnvironment(env_dir.name, f"`{file.relative_to(root)}` is JSON, which this rule does not parse")
    for json_file in sorted(root.glob(f"*{_TFVARS_JSON_SUFFIX}")):
        yield _BlindEnvironment(json_file.name, f"`{json_file.name}` is JSON, which this rule does not parse")
    containers = {
        path.parent.parent
        for paths in files.values()
        for path in paths
        if root not in {path.parent.parent, path.parent}
    }
    for container in sorted(containers, key=str):
        for sibling in sorted(item for item in container.iterdir() if item.is_dir()):
            if sibling.name in _SKIP_DIR_NAMES or sibling.name in files:
                continue
            if next(iter(sibling.glob(f"*{_TFVARS_JSON_SUFFIX}")), None) is not None:
                continue  # Already reported above as unparsed JSON.
            yield _BlindEnvironment(
                sibling.name,
                f"environment directory `{sibling.relative_to(root)}` has no tfvars file while sibling environments have one",
            )


def _manifest_blind(root: Path, environments: frozenset[str]) -> Iterator[_BlindEnvironment]:
    manifest = root / _ENVS_MANIFEST
    if not manifest.is_file():
        return
    text = _read_text(manifest)
    if text is None:
        yield _BlindEnvironment("(all)", f"`{_ENVS_MANIFEST}` names this root's environments but cannot be read")
        return
    try:
        raw: object = json.loads(  # pyright: ignore[reportAny] — json.loads is untyped; the shape is narrowed below
            text
        )
    except json.JSONDecodeError as exc:
        yield _BlindEnvironment(
            "(all)", f"`{_ENVS_MANIFEST}` names this root's environments but cannot be parsed: {exc}"
        )
        return
    if not isinstance(raw, dict):
        yield _BlindEnvironment("(all)", f"`{_ENVS_MANIFEST}` names this root's environments but is not a JSON object")
        return
    for name, entry in raw.items():  # pyright: ignore[reportUnknownVariableType] — json leaves are Any; narrowed below
        if not isinstance(name, str) or name in environments:
            continue
        secret = _tfvars_secret(entry)  # pyright: ignore[reportUnknownArgumentType] — json leaves are Any; `_tfvars_secret` narrows
        held = f" with tfvars held in secret `{secret}`" if secret is not None else ""
        yield _BlindEnvironment(
            name, f"`{_ENVS_MANIFEST}` declares environment `{name}`{held} but no tfvars file for it is on disk"
        )


def _tfvars_secret(entry: object) -> str | None:
    if not isinstance(entry, dict):
        return None
    for key, value in entry.items():  # pyright: ignore[reportUnknownVariableType] — json leaves are Any; narrowed below
        if isinstance(key, str) and "tfvars" in key and isinstance(value, str):
            return value
    return None


def _canonical_for_type(text: str, scalar_type: _ScalarType) -> _Canon | None:
    canon = _canonical(text)
    if canon is None:
        return None
    if scalar_type is _ScalarType.BOOL:
        return canon if canon.tag == "bool" else None
    if scalar_type is _ScalarType.NUMBER:
        return canon if canon.tag == "num" else None

    stripped = text.strip()
    if stripped.startswith('"'):
        parsed = _parse_string(stripped, 0)
        if parsed.value is None or parsed.next_index != len(stripped):
            return None
        return _Canon("str", stripped[1:-1])
    if canon.tag == "bool":
        return _Canon("str", "true" if canon.value is True else "false")
    if canon.tag == "num" and isinstance(canon.value, Decimal):
        return _Canon("str", format(canon.value.normalize(), "f"))
    return canon if canon.tag == "str" else None


def _canonical(text: str) -> _Canon | None:
    if "${" in text or "<<" in text:
        return None
    parsed = _parse_value(text, _skip_ws(text, 0))
    return parsed.value if parsed.value is not None and _skip_ws(text, parsed.next_index) == len(text) else None


def _skip_ws(text: str, index: int) -> int:
    while index < len(text) and text[index].isspace():
        index += 1
    return index


def _parse_value(text: str, index: int) -> _ValueParseResult:
    if index >= len(text):
        return _ValueParseResult(None, index)
    char = text[index]
    if char == '"':
        return _parse_string(text, index)
    if char == "[":
        return _parse_list(text, index)
    if char == "{":
        return _parse_map(text, index)
    if (number := _NUMBER_RE.match(text, index)) is not None:
        return _ValueParseResult(_Canon("num", Decimal(number.group(0))), number.end())
    if (ident := _IDENT_RE.match(text, index)) is not None and (
        keyword := _KEYWORD_SCALARS.get(ident.group(0))
    ) is not None:
        return _ValueParseResult(keyword, ident.end())
    return _ValueParseResult(None, index)


def _parse_string(text: str, index: int) -> _ValueParseResult:
    cursor = index + 1
    while cursor < len(text):
        char = text[cursor]
        if char == "\\":
            cursor += 2
            continue
        if char == '"':
            return _ValueParseResult(_string_scalar(text[index + 1 : cursor]), cursor + 1)
        cursor += 1
    return _ValueParseResult(None, index)


def _string_scalar(inner: str) -> _Canon:
    if (bool_scalar := _BOOL_SCALARS.get(inner)) is not None:
        return bool_scalar
    if _NUMBER_RE.fullmatch(inner) is not None:
        return _Canon("num", Decimal(inner))
    return _Canon("str", inner)


def _parse_list(text: str, index: int) -> _ValueParseResult:
    items: list[_Canon] = []
    cursor = _skip_ws(text, index + 1)
    while cursor < len(text):
        if text[cursor] == "]":
            return _ValueParseResult(_Canon("list", tuple(items)), cursor + 1)
        parsed = _parse_value(text, cursor)
        cursor = parsed.next_index
        if parsed.value is None:
            return _ValueParseResult(None, cursor)
        items.append(parsed.value)
        cursor = _skip_ws(text, cursor)
        if cursor < len(text) and text[cursor] == ",":
            cursor = _skip_ws(text, cursor + 1)
    return _ValueParseResult(None, cursor)


def _parse_map(text: str, index: int) -> _ValueParseResult:
    entries: dict[str, _Canon] = {}
    cursor = _skip_ws(text, index + 1)
    while cursor < len(text):
        if text[cursor] == "}":
            return _ValueParseResult(_Canon("map", tuple(sorted(entries.items()))), cursor + 1)
        parsed_key = _parse_map_key(text, cursor)
        cursor = parsed_key.next_index
        if parsed_key.key is None:
            return _ValueParseResult(None, cursor)
        cursor = _skip_ws(text, cursor)
        if cursor >= len(text) or text[cursor] not in {"=", ":"}:
            return _ValueParseResult(None, cursor)
        parsed_value = _parse_value(text, _skip_ws(text, cursor + 1))
        cursor = parsed_value.next_index
        if parsed_value.value is None:
            return _ValueParseResult(None, cursor)
        entries[parsed_key.key] = parsed_value.value
        cursor = _skip_ws(text, cursor)
        if cursor < len(text) and text[cursor] == ",":
            cursor = _skip_ws(text, cursor + 1)
    return _ValueParseResult(None, cursor)


def _parse_map_key(text: str, index: int) -> _MapKeyParseResult:
    if text[index] == '"':
        cursor = index + 1
        while cursor < len(text) and text[cursor] != '"':
            cursor += 2 if text[cursor] == "\\" else 1
        return (
            _MapKeyParseResult(text[index + 1 : cursor], cursor + 1)
            if cursor < len(text)
            else _MapKeyParseResult(None, index)
        )
    if (ident := _IDENT_RE.match(text, index)) is not None:
        return _MapKeyParseResult(ident.group(0), ident.end())
    return _MapKeyParseResult(None, index)
