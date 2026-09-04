from __future__ import annotations

import ast
import keyword
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, ClassVar, NamedTuple, override

from sarj_python_lint.rule_base import (
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
from sarj_python_lint.rules._paths import is_generated, is_test_path


if TYPE_CHECKING:
    from pathlib import Path


_MODULE_FACTORY = "module-factory"
_NAMED_FACTORY = "named-factory"
_OTHER_BINDING = "other"


class _BindingEvent(NamedTuple):
    line: int
    col: int
    kind: str
    direct: bool


class PreferStructOverNamedtuple(Rule):
    id: str = "prefer-struct-over-namedtuple"
    code: str = "SARJ015"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="Prefer typed declarations for static application-owned `collections.namedtuple` records.",
        rationale="A static `collections.namedtuple` factory declares field names but cannot declare their types.",
        remediation=(
            "Use a class-based `typing.NamedTuple` when tuple behavior is part of the contract. Use a frozen, "
            "slotted dataclass or an existing validation model only when changing tuple semantics is safe."
        ),
        category=RuleCategory.MAINTAINABILITY,
        limitations=(
            "Only statically named declarations with non-empty literal fields and proven `collections` provenance are reported.",
            "Tests, generated or vendored code, compatibility branches, dynamic factories, renamed fields, and already annotated records are excluded.",
        ),
        examples=(
            RuleExample(
                example_id="collections-namedtuple",
                title="Static record omits field types",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "models.py",
                        "from collections import namedtuple\n\nRow = namedtuple('Row', ['id', 'name'])\n",
                    ),
                ),
                focus_path=PurePosixPath("models.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="typed-named-tuple",
                title="Typed tuple-compatible record",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "models.py",
                        "from typing import NamedTuple\n\nclass Row(NamedTuple):\n    id: int\n    name: str\n\nrow = Row(1, 'Ada')\nid, name = row\n",
                    ),
                ),
                focus_path=PurePosixPath("models.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description: str = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if path.suffix != ".py" or "namedtuple" not in source or is_test_path(path) or is_generated(path, source):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
        scopes = [
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        ]
        events = {id(scope): _scope_binding_events(scope) for scope in scopes}
        lines = source.splitlines()
        return [
            self._diag(path, call)
            for call in sorted(
                (node for node in ast.walk(tree) if isinstance(node, ast.Call)),
                key=lambda node: (node.lineno, node.col_offset),
            )
            if _is_static_owned_declaration(call, tree, parents)
            and _resolves_collections_namedtuple(call, tree, parents, events)
            and not _inside_compatibility_branch(call, parents)
            and not is_suppressed(lines, call.lineno, self.code)
        ]

    def _diag(self, path: Path, node: ast.AST) -> Diagnostic:
        return Diagnostic(
            path=path,
            line=getattr(node, "lineno", 1),
            col=getattr(node, "col_offset", 0) + 1,
            code=self.code,
            message=(
                "static `collections.namedtuple` fields have no type declarations — prefer a class-based "
                "`typing.NamedTuple`; change tuple semantics only after reviewing callers"
            ),
            severity=Severity.WARNING,
        )


def _is_static_owned_declaration(call: ast.Call, tree: ast.Module, parents: dict[ast.AST, ast.AST]) -> bool:
    declaration = _declaration_name(call, parents)
    typename = _string_argument(call, 0, "typename")
    fields = _field_names(_argument(call, 1, "field_names"))
    if declaration is None or typename != declaration or not fields or len(fields) != len(set(fields)):
        return False
    if any(not field.isidentifier() or keyword.iskeyword(field) or field.startswith("_") for field in fields):
        return False
    rename = _argument(call, 2, "rename")
    if rename is not None and not (isinstance(rename, ast.Constant) and rename.value is False):
        return False
    if any(item.arg is None for item in call.keywords):
        return False
    module = next((item.value for item in call.keywords if item.arg == "module"), None)
    if module is not None and not (isinstance(module, ast.Constant) and module.value is None):
        return False
    return not _record_has_declared_field_types(tree, call, parents, declaration, fields)


def _declaration_name(call: ast.Call, parents: dict[ast.AST, ast.AST]) -> str | None:
    parent = parents.get(call)
    if isinstance(parent, ast.Assign) and parent.value is call and len(parent.targets) == 1:
        target = parent.targets[0]
        return target.id if isinstance(target, ast.Name) else None
    if isinstance(parent, ast.AnnAssign) and parent.value is call and isinstance(parent.target, ast.Name):
        return parent.target.id
    if isinstance(parent, ast.ClassDef) and call in parent.bases:
        return parent.name
    return None


def _argument(call: ast.Call, position: int, keyword_name: str) -> ast.expr | None:
    if len(call.args) > position:
        return call.args[position]
    return next((item.value for item in call.keywords if item.arg == keyword_name), None)


def _string_argument(call: ast.Call, position: int, keyword_name: str) -> str | None:
    value = _argument(call, position, keyword_name)
    return value.value if isinstance(value, ast.Constant) and isinstance(value.value, str) else None


def _field_names(node: ast.expr | None) -> tuple[str, ...] | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return tuple(part for part in node.value.replace(",", " ").split() if part)
    if not isinstance(node, (ast.List, ast.Tuple)):
        return None
    values = tuple(item.value for item in node.elts if isinstance(item, ast.Constant) and isinstance(item.value, str))
    return values if len(values) == len(node.elts) else None


def _record_has_declared_field_types(
    tree: ast.Module,
    call: ast.Call,
    parents: dict[ast.AST, ast.AST],
    name: str,
    fields: tuple[str, ...],
) -> bool:
    parent = parents.get(call)
    if isinstance(parent, ast.ClassDef):
        annotated = {
            statement.target.id
            for statement in parent.body
            if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name)
        }
        return set(fields) <= annotated
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or node.lineno < call.lineno or not isinstance(node.value, ast.Dict):
            continue
        if not any(_is_annotations_target(target, name) for target in node.targets):
            continue
        typed_fields = {
            key.value
            for key, value in zip(node.value.keys, node.value.values, strict=True)
            if isinstance(key, ast.Constant)
            and isinstance(key.value, str)
            and not (isinstance(value, ast.Constant) and value.value is None)
        }
        if set(fields) <= typed_fields:
            return True
    return False


