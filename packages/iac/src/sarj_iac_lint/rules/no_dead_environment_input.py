"""SARJ205: per-environment tfvars inputs must earn their indirection — constant, default-equal, and orphaned assignments are dead configuration."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache
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
_NON_ENVIRONMENT_STEMS = frozenset({"backup", "bak", "example", "sample", "template", "old", "copy", "tmp"})

# Terraform's own filename: it names no environment, so it takes the name of the
# directory that holds it.
_CONVENTIONAL_STEM = "terraform"

# `type = any` opts out of Terraform's conversions, so this rule's comparison
# does not hold for such a variable and it is left alone.
_ANY_TYPE = "any"

# Every auto-loaded root var-file belongs to one plan, so they share one label
# rather than each inventing an environment named after its file.
_AUTO_ENVIRONMENT = "(auto-loaded)"

_NUMBER_RE = re.compile(r"-?(?:\d+(?:\.\d+)?|\.\d+)(?:[eE][+-]?\d+)?")
_IDENT_RE = re.compile(r"[A-Za-z_][\w-]*")


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
    """Dead per-environment tfvars inputs: constant everywhere, equal to the declared default, or orphaned by a deleted variable."""

    id = "no-dead-environment-input"
    code = "SARJ205"
    documentation = RuleDocumentation(
        summary=(
            "A per-environment tfvars input must vary or exist: constant-everywhere, default-equal, and "
            "undeclared assignments are dead configuration."
        ),
        rationale=(
            "An input assigned one semantic value in every environment, or its declared default, or a variable "
            "that no longer exists, is indirection with no decision behind it — reviewers keep re-reading it."
        ),
        remediation=(
            "Inline the constant as the variable's default and delete the per-environment assignments; delete "
            "assignments equal to the default; delete assignments for variables the root no longer declares."
        ),
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            (
                "A variable declared but never assigned in any tfvars is NOT flagged: in the measured corpus 52 "
                "of 67 such variables were module plumbing wired from parent calls, not dead flags."
            ),
            (
                "Scope is root modules only — a root is a directory whose own .tf files declare at least one "
                "variable, with tfvars beside it or under an env/<name>/ layout. Shared modules without tfvars, "
                "and tfvars with no such root within two directory levels, produce nothing."
            ),
            (
                "When the root's own configuration names an environment whose inputs are not readable on disk — "
                "an envs.json entry with tfvars held in a secret, an env directory without a tfvars file while "
                "siblings have one, or a JSON-only tfvars — the rule reports a blind-environment error and "
                "suppresses constant-everywhere and required-but-constant for that root instead of computing "
                "them from the visible subset. Default-equal and orphaned findings remain valid per file."
            ),
            (
                "The blind-environment error is attributed once, to the root's first tfvars file in path order, "
                "so a changed-files run that omits that file shows no root-level error; the full-tree scan is "
                "the gate that always sees it."
            ),
            (
                'Values compare semantically: "false" equals false and "1" equals 1 (HCL\'s string '
                "conversions), 1 equals 1.0 (HCL has one number type), lists and objects compare structurally; "
                "bool never equals number. Heredocs and interpolations are opaque (bodies are masked) and never "
                "compare equal, so a constant heredoc goes undetected rather than misread."
            ),
            (
                "Cross-environment findings need at least two on-disk environment tfvars; a single-environment "
                "root gets only default-equal and orphaned-key findings."
            ),
            (
                "A default-equal assignment is NOT flagged when a sibling environment gives the variable a "
                "different value: the line is the parallel entry for a knob in use, and deleting it hides the "
                "knob. A blind root reports no value-based finding at all, since the environment it cannot read "
                "is exactly the one whose override would keep the line."
            ),
            (
                "A variable declared `type = any` is left alone: Terraform performs none of the string "
                'conversions this rule\'s comparison relies on, so `"false"` beside `false` is two values there.'
            ),
            (
                "An environment is named by the tfvars file's own stem, except for terraform.tfvars, which takes "
                "the name of its directory — so env/<name>/terraform.tfvars and env/<name>.tfvars both resolve. "
                "Files are keyed by resolved path, so a symlinked alias is not a second environment."
            ),
            (
                "Root-level terraform.tfvars and *.auto.tfvars are auto-loaded into every plan, so they are one "
                "environment between them, never one each. Beside named environment files they are a baseline "
                "whose precedence this rule does not model, and the root reports blind-environment."
            ),
            (
                "A key assigned twice in one file is a redefinition Terraform refuses to load, so that "
                "environment is reported blind rather than judged on whichever assignment came last."
            ),
            (
                "The blind-environment error is suppressed by a `# sarj-noqa: SARJ205` on line 1 of the file it "
                "is reported on; scope such a suppression to the code it means to silence."
            ),
            (
                "When two files define one environment (a root-level <env>.tfvars beside an env/<env>/ file) and "
                "they assign a variable different values, the effective input depends on var-file order, which is "
                "not observable here: the rule reports a blind-environment error rather than picking one."
            ),
            (
                "Only boolean, number and null values are printed in a diagnostic. A tfvars string, list or map "
                "is routinely a password or token, and lint output reaches CI logs and PR annotations that the "
                "(often gitignored) tfvars file never reaches, so those values are named and never echoed."
            ),
            (
                "A tfvars file or env directory labelled backup, bak, old, copy, tmp, example, sample or "
                "template is a copy or specimen, not a deployment: it is neither linted nor counted as an "
                "environment, because comparing a file against its own backup makes every shared line constant."
            ),
            (
                "*.tfvars.json and *.tf.json are not parsed. A JSON tfvars makes its environment blind rather "
                "than silently half-read."
            ),
        ),
        examples=(
            RuleExample(
                example_id="flag-constant-in-every-environment",
                title="Boolean assigned the same semantic value in every environment",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.iac(
                        "variables.tf",
                        'variable "pagerduty_enabled" {\n  type    = string\n  default = "true"\n}\n',
                    ),
                    ExampleFile.iac("env/dev/terraform.tfvars", "pagerduty_enabled = false\n"),
                    ExampleFile.iac("env/prod/terraform.tfvars", 'pagerduty_enabled = "false"\n'),
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
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        """Analyze the tfvars file's whole root once, then report this file's share."""
        # A JSON tfvars is never parsed, but it still has to reach the analysis:
        # a root whose only inputs are JSON would otherwise be silently skipped
        # instead of reporting that it cannot be read.
        if not path.name.endswith((_TFVARS_SUFFIX, _TFVARS_JSON_SUFFIX)):
            return []
        root = _find_root(path)
        if root is None:
            return []
        analysis = _analyze_root(root)
        resolved = path.resolve()
        if path.name.endswith(_TFVARS_JSON_SUFFIX):
            # An unparsed file has no assignments to judge, so it carries only
            # the report that this environment could not be read. Reporting it
            # here rather than on the anchor is what makes a JSON-only root —
            # which contributes no anchor at all — visible.
            return [
                Diagnostic(path=path, line=1, col=1, code=self.code, message=_blind_message(analysis, blind))
                for blind in analysis.blind
                if path.name in blind.reason
            ]
        environment = analysis.environment_of(resolved)
        if environment is None:
            return []
        diags = [
            Diagnostic(path=path, line=attr.line, col=attr.col, code=self.code, message=message)
            for attr in document(source).attributes
            if (message := _assignment_message(analysis, environment, attr.name, attr.value)) is not None
        ]
        if analysis.blind and resolved == analysis.anchor:
            diags.extend(
                Diagnostic(path=path, line=1, col=1, code=self.code, message=_blind_message(analysis, blind))
                for blind in analysis.blind
            )
        return sorted(diags, key=lambda d: (d.line, d.col))


@dataclass(frozen=True, slots=True)
class _Declaration:
    """One root-level `variable` block, reduced to what dead-input analysis needs."""

    has_default: bool
    default: _Canon | None
    untyped: bool


@dataclass(frozen=True, slots=True)
class _AssignmentValue:
    """One tfvars assignment's raw text, comparable form, and defining file."""

    text: str
    canon: _Canon | None
    file: Path


