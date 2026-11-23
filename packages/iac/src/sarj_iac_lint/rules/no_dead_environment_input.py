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

from sarj_rule_contracts import TextEdit, apply_edits

from sarj_iac_lint._hcl import (
    Block,
    ParsedDocument,
    balanced_structure,
    comment_locations,
    document,
    document_result,
    header_comment_lines,
    literal_string,
    physical_lines,
    ungrouped_expression,
)
from sarj_iac_lint.json_boundary import is_object_mapping, parse_json
from sarj_iac_lint.rule_base import (
    AutofixPolicy,
    DefaultLevel,
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    Rule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
)
from sarj_iac_lint.terraform import is_terraform, is_terraform_override, terraform_blocks


if TYPE_CHECKING:
    from collections.abc import Collection, Iterator
    from typing import Never


_TFVARS_SUFFIX = ".tfvars"
_TFVARS_JSON_SUFFIX = ".tfvars.json"
_AUTO_STEM_SUFFIX = ".auto"
_ENVS_MANIFEST = "envs.json"

_SKIP_DIR_NAMES = frozenset({".terraform", ".git", "node_modules", "__pycache__", ".venv", "venv"})
_FIXTURE_DIR_NAMES = frozenset({"fixture", "fixtures", "testdata"})

_MAX_ANCESTOR_HOPS = 3

_MIN_ENVIRONMENTS = 2

_MAX_VALUE_DISPLAY = 48
_MAX_NUMBER_STRING_DIGITS = 10_000
_MAX_FIX_NUMBER_EXPONENT = 308

_PRINTABLE_TAGS = frozenset({"bool", "num", "null"})

_NON_ENVIRONMENT_STEMS = frozenset(
    {
        "backup",
        "bak",
        "backend",
        "backend-config",
        "example",
        "sample",
        "template",
        "old",
        "copy",
        "tmp",
    }
)

_CONVENTIONAL_STEM = "terraform"


class _ScalarType(StrEnum):
    BOOL = "bool"
    NUMBER = "number"
    STRING = "string"


_AUTO_ENVIRONMENT = "(auto-loaded)"

