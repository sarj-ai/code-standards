from __future__ import annotations

import ast
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Literal, final, override

from sarj_python_lint.rule_base import (
    AutofixPolicy,
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    Rule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
    Severity,
)
from sarj_python_lint.rules._annotation_origins import AnnotationOrigins
from sarj_python_lint.rules._annotation_semantics import bit_or_members
from sarj_python_lint.rules._ast_names import assigned_values, assignment_names
from sarj_python_lint.rules._nullable_outcome import nullable_outcome_diagnostics
from sarj_python_lint.rules._paths import is_test_path, is_test_support_path


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext


_SCALARS = frozenset({"str", "bytes", "int", "float", "complex", "bool"})
type _MemberKind = Literal["raw", "failure", "variant"]
_ENUM_TYPES = frozenset({"enum.Enum", "enum.IntEnum", "enum.StrEnum"})
_ENUM_DECORATORS = frozenset({"enum.unique", "typing.final", "typing_extensions.final"})
_DESCRIPTORS = frozenset({"classmethod", "staticmethod", "property"})
_FAILURE_EXAMPLE = "from enum import Enum\nclass ReadFailure(Enum):\n    CLOSED = 1\n"
_RAW_RESULT = _FAILURE_EXAMPLE + "type ReadResult = bytes | ReadFailure | None\ndef read() -> ReadResult: return None\n"
_NAMED_RESULT = (
    "from dataclasses import dataclass\n"
    + _FAILURE_EXAMPLE
    + "@dataclass(frozen=True)\nclass Chunk:\n    data: bytes\n"
    "@dataclass(frozen=True)\nclass EndOfStream:\n    pass\n"
    "type ReadResult = Chunk | ReadFailure | EndOfStream\ndef read() -> ReadResult: return EndOfStream()\n"
)


