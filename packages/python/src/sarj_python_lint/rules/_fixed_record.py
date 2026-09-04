from __future__ import annotations

import ast

from sarj_python_lint.rules._ast_index import children


_RECORD_MUTATOR_METHODS = frozenset({"clear", "pop", "popitem", "setdefault", "update"})


def builds_fixed_record(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    returned: list[ast.expr] = []
    record_names = {
        target.id
        for current in _owned_nodes(node)
        if isinstance(current, ast.Assign) and _is_record_literal(current.value)
        for target in current.targets
        if isinstance(target, ast.Name)
    }
    record_names.update(
        current.target.id
        for current in _owned_nodes(node)
        if isinstance(current, ast.AnnAssign)
        and isinstance(current.target, ast.Name)
        and current.value is not None
        and _is_record_literal(current.value)
    )
    invalidated_names: set[str] = set()
    aliases: dict[str, str] = {}
    stack: list[ast.AST] = list(node.body)
    while stack:
        current = stack.pop()
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        if isinstance(current, ast.Return) and current.value is not None:
            returned.append(current.value)
        elif isinstance(current, ast.Assign) and _is_record_literal(current.value):
            for target in current.targets:
                if isinstance(target, ast.Subscript):
                    invalidated_names.update(_mutated_record_roots(target))
        elif isinstance(current, ast.Assign):
            if isinstance(current.value, ast.Name):
                for target in current.targets:
                    if not isinstance(target, ast.Name):
                        continue
                    if target.id in record_names:
                        invalidated_names.add(target.id)
                    else:
                        aliases[target.id] = current.value.id
            else:
                invalidated_names.update(
                    target.id for target in current.targets if isinstance(target, ast.Name)
                )
            for target in current.targets:
                if isinstance(target, ast.Subscript):
                    invalidated_names.update(_mutated_record_roots(target))
        elif (
            isinstance(current, ast.AnnAssign)
            and isinstance(current.target, ast.Name)
            and current.value is not None
            and _is_record_literal(current.value)
        ):
            pass
        elif (
            isinstance(current, ast.AnnAssign)
            and isinstance(current.target, ast.Name)
            and isinstance(current.value, ast.Name)
        ):
            if current.target.id in record_names:
                invalidated_names.add(current.target.id)
            else:
                aliases[current.target.id] = current.value.id
        elif isinstance(current, (ast.AnnAssign, ast.AugAssign)):
            invalidated_names.update(_mutated_record_roots(current.target))
        elif isinstance(current, ast.Delete):
            for target in current.targets:
                invalidated_names.update(_mutated_record_roots(target))
        elif (
            isinstance(current, ast.Call)
            and isinstance(current.func, ast.Attribute)
            and current.func.attr in _RECORD_MUTATOR_METHODS
            and isinstance(current.func.value, ast.Name)
        ):
            invalidated_names.add(current.func.value.id)
        elif isinstance(current, ast.Call):
            invalidated_names.update(
                argument.id
                for argument in (*current.args, *(keyword.value for keyword in current.keywords))
                if isinstance(argument, ast.Name)
            )
        stack.extend(children(current))

    changed = True
    while changed:
        changed = False
        for alias, original in aliases.items():
            if alias in invalidated_names and original not in invalidated_names:
                invalidated_names.add(original)
                changed = True
            if original in invalidated_names and alias not in invalidated_names:
                invalidated_names.add(alias)
                changed = True

    def original_name(name: str) -> str:
        seen: set[str] = set()
        while name in aliases and name not in seen:
            seen.add(name)
            name = aliases[name]
        return name

    intact_record_names = record_names - invalidated_names
    if any(
        isinstance(value, ast.Name) and original_name(value.id) in record_names & invalidated_names
        for value in returned
    ):
        return False
    return any(
        _is_record_literal(value)
        or (isinstance(value, ast.Name) and original_name(value.id) in intact_record_names)
        for value in returned
    )


def _owned_nodes(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.AST]:
    owned: list[ast.AST] = []
    stack: list[ast.AST] = list(node.body)
    while stack:
        current = stack.pop()
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        owned.append(current)
        stack.extend(children(current))
    return owned


def _is_record_literal(node: ast.expr) -> bool:
    if isinstance(node, ast.List):
        return bool(node.elts) and all(_is_record_literal(element) for element in node.elts)
    if isinstance(node, ast.ListComp):
        return _is_record_literal(node.elt)
    if not isinstance(node, ast.Dict):
        return False
    return bool(node.keys) and all(
        isinstance(key, ast.Constant) and isinstance(key.value, str) for key in node.keys
    )


def _mutated_record_roots(target: ast.AST) -> set[str]:
    while isinstance(target, ast.Subscript):
        target = target.value
    return {target.id} if isinstance(target, ast.Name) else set()
