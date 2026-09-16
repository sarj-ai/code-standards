from __future__ import annotations

import ast

from sarj_python_lint.rules._ast_index import children


_RECORD_MUTATOR_METHODS = frozenset({"clear", "pop", "popitem", "setdefault", "update"})


def builds_fixed_record(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    state = _RecordMutations(_record_names(node))
    stack: list[ast.AST] = list(node.body)
    while stack:
        current = stack.pop()
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        state.read(current)
        stack.extend(children(current))
    state.propagate_alias_mutations()
    return state.returns_intact_record()


def _record_names(node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    names = {
        target.id
        for current in _owned_nodes(node)
        if isinstance(current, ast.Assign) and _is_record_literal(current.value)
        for target in current.targets
        if isinstance(target, ast.Name)
    }
    names.update(
        current.target.id
        for current in _owned_nodes(node)
        if isinstance(current, ast.AnnAssign)
        and isinstance(current.target, ast.Name)
        and current.value is not None
        and _is_record_literal(current.value)
    )
    return names


class _RecordMutations:
    def __init__(self, record_names: set[str]) -> None:
        self.record_names: set[str] = record_names
        self.returned: list[ast.expr] = []
        self.invalidated_names: set[str] = set()
        self.aliases: dict[str, str] = {}

    def read(self, current: ast.AST) -> None:
        match current:
            case ast.Return(value=value) if value is not None:
                self.returned.append(value)
            case ast.Assign():
                self.read_assignment(current)
            case ast.AnnAssign():
                self.read_annotated_assignment(current)
            case ast.AugAssign():
                self.invalidated_names.update(_mutated_record_roots(current.target))
            case ast.Delete():
                for target in current.targets:
                    self.invalidated_names.update(_mutated_record_roots(target))
            case ast.Call():
                self.read_call(current)
            case _:
                pass

    def read_assignment(self, current: ast.Assign) -> None:
        if not _is_record_literal(current.value):
            if isinstance(current.value, ast.Name):
                for target in current.targets:
                    if not isinstance(target, ast.Name):
                        continue
                    self.record_alias(target.id, current.value.id)
            else:
                self.invalidated_names.update(target.id for target in current.targets if isinstance(target, ast.Name))
        self.invalidate_subscript_targets(current.targets)

    def invalidate_subscript_targets(self, targets: list[ast.expr]) -> None:
        for target in targets:
            if isinstance(target, ast.Subscript):
                self.invalidated_names.update(_mutated_record_roots(target))

    def read_annotated_assignment(self, current: ast.AnnAssign) -> None:
        if isinstance(current.target, ast.Name) and current.value is not None and _is_record_literal(current.value):
            return
        if isinstance(current.target, ast.Name) and isinstance(current.value, ast.Name):
            self.record_alias(current.target.id, current.value.id)
            return
        self.invalidated_names.update(_mutated_record_roots(current.target))

    def record_alias(self, target: str, original: str) -> None:
        if target in self.record_names:
            self.invalidated_names.add(target)
        else:
            self.aliases[target] = original

    def read_call(self, current: ast.Call) -> None:
        if (
            isinstance(current.func, ast.Attribute)
            and current.func.attr in _RECORD_MUTATOR_METHODS
            and isinstance(current.func.value, ast.Name)
        ):
            self.invalidated_names.add(current.func.value.id)
        else:
            self.invalidated_names.update(
                argument.id
                for argument in (*current.args, *(keyword.value for keyword in current.keywords))
                if isinstance(argument, ast.Name)
            )

    def propagate_alias_mutations(self) -> None:
        changed = True
        while changed:
            changed = False
            for alias, original in self.aliases.items():
                if alias in self.invalidated_names and original not in self.invalidated_names:
                    self.invalidated_names.add(original)
                    changed = True
                if original in self.invalidated_names and alias not in self.invalidated_names:
                    self.invalidated_names.add(alias)
                    changed = True

    def original_name(self, name: str) -> str:
        seen: set[str] = set()
        while name in self.aliases and name not in seen:
            seen.add(name)
            name = self.aliases[name]
        return name

    def returns_intact_record(self) -> bool:
        intact_record_names = self.record_names - self.invalidated_names
        if any(
            isinstance(value, ast.Name) and self.original_name(value.id) in self.record_names & self.invalidated_names
            for value in self.returned
        ):
            return False
        return any(
            _is_record_literal(value)
            or (isinstance(value, ast.Name) and self.original_name(value.id) in intact_record_names)
            for value in self.returned
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
    return bool(node.keys) and all(isinstance(key, ast.Constant) and isinstance(key.value, str) for key in node.keys)


def _mutated_record_roots(target: ast.AST) -> set[str]:
    while isinstance(target, ast.Subscript):
        target = target.value
    return {target.id} if isinstance(target, ast.Name) else set()