@dataclass(frozen=True, slots=True)
class _BlindEnvironment:
    """An environment the root names whose inputs the scan cannot read."""

    name: str
    reason: str


@dataclass(frozen=True, slots=True)
class _RootAnalysis:
    """One shared cross-tfvars analysis of a root module."""

    root: Path
    files: Mapping[str, tuple[Path, ...]]
    declarations: Mapping[str, _Declaration]
    values: Mapping[str, Mapping[str, _AssignmentValue]]
    blind: tuple[_BlindEnvironment, ...]
    anchor: Path | None

    def environment_of(self, resolved: Path) -> str | None:
        """Name the environment a tfvars file feeds, or None when it is not a root input.

        Matching is on resolved paths because `files` holds the paths as the
        layout presents them — a symlinked input would otherwise never match
        itself, and the file would go unlinted with no error to say so.
        """
        return next((env for env, paths in self.files.items() if any(resolved == p.resolve() for p in paths)), None)


def _assignment_message(analysis: _RootAnalysis, environment: str, name: str, value: str) -> str | None:
    """Classify one assignment against the root, returning its diagnostic message."""
    declaration = analysis.declarations.get(name)
    if declaration is None:
        return (
            f"orphaned-key: `{name}` is not declared as a variable of root `{analysis.root.name}` — "
            "deletion residue; remove the assignment."
        )
    if declaration.untyped:
        return None
    canon = _canonical(value)
    display = _display(canon, value)
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
            "the assignment changes nothing; delete it."
        )
    if not _constant_everywhere(analysis, environment, name, canon):
        return None
    environments = ", ".join(sorted(analysis.files))
    if declaration.has_default:
        return (
            f"constant-everywhere: `{name}` carries one value{display} across every environment "
            f"({environments}) — dead per-environment indirection; make it the variable's default "
            "and delete the assignments."
        )
    return (
        f"required-but-constant: `{name}` has no default yet every environment ({environments}) assigns "
        f"one value{display} — declare that value as the variable's default instead of repeating it."
    )


