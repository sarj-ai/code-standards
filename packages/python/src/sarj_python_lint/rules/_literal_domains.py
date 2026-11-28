from __future__ import annotations

import ast
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple, Self

from sarj_python_lint.rules._annotation_semantics import module_rebindings
from sarj_python_lint.rules._imports import TYPING_SOURCES, ImportIndex


if TYPE_CHECKING:
    from collections.abc import Iterator

    from sarj_python_lint.rules._nominal_project import NominalSource


_ENUM_SOURCES = frozenset({"enum"})


class LiteralAlias(NamedTuple):
    name: str
    node: ast.Subscript
    members: frozenset[str]


class _AliasValue(NamedTuple):
    name: str
    value: ast.expr


class DomainDeclaration(NamedTuple):
    module: str
    path: Path
    name: str


@dataclass(frozen=True, slots=True)
class StringDomain:
    name: str
    path: Path
    members: frozenset[str] | None
    rebound: bool


@dataclass(frozen=True, slots=True)
class LiteralDomainIndex:
    aliases: Mapping[frozenset[str], list[DomainDeclaration]]
    enums: Mapping[frozenset[str], list[DomainDeclaration]]

    @classmethod
    def build(cls, sources: Mapping[str, NominalSource]) -> Self:
        aliases: defaultdict[frozenset[str], list[DomainDeclaration]] = defaultdict(list)
        enums: defaultdict[frozenset[str], list[DomainDeclaration]] = defaultdict(list)
        for module, source in sources.items():
            has_literal = "Literal" in source.text
            has_enum = "Enum" in source.text and "enum" in source.text
            if not (has_literal or has_enum) or (tree := source.tree) is None:
                continue
            imports = ImportIndex.from_tree(tree, module_scope_only=True)
            if has_literal:
                for alias in literal_aliases(tree, imports):
                    aliases[alias.members].append(DomainDeclaration(module, source.path, alias.name))
            if has_enum:
                for name, members in _string_enums(tree, imports).items():
                    enums[members].append(DomainDeclaration(module, source.path, name))
        return cls(aliases, enums)


def string_literal_members(node: ast.Subscript, *, minimum: int = 2) -> frozenset[str] | None:
    elements = node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]
    members: set[str] = set()
    for member in elements:
        if not isinstance(member, ast.Constant) or not isinstance(member.value, str):
            return None
        members.add(member.value)
    return frozenset(members) if len(members) >= minimum else None


def literal_aliases(tree: ast.Module, imports: ImportIndex) -> list[LiteralAlias]:
    candidates = list(_literal_alias_candidates(tree, imports, minimum=2))
    if not candidates:
        return []
    rebound = module_rebindings(tree)
    return [candidate for candidate in candidates if candidate.name not in rebound]


def string_domains(tree: ast.Module, imports: ImportIndex, path: Path) -> tuple[StringDomain, ...]:
    aliases = list(_literal_alias_candidates(tree, imports, minimum=1))
    enums = [
        node for node in tree.body if isinstance(node, ast.ClassDef) and _string_enum_base(node, imports) == "StrEnum"
    ]
    if not aliases and not enums:
        return ()
    rebound = module_rebindings(tree)
    return (
        *(StringDomain(alias.name, path, alias.members, alias.name in rebound) for alias in aliases),
        *(StringDomain(node.name, path, _enum_members(node, minimum=1), node.name in rebound) for node in enums),
    )


def _literal_alias_candidates(tree: ast.Module, imports: ImportIndex, *, minimum: int) -> Iterator[LiteralAlias]:
    for name, value in _alias_values(tree, imports):
        if (
            isinstance(value, ast.Subscript)
            and imports.resolves(value.value, sources=TYPING_SOURCES, symbol="Literal")
            and (members := string_literal_members(value, minimum=minimum)) is not None
        ):
            yield LiteralAlias(name, value, members)


def _alias_values(tree: ast.Module, imports: ImportIndex) -> Iterator[_AliasValue]:
    for statement in tree.body:
        match statement:
            case ast.TypeAlias(name=ast.Name(id=name), value=value, type_params=[]):
                yield _AliasValue(name, value)
            case ast.Assign(targets=[ast.Name(id=name)], value=value):
                yield _AliasValue(name, value)
            case ast.AnnAssign(target=ast.Name(id=name), annotation=annotation, value=ast.expr() as value) if (
                imports.resolves(annotation, sources=TYPING_SOURCES, symbol="TypeAlias")
            ):
                yield _AliasValue(name, value)
            case _:
                pass


def _string_enums(tree: ast.Module, imports: ImportIndex) -> dict[str, frozenset[str]]:
    candidates = [node for node in tree.body if isinstance(node, ast.ClassDef) and _string_enum_base(node, imports)]
    if not candidates:
        return {}
    rebound = module_rebindings(tree)
    return {
        node.name: members
        for node in candidates
        if node.name not in rebound and (members := _enum_members(node)) is not None
    }


def _string_enum_base(node: ast.ClassDef, imports: ImportIndex) -> str | None:
    if node.decorator_list or node.keywords:
        return None
    match node.bases:
        case [base]:
            symbol = imports.resolved_symbol(base, sources=_ENUM_SOURCES)
            return symbol if symbol in {"Enum", "StrEnum"} else None
        case [ast.Name(id="str"), base]:
            if imports.builtin_is_unshadowed("str") and imports.resolves(base, sources=_ENUM_SOURCES, symbol="Enum"):
                return "StrEnum"
        case _:
            pass
    return None


def _enum_members(node: ast.ClassDef, *, minimum: int = 2) -> frozenset[str] | None:
    members: set[str] = set()
    for statement in node.body:
        match statement:
            case (
                ast.Assign(targets=[ast.Name(id=name)], value=ast.Constant(value=str() as value))
                | ast.AnnAssign(target=ast.Name(id=name), value=ast.Constant(value=str() as value))
            ) if not name.startswith("_"):
                members.add(value)
            case ast.Expr(value=ast.Constant(value=str())) | ast.Pass():
                continue
            case ast.FunctionDef(name=name, decorator_list=[]) | ast.AsyncFunctionDef(name=name, decorator_list=[]) if (
                name not in {"__init__", "__new__"}
            ):
                continue
            case _:
                return None
    return frozenset(members) if len(members) >= minimum else None
