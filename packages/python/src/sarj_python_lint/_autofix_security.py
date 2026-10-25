from __future__ import annotations

import ast
from dataclasses import dataclass
from io import StringIO
import re
import tokenize
from typing import TYPE_CHECKING

from sarj_rule_contracts import TextEdit

from sarj_python_lint._autofix_parameters import ParameterFixes
from sarj_python_lint.rules._resource_provenance import ResourceProvenance, builtin_namespace_untouched


if TYPE_CHECKING:
    from pathlib import Path

    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rule_base import Diagnostic


_GUARDED_OWNER_STATEMENTS = 2
_OPERAND_COUNT = 2
_CAPTURE_COUNT = 3
_MAX_IMPORT_ANCESTORS = 24


@dataclass(frozen=True, slots=True)
class _Captures:
    compare: ast.arg
    type_check: ast.arg
    bytes_type: ast.arg
    compare_default: ast.Name


@dataclass(frozen=True, slots=True)
class _CaptureDefault:
    argument: ast.arg
    value: ast.Name


@dataclass(frozen=True, slots=True)
class _GuardedOwner:
    owner: ast.FunctionDef
    guard: ast.If


@dataclass(frozen=True, slots=True)
class _BytesCheck:
    call: ast.Call
    name: str


@dataclass(frozen=True, slots=True)
class _CapturedNamespace:
    alias: ast.alias
    provenance: ResourceProvenance
    captures: _Captures
    guards: list[ast.Call]


def fixes(context: PythonFileContext, diagnostic: Diagnostic) -> list[TextEdit]:
    if diagnostic.code != "SARJ011" or context.tree is None or context.generated or context.path.suffix == ".pyi":
        return []
    for comparison in context.nodes(ast.Compare):
        if (edit := _comparison_edit(context, diagnostic, comparison)) is not None:
            return [edit]
    return []


def _comparison_edit(context: PythonFileContext, diagnostic: Diagnostic, comparison: ast.Compare) -> TextEdit | None:
    operands = _comparison_operands(diagnostic, comparison)
    if operands is None:
        return None
    names = frozenset(operand.id for operand in operands)
    guarded = _guarded_owner(context, comparison, names)
    if guarded is None:
        return None
    owner, guard = guarded.owner, guarded.guard
    captures = _captured_parameters(context, owner)
    if captures is None or not names.isdisjoint(
        (captures.compare.arg, captures.type_check.arg, captures.bytes_type.arg)
    ):
        return None
    guards = _bytes_guard(guard, names, captures)
    if guards is None or not _canonical_captures(context, owner, guards, captures):
        return None
    parameters = ParameterFixes(context)
    calls = parameters.closed_calls(owner)
    if not calls or not _forwarded_parameter_call(context, owner, calls):
        return None
    if any(
        token.type == tokenize.COMMENT and owner.lineno <= token.start[0] <= (owner.end_lineno or owner.lineno)
        for token in parameters.tokens
    ):
        return None
    return _comparison_replacement(context, comparison, captures.compare, operands)


def _captured_parameters(context: PythonFileContext, owner: ast.FunctionDef) -> _Captures | None:
    arguments = owner.args
    if arguments.posonlyargs or arguments.kwonlyargs or arguments.vararg is not None or arguments.kwarg is not None:
        return None
    if (
        len(arguments.args) != _OPERAND_COUNT + _CAPTURE_COUNT
        or len(arguments.defaults) != _CAPTURE_COUNT
        or owner.returns is not None
    ):
        return None
    alias = _canonical_import(context)
    if alias is None:
        return None
    name = alias.asname or alias.name
    defaults: dict[str, _CaptureDefault] = {}
    for argument, default in zip(arguments.args[-_CAPTURE_COUNT:], arguments.defaults, strict=True):
        if argument.annotation is not None or not isinstance(default, ast.Name) or default.id in defaults:
            return None
        defaults[default.id] = _CaptureDefault(argument, default)
    if set(defaults) != {name, "type", "bytes"} or not set(defaults).isdisjoint(arg.arg for arg in arguments.args):
        return None
    return _Captures(
        defaults[name].argument, defaults["type"].argument, defaults["bytes"].argument, defaults[name].value
    )


def _comparison_operands(diagnostic: Diagnostic, comparison: ast.Compare) -> tuple[ast.Name, ast.Name] | None:
    if (
        comparison.lineno != diagnostic.line
        or comparison.col_offset + 1 != diagnostic.col
        or len(comparison.ops) != 1
        or len(comparison.comparators) != 1
    ):
        return None
    if (
        not isinstance(comparison.ops[0], (ast.Eq, ast.NotEq))
        or not isinstance(comparison.left, ast.Name)
        or not isinstance(comparison.comparators[0], ast.Name)
    ):
        return None
    return comparison.left, comparison.comparators[0]


