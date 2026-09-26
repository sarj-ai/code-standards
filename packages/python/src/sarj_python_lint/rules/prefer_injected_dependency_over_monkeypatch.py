from __future__ import annotations

import ast
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
)
from sarj_python_lint.rules._ast_index import parent_map, walk as walk_ast
from sarj_python_lint.rules._ast_position import AstPosition, ast_position
from sarj_python_lint.rules._paths import is_test_path


if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rules._ast_index import NodeIndex
    from sarj_python_lint.rules._imports import ImportIndex


_ATTRIBUTE_MUTATIONS = frozenset({"delattr", "setattr"})
_PYTEST = frozenset({"pytest"})
_PYTEST_MOCK = frozenset({"pytest_mock", "pytest_mock.plugin"})
_UNITTEST_MOCK = frozenset({"unittest.mock"})
_COMPREHENSIONS = (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)
_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda, *_COMPREHENSIONS)


class PreferInjectedDependencyOverMonkeypatch(Rule):
    id: str = "prefer-injected-dependency-over-monkeypatch"
    code: str = "SARJ445"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        default_level=Severity.ERROR,
        summary="Tests should inject dependencies instead of replacing attributes through ambient patching.",
        rationale=(
            "Attribute patching hides collaborators and configuration behind ambient module or object state, coupling "
            "tests to lookup locations instead of an explicit boundary. Pytest monkeypatch remains appropriate for "
            "reversible process state such as environment variables and the working directory."
        ),
        remediation=(
            "Pass the collaborator, settings, clock, sleeper, random source, client, or factory explicitly; prefer a "
            "real in-process dependency, framework override, or purpose-built ABC/Protocol fake. If a runtime "
            "boundary is inherently global, or intercepting its lookup is the behavior under test, suppress SARJ445 "
            "at that call with the concrete reason an owned injection seam would invalidate the test."
        ),
        category=RuleCategory.TESTING,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only maintained test paths are analyzed; generated files and production helpers are excluded.",
            "The rule recognizes pytest monkeypatch and statically resolved unittest.mock or pytest-mock patch APIs.",
            "Environment, mapping, import-path, and working-directory mutations are intentionally allowed.",
            "Untyped handles are recognized only on pytest tests or fixtures; directly parametrized values are excluded.",
            "A nested function that captures a monkeypatch handle from an outer scope is not inferred.",
        ),
        examples=(
            RuleExample(
                example_id="patched-first-party-collaborator",
                title="Test replaces an application collaborator",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_checkout.py",
                        "def test_checkout(monkeypatch):\n"
                        "    monkeypatch.setattr(checkout, 'charge_card', lambda _card: True)\n"
                        "    assert checkout.run() == 'paid'\n",
                    ),
                ),
                focus_path=PurePosixPath("tests/test_checkout.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="injected-recording-collaborator",
                title="Test injects a purpose-built collaborator",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_checkout.py",
                        "def test_checkout(recording_gateway):\n"
                        "    service = CheckoutService(payment_gateway=recording_gateway)\n"
                        "    assert service.run() == 'paid'\n",
                    ),
                ),
                focus_path=PurePosixPath("tests/test_checkout.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description: str = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        path = context.path
        if not is_test_path(path) or context.generated:
            return []
        tree = context.tree
        if tree is None:
            return []
        imports = context.module_imports
        parents = parent_map(tree, index=context.node_index)
        replacements = [
            (call, f"monkeypatch.{_operation(call)}")
            for function in _functions(tree, node_index=context.node_index)
            for call in _attribute_mutations(function, imports, parents)
        ]
        replacements.extend((call, label) for call, label in _patch_calls(tree, imports, node_index=context.node_index))
        diagnostics = [
            Diagnostic(
                path=path,
                line=call.lineno,
                col=call.col_offset + 1,
                code=self.code,
                message=(
                    f"`{label}` replaces an attribute through ambient state. Inject the "
                    "dependency or configuration, use a framework override, or provide a purpose-built fake. "
                    "If global lookup or interception is the behavior under test, suppress SARJ445 locally and explain "
                    "why injection would invalidate the test."
                ),
                severity=Severity.ERROR,
            )
            for call, label in replacements
        ]
        diagnostics.sort(key=lambda diagnostic: (diagnostic.line, diagnostic.col))
        return diagnostics


def _operation(call: ast.Call) -> str:
    func = call.func
    if not isinstance(func, ast.Attribute):  # pragma: no cover - guarded by _attribute_mutations
        msg = "attribute mutation call must use an attribute function"
        raise TypeError(msg)
    return func.attr


def _patch_calls(
    tree: ast.Module, imports: ImportIndex, *, node_index: NodeIndex | None = None
) -> list[tuple[ast.Call, str]]:
    calls: list[tuple[ast.Call, str]] = []
    parents = parent_map(tree, index=node_index)
    bindings: dict[ast.AST, set[str]] = {}
    for function in _functions(tree, node_index=node_index):
        calls.extend(_mocker_calls(function, imports, parents))
    for node in walk_ast(tree, index=node_index):
        if not isinstance(node, ast.Call):
            continue
        if _import_shadowed(node.func, parents, bindings):
            continue
        if _resolves_patch(node.func, imports):
            calls.append((node, "patch"))
            continue
        if (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "object"
            and _resolves_patch(node.func.value, imports)
        ):
            calls.append((node, "patch.object"))
            continue
    return calls


def _resolves_patch(node: ast.expr, imports: ImportIndex) -> bool:
    if imports.resolves(node, sources=_UNITTEST_MOCK, symbol="patch"):
        return True
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "patch"
        and imports.resolved_symbol(node.value, sources=frozenset({"unittest"})) == "mock"
    )


