from __future__ import annotations

import ast
from enum import StrEnum
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, ClassVar, override

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
from sarj_python_lint.rules._imports import ImportIndex
from sarj_python_lint.rules._paths import is_generated


if TYPE_CHECKING:
    from pathlib import Path


_BUILTINS = frozenset({"builtins"})
_PYDANTIC_BASE_MODEL_SOURCES = frozenset({"pydantic", "pydantic.main", "pydantic.v1", "pydantic.v1.main"})
_PYDANTIC_VALIDATOR_SOURCES = frozenset({"pydantic", "pydantic.functional_validators"})
_METACLASS_NEW_CONTRACT_PARAMETER_COUNT = 3
_TRANSPARENT_DECORATORS = frozenset(
    {
        (frozenset({"abc"}), "abstractmethod"),
        (frozenset({"typing", "typing_extensions"}), "override"),
    }
)


class _MethodKind(StrEnum):
    INSTANCE = "instance"
    CLASS = "class"
    STATIC = "static"


def _is_return_self_or_cls(
    outer_func: ast.FunctionDef | ast.AsyncFunctionDef,
    *,
    receiver: str,
    is_classmethod: bool,
    allow_pydantic_constructors: bool,
) -> bool:
    if _block_can_fall_through(outer_func.body):
        return False

    class ReturnVisitor(ast.NodeVisitor):
        returns: list[ast.expr | None]

        def __init__(self) -> None:
            self.returns = []

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            if node is outer_func:
                self.generic_visit(node)

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            if node is outer_func:
                self.generic_visit(node)

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            pass

        def visit_Return(self, node: ast.Return) -> None:
            self.returns.append(node.value)

    visitor = ReturnVisitor()
    visitor.visit(outer_func)
    if not visitor.returns:
        return False

    def preserves_type(value: ast.expr | None) -> bool:
        if not is_classmethod:
            return isinstance(value, ast.Name) and value.id == receiver
        if not isinstance(value, ast.Call):
            return False
        if isinstance(value.func, ast.Name):
            return value.func.id == receiver
        return (
            allow_pydantic_constructors
            and isinstance(value.func, ast.Attribute)
            and isinstance(value.func.value, ast.Name)
            and value.func.value.id == receiver
            and value.func.attr in {"model_construct", "model_validate"}
        )

    return all(preserves_type(value) for value in visitor.returns)


def _block_can_fall_through(statements: list[ast.stmt]) -> bool:
    if not statements:
        return True
    match statements[-1]:
        case ast.Return() | ast.Raise():
            return False
        case ast.If(body=body, orelse=orelse):
            return _block_can_fall_through(body) or _block_can_fall_through(orelse)
        case _:
            return True