def _guarded_owner(
    context: PythonFileContext, comparison: ast.Compare, operands: frozenset[str]
) -> _GuardedOwner | None:
    returned = context.parents.get(comparison)
    if len(operands) != _OPERAND_COUNT or not isinstance(returned, ast.Return) or returned.value is not comparison:
        return None
    guard = context.parents.get(returned)
    if not isinstance(guard, ast.If) or guard.body != [returned] or guard.orelse:
        return None
    owner = context.parents.get(guard)
    if not isinstance(owner, ast.FunctionDef) or not _local_operands(owner, guard, operands):
        return None
    return _GuardedOwner(owner, guard)


def _local_operands(owner: ast.FunctionDef, guard: ast.If, operands: frozenset[str]) -> bool:
    if len(owner.body) != _GUARDED_OWNER_STATEMENTS or owner.body[0] is not guard:
        return False
    fallback = owner.body[1]
    if (
        not isinstance(fallback, ast.Return)
        or not isinstance(fallback.value, ast.Constant)
        or fallback.value.value is not False
    ):
        return False
    required = owner.args.args[:-_CAPTURE_COUNT]
    return len(required) == _OPERAND_COUNT and {argument.arg for argument in required} == operands


def _forwarded_parameter_call(context: PythonFileContext, owner: ast.FunctionDef, calls: list[ast.Call]) -> bool:
    parent = _forwarding_parent(context, owner, calls)
    if parent is None or not _required_parameters(parent):
        return False
    if any(argument.annotation is not None for argument in owner.args.args):
        return False
    call = calls[0]
    if call.keywords or len(call.args) != _OPERAND_COUNT:
        return False
    return all(
        isinstance(value, ast.Name) and value.id == argument.arg
        for value, argument in zip(call.args, parent.args.args, strict=True)
    )


def _forwarding_parent(
    context: PythonFileContext, owner: ast.FunctionDef, calls: list[ast.Call]
) -> ast.FunctionDef | None:
    parent = context.parents.get(owner)
    if not isinstance(parent, ast.FunctionDef) or len(parent.body) != _GUARDED_OWNER_STATEMENTS or len(calls) != 1:
        return None
    returned = parent.body[1]
    if parent.body[0] is not owner or not isinstance(returned, ast.Return) or returned.value is not calls[0]:
        return None
    return parent


def _required_parameters(parent: ast.FunctionDef) -> bool:
    arguments = parent.args
    if arguments.posonlyargs or arguments.kwonlyargs or arguments.vararg is not None or arguments.kwarg is not None:
        return False
    if len(arguments.args) != _OPERAND_COUNT or arguments.defaults or parent.returns is not None:
        return False
    return not any(argument.annotation is not None for argument in arguments.args)


def _bytes_guard(guard: ast.If, operands: frozenset[str], captures: _Captures) -> list[ast.Call] | None:
    test = guard.test
    if not isinstance(test, ast.BoolOp) or not isinstance(test.op, ast.And) or len(test.values) != _OPERAND_COUNT:
        return None
    calls: list[ast.Call] = []
    names: set[str] = set()
    for value in test.values:
        if (checked := _exact_bytes_call(value, captures)) is None:
            return None
        calls.append(checked.call)
        names.add(checked.name)
    return calls if names == operands else None


def _exact_bytes_call(value: ast.expr, captures: _Captures) -> _BytesCheck | None:
    if not isinstance(value, ast.Compare) or len(value.ops) != 1 or len(value.comparators) != 1:
        return None
    comparator = value.comparators[0]
    if (
        not isinstance(value.ops[0], ast.Is)
        or not isinstance(comparator, ast.Name)
        or comparator.id != captures.bytes_type.arg
    ):
        return None
    call = value.left
    if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Name) or call.func.id != captures.type_check.arg:
        return None
    if len(call.args) != 1 or call.keywords or not isinstance(call.args[0], ast.Name):
        return None
    return _BytesCheck(call, call.args[0].id)


def _canonical_captures(
    context: PythonFileContext, owner: ast.FunctionDef, guards: list[ast.Call], captures: _Captures
) -> bool:
    alias = _canonical_import(context)
    if alias is None or _local_hmac(context):
        return False
    provenance = ResourceProvenance(context, require_static_namespace=True)
    if not builtin_namespace_untouched(context) or any(
        not context.imports.builtin_is_unshadowed(builtin) for builtin in ("type", "bytes")
    ):
        return False
    if not _same_import_binding(provenance, captures.compare_default, alias):
        return False
    namespace = _CapturedNamespace(alias, provenance, captures, guards)
    return _captured_namespace_untouched(context, owner, namespace)


def _captured_namespace_untouched(
    context: PythonFileContext, owner: ast.FunctionDef, namespace: _CapturedNamespace
) -> bool:
    name = namespace.alias.asname or namespace.alias.name
    ancestors: set[ast.AST] = {owner}
    ancestor = context.parents.get(owner)
    while ancestor is not None:
        ancestors.add(ancestor)
        ancestor = context.parents.get(ancestor)
    actual_read = False
    for node in context.nodes(ast.AST):
        if not _namespace_node_safe(node, ancestors) or not _allowed_call(node, namespace.guards, name, owner.name):
            return False
        if isinstance(node, ast.Name) and not _captured_read_safe(context, node, namespace.captures, namespace.guards):
            return False
        if isinstance(node, ast.Name) and node.id == name:
            if node is namespace.captures.compare_default:
                continue
            if not _canonical_value_read(context, node, namespace.provenance, namespace.alias):
                return False
            actual_read = True
    return actual_read


