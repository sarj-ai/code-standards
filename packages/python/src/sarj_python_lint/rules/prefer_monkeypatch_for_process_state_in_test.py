from __future__ import annotations

import ast
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, ClassVar, NamedTuple, final, override

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
    parse_or_none,
)
from sarj_python_lint.rules._ast_position import AstPosition, ast_position
from sarj_python_lint.rules._imports import ImportIndex
from sarj_python_lint.rules._paths import is_generated, is_test_path


if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator
    from pathlib import Path


_OS = frozenset({"os"})
_SYS = frozenset({"sys"})
_SCOPE_NODES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)


class _Mutation(NamedTuple):
    node: ast.expr
    family: str
    subject: str
    remedy: str
    identity: str | None = None


@final
class PreferMonkeypatchForProcessStateInTest(Rule):
    id = "prefer-monkeypatch-for-process-state-in-test"
    code = "SARJ446"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="Test mutates process-wide state without a restoring test scope.",
        rationale=(
            "The working directory and Python import registries are shared by every test in the process. A direct "
            "mutation can survive an assertion or setup failure, making later tests depend on execution order."
        ),
        remediation=(
            "Use pytest's monkeypatch.chdir, monkeypatch.syspath_prepend, monkeypatch.setitem, or "
            "monkeypatch.delitem so teardown restores the previous state even when the test fails. A deliberate "
            "manual restoration may remain when it is enclosed by a matching try/finally."
        ),
        category=RuleCategory.TESTING,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only maintained test paths are analyzed; generated files, production code, and module/class bootstrap mutations are excluded.",
            "The rule covers os.chdir, sys.path.insert(0, ...), and direct sys.modules set, delete, or unused pop operations with an equivalent pytest restoring helper.",
            "Environment variables remain owned by Ruff TID251/B003; argv, locale, timezone, warning filters, and process APIs without an equivalent helper are outside this rule.",
            "Imports and import aliases are resolved conservatively. Indirect container aliases and dynamically selected modules are not inferred.",
        ),
        examples=(
            RuleExample(
                example_id="direct-module-registry-mutation",
                title="Test installs a module without guaranteed restoration",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_plugin.py",
                        "import sys\n\ndef test_plugin(fake_plugin):\n    sys.modules['optional_plugin'] = fake_plugin\n",
                    ),
                ),
                focus_path=PurePosixPath("tests/test_plugin.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="scoped-module-registry-mutation",
                title="Pytest restores the module registry after the test",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_plugin.py",
                        "import sys\n\ndef test_plugin(monkeypatch, fake_plugin):\n"
                        "    monkeypatch.setitem(sys.modules, 'optional_plugin', fake_plugin)\n",
                    ),
                ),
                focus_path=PurePosixPath("tests/test_plugin.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if not is_test_path(path) or is_generated(path, source):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []

        module_imports = ImportIndex.from_tree(tree, module_scope_only=True)
        mutations = [
            mutation for function in _functions(tree) for mutation in _function_mutations(function, module_imports)
        ]
        diagnostics = [
            Diagnostic(
                path=path,
                line=mutation.node.lineno,
                col=mutation.node.col_offset + 1,
                code=self.code,
                message=(
                    f"Direct {mutation.subject} mutation can leak into later tests when this scope exits early. "
                    f"Use {mutation.remedy} so pytest restores the previous process state automatically."
                ),
                severity=Severity.WARNING,
            )
            for mutation in mutations
        ]
        diagnostics.sort(key=lambda diagnostic: (diagnostic.line, diagnostic.col))
        return diagnostics


def _functions(tree: ast.Module) -> Iterator[ast.FunctionDef | ast.AsyncFunctionDef]:
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node


def _function_mutations(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    module_imports: ImportIndex,
) -> list[_Mutation]:
    local_tree = ast.Module(body=function.body, type_ignores=[])
    local_imports = ImportIndex.from_tree(local_tree)
    nodes = tuple(_lexical_nodes(function))
    parents = {child: parent for parent in nodes for child in ast.iter_child_nodes(parent)}
    mutations: list[_Mutation] = []
    for node in nodes:
        mutation = _mutation(node, parents, module_imports, local_imports)
        if mutation is None or _import_root_rebound_before(function, mutation.node, module_imports, local_imports):
            continue
        mutations.append(mutation)
    restored = _restored_mutations(nodes, mutations, module_imports, local_imports)
    return [mutation for mutation in mutations if mutation.node not in restored]


def _lexical_nodes(function: ast.FunctionDef | ast.AsyncFunctionDef) -> Iterator[ast.AST]:
    stack: list[ast.AST] = [node for node in reversed(function.body) if not isinstance(node, _SCOPE_NODES)]
    while stack:
        node = stack.pop()
        yield node
        for child in reversed(list(ast.iter_child_nodes(node))):
            if isinstance(child, _SCOPE_NODES):
                continue
            stack.append(child)


def _mutation(
    node: ast.AST,
    parents: dict[ast.AST, ast.AST],
    module_imports: ImportIndex,
    local_imports: ImportIndex,
) -> _Mutation | None:
    if isinstance(node, ast.Call):
        mutation = _call_mutation(node, parents, module_imports, local_imports)
        if mutation is not None:
            return mutation
    target: ast.expr | None = None
    if isinstance(node, ast.Assign):
        target = next((item for item in node.targets if _is_modules_item(item, module_imports, local_imports)), None)
    elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
        target = node.target
    if target is not None and _is_modules_item(target, module_imports, local_imports):
        return _Mutation(
            target,
            "modules",
            "sys.modules",
            "monkeypatch.setitem(sys.modules, key, value)",
            _item_key(target),
        )
    if isinstance(node, ast.Delete):
        target = next((item for item in node.targets if _is_modules_item(item, module_imports, local_imports)), None)
        if target is not None:
            return _Mutation(
                target,
                "modules",
                "sys.modules",
                "monkeypatch.delitem(sys.modules, key)",
                _item_key(target),
            )
    return None


def _call_mutation(
    call: ast.Call,
    parents: dict[ast.AST, ast.AST],
    module_imports: ImportIndex,
    local_imports: ImportIndex,
) -> _Mutation | None:
    if _resolves(call.func, module_imports, local_imports, sources=_OS, symbol="chdir"):
        return _Mutation(call, "cwd", "working-directory", "monkeypatch.chdir(path)")
    if (
        isinstance(call.func, ast.Attribute)
        and call.func.attr == "insert"
        and _resolves(call.func.value, module_imports, local_imports, sources=_SYS, symbol="path")
        and call.args
        and _is_zero(call.args[0])
    ):
        identity = ast.dump(call.args[1], include_attributes=False) if len(call.args) > 1 else None
        return _Mutation(call, "path", "sys.path", "monkeypatch.syspath_prepend(path)", identity)
    if (
        isinstance(call.func, ast.Attribute)
        and call.func.attr == "pop"
        and _resolves(call.func.value, module_imports, local_imports, sources=_SYS, symbol="modules")
        and isinstance(parents.get(call), ast.Expr)
    ):
        identity = ast.dump(call.args[0], include_attributes=False) if call.args else None
        return _Mutation(
            call,
            "modules",
            "sys.modules",
            "monkeypatch.delitem(sys.modules, key, raising=False)",
            identity,
        )
    return None


def _is_modules_item(node: ast.expr, module_imports: ImportIndex, local_imports: ImportIndex) -> bool:
    return isinstance(node, ast.Subscript) and _resolves(
        node.value,
        module_imports,
        local_imports,
        sources=_SYS,
        symbol="modules",
    )


def _item_key(node: ast.expr) -> str | None:
    return ast.dump(node.slice, include_attributes=False) if isinstance(node, ast.Subscript) else None


def _is_zero(node: ast.expr) -> bool:
    return isinstance(node, ast.Constant) and not isinstance(node.value, bool) and node.value == 0


def _resolves(
    node: ast.expr,
    module_imports: ImportIndex,
    local_imports: ImportIndex,
    *,
    sources: frozenset[str],
    symbol: str,
) -> bool:
    return module_imports.resolves(node, sources=sources, symbol=symbol) or local_imports.resolves(
        node,
        sources=sources,
        symbol=symbol,
    )


def _import_root_rebound_before(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    use: ast.AST,
    module_imports: ImportIndex,
    local_imports: ImportIndex,
) -> bool:
    roots = {
        node.id
        for node in ast.walk(use)
        if isinstance(node, ast.Name) and (node.id in module_imports.bindings or node.id in local_imports.bindings)
    }
    parameters = {
        argument.arg
        for argument in (
            *function.args.posonlyargs,
            *function.args.args,
            *function.args.kwonlyargs,
        )
    }
    if not roots.isdisjoint(parameters):
        return True
    use_position = _position(use)
    return any(
        isinstance(node, ast.Name)
        and isinstance(node.ctx, (ast.Store, ast.Del))
        and node.id in roots
        and _position(node) < use_position
        for node in _lexical_nodes(function)
    )


def _position(node: ast.AST) -> AstPosition:
    return ast_position(node, missing=0)


def _restored_mutations(
    nodes: tuple[ast.AST, ...],
    mutations: list[_Mutation],
    module_imports: ImportIndex,
    local_imports: ImportIndex,
) -> set[ast.AST]:
    restored: set[ast.AST] = set()
    for node in nodes:
        if not isinstance(node, (ast.Try, ast.TryStar)) or not node.finalbody:
            continue
        restored.update(_restored_for_try(node, mutations, module_imports, local_imports))
    return restored


def _restored_for_try(
    node: ast.Try | ast.TryStar,
    mutations: list[_Mutation],
    module_imports: ImportIndex,
    local_imports: ImportIndex,
) -> set[ast.AST]:
    protected_nodes = set(_descendants(node.body))
    final_nodes = set(_descendants(node.finalbody))
    protected = [mutation for mutation in mutations if mutation.node in protected_nodes]
    final = [mutation for mutation in mutations if mutation.node in final_nodes]
    restored: set[ast.AST] = set()
    for mutation in protected:
        matching = next((item for item in final if _same_state(mutation, item)), None)
        if matching is not None:
            restored.update((mutation.node, matching.node))
            continue
        if mutation.family == "path" and _finalbody_removes_path(
            node.finalbody,
            mutation.identity,
            module_imports,
            local_imports,
        ):
            restored.add(mutation.node)
    return restored


def _descendants(statements: Iterable[ast.stmt]) -> Iterator[ast.AST]:
    for statement in statements:
        yield from ast.walk(statement)


def _same_state(left: _Mutation, right: _Mutation) -> bool:
    return left.family == right.family and (left.identity is None or left.identity == right.identity)


def _finalbody_removes_path(
    statements: list[ast.stmt],
    identity: str | None,
    module_imports: ImportIndex,
    local_imports: ImportIndex,
) -> bool:
    if identity is None:
        return False
    return any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "remove"
        and _resolves(node.func.value, module_imports, local_imports, sources=_SYS, symbol="path")
        and bool(node.args)
        and ast.dump(node.args[0], include_attributes=False) == identity
        for statement in statements
        for node in ast.walk(statement)
    )