def _is_annotations_target(node: ast.expr, name: str) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "__annotations__"
        and isinstance(node.value, ast.Name)
        and node.value.id == name
    )


def _resolves_collections_namedtuple(
    call: ast.Call,
    tree: ast.Module,
    parents: dict[ast.AST, ast.AST],
    events: dict[int, dict[str, tuple[_BindingEvent, ...]]],
) -> bool:
    match call.func:
        case ast.Name(id=root):
            expected = _NAMED_FACTORY
        case ast.Attribute(value=ast.Name(id=root), attr="namedtuple"):
            expected = _MODULE_FACTORY
        case _:
            return False
    scopes = _enclosing_scopes(call, tree, parents)
    crossed_function = False
    left_class_body = False
    position = (call.lineno, call.col_offset)
    for scope in scopes:
        if isinstance(scope, ast.ClassDef):
            if _inside_class_header(call, scope, parents):
                continue
            if crossed_function or left_class_body:
                continue
            left_class_body = True
        bindings = (*events[id(scope)].get(root, ()), *events[id(scope)].get("*", ()))
        prior = [event for event in bindings if (event.line, event.col) < position]
        if prior:
            latest = max(prior, key=lambda event: (event.line, event.col))
            return latest.direct and latest.kind == expected
        if isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)) and bindings:
            return False
        if isinstance(scope, ast.Module):
            return False
        crossed_function = crossed_function or isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef))
    return False


def _inside_class_header(call: ast.Call, scope: ast.ClassDef, parents: dict[ast.AST, ast.AST]) -> bool:
    current: ast.AST = call
    while (parent := parents.get(current)) is not None and parent is not scope:
        current = parent
    if parents.get(current) is not scope:
        return False
    return current in {*scope.bases, *scope.decorator_list, *(keyword.value for keyword in scope.keywords)}