def _varies_elsewhere(analysis: _RootAnalysis, name: str) -> bool:
    """Report whether another environment gives `name` a different value.

    An assignment equal to the default is a no-op in its own environment, but
    when a sibling environment sets the variable to something else the line is
    the parallel entry for a knob that is genuinely in use: deleting it hides
    the knob and stops the environment files reading side by side. The measured
    corpus put a quarter of default-equal assignments in this shape, including
    the `deletion_protection` / `backup_enabled` family, where the explicit
    false IS the audit surface.
    """
    canons = {value.canon for value in analysis.values.get(name, {}).values()}
    # An opaque sibling (heredoc or interpolation) counts as variation, not as
    # agreement: `None` joins the set on its own. Advising deletion of a line a
    # sibling may override is the costly direction to be wrong in.
    return len(canons) > 1


def _constant_everywhere(analysis: _RootAnalysis, environment: str, name: str, canon: _Canon | None) -> bool:
    """Report whether `name` carries one semantic value across every enumerated environment."""
    if analysis.blind or canon is None or len(analysis.files) < _MIN_ENVIRONMENTS:
        return False
    per_env = analysis.values.get(name, {})
    if set(per_env) != set(analysis.files):
        return False
    return all(
        env == environment or (other.canon is not None and other.canon == canon) for env, other in per_env.items()
    )


def _blind_message(analysis: _RootAnalysis, blind: _BlindEnvironment) -> str:
    """Say which environment the scan cannot see and what that suppresses."""
    return (
        f"blind-environment: {blind.reason}; cross-environment analysis (constant-everywhere, "
        f"required-but-constant) is suppressed for root `{analysis.root.name}` because the scan cannot "
        "enumerate every environment's inputs."
    )


def _display(canon: _Canon | None, value: str) -> str:
    """Render a value only when it cannot be a secret, else name nothing.

    A tfvars file holds passwords, API keys and tokens, and a diagnostic travels
    further than the file does — into CI logs, PR annotations and shared
    terminals — so only the tags that cannot carry a secret are ever printed.
    The variable name and the environments already make every finding
    actionable; the value is convenience, and convenience does not justify
    echoing `database_password` into a build log.
    """
    text = " ".join(value.split())
    if canon is None or canon.tag not in _PRINTABLE_TAGS or text.startswith(('"', "'")):
        return ""
    return f" ({text})" if len(text) <= _MAX_VALUE_DISPLAY else ""


def _find_root(path: Path) -> Path | None:
    """Resolve the root module a tfvars file feeds: the nearest ancestor with .tf files.

    The nearest ancestor holding any .tf file is the configuration the tfvars
    pairs with; it only counts as a root when it declares at least one variable,
    so fixture directories and variable-free stacks stay out of scope.

    Ancestors are walked as the path is written, not as it resolves: a tfvars
    symlinked in from elsewhere belongs to the configuration it is linked INTO,
    and resolving first walked away from that root and found nothing.
    """
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


