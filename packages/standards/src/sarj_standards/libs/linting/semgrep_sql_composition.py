from __future__ import annotations

import ast
from collections import Counter
from dataclasses import dataclass
import json
import math
from pathlib import Path
import sys
from typing import TYPE_CHECKING, Annotated, ClassVar, Literal, TypeGuard

from pydantic import BaseModel, ConfigDict, JsonValue, RootModel
import typer


if TYPE_CHECKING:
    from collections.abc import Callable


RULE = "rules.python.sqlalchemy.security.sqlalchemy-execute-raw-query"
REASON = "psycopg-fixed-literal-composition-v1"
_MAX_EXIT_STATUS = 255
_MAX_ALIAS_PASSES = 32
_DYNAMIC_BUILTINS = frozenset({"exec", "eval", "globals", "locals", "getattr", "setattr", "delattr", "vars"})
_INTROSPECTION_ATTRIBUTES = frozenset(
    {
        "__dict__",
        "__getattribute__",
        "__getattr__",
        "__setattr__",
        "__delattr__",
        "__globals__",
        "__closure__",
        "f_globals",
        "f_locals",
        "gi_frame",
        "cr_frame",
        "ag_frame",
    }
)


@dataclass(frozen=True)
class Correction:
    report: dict[str, JsonValue]
    exit_status: int


@dataclass(frozen=True)
class _Position:
    line: int
    column: int


@dataclass(frozen=True)
class _Artifacts:
    input_path: Path
    output_path: Path
    source_root: Path
    raw_exit_status: int


