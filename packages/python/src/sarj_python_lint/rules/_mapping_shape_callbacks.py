from __future__ import annotations

import ast
from typing import TYPE_CHECKING, final


if TYPE_CHECKING:
    from collections.abc import Callable

    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rules._resource_provenance import ResourceProvenance


type _Function = ast.FunctionDef | ast.AsyncFunctionDef
_VALIDATORS = frozenset(
    {
        "pydantic.model_validator",
        "pydantic.field_validator",
        "pydantic.functional_validators.model_validator",
        "pydantic.functional_validators.field_validator",
    }
)
_DISCRIMINATORS = frozenset({"pydantic.Discriminator", "pydantic.types.Discriminator"})
_RAW_METADATA = frozenset(
    {
        "pydantic.BeforeValidator",
        "pydantic.WrapValidator",
        "pydantic.functional_validators.BeforeValidator",
        "pydantic.functional_validators.WrapValidator",
    }
)
_MAX_DEPTH = 32


@final
class RawMappingCallbacks:
    def __init__(
        self,
        context: PythonFileContext,
        provenance: ResourceProvenance,
        qualified: Callable[[ast.expr, ast.AST], str | None],
        builtin: Callable[[ast.expr, str, ast.AST], bool],
        shadowed: Callable[[str, ast.AST], bool],
    ) -> None:
        self.context = context
        self.provenance = provenance
        self.qualified = qualified
        self.builtin = builtin
        self.shadowed = shadowed
        self.ownership: dict[_Function, bool] = {}
        self.callbacks = {
            binding
            for call in context.nodes(ast.Call)
            if (origin := qualified(call.func, call)) in _DISCRIMINATORS | _RAW_METADATA
            if (argument := _callback_argument(call, origin)) is not None
            if (binding := self.callback(argument)) is not None
        }

    def callback(self, node: ast.expr, *, seen: frozenset[ast.AST] = frozenset()) -> _Function | None:
        if len(seen) >= _MAX_DEPTH:
            return None
        if isinstance(node, ast.Call):
            return (
                self._partial(node, seen)
                if self.qualified(node.func, node) == "functools.partial"
                else self._method(node, "__call__", seen)
            )
        if isinstance(node, ast.Attribute):
            return self._method(node.value, node.attr, seen)
        if not isinstance(node, ast.Name) or not self._stable(node.id) or self.shadowed(node.id, node):
            return None
        binding = self.provenance.binding(node.id, node)
        if isinstance(binding, ast.FunctionDef | ast.AsyncFunctionDef):
            return binding if not binding.decorator_list else None
        if not isinstance(binding, ast.Name) or binding in seen:
            return None
        value = self.provenance.assignment_value(binding, node)
        return self.callback(value, seen=seen | {binding}) if value is not None else None

    def _partial(self, node: ast.Call, seen: frozenset[ast.AST]) -> _Function | None:
        if len(node.args) != 1 or isinstance(node.args[0], ast.Starred):
            return None
        callback = self.callback(node.args[0], seen=seen | {node})
        if callback is None or not (callback.args.posonlyargs or callback.args.args):
            return None
        configuration = {argument.arg for argument in callback.args.kwonlyargs}
        return callback if all(keyword.arg in configuration for keyword in node.keywords) else None

    def _stable(self, name: str) -> bool:
        return name not in self.provenance.mutated | self.provenance.external_bindings

    def _method(self, node: ast.expr, name: str, seen: frozenset[ast.AST]) -> ast.FunctionDef | None:
        owner = self._owner(node, seen)
        if owner is None:
            return None
        declaration, on_class = owner
        if declaration.bases or declaration.keywords or declaration.type_params:
            return None
        if (
            not isinstance(self.context.parents.get(declaration), ast.Module | ast.FunctionDef | ast.AsyncFunctionDef)
            or not self._stable(declaration.name)
            or any(
                self.qualified(decorator, decorator) not in {"typing.final", "typing_extensions.final"}
                for decorator in declaration.decorator_list
            )
        ):
            return None
        method = _plain_method(declaration, name)
        if method is None:
            return None
        if not method.decorator_list:
            return method if not on_class else None
        if len(method.decorator_list) != 1:
            return None
        decorator = method.decorator_list[0]
        return (
            method
            if any(self.builtin(decorator, kind, decorator) for kind in ("staticmethod", "classmethod"))
            else None
        )

    def _owner(self, node: ast.expr, seen: frozenset[ast.AST]) -> tuple[ast.ClassDef, bool] | None:
        if len(seen) >= _MAX_DEPTH:
            return None
        if isinstance(node, ast.Call):
            if node.args or node.keywords or not isinstance(node.func, ast.Name):
                return None
            owner = self._owner(node.func, seen | {node})
            return (owner[0], False) if owner is not None and owner[1] else None
        if not isinstance(node, ast.Name) or not self._stable(node.id) or self.shadowed(node.id, node):
            return None
        binding = self.provenance.binding(node.id, node)
        if isinstance(binding, ast.ClassDef):
            return binding, True
        if not isinstance(binding, ast.Name) or binding in seen:
            return None
        value = self.provenance.assignment_value(binding, node)
        return self._owner(value, seen | {binding}) if value is not None else None

    def owns(self, node: ast.AST) -> bool:
        function = self._function(node)
        return function is not None and self._owned(function, frozenset())

    def _function(self, node: ast.AST) -> _Function | None:
        current = self.context.parents.get(node)
        while current is not None:
            if isinstance(current, ast.FunctionDef | ast.AsyncFunctionDef):
                return current
            if isinstance(current, ast.ClassDef | ast.Lambda):
                return None
            current = self.context.parents.get(current)
        return None

    def _owned(self, function: _Function, seen: frozenset[ast.AST]) -> bool:
        if function in self.ownership:
            return self.ownership[function]
        if function in seen or len(seen) >= _MAX_DEPTH:
            return False
        result = self._raw_validator(function)
        if not result:
            owner = self._function(function)
            result = owner is not None and self._owned(owner, seen | {function}) and self._local_helper(function, owner)
        self.ownership[function] = result
        return result

    def _local_helper(self, function: _Function, owner: _Function) -> bool:
        if (
            function.decorator_list
            or self.context.parents.get(function) is not owner
            or not self._stable(function.name)
        ):
            return False
        reads = [
            read
            for read in self.provenance.reads.get(function.name, ())
            if self.provenance.binding(function.name, read) is function
        ]
        return bool(reads) and all(
            isinstance(parent := self.context.parents.get(read), ast.Call)
            and parent.func is read
            and self._function(read) in {owner, function}
            for read in reads
        )

    def _raw_validator(self, function: _Function) -> bool:
        if function in self.callbacks:
            return True
        return any(
            isinstance(decorator, ast.Call)
            and self.qualified(decorator.func, decorator) in _VALIDATORS
            and any(
                keyword.arg == "mode" and self._mode(keyword.value) in {"before", "wrap"}
                for keyword in decorator.keywords
            )
            for decorator in function.decorator_list
        )

    def _mode(self, node: ast.expr, *, seen: frozenset[ast.AST] = frozenset()) -> str | None:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if (
            len(seen) >= _MAX_DEPTH
            or not isinstance(node, ast.Name)
            or not self._stable(node.id)
            or self.shadowed(node.id, node)
        ):
            return None
        binding = self.provenance.binding(node.id, node)
        if not isinstance(binding, ast.Name) or binding in seen:
            return None
        statement = self.context.parents.get(binding)
        if not isinstance(statement, ast.Assign | ast.AnnAssign):
            return None
        if (
            (isinstance(statement, ast.Assign) and len(statement.targets) != 1)
            or statement.value is None
            or statement.lineno >= node.lineno
            or not isinstance(
                self.context.parents.get(statement), ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef
            )
        ):
            return None
        return self._mode(statement.value, seen=seen | {binding})