@lru_cache(maxsize=256)
def _has_tf_files(directory: Path) -> bool:
    """Report whether the directory directly holds any Terraform configuration."""
    return next(iter(directory.glob("*.tf")), None) is not None


@lru_cache(maxsize=256)
def _declares_variables(directory: Path) -> bool:
    """Report whether any .tf file directly in the directory declares a variable."""
    return next(_variable_blocks(directory), None) is not None


def _variable_blocks(directory: Path) -> Iterator[tuple[str, str | None, bool]]:
    """Yield `(name, default value, untyped)` for every top-level variable block.

    `untyped` marks `type = any`, where Terraform performs none of the string
    conversions this rule's comparison relies on: `"false"` stays a string
    beside a bare `false`, so the two are not one value.
    """
    for tf in sorted(directory.glob("*.tf")):
        text = _read_text(tf)
        if text is None:
            continue
        for block in document(text).blocks:
            if block.type == "variable" and block.labels:
                default = block.attribute("default")
                declared = block.attribute("type")
                untyped = declared is not None and declared.value.strip() == _ANY_TYPE
                yield block.labels[0], None if default is None else default.value, untyped


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


@lru_cache(maxsize=64)
def _analyze_root(root: Path) -> _RootAnalysis:
    """Run the one shared cross-tfvars analysis for a root, cached per process."""
    files = _environment_files(root)
    declarations = {
        name: _Declaration(default is not None, None if default is None else _canonical(default), untyped)
        for name, default, untyped in _variable_blocks(root)
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
                assignment = _AssignmentValue(attr.value, _canonical(attr.value), file)
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
    # Resolved, and readable: the blind error is reported on this file, so an
    # anchor the CLI skips (unreadable) or never matches (an unresolved symlink
    # compared against a resolved path) would silently delete the whole warning.
    anchor = min(
        (path.resolve() for paths in files.values() for path in paths if _read_text(path) is not None),
        default=None,
        key=str,
    )
    return _RootAnalysis(
        root=root,
        files={env: tuple(paths) for env, paths in files.items()},
        declarations=declarations,
        values=values,
        blind=tuple(sorted(blind, key=lambda item: (item.name, item.reason))),
        anchor=anchor,
    )


def _auto_loaded_blind(files: Mapping[str, Sequence[Path]]) -> Iterator[_BlindEnvironment]:
    """Report a root that mixes Terraform's auto-loaded var-files with named environments.

    `terraform.tfvars` and `*.auto.tfvars` in the root are loaded into EVERY
    plan, so beside named environment files they are a baseline, not a peer:
    their assignments belong to every environment at a precedence this rule
    cannot model. Analyzing them as one more environment silently turns real
    findings into none, so the root goes blind instead. A root whose only
    inputs are auto-loaded is unambiguous and stays analyzable.
    """
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
    """Say that one file redefines a key, which Terraform refuses to load."""
    return (
        f"`{file.name}` assigns `{name}` twice, which Terraform rejects as a redefined attribute, "
        f"so environment `{environment}` has no inputs this rule can read"
    )


def _conflict_reason(environment: str, name: str, paths: Sequence[Path]) -> str:
    """Say which files disagree about one environment's input.

    Terraform merges several var-files by an order this rule cannot observe, so
    two files claiming one environment with different values for `name` leave no
    single answer to compare against. Guessing one would compute a
    constant-everywhere finding from a value the other file overrides.
    """
    named = ", ".join(f"`{path.name}`" for path in paths)
    return (
        f"environment `{environment}` is defined by more than one file ({named}) and they assign "
        f"`{name}` different values, so its effective inputs depend on var-file order"
    )


def _environment_files(root: Path) -> dict[str, list[Path]]:
    """Map each environment name to the root's tfvars files that define it.

    Files are keyed by resolved path so an alias — `current.tfvars` symlinked at
    `prod.tfvars`, or `env/current` at `env/prod` — is the one environment it
    really is, not a second one whose every shared line reads as constant.
    """
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
    """Yield `(file, environment)` for every tfvars that names one environment.

    The environment is the file's own stem, except for Terraform's conventional
    `terraform.tfvars`, which carries no identity of its own and takes the name
    of the directory holding it. That one rule covers both shipped layouts —
    `env/<name>/terraform.tfvars` and `env/<name>.tfvars` — where keying on the
    directory alone collapsed the second into a single environment called `env`.
    """
    for file in sorted(root.glob(f"*{_TFVARS_SUFFIX}")):
        # Terraform loads every auto-loaded root var-file into the SAME plan, so
        # `a.auto.tfvars` and `b.auto.tfvars` are one environment, not two whose
        # shared lines would read as constant across it.
        yield file, _AUTO_ENVIRONMENT if _is_auto_loaded(file.name) else _stem_environment(file.name)
    for file, env_dir in _nested_tfvars(root, _TFVARS_SUFFIX):
        stem = _stem_environment(file.name)
        yield file, env_dir.name if stem == _CONVENTIONAL_STEM else stem


def _is_auto_loaded(name: str) -> bool:
    """Report whether Terraform loads this root-level var-file into every plan.

    Returns:
        True for `terraform.tfvars` and any `*.auto.tfvars`.

    """
    stem = name.removesuffix(_TFVARS_SUFFIX)
    return stem == _CONVENTIONAL_STEM or stem.endswith(_AUTO_STEM_SUFFIX)


def _is_non_environment(label: str) -> bool:
    """Report whether a tfvars label names a copy or specimen rather than a deployment.

    The whole label, or its final dotted segment, has to be one of the specimen
    words: `prod.bak` is a copy, while `old-west` is somebody's region and is
    left alone. Splitting on every separator swallowed real environment names.
    """
    lowered = label.lower()
    return lowered in _NON_ENVIRONMENT_STEMS or lowered.rsplit(".", 1)[-1] in _NON_ENVIRONMENT_STEMS


def _nested_tfvars(root: Path, suffix: str) -> Iterator[tuple[Path, Path]]:
    """Yield `(file, environment directory)` for tfvars one or two levels below the root.

    An intermediate directory holding its own .tf files is its own configuration,
    never an environment of this root; skip-listed directories never count.
    """
    for pattern in (f"*/*{suffix}", f"*/*/*{suffix}"):
        for file in sorted(root.glob(pattern)):
            relative_dirs = file.relative_to(root).parts[:-1]
            if any(part in _SKIP_DIR_NAMES for part in relative_dirs):
                continue
            if any(_has_tf_files(root.joinpath(*relative_dirs[: index + 1])) for index in range(len(relative_dirs))):
                continue
            yield file, file.parent


def _stem_environment(name: str) -> str:
    """Reduce a root-level tfvars filename to its environment label."""
    stem = name.removesuffix(_TFVARS_SUFFIX)
    return stem.removesuffix(_AUTO_STEM_SUFFIX)


def _structural_blind(root: Path, files: dict[str, list[Path]]) -> Iterator[_BlindEnvironment]:
    """Find environments the directory layout names but the scan cannot read."""
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
    """Find environments an `envs.json` manifest declares beyond the visible tfvars."""
    manifest = root / _ENVS_MANIFEST
    if not manifest.is_file():
        return
    text = _read_text(manifest)
    if text is None:
        yield _BlindEnvironment("(all)", f"`{_ENVS_MANIFEST}` names this root's environments but cannot be read")
        return
    try:
        raw: object = json.loads(  # pyright: ignore[reportAny] — json.loads is an untyped stdlib boundary; the shape is narrowed below
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
    """Pull the secret-manager tfvars reference out of one manifest entry, if any."""
    if not isinstance(entry, dict):
        return None
    for key, value in entry.items():  # pyright: ignore[reportUnknownVariableType] — json leaves are Any; narrowed below
        if isinstance(key, str) and "tfvars" in key and isinstance(value, str):
            return value
    return None


def _canonical(text: str) -> _Canon | None:
    """Parse one literal HCL value into a comparable shape, or None when opaque.

    Heredocs and interpolations are opaque because their bodies are masked before
    this rule sees them: two masked heredocs must never read as equal.
    """
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
    """Read one quoted string, coercing "true"/"false"/numeric text like HCL would."""
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
    """Coerce string text the way HCL converts it: to bool or number, never to null."""
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