class _Envelope(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(strict=True, extra="allow")
    version: Literal["1.182.0"]
    results: list[dict[str, JsonValue]]
    errors: list[JsonValue]


def _table(value: JsonValue) -> TypeGuard[dict[str, JsonValue]]:
    return isinstance(value, dict)


class _Proof:
    def __init__(self, source: str) -> None:
        self.tree = ast.parse(source)
        self.nodes = tuple(ast.walk(self.tree))
        self.parents = {child: node for node in self.nodes for child in ast.iter_child_nodes(node)}
        self.writes: Counter[str] = Counter()
        self.imports: dict[str, str] = {}
        self.literals: dict[str, ast.Constant] = {}
        self.composables: dict[str, ast.expr] = {}
        for node in self.nodes:
            self._record_binding(node)
        for node in self.tree.body:
            self._record_literal(node)
        self.protected = (
            set(self.imports)
            | set(self.composables)
            | {
                node.name
                for node in self.nodes
                if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
            }
        )
        aliases_proven = self._protect_aliases()
        self.dependencies: set[str] = set()
        self.unsafe_mutation = not aliases_proven or any(self._mutation(node) for node in self.nodes)

    def _record_binding(self, node: ast.AST) -> None:
        match node:
            case ast.Name(id=name, ctx=ast.Store() | ast.Del()) | ast.arg(arg=name):
                self.writes[name] += 1
            case ast.FunctionDef(name=name) | ast.AsyncFunctionDef(name=name) | ast.ClassDef(name=name):
                self.writes[name] += 1
            case (
                ast.ExceptHandler(name=str() as name)
                | ast.MatchAs(name=str() as name)
                | ast.MatchStar(name=str() as name)
            ):
                self.writes[name] += 1
            case ast.MatchMapping(rest=str() as name):
                self.writes[name] += 1
            case ast.Import() | ast.ImportFrom():
                self._record_import(node)
            case _:
                pass

    def _record_import(self, node: ast.Import | ast.ImportFrom) -> None:
        for alias in node.names:
            name = alias.asname or alias.name.split(".")[0]
            self.writes[name] += 1
            if self.parents[node] is not self.tree:
                continue
            if isinstance(node, ast.Import):
                self.imports[name] = alias.name if alias.asname else alias.name.split(".")[0]
            elif node.level == 0:
                self.imports[name] = f"{node.module}.{alias.name}"

    def _record_literal(self, node: ast.stmt) -> None:
        match node:
            case ast.Assign(targets=[ast.Name(id=name)], value=value):
                self._literal(name, value)
                self.composables[name] = value
            case ast.AnnAssign(target=ast.Name(id=name), value=ast.expr() as value):
                self._literal(name, value)
                self.composables[name] = value
            case _:
                pass

    def _protect_aliases(self) -> bool:
        for _ in range(_MAX_ALIAS_PASSES):
            added: set[str] = set()
            for node in self.nodes:
                added.update(self._alias_bindings(node))
            if added <= self.protected:
                return True
            self.protected.update(added)
        return False

    def _alias_bindings(self, node: ast.AST) -> set[str]:
        if not isinstance(node, (ast.Assign, ast.AnnAssign, ast.NamedExpr)) or node.value is None:
            return set()
        references = {item.id for item in ast.walk(node.value) if isinstance(item, ast.Name)}
        if references.isdisjoint(self.protected):
            return set()
        return {item.id for item in ast.walk(node) if isinstance(item, ast.Name) and isinstance(item.ctx, ast.Store)}

    def _literal(self, name: str, value: ast.expr) -> None:
        if isinstance(value, ast.Constant) and isinstance(value.value, str) and self.writes[name] == 1:
            self.literals[name] = value

    def _qualified(self, node: ast.expr) -> str | None:
        if isinstance(node, ast.Name) and self.writes[node.id] == 1:
            return self.imports.get(node.id)
        if isinstance(node, ast.Attribute) and (base := self._qualified(node.value)):
            return f"{base}.{node.attr}"
        return None

    def _mutation(self, node: ast.AST) -> bool:
        if isinstance(node, ast.Name) and node.id in _DYNAMIC_BUILTINS:
            return True
        if isinstance(node, ast.ImportFrom) and any(alias.name == "*" for alias in node.names):
            return True
        if isinstance(node, ast.Attribute) and node.attr in _DYNAMIC_BUILTINS | _INTROSPECTION_ATTRIBUTES:
            return True
        if isinstance(node, ast.Attribute) and isinstance(node.ctx, (ast.Store, ast.Del)):
            base = node.value
            while isinstance(base, (ast.Attribute, ast.Subscript)):
                base = base.value
            return not isinstance(base, ast.Name) or base.id in self.protected
        return False

    def safe(self, start: _Position, end: _Position) -> bool:
        if self.unsafe_mutation:
            return False
        matches = [
            node
            for node in self.nodes
            if isinstance(node, ast.Call)
            and (node.lineno, node.col_offset + 1) == (start.line, start.column)
            and (node.end_lineno, (node.end_col_offset or 0) + 1) == (end.line, end.column)
        ]
        if len(matches) != 1:
            return False
        call = matches[0]
        proven = (
            isinstance(call.func, ast.Attribute)
            and call.func.attr == "execute"
            and bool(call.args)
            and not any(isinstance(arg, ast.Starred) for arg in call.args)
            and not any(keyword.arg is None for keyword in call.keywords)
            and isinstance(call.args[0], ast.Call)
            and isinstance(call.args[0].func, ast.Attribute)
            and call.args[0].func.attr == "format"
            and self._composable(call.args[0], call)
        )
        return proven and not self._escaped()

    def _composable(self, node: ast.expr, at: ast.AST) -> bool:
        if isinstance(node, ast.Name):
            self.dependencies.add(node.id)
            value = self.composables.get(node.id)
            return (
                self.writes[node.id] == 1
                and isinstance(value, ast.Call)
                and self._qualified(value.func) == "psycopg.sql.SQL"
                and self._composable(value, at)
            )
        if not isinstance(node, ast.Call) or any(isinstance(arg, ast.Starred) for arg in node.args):
            return False
        if any(keyword.arg is None for keyword in node.keywords):
            return False
        if self._qualified(node.func) == "psycopg.sql.SQL":
            return len(node.args) == 1 and not node.keywords and self._fixed_string(node.args[0], at)
        if isinstance(node.func, ast.Attribute) and node.func.attr == "format":
            return (
                self._composable(node.func.value, at)
                and all(self._composable(arg, at) for arg in node.args)
                and all(self._composable(keyword.value, at) for keyword in node.keywords)
            )
        return False

    def _fixed_string(self, node: ast.expr, at: ast.AST) -> bool:
        match node:
            case ast.Constant(value=str()):
                return True
            case ast.Name(id=name):
                return name in self.literals
            case ast.Attribute():
                return self._class_literal(node, at)
            case _:
                return False

    def _class_literal(self, node: ast.Attribute, at: ast.AST) -> bool:
        owner = self.parents.get(at)
        while owner is not None and not isinstance(owner, ast.ClassDef):
            owner = self.parents.get(owner)
        if not isinstance(owner, ast.ClassDef) or not self._plain_class(owner, set()):
            return False
        self.dependencies.add(owner.name)
        self.dependencies.update(base.id for base in owner.bases if isinstance(base, ast.Name))
        if self._has_subclass(owner) or not self._class_receiver(node.value, at, owner):
            return False
        return self._declared_leaf(owner, node.attr)

    def _has_subclass(self, owner: ast.ClassDef) -> bool:
        return any(
            isinstance(item, ast.ClassDef)
            and item is not owner
            and any(isinstance(base, ast.Name) and base.id == owner.name for base in item.bases)
            for item in self.nodes
        )

    def _class_receiver(self, receiver: ast.expr, at: ast.AST, owner: ast.ClassDef) -> bool:
        if not isinstance(receiver, ast.Name):
            return False
        if receiver.id == owner.name:
            return self.writes[owner.name] == 1
        method = self.parents.get(at)
        while method is not None and not isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)):
            method = self.parents.get(method)
        if method is None or self.parents.get(method) is not owner or method.decorator_list:
            return False
        positional = method.args.posonlyargs + method.args.args
        if not positional or positional[0].arg != receiver.id:
            return False
        return not any(
            isinstance(item, ast.Name) and item.id == receiver.id and isinstance(item.ctx, (ast.Store, ast.Del))
            for item in ast.walk(method)
        )

    def _declared_leaf(self, owner: ast.ClassDef, name: str) -> bool:
        declarations = [
            item
            for item in owner.body
            if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name) and item.target.id == name
        ]
        mutated = any(
            isinstance(item, ast.Attribute) and item.attr == name and isinstance(item.ctx, (ast.Store, ast.Del))
            for item in self.nodes
        )
        if len(declarations) != 1 or self.writes[name] != 1 or mutated:
            return False
        leaf = declarations[0]
        annotation = leaf.annotation
        return (
            isinstance(annotation, ast.Subscript)
            and self._qualified(annotation.value) == "typing.ClassVar"
            and self._qualified(annotation.slice) == "typing.LiteralString"
            and isinstance(leaf.value, ast.Constant)
            and isinstance(leaf.value.value, str)
        )

    def _plain_class(self, owner: ast.ClassDef, seen: set[str]) -> bool:
        if owner.name in seen or owner.decorator_list or owner.keywords or self.writes[owner.name] != 1:
            return False
        seen |= {owner.name}
        self.dependencies.add(owner.name)
        if any(
            (
                (
                    isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                    or (isinstance(item, ast.Name) and isinstance(item.ctx, ast.Store))
                )
                and (item.name if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) else item.id)
                in {"__getattribute__", "__getattr__", "__setattr__", "__init_subclass__", "__new__"}
            )
            for item in ast.walk(owner)
        ):
            return False
        for base in owner.bases:
            if self._qualified(base) in {"abc.ABC", "typing.Protocol"}:
                continue
            candidates = [
                item
                for item in self.tree.body
                if isinstance(item, ast.ClassDef) and isinstance(base, ast.Name) and item.name == base.id
            ]
            if len(candidates) != 1 or not self._plain_class(candidates[0], seen):
                return False
        return True

    def _escaped(self) -> bool:
        aliases = set(self.dependencies)
        for _ in range(_MAX_ALIAS_PASSES):
            added: set[str] = set()
            for node in self.nodes:
                assigned = self._escaped_assignment(node, aliases)
                if assigned is None:
                    return True
                added.update(assigned)
            if added <= aliases:
                break
            aliases.update(added)
        else:
            return True
        return any(self._call_escapes(node, aliases) for node in self.nodes)

    def _escaped_assignment(self, node: ast.AST, aliases: set[str]) -> set[str] | None:
        if not isinstance(node, (ast.Assign, ast.AnnAssign, ast.NamedExpr)) or node.value is None:
            return set()
        if not self._references(node.value, aliases):
            return set()
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if any(not isinstance(target, (ast.Name, ast.Tuple, ast.List)) for target in targets):
            return None
        return {item.id for target in targets for item in ast.walk(target) if isinstance(item, ast.Name)}

    def _call_escapes(self, node: ast.AST, aliases: set[str]) -> bool:
        match node:
            case ast.Return(value=value) | ast.Yield(value=value) | ast.YieldFrom(value=value) if value is not None:
                return self._references(value, aliases)
            case ast.Lambda(body=body):
                return self._references(body, aliases)
            case ast.ClassDef(name=name, bases=bases):
                return name not in self.dependencies and any(self._references(base, aliases) for base in bases)
            case ast.Call(func=callee, args=args, keywords=keywords):
                arguments = [*args, *(keyword.value for keyword in keywords)]
                captures = self._references(callee, aliases) or any(self._references(arg, aliases) for arg in arguments)
                return captures and not (
                    isinstance(callee, ast.Attribute)
                    and callee.attr == "format"
                    and self._composable(callee.value, node)
                )
            case _:
                return False

    def _references(self, value: ast.expr, names: set[str]) -> bool:
        match value:
            case ast.Name(id=name):
                return name in names
            case ast.Attribute(value=ast.Name(id=owner), attr=member) if self._unbound_member(owner, member):
                return False
            case ast.Call(func=ast.Attribute(attr="format"), args=args, keywords=keywords):
                return any(self._references(arg, names) for arg in [*args, *(item.value for item in keywords)])
            case ast.Call():
                return False
            case _:
                return any(
                    self._references(child, names)
                    for child in ast.iter_child_nodes(value)
                    if isinstance(child, ast.expr)
                )

    def _unbound_member(self, owner: str, member: str) -> bool:
        if self.writes[owner] != 1 or self.writes[member] != 1:
            return False
        classes = [node for node in self.tree.body if isinstance(node, ast.ClassDef) and node.name == owner]
        if len(classes) != 1:
            return False
        members = [
            node
            for node in classes[0].body
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == member
        ]
        if len(members) != 1:
            return False
        selected = members[0]
        if isinstance(selected, ast.ClassDef):
            return True
        if any(isinstance(item, ast.Name) and item.id in {"__class__", "super"} for item in ast.walk(selected)):
            return False
        return (
            self.writes["staticmethod"] == 0
            and len(selected.decorator_list) == 1
            and isinstance(selected.decorator_list[0], ast.Name)
            and selected.decorator_list[0].id == "staticmethod"
        )