def _mocker_calls(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    imports: ImportIndex,
    parents: Mapping[ast.AST, ast.AST],
) -> list[tuple[ast.Call, str]]:
    parameters = _parameter_handles(
        function, imports, parents, fixture_name="mocker", sources=_PYTEST_MOCK, symbol="MockerFixture"
    )
    nodes = tuple(_lexical_body_nodes(function))
    handles = parameters | _direct_aliases(nodes, parameters, parameters)
    calls: list[tuple[ast.Call, str]] = []
    for node in nodes:
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        func = node.func
        label = "mocker.patch"
        if func.attr == "object" and isinstance(func.value, ast.Attribute):
            func = func.value
            label = "mocker.patch.object"
        if (
            func.attr == "patch"
            and isinstance(func.value, ast.Name)
            and func.value.id in handles
            and not _parameter_rebound_before(node, func.value.id, nodes, parameters)
        ):
            calls.append((node, label))
    return calls


def _import_shadowed(
    expression: ast.expr, parents: Mapping[ast.AST, ast.AST], bindings: dict[ast.AST, set[str]]
) -> bool:
    root = expression
    while isinstance(root, ast.Attribute):
        root = root.value
    if not isinstance(root, ast.Name):
        return False
    child: ast.AST = expression
    while (parent := parents.get(child)) is not None:
        if _inside_scope_body(parent, child):
            if parent not in bindings:
                bindings[parent] = _scope_bindings(parent)
            if root.id in bindings[parent]:
                return True
        child = parent
    return False


def _inside_scope_body(parent: ast.AST, child: ast.AST) -> bool:
    if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return child in parent.body
    return isinstance(parent, (ast.Lambda, *_COMPREHENSIONS))


def _scope_bindings(scope: ast.AST) -> set[str]:
    names: set[str] = set()
    if isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        names.update(name for node in _lexical_body_nodes(scope) for name in _bound_targets(node))
    if isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
        names.update(argument.arg for argument in _arguments(scope.args))
    if isinstance(scope, _COMPREHENSIONS):
        names.update(name for generator in scope.generators for name in _target_names(generator.target))
    return names


def _arguments(arguments: ast.arguments) -> Iterator[ast.arg]:
    yield from (*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs)
    if arguments.vararg is not None:
        yield arguments.vararg
    if arguments.kwarg is not None:
        yield arguments.kwarg


def _functions(
    tree: ast.Module, *, node_index: NodeIndex | None = None
) -> Iterator[ast.FunctionDef | ast.AsyncFunctionDef]:
    for node in walk_ast(tree, index=node_index):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node


def _attribute_mutations(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    imports: ImportIndex,
    parents: Mapping[ast.AST, ast.AST],
) -> list[ast.Call]:
    parameters = _parameter_handles(function, imports, parents)
    if not parameters:
        return []
    nodes = tuple(_lexical_body_nodes(function))
    handles = set(parameters)
    handles |= _direct_aliases(nodes, handles, parameters)
    return [
        node
        for node in nodes
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in _ATTRIBUTE_MUTATIONS
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id in handles
        and not _parameter_rebound_before(node, node.func.value.id, nodes, parameters)
    ]


def _parameter_handles(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    imports: ImportIndex,
    parents: Mapping[ast.AST, ast.AST],
    *,
    fixture_name: str = "monkeypatch",
    sources: frozenset[str] = _PYTEST,
    symbol: str = "MonkeyPatch",
) -> set[str]:
    args = function.args
    parameters = (*args.posonlyargs, *args.args, *args.kwonlyargs)
    fixture_consumer = function.name.startswith("test_") or any(
        imports.resolves(
            decorator.func if isinstance(decorator, ast.Call) else decorator,
            sources=frozenset({"pytest", "pytest_asyncio"}),
            symbol="fixture",
        )
        for decorator in function.decorator_list
    )
    parametrized = _parametrized_names(function, imports)
    ancestor: ast.AST = function
    while (parent := parents.get(ancestor)) is not None:
        if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef)):
            fixture_consumer = False
        if isinstance(parent, ast.ClassDef):
            parametrized.update(_parametrized_names(parent, imports))
        ancestor = parent
    return {
        parameter.arg
        for parameter in parameters
        if _is_handle_annotation(parameter.annotation, imports, sources=sources, symbol=symbol)
        or (parameter.arg == fixture_name and fixture_consumer and parameter.arg not in parametrized)
    }