def _callback_argument(call: ast.Call, qualified: str | None) -> ast.expr | None:
    if call.args:
        return call.args[0]
    parameter = "discriminator" if qualified in _DISCRIMINATORS else "func"
    return next((keyword.value for keyword in call.keywords if keyword.arg == parameter), None)


def _plain_method(node: ast.ClassDef, name: str) -> ast.FunctionDef | None:
    method: ast.FunctionDef | None = None
    for statement in node.body:
        match statement:
            case ast.FunctionDef(name=declared) if declared == name and method is None:
                method = statement
            case ast.Assign(value=value, targets=targets) if all(
                isinstance(target, ast.Name) and target.id != name and _inert_attribute(target.id, value)
                for target in targets
            ):
                continue
            case ast.AnnAssign(target=ast.Name(id=attribute), value=value) if attribute != name and _inert_attribute(
                attribute, value
            ):
                continue
            case ast.Pass() | ast.Expr(value=ast.Constant(value=str())):
                continue
            case _:
                return None
    return method


def _inert_attribute(name: str, value: ast.expr | None) -> bool:
    if name == "__slots__":
        return isinstance(value, ast.Tuple) and not value.elts
    return (name == "__name__" or not (name.startswith("__") and name.endswith("__"))) and (
        value is None or isinstance(value, ast.Constant)
    )