def correct(payload: str, *, source_root: Path, raw_exit_status: int) -> Correction:
    _status(raw_exit_status)
    report = _decode_report(payload)
    envelope = _Envelope.model_validate(report)
    results, errors = envelope.results, envelope.errors
    retained: list[JsonValue] = []
    cleared: list[JsonValue] = []
    root = source_root.resolve(strict=True)
    for finding in results:
        if not _table(finding) or not isinstance(finding.get("check_id"), str):
            message = "invalid Semgrep finding"
            raise ValueError(message)
        start, end = _position(finding.get("start")), _position(finding.get("end"))
        if finding["check_id"] != RULE:
            retained.append(finding)
            continue
        if _safe_finding(finding, root, start, end):
            cleared.append({"finding": finding, "reason": REASON})
        else:
            retained.append(finding)
    effective = dict(report)
    effective["results"] = retained
    effective["sql_composition_correction"] = {"reason": REASON, "cleared": cleared, "raw_exit_status": raw_exit_status}
    status = raw_exit_status
    if errors or retained:
        status = status or 1
    elif raw_exit_status == 1:
        status = 0 if cleared and len(cleared) == len(results) else 1
    return Correction(effective, status)


def _position(value: JsonValue) -> _Position:
    if not _table(value):
        message = "invalid finding position"
        raise ValueError(message)
    line, column = value.get("line"), value.get("col")
    if type(line) is not int or type(column) is not int or line < 1 or column < 1:
        message = "invalid finding position"
        raise ValueError(message)
    return _Position(line, column)