class PreferSelfTypeAnnotation(Rule):
    id: str = "prefer-self-type-annotation"
    code: str = "SARJ078"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="Prefer `Self` for self-returning methods and alternate constructors.",
        rationale="`Self` preserves the concrete subclass type when an inherited method returns its receiver or constructs through its class receiver.",
        remediation="Import `Self` from `typing` (or `typing_extensions` on Python before 3.11) and use it as the return annotation.",
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only undecorated or provenance-safe methods whose every return directly preserves the receiver type are analyzed.",
            "Static methods, generators, final classes, metaclasses, inherited-base annotations, and behavior-changing decorators are excluded.",
        ),
        examples=(
            RuleExample(
                example_id="enclosing-class-return",
                title="Fluent method names its enclosing class",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/builder.py",
                        "class Builder:\n"
                        '    def set_name(self, name: str) -> "Builder":\n'
                        "        self.name = name\n"
                        "        return self\n",
                    ),
                ),
                focus_path=PurePosixPath("app/builder.py"),
                expected_count=1,
                public=True,
                scenario="fluent-method",
            ),
            RuleExample(
                example_id="self-return-annotation",
                title="Fluent method preserves subclass type",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/builder.py",
                        "from typing import Self\n\n"
                        "class Builder:\n"
                        "    def set_name(self, name: str) -> Self:\n"
                        "        self.name = name\n"
                        "        return self\n",
                    ),
                ),
                focus_path=PurePosixPath("app/builder.py"),
                expected_count=0,
                public=True,
                scenario="fluent-method",
            ),
            RuleExample(
                example_id="concrete-classmethod-return",
                title="Alternate constructor names its enclosing class",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/builder.py",
                        'class Builder:\n    @classmethod\n    def create(cls) -> "Builder":\n        return cls()\n',
                    ),
                ),
                focus_path=PurePosixPath("app/builder.py"),
                expected_count=1,
                public=True,
                scenario="alternate-constructor",
            ),
            RuleExample(
                example_id="self-classmethod-return",
                title="Alternate constructor preserves subclass type",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/builder.py",
                        "from typing import Self\n\n"
                        "class Builder:\n"
                        "    @classmethod\n"
                        "    def create(cls) -> Self:\n"
                        "        return cls()\n",
                    ),
                ),
                focus_path=PurePosixPath("app/builder.py"),
                expected_count=0,
                public=True,
                scenario="alternate-constructor",
            ),
        ),
    )
    description: str = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        tree = parse_or_none(path, source)
        if tree is None or not _has_candidate_annotation(tree) or is_generated(path, source):
            return []
        imports = ImportIndex.from_tree(tree)
        mutated_builtins = _mutated_builtin_symbols(tree, imports)
        metaclass_ids = _metaclass_ids(tree, imports, mutated_builtins)

        source_lines = source.splitlines()
        diags: list[Diagnostic] = []

        class ClassVisitor(ast.NodeVisitor):
            def __init__(self) -> None:
                self.class_stack: list[ast.ClassDef] = []

            def visit_ClassDef(self, node: ast.ClassDef) -> None:
                self.class_stack.append(node)
                for child in node.body:
                    if isinstance(child, ast.ClassDef):
                        self.visit(child)
                    elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        self._check_func(child)
                self.class_stack.pop()

            def _check_func(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
                if not self.class_stack:
                    return
                if node.name == "__init__" or _ruff_owns_self_annotation(node.name):
                    return
                current_class = self.class_stack[-1]
                if id(current_class) in metaclass_ids or _is_final_class(current_class, imports):
                    return
                if _ruff_owns_iterator_method(node.name, current_class, imports):
                    return
                method_kind = _method_kind(node, imports, mutated_builtins)
                if method_kind is None or method_kind is _MethodKind.STATIC:
                    return
                receiver = _first_positional_parameter(node)
                bindings, is_generator = _method_scope_facts(node)
                if receiver is None or receiver in bindings or is_generator:
                    return
                returns = node.returns
                if returns is None:
                    return

                matched_name = _matched_enclosing_class_annotation(returns, current_class.name)

                if (
                    matched_name
                    and _is_return_self_or_cls(
                        node,
                        receiver=receiver,
                        is_classmethod=method_kind is _MethodKind.CLASS,
                        allow_pydantic_constructors=_is_pydantic_model(current_class, imports),
                    )
                    and not is_suppressed(source_lines, returns.lineno, "SARJ078")
                ):
                    diags.append(
                        Diagnostic(
                            path=path,
                            line=returns.lineno,
                            col=returns.col_offset + 1,
                            code="SARJ078",
                            message=(
                                f"Method `{node.name}` returns an instance of its class but annotates it as `{matched_name}` — "
                                "consider `Self` to preserve the receiver's concrete subclass type."
                            ),
                            severity=Severity.WARNING,
                        )
                    )

        visitor = ClassVisitor()
        visitor.visit(tree)

        return sorted(diags, key=lambda d: (d.line, d.col))


def _method_kind(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    imports: ImportIndex,
    mutated_builtins: frozenset[str],
) -> _MethodKind | None:
    binding_kinds: set[_MethodKind] = set()
    for decorator in node.decorator_list:
        if not isinstance(decorator, ast.Call):
            if _is_builtin(decorator, "staticmethod", imports, mutated_builtins):
                binding_kinds.add(_MethodKind.STATIC)
                continue
            if _is_builtin(decorator, "classmethod", imports, mutated_builtins):
                binding_kinds.add(_MethodKind.CLASS)
                continue
            if _is_builtin(decorator, "property", imports, mutated_builtins):
                continue
            if any(
                imports.resolves(decorator, sources=sources, symbol=symbol)
                for sources, symbol in _TRANSPARENT_DECORATORS
            ):
                continue
        if _is_after_model_validator(decorator, imports):
            continue
        return None
    if len(binding_kinds) > 1:
        return None
    return next(iter(binding_kinds), _MethodKind.INSTANCE)


def _is_builtin(
    node: ast.expr,
    symbol: str,
    imports: ImportIndex,
    mutated_builtins: frozenset[str] = frozenset(),
) -> bool:
    if symbol in mutated_builtins:
        return False
    return (
        isinstance(node, ast.Name) and node.id == symbol and imports.builtin_is_unshadowed(symbol)
    ) or imports.resolves(node, sources=_BUILTINS, symbol=symbol)


def _is_after_model_validator(node: ast.expr, imports: ImportIndex) -> bool:
    if not isinstance(node, ast.Call) or not imports.resolves(
        node.func, sources=_PYDANTIC_VALIDATOR_SOURCES, symbol="model_validator"
    ):
        return False
    modes = [keyword.value for keyword in node.keywords if keyword.arg == "mode"]
    return len(modes) == 1 and isinstance(modes[0], ast.Constant) and modes[0].value == "after"


def _first_positional_parameter(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    positional = (*node.args.posonlyargs, *node.args.args)
    return positional[0].arg if positional else None


def _matched_enclosing_class_annotation(node: ast.expr, class_name: str) -> str | None:
    if isinstance(node, ast.Name) and node.id == class_name:
        return class_name
    if isinstance(node, ast.Constant) and node.value == class_name:
        return class_name
    return None


def _method_scope_facts(node: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[frozenset[str], bool]:
    bindings: set[str] = set()
    has_yield = False

    class Visitor(ast.NodeVisitor):
        @override
        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            bindings.add(node.name)

        @override
        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            bindings.add(node.name)

        @override
        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            bindings.add(node.name)

        @override
        def visit_Lambda(self, node: ast.Lambda) -> None:
            pass

        @override
        def visit_Name(self, node: ast.Name) -> None:
            if isinstance(node.ctx, (ast.Store, ast.Del)):
                bindings.add(node.id)

        @override
        def visit_Import(self, node: ast.Import) -> None:
            bindings.update(alias.asname or alias.name.partition(".")[0] for alias in node.names)

        @override
        def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
            bindings.update(alias.asname or alias.name for alias in node.names if alias.name != "*")

        @override
        def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
            if node.name is not None:
                bindings.add(node.name)
            self.generic_visit(node)

        @override
        def visit_MatchAs(self, node: ast.MatchAs) -> None:
            if node.name is not None:
                bindings.add(node.name)
            self.generic_visit(node)

        @override
        def visit_MatchStar(self, node: ast.MatchStar) -> None:
            if node.name is not None:
                bindings.add(node.name)

        @override
        def visit_MatchMapping(self, node: ast.MatchMapping) -> None:
            if node.rest is not None:
                bindings.add(node.rest)
            self.generic_visit(node)

        @override
        def visit_Yield(self, node: ast.Yield) -> None:
            nonlocal has_yield
            has_yield = True
            self.generic_visit(node)

        @override
        def visit_YieldFrom(self, node: ast.YieldFrom) -> None:
            nonlocal has_yield
            has_yield = True
            self.generic_visit(node)

    visitor = Visitor()
    for statement in node.body:
        visitor.visit(statement)
    return frozenset(bindings), has_yield


def _is_final_class(node: ast.ClassDef, imports: ImportIndex) -> bool:
    return any(
        imports.resolves(decorator, sources=frozenset({"typing", "typing_extensions"}), symbol="final")
        for decorator in node.decorator_list
    )


def _is_pydantic_model(node: ast.ClassDef, imports: ImportIndex) -> bool:
    return any(imports.resolves(base, sources=_PYDANTIC_BASE_MODEL_SOURCES, symbol="BaseModel") for base in node.bases)


def _metaclass_ids(
    tree: ast.Module,
    imports: ImportIndex,
    mutated_builtins: frozenset[str],
) -> frozenset[int]:
    classes = [node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]
    metaclass_type_names = {
        node.name
        for node in classes
        if _looks_like_metaclass(node)
        or _metaclass_shaped_name(node.name)
        or any(_metaclass_shaped_name(_trailing_annotation_name(base) or "") for base in node.bases)
    }
    aliases = _safe_module_assignment_aliases(tree)
    changed = True
    while changed:
        changed = False
        for alias, value in aliases.items():
            if alias in metaclass_type_names:
                continue
            if _is_metaclass_base(value, imports, mutated_builtins, metaclass_type_names):
                metaclass_type_names.add(alias)
                changed = True
        for node in classes:
            if node.name in metaclass_type_names:
                continue
            if any(_is_metaclass_base(base, imports, mutated_builtins, metaclass_type_names) for base in node.bases):
                metaclass_type_names.add(node.name)
                changed = True
    return frozenset(id(node) for node in classes if node.name in metaclass_type_names)


def _is_metaclass_base(
    base: ast.expr,
    imports: ImportIndex,
    mutated_builtins: frozenset[str],
    local_metaclasses: set[str],
) -> bool:
    return (
        _is_builtin(base, "type", imports, mutated_builtins)
        or imports.resolves(base, sources=frozenset({"abc"}), symbol="ABCMeta")
        or (isinstance(base, ast.Name) and base.id in local_metaclasses)
    )


def _looks_like_metaclass(node: ast.ClassDef) -> bool:
    for statement in node.body:
        if not isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)) or statement.name != "__new__":
            continue
        positional = (*statement.args.posonlyargs, *statement.args.args)
        names = tuple(argument.arg for argument in positional[1:4])
        if (
            len(names) == _METACLASS_NEW_CONTRACT_PARAMETER_COUNT
            and names[0] in {"name", "class_name"}
            and names[1] in {"bases", "base_classes"}
        ):
            return names[2] in {"attrs", "namespace", "namespace_dict"}
    return False


def _metaclass_shaped_name(name: str) -> bool:
    return name == "Meta" or name.endswith(("Meta", "Metaclass"))


def _safe_module_assignment_aliases(tree: ast.Module) -> dict[str, ast.expr]:
    binding_counts: dict[str, int] = {}

    class BindingVisitor(ast.NodeVisitor):
        @staticmethod
        def _record(name: str) -> None:
            binding_counts[name] = binding_counts.get(name, 0) + 1

        @override
        def visit_Name(self, node: ast.Name) -> None:
            if isinstance(node.ctx, (ast.Store, ast.Del)):
                self._record(node.id)

        @override
        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self._record(node.name)

        @override
        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            self._record(node.name)

        @override
        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            self._record(node.name)

        @override
        def visit_Lambda(self, node: ast.Lambda) -> None:
            pass

        @override
        def visit_Import(self, node: ast.Import) -> None:
            for alias in node.names:
                self._record(alias.asname or alias.name.partition(".")[0])

        @override
        def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
            for alias in node.names:
                if alias.name != "*":
                    self._record(alias.asname or alias.name)

        @override
        def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
            if node.name is not None:
                self._record(node.name)
            self.generic_visit(node)

        @override
        def visit_MatchAs(self, node: ast.MatchAs) -> None:
            if node.name is not None:
                self._record(node.name)
            self.generic_visit(node)

        @override
        def visit_MatchStar(self, node: ast.MatchStar) -> None:
            if node.name is not None:
                self._record(node.name)

        @override
        def visit_MatchMapping(self, node: ast.MatchMapping) -> None:
            if node.rest is not None:
                self._record(node.rest)
            self.generic_visit(node)

    visitor = BindingVisitor()
    for statement in tree.body:
        visitor.visit(statement)

    candidates: dict[str, ast.expr] = {}
    for statement in tree.body:
        if isinstance(statement, ast.Assign):
            for target in statement.targets:
                if isinstance(target, ast.Name):
                    candidates[target.id] = statement.value
        elif (
            isinstance(statement, ast.AnnAssign)
            and isinstance(statement.target, ast.Name)
            and statement.value is not None
        ):
            candidates[statement.target.id] = statement.value
    return {name: value for name, value in candidates.items() if binding_counts.get(name) == 1}


def _has_candidate_annotation(tree: ast.Module) -> bool:
    def class_has_candidate(node: ast.ClassDef) -> bool:
        for statement in node.body:
            if not isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)) or statement.returns is None:
                continue
            returns = statement.returns
            if (isinstance(returns, ast.Name) and returns.id == node.name) or (
                isinstance(returns, ast.Constant) and returns.value == node.name
            ):
                return True
        return False

    return any(isinstance(node, ast.ClassDef) and class_has_candidate(node) for node in ast.walk(tree))


