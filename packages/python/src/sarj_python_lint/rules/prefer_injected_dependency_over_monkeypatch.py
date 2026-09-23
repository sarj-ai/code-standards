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
    parse_or_none,
)
from sarj_python_lint.rules._ast_position import AstPosition, ast_position
from sarj_python_lint.rules._imports import ImportIndex
from sarj_python_lint.rules._paths import is_generated, is_test_path


if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


_ATTRIBUTE_MUTATIONS = frozenset({"delattr", "setattr"})
_MONKEYPATCH = "monkeypatch"
_PYTEST = frozenset({"pytest"})
_UNITTEST_MOCK = frozenset({"unittest.mock"})
_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)


class PreferInjectedDependencyOverMonkeypatch(Rule):
    id: str = "prefer-injected-dependency-over-monkeypatch"
    code: str = "SARJ445"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
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
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if not is_test_path(path) or is_generated(path, source):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        imports = ImportIndex.from_tree(tree, module_scope_only=True)
        replacements = [
            (call, f"monkeypatch.{_operation(call)}")
            for function in _functions(tree)
            for call in _attribute_mutations(function, imports)
        ]
        replacements.extend((call, label) for call, label in _patch_calls(tree, imports))
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
                severity=Severity.WARNING,
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


def _patch_calls(tree: ast.Module, imports: ImportIndex) -> list[tuple[ast.Call, str]]:
    calls: list[tuple[ast.Call, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
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
        label = _pytest_mock_patch_label(node)
        if label is not None:
            calls.append((node, label))
    return calls


def _resolves_patch(node: ast.expr, imports: ImportIndex) -> bool:
    if imports.resolves(node, sources=_UNITTEST_MOCK, symbol="patch"):
        return True
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "patch"
        and imports.resolved_symbol(node.value, sources=frozenset({"unittest"})) == "mock"
    )


def _pytest_mock_patch_label(call: ast.Call) -> str | None:
    func = call.func
    if not isinstance(func, ast.Attribute):
        return None
    if isinstance(func.value, ast.Name) and func.value.id == "mocker" and func.attr == "patch":
        return "mocker.patch"
    if (
        func.attr == "object"
        and isinstance(func.value, ast.Attribute)
        and func.value.attr == "patch"
        and isinstance(func.value.value, ast.Name)
        and func.value.value.id == "mocker"
    ):
        return "mocker.patch.object"
    return None


def _functions(tree: ast.Module) -> Iterator[ast.FunctionDef | ast.AsyncFunctionDef]:
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node


def _attribute_mutations(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    imports: ImportIndex,
) -> list[ast.Call]:
    parameters = _parameter_handles(function, imports)
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
) -> set[str]:
    args = function.args
    parameters = (*args.posonlyargs, *args.args, *args.kwonlyargs)
    return {
        parameter.arg
        for parameter in parameters
        if parameter.arg == _MONKEYPATCH or _is_monkeypatch_annotation(parameter.annotation, imports)
    }


def _is_monkeypatch_annotation(annotation: ast.expr | None, imports: ImportIndex) -> bool:
    if annotation is None:
        return False
    if imports.resolves(annotation, sources=_PYTEST, symbol="MonkeyPatch"):
        return True
    if isinstance(annotation, ast.BinOp) and isinstance(annotation.op, ast.BitOr):
        return _is_monkeypatch_annotation(annotation.left, imports) or _is_monkeypatch_annotation(
            annotation.right, imports
        )
    if isinstance(annotation, ast.Constant) and isinstance(annotation.value, str):
        return annotation.value in {"MonkeyPatch", "pytest.MonkeyPatch"}
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


def _lexical_body_nodes(function: ast.FunctionDef | ast.AsyncFunctionDef) -> Iterator[ast.AST]:
    pending: list[ast.AST] = list(reversed(function.body))
    while pending:
        node = pending.pop()
        yield node
        if isinstance(node, _SCOPES):
            continue
        pending.extend(reversed(list(ast.iter_child_nodes(node))))