def _captured_read_safe(
    context: PythonFileContext, node: ast.Name, captures: _Captures, guards: list[ast.Call]
) -> bool:
    if node.id == captures.compare.arg:
        return False
    if node.id == captures.type_check.arg:
        return any(call.func is node for call in guards)
    if node.id == captures.bytes_type.arg:
        parent = context.parents.get(node)
        return isinstance(parent, ast.Compare) and parent.left in guards and parent.comparators == [node]
    return True


def _canonical_import(context: PythonFileContext) -> ast.alias | None:
    tree = context.tree
    if tree is None:
        return None
    canonical: list[ast.alias] = []
    for statement in context.nodes(ast.Import, ast.ImportFrom):
        if not isinstance(statement, ast.ImportFrom) or statement not in tree.body or statement.level != 0:
            return None
        if statement.module == "__future__" and all(alias.name == "annotations" for alias in statement.names):
            continue
        if statement.module != "hmac" or len(statement.names) != 1 or statement.names[0].name != "compare_digest":
            return None
        canonical.extend(statement.names)
    return canonical[0] if len(canonical) == 1 else None


def _local_hmac(context: PythonFileContext) -> bool:
    root = context.session.first_party.project_root(context.path)
    if root is None:
        return False
    try:
        return _contains_local_hmac(context.path, root)
    except OSError:
        return True


def _contains_local_hmac(path: Path, root: Path) -> bool:
    for base in list(path.absolute().parents)[:_MAX_IMPORT_ANCESTORS]:
        if not base.is_relative_to(root):
            break
        candidates = [base]
        if (base / "pyproject.toml").exists():
            candidates.append(base / "src")
        if any((candidate / "hmac.py").exists() or (candidate / "hmac").exists() for candidate in candidates):
            return True
        if base == root:
            break
    return False


def _namespace_node_safe(node: ast.AST, ancestors: set[ast.AST]) -> bool:
    if isinstance(
        node,
        (
            ast.AsyncFunctionDef,
            ast.ClassDef,
            ast.Lambda,
            ast.TypeAlias,
            ast.Global,
            ast.Nonlocal,
            ast.Yield,
            ast.YieldFrom,
            ast.GeneratorExp,
        ),
    ):
        return False
    if isinstance(node, ast.FunctionDef) and node not in ancestors:
        return False
    if isinstance(node, (ast.Attribute, ast.Subscript)) and not isinstance(node.ctx, ast.Load):
        return False
    return not isinstance(node, ast.Attribute) or not node.attr.startswith("__")


def _canonical_value_read(
    context: PythonFileContext, node: ast.Name, provenance: ResourceProvenance, alias: ast.alias
) -> bool:
    call = context.parents.get(node)
    if not isinstance(node.ctx, ast.Load) or not isinstance(call, ast.Call) or call.func is not node:
        return False
    if len(call.args) != _OPERAND_COUNT or call.keywords:
        return False
    return all(isinstance(argument, ast.Constant) and isinstance(argument.value, bytes) for argument in call.args) and (
        _same_import_binding(provenance, node, alias)
    )


def _same_import_binding(provenance: ResourceProvenance, node: ast.Name, alias: ast.alias) -> bool:
    return provenance.binding(node.id, node) is alias and provenance.runtime_binding(node.id, node) is alias


def _allowed_call(node: ast.AST, guards: list[ast.Call], alias: str, owner: str) -> bool:
    if not isinstance(node, ast.Call) or node in guards:
        return True
    return isinstance(node.func, ast.Name) and node.func.id in {alias, owner}


def _comparison_replacement(
    context: PythonFileContext, comparison: ast.Compare, alias: ast.arg, operands: tuple[ast.Name, ast.Name]
) -> TextEdit | None:
    start = _offset(context.source, comparison.lineno, comparison.col_offset)
    end = _offset(context.source, comparison.end_lineno or comparison.lineno, comparison.end_col_offset or 0)
    alias_text = ast.get_source_segment(context.source, alias)
    left, right = (ast.get_source_segment(context.source, operand) for operand in operands)
    if alias_text is None or left is None or right is None:
        return None
    prefix = "not " if isinstance(comparison.ops[0], ast.NotEq) else ""
    newlines = "".join(re.findall(r"\r\n|\r|\n", context.source[start:end]))
    return TextEdit(start, end, f"{prefix}{alias_text}({left}, {right}){newlines}")


def _offset(source: str, line: int, column: int) -> int:
    lines = StringIO(source, newline="").readlines()
    return sum(map(len, lines[: line - 1])) + len(lines[line - 1].encode("utf-8")[:column].decode("utf-8"))