def _mutated_builtin_symbols(tree: ast.Module, imports: ImportIndex) -> frozenset[str]:
    symbols = {"classmethod", "property", "staticmethod", "type"}
    return frozenset(
        symbol
        for symbol in symbols
        if any(
            isinstance(node, ast.Attribute)
            and isinstance(node.ctx, (ast.Store, ast.Del))
            and imports.resolves(node, sources=_BUILTINS, symbol=symbol)
            for node in ast.walk(tree)
        )
    )


def _trailing_annotation_name(node: ast.expr) -> str | None:
    match node:
        case ast.Name(id=name) | ast.Attribute(attr=name):
            return name
        case ast.Subscript(value=value):
            return _trailing_annotation_name(value)
        case _:
            return None


_RUFF_SELF_DUNDERS = frozenset({"__aenter__", "__enter__", "__new__"})
_INPLACE_DUNDERS = frozenset(
    {
        "__iadd__",
        "__iand__",
        "__ifloordiv__",
        "__ilshift__",
        "__imatmul__",
        "__imod__",
        "__imul__",
        "__ior__",
        "__ipow__",
        "__irshift__",
        "__isub__",
        "__itruediv__",
        "__ixor__",
    }
)


def _ruff_owns_self_annotation(name: str) -> bool:
    return name in _RUFF_SELF_DUNDERS or name in _INPLACE_DUNDERS


def _ruff_owns_iterator_method(name: str, node: ast.ClassDef, imports: ImportIndex) -> bool:
    expected = {"__iter__": "Iterator", "__aiter__": "AsyncIterator"}.get(name)
    if expected is None:
        return False
    return any(
        imports.resolves(
            base.value if isinstance(base, ast.Subscript) else base,
            sources=frozenset({"typing", "collections.abc"}),
            symbol=expected,
        )
        for base in node.bases
    )
