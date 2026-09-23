from __future__ import annotations

import ast
from functools import lru_cache
from pathlib import PurePosixPath
import re
import tomllib
from typing import TYPE_CHECKING, ClassVar, NotRequired, TypedDict, TypeGuard, final, override

from packaging.requirements import InvalidRequirement, Requirement
from packaging.version import Version

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
    is_suppressed,
    parse_or_none,
)
from sarj_python_lint.rules._annotation_semantics import AnnotationSemantics
from sarj_python_lint.rules._first_party import FirstPartyFacts, distribution_root
from sarj_python_lint.rules._paths import is_generated


if TYPE_CHECKING:
    from pathlib import Path


_JSON_SCALARS = frozenset({"None", "bool", "float", "int", "str"})
_MAPPING_ARGUMENT_COUNT = 2
_PYDANTIC_V2_MAJOR = 2
_TYPING_SOURCES = frozenset({"typing", "typing_extensions"})
_V2_CANDIDATES = tuple(Version(f"2.{minor}.{patch}") for minor in range(100) for patch in (0, 5, 99))
_PEP695_ALIAS = re.compile(r"(?m)^[ \t]*type[ \t]+[A-Za-z_]\w*[ \t]*(?:\[|=)")


class _ProjectTable(TypedDict):
    dependencies: NotRequired[list[object]]


class _ProjectDocument(TypedDict):
    project: NotRequired[_ProjectTable]