def _parametrized_names(
    function: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef, imports: ImportIndex
) -> set[str]:
    names: set[str] = set()
    for decorator in function.decorator_list:
        if not isinstance(decorator, ast.Call) or not imports.resolves(
            decorator.func, sources=frozenset({"pytest.mark"}), symbol="parametrize"
        ):
            continue
        argument = (
            decorator.args[0]
            if decorator.args
            else next((keyword.value for keyword in decorator.keywords if keyword.arg == "argnames"), None)
        )
        names.update(_literal_parameter_names(argument))
    return names


def _literal_parameter_names(argument: ast.expr | None) -> set[str]:
    if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
        return {name.strip() for name in argument.value.split(",")}
    if isinstance(argument, (ast.List, ast.Tuple)):
        return {item.value for item in argument.elts if isinstance(item, ast.Constant) and isinstance(item.value, str)}
    return set()


def _is_handle_annotation(
    annotation: ast.expr | None, imports: ImportIndex, *, sources: frozenset[str], symbol: str
) -> bool:
    if annotation is None:
        return False
    if imports.resolves(annotation, sources=sources, symbol=symbol):
        return True
    if isinstance(annotation, ast.BinOp) and isinstance(annotation.op, ast.BitOr):
        return _is_handle_annotation(annotation.left, imports, sources=sources, symbol=symbol) or _is_handle_annotation(
            annotation.right, imports, sources=sources, symbol=symbol
        )
    if isinstance(annotation, ast.Constant) and isinstance(annotation.value, str):
        try:
            parsed = ast.parse(annotation.value, mode="eval").body
        except SyntaxError:
            return False
        if not isinstance(parsed, ast.Constant):
            return _is_handle_annotation(parsed, imports, sources=sources, symbol=symbol)
    return False


def _parameter_rebound_before(
    use: ast.AST,
    handle: str,
    nodes: tuple[ast.AST, ...],
    parameters: set[str],
) -> bool:
    if handle not in parameters:
        return False
    use_position = _position(use)
    return any(handle in _bound_targets(node) and _position(node) < use_position for node in nodes)


def _position(node: ast.AST) -> AstPosition:
    if isinstance(node, ast.withitem):
        return _position(node.context_expr)
    return ast_position(node, missing=0)


def _direct_aliases(nodes: tuple[ast.AST, ...], handles: set[str], parameters: set[str]) -> set[str]:
    binding_counts: dict[str, int] = {}
    for node in nodes:
        for name in _bound_targets(node):
            binding_counts[name] = binding_counts.get(name, 0) + 1
    aliases: set[str] = set()
    changed = True
    while changed:
        changed = False
        known = handles | aliases
        for node in nodes:
            binding = _alias_binding(node, known)
            if binding is None:
                continue
            candidate, source = binding
            source_was_rebound = _parameter_rebound_before(node, source, nodes, parameters)
            if not source_was_rebound and binding_counts.get(candidate) == 1 and candidate not in known:
                aliases.add(candidate)
                changed = True
    return aliases


def _bound_targets(node: ast.AST) -> set[str]:
    match node:
        case ast.Assign(targets=targets) | ast.Delete(targets=targets):
            return {name for target in targets for name in _target_names(target)}
        case (
            ast.AnnAssign(target=target)
            | ast.AugAssign(target=target)
            | ast.NamedExpr(target=target)
            | ast.For(target=target)
            | ast.AsyncFor(target=target)
        ):
            return _target_names(target)
        case ast.withitem(optional_vars=target) if target is not None:
            return _target_names(target)
        case ast.FunctionDef() | ast.AsyncFunctionDef() | ast.ClassDef():
            return {node.name}
        case ast.Import() | ast.ImportFrom():
            return {alias.asname or alias.name.split(".")[0] for alias in node.names}
        case ast.ExceptHandler(name=str(name)):
            return {name}
        case _:
            return set()


def _alias_binding(node: ast.AST, handles: set[str]) -> tuple[str, str] | None:
    if isinstance(node, (ast.Assign, ast.AnnAssign)):
        value = node.value
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if isinstance(value, ast.Name) and value.id in handles and len(targets) == 1:
            names = _target_names(targets[0])
            return (next(iter(names)), value.id) if len(names) == 1 else None
    if isinstance(node, ast.withitem) and node.optional_vars is not None:
        expression = node.context_expr
        if (
            isinstance(expression, ast.Call)
            and isinstance(expression.func, ast.Attribute)
            and expression.func.attr == "context"
            and isinstance(expression.func.value, ast.Name)
            and expression.func.value.id in handles
        ):
            names = _target_names(node.optional_vars)
            return (next(iter(names)), expression.func.value.id) if len(names) == 1 else None
    return None


def _target_names(node: ast.expr) -> set[str]:
    if isinstance(node, ast.Name):
        return {node.id}
    if isinstance(node, (ast.List, ast.Tuple)):
        return {name for element in node.elts for name in _target_names(element)}
    return set()


def _lexical_body_nodes(function: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> Iterator[ast.AST]:
    pending: list[ast.AST] = list(reversed(function.body))
    while pending:
        node = pending.pop()
        yield node
        if isinstance(node, _SCOPES):
            continue
        pending.extend(reversed(list(ast.iter_child_nodes(node))))