@final
class PreferOutcomeVariants(Rule):
    id = "prefer-outcome-variants"
    code = "SARJ571"
    documentation = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Represent distinct outcomes with named variants.",
        rationale="An optional error beside success state admits contradictory combinations. A bare scalar or None in a result union also lets a caller return an unrelated value of the same type. Named variants make each decision explicit.",
        remediation="Use a payload class for success and a fieldless class for a distinct empty outcome. Match on their classes and the existing failure type. For serialized records, retain the established Result or shared Literal discriminator and preserve the wire contract.",
        category=RuleCategory.ARCHITECTURE,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "For module-level, non-generic Result or Outcome aliases returned by a function in the same module, the advisory recognizes direct PEP 604 or typing.Union members containing a bare builtin scalar or None and a locally declared Error or Failure enum. It excludes ordinary optionals, opaque failure types and test-support filenames such as double_reader.py.",
            "A nullable error must be paired with a success Boolean, a finite success/error Literal tag, a nullable payload, or a Result/Outcome name plus other fields. Names alone never trigger this advisory.",
            "Recognizes direct import-proven Pydantic, dataclass, TypedDict, attrs and msgspec records, bounded Optional/Union/Annotated aliases and quoted annotations. Opaque ancestry and imported aliases are not guessed.",
            "Separate variants, independent last-error telemetry, scalar numeric uncertainty, mandatory error context, class metadata, tests and generated files are excluded. Exact-code suppressions are respected.",
            "Source-proven validator dependencies retain SARJ510 as their stronger owner when both rules are enabled. This warning does not change existing SARJ510 errors or automatically migrate constructors, persistence or partial progress.",
        ),
        examples=(
            RuleExample(
                example_id="raw-result-union",
                scenario="nominal-result",
                title="A result uses bare bytes and None for two outcomes",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.python("app/reader.py", _RAW_RESULT),),
                focus_path=PurePosixPath("app/reader.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="nominal-result-union",
                scenario="nominal-result",
                title="A chunk, end of stream and failure each have a distinct type",
                outcome=ExampleOutcome.NO_MATCH,
                files=(ExampleFile.python("app/reader.py", _NAMED_RESULT),),
                focus_path=PurePosixPath("app/reader.py"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="nullable-outcome-record",
                title="A nullable error and success flag admit contradictory outcomes",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/models.py",
                        "from pydantic import BaseModel\nclass AudioResult(BaseModel):\n    passed: bool = False\n    error: str | None = None\n    value: bytes | None = None\n",
                    ),
                ),
                focus_path=PurePosixPath("app/models.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="separate-outcome-variants",
                title="Success and error variants have non-null payloads",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/models.py",
                        "from typing import Literal\nfrom pydantic import BaseModel\nclass RunSuccess(BaseModel):\n    passed: Literal[True] = True\n    value: bytes\nclass RunError(BaseModel):\n    passed: Literal[False] = False\n    error: str\ntype RunResult = RunSuccess | RunError\n",
                    ),
                ),
                focus_path=PurePosixPath("app/models.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if is_test_path(context.path):
            return []
        return nullable_outcome_diagnostics(context, self.code) + _raw_result_diagnostics(context, self.code)


def _raw_result_diagnostics(context: PythonFileContext, code: str) -> list[Diagnostic]:
    if context.tree is None or context.generated or context.has_wildcard_import or is_test_support_path(context.path):
        return []
    if "Result" not in context.source and "Outcome" not in context.source:
        return []
    aliases = {
        name: value
        for name, value in context.annotation_semantics.aliases.items()
        if name.endswith(("Result", "Outcome"))
    }
    if not aliases:
        return []
    facts = AnnotationOrigins(context)
    used = _returned_aliases(context, facts, aliases)
    findings: list[Diagnostic] = []
    for name, value in aliases.items():
        if name not in used or not _mixes_raw_outcomes(value, facts):
            continue
        match context.parents[value]:
            case ast.TypeAlias() | ast.AnnAssign() as declaration if not context.suppressions.is_suppressed(
                declaration.lineno, code
            ):
                findings.append(
                    Diagnostic(
                        context.path,
                        declaration.lineno,
                        declaration.col_offset + 1,
                        code,
                        f"`{name}` mixes a failure enum with an unwrapped scalar or None. Give successful payloads and "
                        "distinct empty outcomes named classes, then match on each variant.",
                        severity=Severity.WARNING,
                    )
                )
            case _:
                pass
    return findings


def _returned_aliases(context: PythonFileContext, facts: AnnotationOrigins, aliases: dict[str, ast.expr]) -> set[str]:
    used: set[str] = set()
    for function in context.nodes(ast.FunctionDef, ast.AsyncFunctionDef):
        if function.returns is None:
            continue
        match context.annotation_semantics.parse(function.returns):
            case ast.Name(id=name) as reference if (
                name in aliases and facts.alias_value(reference, function.returns) is aliases[name]
            ):
                used.add(name)
            case _:
                pass
    return used


def _mixes_raw_outcomes(value: ast.expr, facts: AnnotationOrigins) -> bool:
    match value:
        case ast.BinOp(op=ast.BitOr()):
            members = bit_or_members(value)
        case ast.Subscript(value=wrapper, slice=ast.Tuple(elts=members)) if facts.qualified(wrapper, value) in {
            "typing.Union",
            "typing_extensions.Union",
        }:
            pass
        case _:
            return False
    kinds = {_member_kind(member, facts) for member in members}
    return None not in kinds and {"raw", "failure"}.issubset(kinds)


def _member_kind(member: ast.expr, facts: AnnotationOrigins) -> _MemberKind | None:
    match member:
        case ast.Constant(value=None):
            return "raw"
        case ast.Name(id=name) if name in _SCALARS and facts.builtin(member, name, member):
            return "raw"
        case ast.Name(id=name) if isinstance(owner := facts.binding(name, member), ast.ClassDef):
            return "failure" if _failure_enum(owner, facts) else "variant"
        case _:
            return None


def _failure_enum(owner: ast.ClassDef, facts: AnnotationOrigins) -> bool:
    return (
        owner.name.endswith(("Failure", "Error"))
        and len(owner.bases) == 1
        and facts.qualified(owner.bases[0], owner.bases[0]) in _ENUM_TYPES
        and all(facts.qualified(decorator, decorator) in _ENUM_DECORATORS for decorator in owner.decorator_list)
        and _has_enum_member(owner, facts)
    )


def _has_enum_member(owner: ast.ClassDef, facts: AnnotationOrigins) -> bool:
    ignored: set[str] = set()
    for target, value in assigned_values(owner.body):
        names = assignment_names(target)
        if "_ignore_" in names:
            ignored_names = _enum_ignore_names(value)
            if ignored_names is None:
                return False
            ignored.update(ignored_names)
        if _nonmember_value(value, facts):
            continue
        if any(name not in ignored and _enum_value_name(name, owner.name) for name in names):
            return True
    return False


def _enum_ignore_names(value: ast.expr) -> set[str] | None:
    match value:
        case ast.Constant(value=str() as words):
            return set(words.replace(",", " ").split())
        case ast.List(elts=items) | ast.Tuple(elts=items) | ast.Set(elts=items):
            names: set[str] = set()
            for item in items:
                match item:
                    case ast.Constant(value=str() as name):
                        names.add(name)
                    case _:
                        return None
            return names
        case _:
            return None


def _enum_value_name(name: str, class_name: str) -> bool:
    stem = name.strip("_")
    if not stem:
        return True
    if name.startswith(("__", f"_{class_name}__")) and not name.endswith("__"):
        return False
    return name not in {f"_{stem}_", f"__{stem}__"}


def _nonmember_value(value: ast.expr, facts: AnnotationOrigins) -> bool:
    match value:
        case ast.Lambda():
            return True
        case ast.Call(func=ast.Name(id=name) as func) if name in _DESCRIPTORS and facts.builtin(func, name, value):
            return True
        case ast.Call(func=func):
            return facts.qualified(func, value) in {
                "enum.nonmember",
                "enum.property",
                "builtins.classmethod",
                "builtins.staticmethod",
                "builtins.property",
            }
        case _:
            return False