@final
class PreferPydanticJsonValue(Rule):
    id = "prefer-pydantic-json-value"
    code = "SARJ454"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Recursive JSON value alias duplicates `pydantic.JsonValue`.",
        rationale=(
            "Pydantic's canonical JSON value alias keeps the static contract aligned with runtime validation and "
            "prevents subtly divergent recursive definitions inside packages that already depend on Pydantic v2."
        ),
        remediation="Import and use `pydantic.JsonValue` instead of maintaining an equivalent recursive alias.",
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only exact recursive JSON domains in distributions proven to depend on Pydantic v2 are reported.",
            "Generic, imported, narrower, extended, mutually recursive, ambiguous, generated, and vendored aliases are excluded.",
        ),
        examples=(
            RuleExample(
                example_id="home-grown-json-value",
                title="Use Pydantic's canonical recursive JSON value",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile(
                        path=PurePosixPath("pyproject.toml"),
                        source='[project]\nname = "app"\nversion = "0.1.0"\ndependencies = ["pydantic>=2"]\n',
                    ),
                    ExampleFile.python(
                        "src/app/types.py",
                        "type JsonValue = str | int | float | bool | None | list[JsonValue] | dict[str, JsonValue]\n",
                    ),
                ),
                focus_path=PurePosixPath("src/app/types.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="canonical-pydantic-json-value",
                title="The Pydantic alias is already canonical",
                outcome=ExampleOutcome.NO_MATCH,
                files=(ExampleFile.python("src/app/types.py", "from pydantic import JsonValue\nvalue: JsonValue\n"),),
                focus_path=PurePosixPath("src/app/types.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if is_generated(path, source) or _is_vendor_path(path):
            return []
        if "TypeAlias" not in source and _PEP695_ALIAS.search(source) is None:
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        semantics = AnnotationSemantics.from_tree(tree)
        aliases = [alias for statement in tree.body if (alias := _explicit_alias(statement, semantics)) is not None]
        if not aliases:
            return []
        facts = self._analysis_session.first_party if self._analysis_session is not None else FirstPartyFacts()
        if not _depends_on_pydantic_v2(path, facts):
            return []
        lines = source.splitlines()
        findings: list[Diagnostic] = []
        for alias in aliases:
            name, value, location = alias
            if is_suppressed(lines, location.lineno, self.code) or not _is_exact_json_value(name, value, semantics):
                continue
            findings.append(
                Diagnostic(
                    path=path,
                    line=location.lineno,
                    col=location.col_offset + 1,
                    code=self.code,
                    message=(
                        f"recursive JSON alias `{name}` duplicates `pydantic.JsonValue`; import the canonical alias instead"
                    ),
                )
            )
        return findings


def _explicit_alias(statement: ast.stmt, semantics: AnnotationSemantics) -> tuple[str, ast.expr, ast.expr] | None:
    match statement:
        case ast.TypeAlias(name=ast.Name(id=name) as location, value=value, type_params=[]):
            return (name, value, location) if name in semantics.aliases else None
        case ast.AnnAssign(target=ast.Name(id=name) as location, annotation=annotation, value=value) if (
            value is not None and semantics.imports.resolves(annotation, sources=_TYPING_SOURCES, symbol="TypeAlias")
        ):
            return (name, value, location) if name in semantics.aliases else None
        case _:
            return None


def _is_exact_json_value(name: str, value: ast.expr, semantics: AnnotationSemantics) -> bool:
    members = _union_members(value, semantics)
    kinds = {_json_member(name, member, semantics) for member in members}
    return None not in kinds and kinds == {*_JSON_SCALARS, "list[self]", "dict[str,self]"}


def _union_members(node: ast.expr, semantics: AnnotationSemantics) -> tuple[ast.expr, ...]:
    parsed = semantics.parse(node)
    if parsed is None:
        return ()
    if isinstance(parsed, ast.BinOp) and isinstance(parsed.op, ast.BitOr):
        return _union_members(parsed.left, semantics) + _union_members(parsed.right, semantics)
    if isinstance(parsed, ast.Subscript) and semantics.imports.resolves(
        parsed.value, sources=_TYPING_SOURCES, symbol="Union"
    ):
        return tuple(parsed.slice.elts) if isinstance(parsed.slice, ast.Tuple) else (parsed.slice,)
    return (parsed,)


def _json_member(name: str, node: ast.expr, semantics: AnnotationSemantics) -> str | None:
    parsed = semantics.parse(node)
    if parsed is None:
        return None
    if isinstance(parsed, ast.Constant) and parsed.value is None:
        return "None"
    if isinstance(parsed, ast.Name) and parsed.id in _JSON_SCALARS - {"None"}:
        return parsed.id if semantics.imports.builtin_is_unshadowed(parsed.id) else None
    if not isinstance(parsed, ast.Subscript):
        return None
    if _is_container(parsed.value, semantics, builtin="list", typing_symbol="List"):
        return "list[self]" if _is_self(name, parsed.slice, semantics) else None
    if _is_container(parsed.value, semantics, builtin="dict", typing_symbol="Dict"):
        if not isinstance(parsed.slice, ast.Tuple) or len(parsed.slice.elts) != _MAPPING_ARGUMENT_COUNT:
            return None
        key, value = parsed.slice.elts
        if not (
            isinstance(key, ast.Name)
            and key.id == "str"
            and semantics.imports.builtin_is_unshadowed("str")
            and _is_self(name, value, semantics)
        ):
            return None
        return "dict[str,self]"
    return None


def _is_self(name: str, node: ast.expr, semantics: AnnotationSemantics) -> bool:
    parsed = semantics.parse(node)
    return isinstance(parsed, ast.Name) and parsed.id == name


def _is_container(
    node: ast.expr,
    semantics: AnnotationSemantics,
    *,
    builtin: str,
    typing_symbol: str,
) -> bool:
    return (
        isinstance(node, ast.Name) and node.id == builtin and semantics.imports.builtin_is_unshadowed(builtin)
    ) or semantics.imports.resolves(node, sources=_TYPING_SOURCES, symbol=typing_symbol)


def _depends_on_pydantic_v2(path: Path, facts: FirstPartyFacts) -> bool:
    root = distribution_root(path, facts=facts)
    if root is None:
        return False
    try:
        source = (root / "pyproject.toml").read_text(encoding="utf-8")
    except OSError:
        return False
    return _document_depends_on_pydantic_v2(source)


@lru_cache(maxsize=256)
def _document_depends_on_pydantic_v2(source: str) -> bool:
    try:
        document: object = tomllib.loads(source)
    except tomllib.TOMLDecodeError:
        return False
    for raw in _project_dependencies(document):
        requirement = _pydantic_requirement(raw)
        if requirement is not None:
            return _requirement_targets_pydantic_v2(requirement)
    return False


def _project_dependencies(document: object) -> list[object]:
    if not _is_project_document(document):
        return []
    project = document.get("project")
    if project is None:
        return []
    return project.get("dependencies", [])


def _pydantic_requirement(raw: object) -> Requirement | None:
    if not isinstance(raw, str):
        return None
    try:
        requirement = Requirement(raw)
    except InvalidRequirement:
        return None
    if requirement.name.casefold() != "pydantic" or requirement.marker is not None:
        return None
    return requirement


def _requirement_targets_pydantic_v2(requirement: Requirement) -> bool:
    if not _has_v2_floor(requirement):
        return False
    candidates = (*_V2_CANDIDATES, *_exact_version_candidates(requirement))
    return any(
        candidate.major == _PYDANTIC_V2_MAJOR and requirement.specifier.contains(candidate, prereleases=True)
        for candidate in candidates
    )


def _exact_version_candidates(requirement: Requirement) -> list[Version]:
    candidates: list[Version] = []
    for specifier in requirement.specifier:
        try:
            candidates.append(Version(specifier.version.removesuffix(".*")))
        except ValueError:
            continue
    return candidates


def _has_v2_floor(requirement: Requirement) -> bool:
    for specifier in requirement.specifier:
        version_text = specifier.version.removesuffix(".*")
        try:
            version = Version(version_text)
        except ValueError:
            continue
        if version.major != _PYDANTIC_V2_MAJOR:
            continue
        if specifier.operator in {">", ">=", "~=", "==", "==="}:
            return True
    return False


def _is_project_document(value: object) -> TypeGuard[_ProjectDocument]:
    if not _is_object_mapping(value):
        return False
    project = value.get("project")
    if project is None:
        return True
    if not _is_object_mapping(project):
        return False
    dependencies = project.get("dependencies")
    return dependencies is None or isinstance(dependencies, list)


def _is_object_mapping(value: object) -> TypeGuard[dict[object, object]]:
    return isinstance(value, dict)


def _is_vendor_path(path: Path) -> bool:
    return any(part.casefold() in {"vendor", "vendored", "third_party"} for part in path.parts)