def _safe_finding(finding: dict[str, JsonValue], root: Path, start: _Position, end: _Position) -> bool:
    raw_path = finding.get("path")
    if not isinstance(raw_path, str) or not raw_path:
        message = "invalid finding path"
        raise ValueError(message)
    path = (root / raw_path).resolve()
    if not path.is_relative_to(root) or path.suffix != ".py":
        message = "finding source outside Python source root"
        raise ValueError(message)
    if path.stat().st_size > 2 * 1024 * 1024:
        message = "finding source exceeds size limit"
        raise ValueError(message)
    return _Proof(path.read_text(encoding="utf-8")).safe(start, end)


def _run(paths: _Artifacts) -> int:
    if paths.input_path.resolve() == paths.output_path.resolve() or (
        paths.input_path.exists() and paths.output_path.exists() and paths.input_path.samefile(paths.output_path)
    ):
        return paths.raw_exit_status or 2
    correction = correct(
        paths.input_path.read_text(encoding="utf-8"),
        source_root=paths.source_root,
        raw_exit_status=paths.raw_exit_status,
    )
    paths.output_path.write_text(json.dumps(correction.report, indent=2) + "\n", encoding="utf-8")
    return correction.exit_status


def _status(value: int) -> int:
    if type(value) is not int or not 0 <= value <= _MAX_EXIT_STATUS:
        message = "invalid raw scanner exit status"
        raise ValueError(message)
    return value