_NUMBER_RE = re.compile(r"-?(?:\d+(?:\.\d+)?|\.\d+)(?:[eE][+-]?\d+)?")
_IDENT_RE = re.compile(r"[A-Za-z_][\w-]*")
_GENERATED_RE = re.compile(r"generated.{0,80}(?:do not edit|don't edit)", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class _Canon:
    tag: str
    value: bool | Decimal | str | tuple[_Canon, ...] | tuple[tuple[str, _Canon], ...] | None


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
        default_level=DefaultLevel.WARNING,
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
        autofix=AutofixPolicy.SAFE,
        limitations=(
            "Cross-environment comparisons require at least two discovered, readable HCL or JSON tfvars environments.",
            (
                "Only scalar variables declared exactly as bool, number, or string are compared; dynamic, collection, "
                "interpolated HCL, heredoc, and incomplete roots are conservatively skipped."
            ),
            "Unreadable, malformed, duplicate declarations and override files make project analysis incomplete. HCL and Terraform JSON declarations are supported.",
            "Unbalanced, missing-value, duplicate or parser-rejected inputs make selected project analysis incomplete; native Terraform remains the full language-validity owner. Standalone advisory analysis abstains for rejected files and comparisons across their root.",
            "Numeric-to-string comparisons abstain for non-finite values or exponents expanding beyond 10,000 decimal places; unsupported HCL string escapes are also skipped.",
            (
                "Named tfvars files are inferred as environments; repeated values are advisory because invocation "
                "order and intentional fail-closed contracts cannot be proven from filenames."
            ),
            (
                "Generated fixtures, testdata, backend configuration, backups, templates, and other specimen inputs "
                "are excluded."
            ),
            "Sensitive and non-primitive values are never printed in diagnostics.",
            "Code Standards safe fixes only remove tracked root-level auto-loaded HCL/JSON boolean, number and null assignments with no declaration in a complete selected root. String and collection values may contain secrets and are retained. Named varfiles, default-equal and repeated values, ignored/private files, generated sources, directives, source-reading functions and incomplete roots receive no deletion fix. Standalone file fixes lack this proof and leave assignments unchanged.",
            "Provider-defined functions, external data programs and provisioners have unknown filesystem/evaluation effects and prevent project fixes. Source-observation checks include Terraform 1.17 file-content hash functions such as filesha1.",
            "Terraform JSON comment properties are not assignments. Generated comment metadata is excluded; other comment metadata requires manual fixes because it can convey ownership or tool directives.",
            "HCL fixes require a single-line ASCII identifier and boolean/null or decimal/exponent literal with ASCII whitespace. Coercible strings, parenthesized expressions and unsupported numeric syntax are retained; a comparison canonicalizer cannot prove Terraform syntax or preserve parse failures.",
            "Numeric fixes additionally require a finite Decimal with absolute adjusted decimal exponent at most 308, a conservative Terraform 1.17-supported range. Larger and smaller magnitudes remain review-only, including valid values outside this proof boundary. Quoted numeric/boolean strings are always retained.",
            "Project fixes require all selected Terraform source to consist only of variables, locals, outputs and Terraform required_version declarations. Module calls, providers, resources, data, backends and unknown constructs can observe file contents outside the proven value flow and require manual remediation. Source-observation checks include unchanged files throughout the selected project.",
        ),
        examples=(
            RuleExample(
                example_id="stale-auto-loaded-assignment",
                title="Remove a tracked auto-loaded assignment Terraform cannot consume",
                outcome=ExampleOutcome.MATCH,
                scenario="auto-loaded-fix",
                files=(
                    ExampleFile.iac("variables.tf", 'variable "live" { type = bool }\n'),
                    ExampleFile.iac("terraform.tfvars", "live = false\nretired = true\n"),
                ),
                fixed_files=(ExampleFile.iac("terraform.tfvars", "live = false\n"),),
                focus_path=PurePosixPath("terraform.tfvars"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="declared-auto-loaded-assignment",
                title="Keep a declared startup input",
                outcome=ExampleOutcome.NO_MATCH,
                scenario="auto-loaded-fix",
                files=(
                    ExampleFile.iac("variables.tf", 'variable "live" { type = bool }\n'),
                    ExampleFile.iac("terraform.tfvars", "live = false\n"),
                ),
                focus_path=PurePosixPath("terraform.tfvars"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="json-orphaned-assignment",
                title="JSON variable files receive the same declaration checks",
                outcome=ExampleOutcome.MATCH,
                scenario="json-input",
                files=(
                    ExampleFile.iac("variables.tf", 'variable "region" {\n  type = string\n}\n'),
                    ExampleFile.iac("dev.tfvars.json", '{"region":"west","ghost":true}\n'),
                ),
                focus_path=PurePosixPath("dev.tfvars.json"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="json-input-varies",
                title="JSON scalar values retain environment differences",
                outcome=ExampleOutcome.NO_MATCH,
                scenario="json-input",
                files=(
                    ExampleFile.iac("variables.tf", 'variable "region" {\n  type = string\n}\n'),
                    ExampleFile.iac("dev.tfvars.json", '{"region":"west"}\n'),
                    ExampleFile.iac("prod.tfvars.json", '{"region":"east"}\n'),
                ),
                focus_path=PurePosixPath("dev.tfvars.json"),
                expected_count=0,
                public=True,
            ),
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
                title="Sensitive input repeated across environments",
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

    def __init__(self, *, sources: Mapping[Path, str] | None = None) -> None:
        self._files = _InputFiles(sources)
        self._analyses: dict[Path, _RootAnalysis] = {}

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        documentation = self.documentation
        level = DefaultLevel.WARNING if documentation is None else documentation.default_level
        if level is DefaultLevel.OFF:
            return []
        if not path.name.endswith((_TFVARS_SUFFIX, _TFVARS_JSON_SUFFIX)):
            return []
        if _excluded_input(path, source):
            return []
        root = _find_root(path, self._files)
        if root is None:
            if self._files.sources is not None:
                message = f"Cannot establish the Terraform root for {path} in the selected source tree"
                raise ValueError(message)
            return []
        if self._files.sources is None:
            analysis = _analyze_root(root, self._files)
        else:
            if root not in self._analyses:
                self._analyses[root] = _analyze_root(root, self._files)
            analysis = self._analyses[root]
            if not analysis.declarations_complete:
                message = f"Cannot establish complete Terraform variable declarations in {root}"
                raise ValueError(message)
        resolved = self._files.identity(path)
        environment = analysis.environment_of(resolved, self._files)
        if environment is None:
            return []
        assignments = _assignments(path, source)
        if assignments is None:
            if self._files.sources is not None:
                message = f"Cannot analyze malformed Terraform variable assignments in {path}"
                raise ValueError(message)
            return []
        diags = [
            Diagnostic(
                path=path,
                line=attr.line,
                col=attr.col,
                code=self.code,
                message=message,
                severity=level,
            )
            for attr in assignments
            if (message := _assignment_message(analysis, environment, attr)) is not None
        ]
        return sorted(diags, key=lambda d: (d.line, d.col))

    @classmethod
    def check_project(cls, root: Path, sources: Mapping[PurePosixPath, str]) -> list[Diagnostic]:
        files = {root / path: text for path, text in sources.items()}
        rule = cls(sources=files)
        return [
            diagnostic
            for path, source in files.items()
            if path.name.endswith((_TFVARS_SUFFIX, _TFVARS_JSON_SUFFIX))
            for diagnostic in rule.check(path, source)
            if not diagnostic.suppressible or not _suppressed(path, source, diagnostic)
        ]


def _suppressed(path: Path, source: str, diagnostic: Diagnostic) -> bool:
    from sarj_iac_lint._hcl import suppression_comment_lines  # ruff: ignore[import-outside-top-level] -- only project-wide findings need the native suppression contract.
    from sarj_iac_lint.rule_base import is_suppressed  # ruff: ignore[import-outside-top-level] -- retain the same reviewed exception behavior as file-local checks.

    comments: Mapping[int, str] = {} if path.name.endswith(_TFVARS_JSON_SUFFIX) else suppression_comment_lines(source)
    return is_suppressed(source.splitlines(), diagnostic.line, diagnostic.code, comments=comments)


class _InputFiles:
    def __init__(self, sources: Mapping[Path, str] | None = None) -> None:
        self.sources = None if sources is None else {path.absolute(): text for path, text in sources.items()}

    def read(self, path: Path) -> str | None:
        return _read_text(path) if self.sources is None else self.sources.get(path.absolute())

    def identity(self, path: Path) -> Path:
        return path.resolve() if self.sources is None else path.absolute()

    def glob(self, directory: Path, pattern: str) -> list[Path]:
        if self.sources is None:
            return sorted(directory.glob(pattern))
        directory = directory.absolute()
        return sorted(
            path
            for path in self.sources
            if path.is_relative_to(directory) and path.relative_to(directory).full_match(pattern)
        )

    def directories(self, directory: Path) -> list[Path]:
        if self.sources is None:
            return sorted(path for path in directory.iterdir() if path.is_dir())
        directory = directory.absolute()
        return sorted(
            {
                directory / path.relative_to(directory).parts[0]
                for path in self.sources
                if path.is_relative_to(directory) and len(path.relative_to(directory).parts) > 1
            }
        )


@dataclass(frozen=True, slots=True)
class _Declaration:
    has_default: bool
    default: _Canon | None
    scalar_type: _ScalarType | None
    sensitive: bool


@dataclass(frozen=True, slots=True)
class _VariableContract:
    name: str
    default: str | None
    scalar_type: _ScalarType | None
    sensitive: bool


@dataclass(frozen=True, slots=True)
class _InputAssignment:
    name: str
    text: str
    line: int
    col: int
    is_json: bool = False
    native: object = None  # sarj-noqa: SARJ528 -- Preserve uncoerced Decimal-aware JSONDecoder values, including nested raw payloads.


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

    def environment_of(self, resolved: Path, inputs: _InputFiles) -> str | None:
        return next(
            (env for env, paths in self.files.items() if any(resolved == inputs.identity(p) for p in paths)), None
        )


def _assignment_message(analysis: _RootAnalysis, environment: str, assignment: _InputAssignment) -> str | None:
    if not analysis.declarations_complete:
        return None
    name, value = assignment.name, assignment.text
    declaration = analysis.declarations.get(name)
    if declaration is None:
        return (
            f"orphaned-key: `{name}` has no declaration in the parsed root `{analysis.root.name}`; "
            "remove it if this is a variable file, or restore the missing declaration."
        )
    if declaration.scalar_type is None:
        return None
    canon = _assignment_canon(assignment, declaration.scalar_type)
    display = _display(canon, value, sensitive=declaration.sensitive)
    if (
        canon is not None
        and declaration.default is not None
        and canon == declaration.default
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
            f"({environments}); matching values alone do not establish a shared secret source. "
            "Review delivery ownership while preserving requiredness, access and rotation contracts; "
            "do not hard-code a default."
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
    if (
        sensitive
        or canon is None
        or canon.tag not in _PRINTABLE_TAGS
        or ungrouped_expression(text).lstrip().startswith(('"', "'"))
    ):
        return ""
    return f" ({text})" if len(text) <= _MAX_VALUE_DISPLAY else ""


def _excluded_input(path: Path, source: str) -> bool:
    return any(part.lower() in _FIXTURE_DIR_NAMES for part in path.parts) or _generated_header(source)


def _generated_header(source: str) -> bool:
    header = "\n".join(
        line for line in header_comment_lines(source) if line.lstrip().startswith(("#", "//", "/*", "*"))
    )
    if source.lstrip().startswith("{"):
        try:
            value = parse_json(source)
        except ValueError, RecursionError, ArithmeticError:
            return False
        if is_object_mapping(value) and isinstance(comment := value.get("//"), str):
            header += "\n" + comment
    return _GENERATED_RE.search(header) is not None


def _find_root(path: Path, files: _InputFiles) -> Path | None:
    absolute = path if path.is_absolute() else Path.cwd() / path
    if any(part in _SKIP_DIR_NAMES for part in absolute.parts):
        return None
    directory = absolute.parent
    for _ in range(_MAX_ANCESTOR_HOPS):
        if _has_tf_files(directory, files):
            return directory
        if directory.parent == directory:
            return None
        directory = directory.parent
    return None


def _has_tf_files(directory: Path, files: _InputFiles) -> bool:
    return bool(files.glob(directory, "*.tf") or files.glob(directory, "*.tf.json"))


def _variable_blocks(directory: Path, files: _InputFiles) -> Iterator[_VariableContract]:
    for tf in sorted((*files.glob(directory, "*.tf"), *files.glob(directory, "*.tf.json"))):
        text = files.read(tf)
        if text is None:
            continue
        try:
            blocks = terraform_blocks(tf, text)
        except ValueError:
            continue
        for block in blocks:
            if block.type == "variable" and block.labels:
                yield _variable_contract(block)


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except OSError, UnicodeError:
        return None


def _is_override(path: Path) -> bool:
    return path.name == "override.tf" or path.name.endswith("_override.tf")


def _assignments(path: Path, source: str) -> tuple[_InputAssignment, ...] | None:
    if path.name.endswith(_TFVARS_JSON_SUFFIX):
        return _json_assignments(source)
    parsed = document_result(source)
    if not isinstance(parsed, ParsedDocument) or not balanced_structure(source):
        return None
    attributes = parsed.root.attributes
    if (
        parsed.root.blocks
        or len({attr.name for attr in attributes}) != len(attributes)
        or any(not attr.value.strip() for attr in attributes)
    ):
        return None
    return tuple(_InputAssignment(attr.name, attr.value, attr.line, attr.col) for attr in attributes)


def _unique_json_object[T](pairs: list[tuple[str, T]]) -> dict[str, T]:
    result: dict[str, T] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


def _reject_json_constant(_value: str) -> Never:
    raise ValueError


_JSON_DECODER = json.JSONDecoder(
    parse_int=Decimal,
    parse_float=Decimal,
    parse_constant=_reject_json_constant,
    object_pairs_hook=_unique_json_object,
)


def _json_assignments(source: str) -> tuple[_InputAssignment, ...] | None:
    try:
        return _validated_json_assignments(source)
    except ValueError, RecursionError, ArithmeticError:
        return None


def _validated_json_assignments(source: str) -> tuple[_InputAssignment, ...] | None:
    start = _skip_json_ws(source, 0)
    decoded: tuple[object, int] = _JSON_DECODER.raw_decode(source, start)
    value, end = decoded
    if not is_object_mapping(value) or _skip_json_ws(source, end) != len(source):
        return None
    cursor = _skip_json_ws(source, start + 1)
    assignments: list[_InputAssignment] = []
    while cursor < end - 1:
        key_start = cursor
        decoded_key: tuple[object, int] = _JSON_DECODER.raw_decode(source, cursor)
        name, cursor = decoded_key
        if not isinstance(name, str):
            return None
        cursor = _skip_json_ws(source, cursor) + 1
        value_start = _skip_json_ws(source, cursor)
        decoded_value: tuple[object, int] = _JSON_DECODER.raw_decode(source, value_start)
        native, cursor = decoded_value
        if name != "//":
            assignments.append(
                _InputAssignment(
                    name,
                    source[value_start:cursor],
                    source.count("\n", 0, key_start) + 1,
                    key_start - source.rfind("\n", 0, key_start),
                    is_json=True,
                    native=native,
                )
            )
        cursor = _skip_json_ws(source, cursor)
        if source[cursor] == ",":
            cursor = _skip_json_ws(source, cursor + 1)
    return tuple(assignments)


def _skip_json_ws(source: str, index: int) -> int:
    while index < len(source) and source[index] in " \t\r\n":
        index += 1
    return index


def _assignment_canon(assignment: _InputAssignment, scalar_type: _ScalarType) -> _Canon | None:
    if not assignment.is_json:
        return _canonical_for_type(assignment.text, scalar_type)
    value = assignment.native
    if isinstance(value, str):
        if scalar_type is _ScalarType.STRING:
            return _Canon("str", value)
        canon = _string_scalar(value)
    elif isinstance(value, bool):
        canon = _Canon("bool", value)
    elif isinstance(value, Decimal):
        canon = _Canon("num", value)
    else:
        return None
    if scalar_type is _ScalarType.BOOL:
        return canon if canon.tag == "bool" else None
    if scalar_type is _ScalarType.NUMBER:
        return canon if canon.tag == "num" else None
    if canon.tag == "bool":
        return _Canon("str", "true" if canon.value is True else "false")
    if isinstance(canon.value, Decimal):
        return _number_string(canon.value)
    return None


def _number_string(value: Decimal) -> _Canon | None:
    if not value.is_finite() or abs(value.adjusted()) > _MAX_NUMBER_STRING_DIGITS:
        return None
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return _Canon("str", "0" if value == 0 else text)


def _analyze_root(root: Path, inputs: _InputFiles) -> _RootAnalysis:
    files = _environment_files(root, inputs)
    contracts = tuple(_variable_blocks(root, inputs))
    declarations = {
        contract.name: _Declaration(
            contract.default is not None,
            None
            if contract.default is None or contract.scalar_type is None
            else _canonical_for_type(contract.default, contract.scalar_type),
            contract.scalar_type,
            contract.sensitive,
        )
        for contract in contracts
    }
    values: dict[str, dict[str, _AssignmentValue]] = {}
    blind = list(_structural_blind(root, files, inputs))
    conflicted: set[str] = set()
    blind.extend(_auto_loaded_blind(files))
    for env, paths in files.items():
        for file in paths:
            _collect_environment_values(
                env, paths, file, declarations, values, inputs=inputs, blind=blind, conflicted=conflicted
            )
    blind.extend(_manifest_blind(root, frozenset(files), inputs))
    return _RootAnalysis(
        root=root,
        files={env: tuple(paths) for env, paths in files.items()},
        declarations=declarations,
        values=values,
        blind=tuple(sorted(blind, key=lambda item: (item.name, item.reason))),
        declarations_complete=len(contracts) == len(declarations) and _complete_declarations(root, inputs),
    )


def _complete_declarations(root: Path, inputs: _InputFiles) -> bool:
    for path in (*inputs.glob(root, "*.tf"), *inputs.glob(root, "*.tf.json")):
        text = inputs.read(path)
        if text is None or is_terraform_override(path):
            return False
        try:
            blocks = terraform_blocks(path, text)
        except ValueError:
            return False
        if any(block.type == "variable" and len(block.labels) != 1 for block in blocks):
            return False
    return True


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


def _environment_files(root: Path, inputs: _InputFiles) -> dict[str, list[Path]]:
    out: dict[str, list[Path]] = {}
    seen: set[Path] = set()
    for file, environment in _candidate_environments(root, inputs):
        if _is_non_environment(environment) or _excluded_input(file, inputs.read(file) or ""):
            continue
        resolved = inputs.identity(file)
        if resolved in seen:
            continue
        seen.add(resolved)
        out.setdefault(environment, []).append(file)
    return out


def _candidate_environments(root: Path, inputs: _InputFiles) -> Iterator[tuple[Path, str]]:
    for suffix in (_TFVARS_SUFFIX, _TFVARS_JSON_SUFFIX):
        for file in inputs.glob(root, f"*{suffix}"):
            yield file, _AUTO_ENVIRONMENT if _is_auto_loaded(file.name) else _stem_environment(file.name)
        for file, env_dir in _nested_tfvars(root, suffix, inputs):
            stem = _stem_environment(file.name)
            yield file, env_dir.name if stem == _CONVENTIONAL_STEM else stem


def _is_auto_loaded(name: str) -> bool:
    stem = name.removesuffix(_TFVARS_JSON_SUFFIX).removesuffix(_TFVARS_SUFFIX)
    return stem == _CONVENTIONAL_STEM or stem.endswith(_AUTO_STEM_SUFFIX)


def _is_non_environment(label: str) -> bool:
    lowered = label.lower()
    return lowered in _NON_ENVIRONMENT_STEMS or lowered.rsplit(".", 1)[-1] in _NON_ENVIRONMENT_STEMS


def _nested_tfvars(root: Path, suffix: str, inputs: _InputFiles) -> Iterator[tuple[Path, Path]]:
    for pattern in (f"*/*{suffix}", f"*/*/*{suffix}"):
        for file in inputs.glob(root, pattern):
            relative_dirs = file.relative_to(root).parts[:-1]
            if any(part in _SKIP_DIR_NAMES or part.lower() in _FIXTURE_DIR_NAMES for part in relative_dirs):
                continue
            if any(
                _has_tf_files(root.joinpath(*relative_dirs[: index + 1]), inputs) for index in range(len(relative_dirs))
            ):
                continue
            yield file, file.parent


def _stem_environment(name: str) -> str:
    stem = name.removesuffix(_TFVARS_JSON_SUFFIX).removesuffix(_TFVARS_SUFFIX)
    return stem.removesuffix(_AUTO_STEM_SUFFIX)


def _structural_blind(root: Path, files: dict[str, list[Path]], inputs: _InputFiles) -> Iterator[_BlindEnvironment]:
    containers = _environment_containers(root, files)
    for container in sorted(containers, key=str):
        for sibling in inputs.directories(container):
            if sibling.name in _SKIP_DIR_NAMES or sibling.name.lower() in _FIXTURE_DIR_NAMES or sibling.name in files:
                continue
            if _only_excluded_inputs(sibling, inputs):
                continue
            yield _BlindEnvironment(
                sibling.name,
                f"environment directory `{sibling.relative_to(root)}` has no tfvars file while sibling environments have one",
            )


def _only_excluded_inputs(directory: Path, files: _InputFiles) -> bool:
    try:
        inputs = tuple(path for path in (*files.glob(directory, "*.tfvars"), *files.glob(directory, "*.tfvars.json")))
    except OSError:
        return False
    return bool(inputs) and all(_excluded_input(path, files.read(path) or "") for path in inputs)


def _manifest_blind(root: Path, environments: frozenset[str], inputs: _InputFiles) -> Iterator[_BlindEnvironment]:
    manifest = root / _ENVS_MANIFEST
    if not inputs.glob(root, _ENVS_MANIFEST):
        return
    text = inputs.read(manifest)
    if text is None:
        yield _BlindEnvironment("(all)", f"`{_ENVS_MANIFEST}` names this root's environments but cannot be read")
        return
    try:
        raw = parse_json(text)
    except json.JSONDecodeError as exc:
        yield _BlindEnvironment(
            "(all)", f"`{_ENVS_MANIFEST}` names this root's environments but cannot be parsed: {exc}"
        )
        return
    if not is_object_mapping(raw):
        yield _BlindEnvironment("(all)", f"`{_ENVS_MANIFEST}` names this root's environments but is not a JSON object")
        return
    for name, entry in raw.items():
        if not isinstance(name, str) or name in environments:
            continue
        secret = _tfvars_secret(entry)
        held = f" with tfvars held in secret `{secret}`" if secret is not None else ""
        yield _BlindEnvironment(
            name, f"`{_ENVS_MANIFEST}` declares environment `{name}`{held} but no tfvars file for it is on disk"
        )


def _tfvars_secret(entry: object) -> str | None:
    if not is_object_mapping(entry):
        return None
    for key, value in entry.items():
        if isinstance(key, str) and "tfvars" in key and isinstance(value, str):
            return value
    return None


def _canonical_for_type(text: str, scalar_type: _ScalarType) -> _Canon | None:
    text = ungrouped_expression(text)
    canon = _canonical(text)
    if canon is None:
        return None
    if scalar_type is _ScalarType.BOOL:
        return canon if canon.tag == "bool" else None
    if scalar_type is _ScalarType.NUMBER:
        return canon if canon.tag == "num" else None

    stripped = text.strip()
    if stripped.startswith('"'):
        literal = literal_string(stripped)
        return None if literal is None else _Canon("str", literal)
    if canon.tag == "bool":
        return _Canon("str", "true" if canon.value is True else "false")
    if canon.tag == "num" and isinstance(canon.value, Decimal):
        return _number_string(canon.value)
    return canon if canon.tag == "str" else None


def _canonical(text: str) -> _Canon | None:
    if "${" in text or "%{" in text or "<<" in text:
        return None
    text = ungrouped_expression(text)
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
        return _ValueParseResult(_numeric_scalar(number.group(0)), number.end())
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
            literal = literal_string(text[index : cursor + 1])
            return _ValueParseResult(None if literal is None else _string_scalar(literal), cursor + 1)
        cursor += 1
    return _ValueParseResult(None, index)


def _string_scalar(inner: str) -> _Canon:
    if (bool_scalar := _BOOL_SCALARS.get(inner)) is not None:
        return bool_scalar
    if _NUMBER_RE.fullmatch(inner) is not None:
        return _numeric_scalar(inner) or _Canon("str", inner)
    return _Canon("str", inner)


def _numeric_scalar(text: str) -> _Canon | None:
    try:
        return _Canon("num", Decimal(text))
    except ArithmeticError:
        return None


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


def _variable_contract(block: Block) -> _VariableContract:
    default = block.attribute("default")
    declared = block.attribute("type")
    declared_type = None if declared is None else declared.value.strip()
    try:
        scalar_type = None if declared_type is None else _ScalarType(declared_type)
    except ValueError:
        scalar_type = None
    sensitive_attr = block.attribute("sensitive")
    sensitive = sensitive_attr is not None and _canonical(sensitive_attr.value) != _BOOL_SCALARS["false"]
    return _VariableContract(
        name=block.labels[0],
        default=None if default is None else default.value,
        scalar_type=scalar_type,
        sensitive=sensitive,
    )


def _collect_environment_values(
    env: str,
    paths: list[Path],
    file: Path,
    declarations: dict[str, _Declaration],
    values: dict[str, dict[str, _AssignmentValue]],
    *,
    inputs: _InputFiles,
    blind: list[_BlindEnvironment],
    conflicted: set[str],
) -> None:
    text = inputs.read(file)
    if text is None:
        blind.append(_BlindEnvironment(env, f"`{file.name}` for environment `{env}` cannot be read"))
        return
    assignments = _assignments(file, text)
    if assignments is None:
        blind.append(_BlindEnvironment(env, f"`{file.name}` for environment `{env}` is not unambiguous JSON input"))
        return
    for attr in assignments:
        declaration = declarations.get(attr.name)
        assignment = _AssignmentValue(
            attr.text,
            None
            if declaration is None or declaration.scalar_type is None
            else _assignment_canon(attr, declaration.scalar_type),
            file,
        )
        previous = values.setdefault(attr.name, {}).get(env)
        if previous is not None and env not in conflicted:
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


def _conflict_reason(environment: str, name: str, paths: Sequence[Path]) -> str:
    named = ", ".join(f"`{path.name}`" for path in paths)
    return (
        f"environment `{environment}` is defined by more than one file ({named}) and they assign "
        f"`{name}` different values, so its effective inputs depend on var-file order"
    )


def _redefinition_reason(environment: str, name: str, file: Path) -> str:
    return (
        f"`{file.name}` assigns `{name}` twice, which Terraform rejects as a redefined attribute, "
        f"so environment `{environment}` has no inputs this rule can read"
    )


def _environment_containers(root: Path, files: dict[str, list[Path]]) -> set[Path]:
    return {
        path.parent.parent
        for paths in files.values()
        for path in paths
        if root not in {path.parent.parent, path.parent}
    }


def remove_stale_assignments(sources: Mapping[Path, str], *, selected: Collection[Path]) -> dict[Path, str]:
    files = _InputFiles(sources)
    changes: dict[Path, str] = {}
    for path in sorted(set(selected) & sources.keys()):
        fixed = _fixed_source(path, sources, files)
        if fixed != sources[path]:
            changes[path] = fixed
    return changes


def _fixed_source(path: Path, sources: Mapping[Path, str], files: _InputFiles) -> str:
    from sarj_iac_lint.declaration_fixes import observes_source  # ruff: ignore[import-outside-top-level] -- reuse project source-observation safeguards only during explicit fixing.

    source = sources[path]
    if (
        not path.name.endswith((".tfvars", ".tfvars.json"))
        or not _is_auto_loaded(path.name)
        or _excluded_input(path, source)
        or _find_root(path, files) != path.parent
    ):
        return source
    analysis = _analyze_root(path.parent, files)
    if not analysis.declarations_complete:
        return source
    parsed = {member: terraform_blocks(member, text) for member, text in sources.items() if is_terraform(member)}
    if not _pure_input_project(parsed) or observes_source(parsed):
        return source
    assignments = _assignments(path, source)
    if assignments is None:
        return source
    findings = NoDeadEnvironmentInput(sources=sources).check(path, source)
    lines = {finding.line for finding in findings if not _suppressed(path, source, finding)}
    names = _stale_names(assignments, analysis, lines)
    edits = _json_edits(source, names) if path.name.endswith(".json") else _hcl_edits(source, names)
    fixed = apply_edits(source, edits)
    _verify_retained_assignments(path, assignments, fixed, names)
    return fixed


def _pure_input_project(parsed: Mapping[Path, tuple[Block, ...]]) -> bool:
    return all(
        block.type in {"variable", "locals", "output"}
        or (
            block.type == "terraform"
            and not block.blocks
            and all(attribute.name == "required_version" for attribute in block.attributes)
        )
        for blocks in parsed.values()
        for block in blocks
    )


def _stale_names(
    assignments: Collection[_InputAssignment], analysis: _RootAnalysis, lines: Collection[int]
) -> set[str]:
    return {
        assignment.name
        for assignment in assignments
        if assignment.line in lines
        and assignment.name not in analysis.declarations
        and _fixable_scalar(assignment.text)
    }


def _fixable_scalar(text: str) -> bool:
    text = ungrouped_expression(text).strip()
    if text.startswith('"') or (canon := _canonical(text)) is None:
        return False
    if canon.tag in {"bool", "null"}:
        return True
    return (
        canon.tag == "num"
        and isinstance(canon.value, Decimal)
        and canon.value.is_finite()
        and abs(canon.value.adjusted()) <= _MAX_FIX_NUMBER_EXPONENT
    )


def _verify_retained_assignments(
    path: Path, assignments: Collection[_InputAssignment], fixed: str, names: Collection[str]
) -> None:
    remaining = _assignments(path, fixed)
    if remaining is None:
        message = "Stale input fix produced invalid assignments; no files changed"
        raise ValueError(message)
    before = {assignment.name: assignment.text for assignment in assignments}
    after = {assignment.name: assignment.text for assignment in remaining}
    removed = before.keys() - after.keys()
    if not removed.issubset(names) or after != {name: value for name, value in before.items() if name not in removed}:
        message = "Stale input fix changed a retained assignment; no files changed"
        raise ValueError(message)


def _hcl_edits(source: str, names: Collection[str]) -> list[TextEdit]:
    lines = physical_lines(source, keepends=True)
    comments = {line for line, _column in comment_locations(source)}
    edits: list[TextEdit] = []
    for attribute in document(source).attributes:
        if attribute.name not in names or attribute.line in comments:
            continue
        first = lines[attribute.line - 1]
        match = re.fullmatch(
            r"[ \t]*([A-Za-z_][A-Za-z0-9_-]*)[ \t]*=[ \t]*"
            r"(true|false|null|-?[0-9]+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?)[ \t]*(?:\r?\n)?",
            first,
        )
        if match is None or match[1] != attribute.name or _canonical(match[2]) != _canonical(attribute.value):
            continue
        start = sum(len(line) for line in lines[: attribute.line - 1])
        end = start + len(first)
        edits.append(TextEdit(start, end, ""))
    return edits


def _json_edits(source: str, names: Collection[str]) -> list[TextEdit]:
    members: list[tuple[str, int, int]] = []
    cursor = _skip_json_ws(source, _skip_json_ws(source, 0) + 1)
    while source[cursor] != "}":
        start = cursor
        decoded_key: tuple[object, int] = _JSON_DECODER.raw_decode(source, cursor)
        name, cursor = decoded_key
        cursor = _skip_json_ws(source, cursor) + 1
        decoded_value: tuple[object, int] = _JSON_DECODER.raw_decode(source, _skip_json_ws(source, cursor))
        cursor = decoded_value[1]
        if not isinstance(name, str) or name == "//":
            return []
        members.append((name, start, cursor))
        cursor = _skip_json_ws(source, cursor)
        if source[cursor] == ",":
            cursor = _skip_json_ws(source, cursor + 1)
    edits: list[TextEdit] = []
    index = 0
    while index < len(members):
        if members[index][0] not in names:
            index += 1
            continue
        first = index
        while index < len(members) and members[index][0] in names:
            index += 1
        start = members[first][1]
        end = members[index][1] if index < len(members) else members[index - 1][2]
        if index == len(members) and first:
            start = source.index(",", members[first - 1][2], start)
        edits.append(TextEdit(start, end, ""))
    return edits
