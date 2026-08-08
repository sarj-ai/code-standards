"""SARJ401 — Frozen Pydantic after-validators must not assign declared fields.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_no_frozen_after_validator_field_write.py
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING, final, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none
from sarj_python_lint.rules._imports import ImportIndex
from sarj_python_lint.rules._paths import is_generated, is_test_path


if TYPE_CHECKING:
    from pathlib import Path


_PYDANTIC_SOURCES = frozenset({"pydantic"})
_PYDANTIC_BASE_MODEL_SOURCES = frozenset({"pydantic", "pydantic.main"})
_PYDANTIC_CONFIG_SOURCES = frozenset({"pydantic", "pydantic.config"})
_TYPING_SOURCES = frozenset({"typing", "typing_extensions"})


@final
class NoFrozenAfterValidatorFieldWrite(Rule):
    id = "no-frozen-after-validator-field-write"
    code = "SARJ401"
    description = "Frozen Pydantic after-validators cannot directly assign declared model fields."

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if is_test_path(path) or is_generated(path, source):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        imports = ImportIndex.from_tree(tree)
        diagnostics: list[Diagnostic] = []
        for class_node in (node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)):
            if not _is_frozen_direct_model(class_node, imports):
                continue
            fields = _direct_public_fields(class_node, imports)
            if not fields:
                continue
            for statement in class_node.body:
                if not isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                receiver = _after_validator_receiver(statement, imports)
                if receiver is None:
                    continue
                diagnostics.extend(
                    Diagnostic(
                        path=path,
                        line=target.lineno,
                        col=target.col_offset + 1,
                        code=self.code,
                        message=(
                            f"Frozen model `{class_node.name}` assigns declared field `{target.attr}` in an "
                            "after-validator; validate without mutation or compute the value before freezing."
                        ),
                    )
                    for target in _declared_field_writes(statement, receiver, fields)
                )
        return diagnostics


def _is_frozen_direct_model(node: ast.ClassDef, imports: ImportIndex) -> bool:
    if len(node.bases) != 1 or not imports.resolves(
        node.bases[0], sources=_PYDANTIC_BASE_MODEL_SOURCES, symbol="BaseModel"
    ):
        return False
    configs: list[ast.expr] = []
    for statement in node.body:
        match statement:
            case ast.Assign(targets=[ast.Name(id="model_config")]) | ast.AnnAssign(target=ast.Name(id="model_config")):
                if isinstance(statement.value, ast.expr):
                    configs.append(statement.value)
            case _:
                pass
    if len(configs) != 1 or not isinstance(configs[0], ast.Call):
        return False
    call = configs[0]
    return imports.resolves(call.func, sources=_PYDANTIC_CONFIG_SOURCES, symbol="ConfigDict") and any(
        keyword.arg == "frozen" and isinstance(keyword.value, ast.Constant) and keyword.value.value is True
        for keyword in call.keywords
    )


def _direct_public_fields(node: ast.ClassDef, imports: ImportIndex) -> frozenset[str]:
    fields: set[str] = set()
    for statement in node.body:
        if not isinstance(statement, ast.AnnAssign) or not isinstance(statement.target, ast.Name):
            continue
        name = statement.target.id
        if name.startswith("_") or name == "model_config" or _is_class_only_annotation(statement.annotation, imports):
            continue
        fields.add(name)
    return frozenset(fields)


def _is_class_only_annotation(node: ast.expr, imports: ImportIndex) -> bool:
    return isinstance(node, ast.Subscript) and any(
        imports.resolves(node.value, sources=_TYPING_SOURCES, symbol=symbol) for symbol in ("ClassVar", "Final")
    )


def _after_validator_receiver(node: ast.FunctionDef | ast.AsyncFunctionDef, imports: ImportIndex) -> str | None:
    if any(_decorator_name(decorator) in {"classmethod", "staticmethod"} for decorator in node.decorator_list):
        return None
    is_after = False
    for decorator in node.decorator_list:
        if not isinstance(decorator, ast.Call) or not imports.resolves(
            decorator.func, sources=_PYDANTIC_SOURCES, symbol="model_validator"
        ):
            continue
        is_after = any(
            keyword.arg == "mode" and isinstance(keyword.value, ast.Constant) and keyword.value.value == "after"
            for keyword in decorator.keywords
        )
    if not is_after:
        return None
    positional = (*node.args.posonlyargs, *node.args.args)
    return positional[0].arg if positional else None


def _decorator_name(node: ast.expr) -> str | None:
    target = node.func if isinstance(node, ast.Call) else node
    match target:
        case ast.Name(id=name) | ast.Attribute(attr=name):
            return name
        case _:
            return None


def _declared_field_writes(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    receiver: str,
    fields: frozenset[str],
) -> tuple[ast.Attribute, ...]:
    writes: list[ast.Attribute] = []
    stack: list[ast.AST] = list(node.body)
    while stack:
        current = stack.pop()
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        targets: tuple[ast.expr, ...] = ()
        match current:
            case ast.Assign():
                targets = tuple(current.targets)
            case ast.AnnAssign() | ast.AugAssign():
                targets = (current.target,)
            case _:
                pass
        for target in targets:
            writes.extend(_matching_attributes(target, receiver, fields))
        stack.extend(ast.iter_child_nodes(current))
    return tuple(sorted(writes, key=lambda target: (target.lineno, target.col_offset)))


def _matching_attributes(node: ast.expr, receiver: str, fields: frozenset[str]) -> list[ast.Attribute]:
    if (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == receiver
        and node.attr in fields
    ):
        return [node]
    if isinstance(node, (ast.Tuple, ast.List)):
        return [match for element in node.elts for match in _matching_attributes(element, receiver, fields)]
    return []