def main() -> None:
    typer.run(_command)


def _command(
    *,
    input_path: Annotated[Path, typer.Option("--input")],
    output_path: Annotated[Path, typer.Option("--output")],
    source_root: Annotated[Path, typer.Option("--source-root")],
    raw_exit_status: Annotated[int, typer.Option("--raw-exit-status", min=0, max=_MAX_EXIT_STATUS)],
) -> None:
    status = raw_exit_status
    try:
        status = _run(_Artifacts(input_path, output_path, source_root, raw_exit_status))
    except OSError, ValueError, SyntaxError, RecursionError:
        sys.stderr.write("SQL composition correction failed; raw scanner result remains authoritative.\n")
        raise typer.Exit(status or 2) from None
    raise typer.Exit(status)


class _JsonReport(RootModel[dict[str, JsonValue]]):
    pass


def _decode_report(payload: str) -> dict[str, JsonValue]:
    decode: Callable[..., JsonValue] = json.loads
    value = decode(payload, object_pairs_hook=_unique, parse_constant=_constant, parse_float=_finite_float)
    return _JsonReport.model_validate(value, strict=True).root


def _unique(pairs: list[tuple[str, JsonValue]]) -> dict[str, JsonValue]:
    result: dict[str, JsonValue] = {}
    for key, value in pairs:
        if key in result:
            message = "duplicate JSON key"
            raise ValueError(message)
        result[key] = value
    return result


def _constant(_value: str) -> None:
    message = "non-finite JSON constant"
    raise ValueError(message)


def _finite_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        message = "non-finite JSON number"
        raise ValueError(message)
    return number


if __name__ == "__main__":
    main()