def _enclosing_scopes(
    node: ast.AST,
    tree: ast.Module,
    parents: dict[ast.AST, ast.AST],
) -> tuple[ast.Module | ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef, ...]:
    scopes: list[ast.Module | ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef] = []
    current: ast.AST | None = node
    while current is not None:
        if isinstance(current, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            scopes.append(current)
        current = parents.get(current)
    if tree not in scopes:
        scopes.append(tree)
    return tuple(scopes)


def _scope_binding_events(
    scope: ast.Module | ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef,
) -> dict[str, tuple[_BindingEvent, ...]]:
    collected: dict[str, list[_BindingEvent]] = {}
    if isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)):
        for argument in (
            *scope.args.posonlyargs,
            *scope.args.args,
            *scope.args.kwonlyargs,
            *((scope.args.vararg,) if scope.args.vararg is not None else ()),
            *((scope.args.kwarg,) if scope.args.kwarg is not None else ()),
        ):
            collected.setdefault(argument.arg, []).append(
                _BindingEvent(scope.lineno, scope.col_offset, _OTHER_BINDING, direct=True)
            )
    for statement in scope.body:
        _collect_statement_bindings(statement, collected, direct=True)
    return {
        name: tuple(sorted(bindings, key=lambda event: (event.line, event.col)))
        for name, bindings in collected.items()
    }


def _collect_statement_bindings(
    node: ast.AST,
    collected: dict[str, list[_BindingEvent]],
    *,
    direct: bool,
) -> None:
    match node:
        case ast.Import(names=names):
            for alias in names:
                local = alias.asname or alias.name.partition(".")[0]
                kind = (
                    _MODULE_FACTORY
                    if alias.name == "collections"
                    or (alias.name.startswith("collections.") and alias.asname is None)
                    else _OTHER_BINDING
                )
                collected.setdefault(local, []).append(
                    _BindingEvent(alias.lineno, alias.col_offset, kind, direct=direct)
                )
            return
        case ast.ImportFrom(module=module, names=names):
            for alias in names:
                local = alias.asname or alias.name
                kind = _NAMED_FACTORY if module == "collections" and alias.name == "namedtuple" else _OTHER_BINDING
                collected.setdefault(local, []).append(
                    _BindingEvent(alias.lineno, alias.col_offset, kind, direct=direct)
                )
            return
        case ast.FunctionDef() | ast.AsyncFunctionDef() | ast.ClassDef():
            collected.setdefault(node.name, []).append(
                _BindingEvent(node.lineno, node.col_offset, _OTHER_BINDING, direct=direct)
            )
            return
        case ast.MatchAs(name=str(name)) | ast.MatchStar(name=str(name)) | ast.MatchMapping(rest=str(name)):
            collected.setdefault(name, []).append(
                _BindingEvent(node.lineno, node.col_offset, _OTHER_BINDING, direct=direct)
            )
        case _:
            pass
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.Name) and isinstance(child.ctx, (ast.Store, ast.Del)):
            collected.setdefault(child.id, []).append(
                _BindingEvent(child.lineno, child.col_offset, _OTHER_BINDING, direct)
            )
        elif isinstance(child, ast.ExceptHandler) and child.name is not None:
            collected.setdefault(child.name, []).append(
                _BindingEvent(child.lineno, child.col_offset, _OTHER_BINDING, direct)
            )
            _collect_statement_bindings(child, collected, direct=False)
        elif not isinstance(child, (ast.Lambda, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            _collect_statement_bindings(child, collected, direct=False)


def _inside_compatibility_branch(call: ast.Call, parents: dict[ast.AST, ast.AST]) -> bool:
    current = parents.get(call)
    while current is not None:
        if isinstance(current, ast.If) and any(
            (isinstance(node, ast.Name) and node.id == "TYPE_CHECKING")
            or (isinstance(node, ast.Attribute) and node.attr in {"version_info", "platform", "implementation"})
            for node in ast.walk(current.test)
        ):
            return True
        current = parents.get(current)
    return False
