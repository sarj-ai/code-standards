from __future__ import annotations

import ast
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, ClassVar, final, override

from sarj_python_lint.rule_base import (
    AutofixPolicy,
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    Rule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
    is_suppressed,
    parse_or_none,
)
from sarj_python_lint.rules._paths import is_generated


if TYPE_CHECKING:
    from pathlib import Path


@final
class PreferSetIsdisjoint(Rule):
    id = "prefer-set-isdisjoint"
    code = "SARJ431"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="Prefer `set.isdisjoint` when a built-in set intersection is used only as a boolean predicate.",
        rationale="`isdisjoint` names the overlap predicate directly and avoids allocating an intersection that is immediately discarded.",
        remediation="Use `left.isdisjoint(right)` and negate it when the condition requires overlap.",
        category=RuleCategory.STYLE,
        autofix=AutofixPolicy.SUGGESTION,
        limitations=(
            "Built-in set identity must be proven from a literal, comprehension, constructor, or one dominating local assignment.",
            "Both intersection operands must be proven built-in sets; annotations, parameters, attributes, subclasses, branch-merged bindings, stored intersections, and generated files are excluded.",
            "The suggestion is intentionally not an autofix because short-circuiting may make custom element equality or hashing side effects observable.",
        ),
        examples=(
            RuleExample(
                example_id="discarded-intersection",
                title="Set intersection is used only for an emptiness test",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/policy.py",
                        "allowed = {'read', 'write'}\nrequested = set(scopes)\nif not (allowed & requested):\n    deny()\n",
                    ),
                ),
                focus_path=PurePosixPath("app/policy.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="named-disjoint-predicate",
                title="Set overlap is expressed without allocating an intersection",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/policy.py",
                        "allowed = {'read', 'write'}\nrequested = set(scopes)\nif allowed.isdisjoint(requested):\n    deny()\n",
                    ),
                ),
                focus_path=PurePosixPath("app/policy.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if ("&" not in source and ".intersection" not in source) or is_generated(path, source):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        scanner = _Scanner(path, source.splitlines(), _shadowed_builtins(tree))
        scanner.scan_body(tree.body, set())
        scanner.diagnostics.sort(key=lambda item: (item.line, item.col))
        return scanner.diagnostics


@final
class _Scanner:
    def __init__(self, path: Path, source_lines: list[str], shadowed: frozenset[str]) -> None:
        self.path = path
        self.source_lines = source_lines
        self.shadowed = shadowed
        self.diagnostics: list[Diagnostic] = []
        self.reported: set[int] = set()

    def scan_body(self, body: list[ast.stmt], exact: set[str]) -> None:
        local = set(exact)
        for statement in body:
            self._scan_statement(statement, local)
            self._update_binding(statement, local)

    def _scan_statement(self, statement: ast.stmt, exact: set[str]) -> None:
        match statement:
            case ast.If():
                self._scan_boolean(statement.test, exact)
                self._scan_embedded(statement.test, exact)
                self.scan_body(statement.body, set(exact))
                self.scan_body(statement.orelse, set(exact))
            case ast.While():
                loop_exact = exact - _stored_names(ast.Module(body=[*statement.body, *statement.orelse]))
                self._scan_boolean(statement.test, loop_exact)
                self._scan_embedded(statement.test, loop_exact)
                self.scan_body(statement.body, set(exact))
                self.scan_body(statement.orelse, set(exact))
            case ast.Assert(test=test):
                self._scan_boolean(test, exact)
                self._scan_embedded(test, exact)
            case ast.FunctionDef() | ast.AsyncFunctionDef() | ast.ClassDef():
                self.scan_body(statement.body, set())
            case ast.For() | ast.AsyncFor():
                self._scan_embedded(statement.iter, exact)
                nested = set(exact)
                nested.difference_update(_stored_names(statement.target))
                self.scan_body(statement.body, nested)
                self.scan_body(statement.orelse, set(exact))
            case ast.With() | ast.AsyncWith():
                nested = set(exact)
                for item in statement.items:
                    self._scan_embedded(item.context_expr, exact)
                    if item.optional_vars is not None:
                        nested.difference_update(_stored_names(item.optional_vars))
                self.scan_body(statement.body, nested)
            case ast.Try(body=body, handlers=handlers, orelse=orelse, finalbody=finalbody):
                self.scan_body(body, set(exact))
                for handler in handlers:
                    handler_exact = set(exact)
                    if handler.name is not None:
                        handler_exact.discard(handler.name)
                    self.scan_body(handler.body, handler_exact)
                self.scan_body(orelse, set(exact))
                self.scan_body(finalbody, set(exact))
            case _:
                for child in ast.iter_child_nodes(statement):
                    if isinstance(child, ast.expr):
                        self._scan_embedded(child, exact)

    def _scan_embedded(self, expression: ast.expr, exact: set[str]) -> None:
        if isinstance(expression, ast.Lambda):
            nested = exact - _argument_names(expression.args)
            self._scan_embedded(expression.body, nested)
            return
        if isinstance(expression, ast.IfExp):
            self._scan_boolean(expression.test, exact)
        if isinstance(expression, ast.DictComp):
            nested = self._scan_comprehensions(expression.generators, exact)
            self._scan_embedded(expression.key, nested)
            self._scan_embedded(expression.value, nested)
            return
        if isinstance(expression, ast.ListComp | ast.SetComp | ast.GeneratorExp):
            nested = self._scan_comprehensions(expression.generators, exact)
            self._scan_embedded(expression.elt, nested)
            return
        for child in ast.iter_child_nodes(expression):
            if isinstance(child, ast.expr):
                self._scan_embedded(child, exact)

    def _scan_comprehensions(self, generators: list[ast.comprehension], exact: set[str]) -> set[str]:
        nested = set(exact)
        for generator in generators:
            self._scan_embedded(generator.iter, nested)
            nested.difference_update(_stored_names(generator.target))
            for condition in generator.ifs:
                self._scan_boolean(condition, nested)
                self._scan_embedded(condition, nested)
        return nested

    def _scan_boolean(self, expression: ast.expr, exact: set[str]) -> None:
        safe_exact = exact - _named_expression_targets(expression)
        if isinstance(expression, ast.BoolOp):
            for value in expression.values:
                self._scan_boolean(value, safe_exact)
            return
        negated = False
        candidate = expression
        if isinstance(expression, ast.UnaryOp) and isinstance(expression.op, ast.Not):
            negated = True
            candidate = expression.operand
        if _is_intersection(candidate, safe_exact, self.shadowed):
            self._report(candidate, negated=negated)

    def _report(self, node: ast.expr, *, negated: bool) -> None:
        if id(node) in self.reported or is_suppressed(self.source_lines, node.lineno, PreferSetIsdisjoint.code):
            return
        self.reported.add(id(node))
        replacement = "`left.isdisjoint(right)`" if negated else "`not left.isdisjoint(right)`"
        self.diagnostics.append(
            Diagnostic(
                path=self.path,
                line=node.lineno,
                col=node.col_offset + 1,
                code=PreferSetIsdisjoint.code,
                message=f"built-in set intersection is allocated only for a boolean test — use {replacement}",
            )
        )

    def _update_binding(self, statement: ast.stmt, exact: set[str]) -> None:
        exact.difference_update(_named_expression_targets(statement))
        match statement:
            case ast.Assign(targets=[ast.Name(id=name)], value=value):
                if _is_exact_set(value, exact, self.shadowed):
                    exact.add(name)
                else:
                    exact.discard(name)
            case ast.AnnAssign(target=ast.Name(id=name)) | ast.AugAssign(target=ast.Name(id=name)):
                exact.discard(name)
            case ast.Delete(targets=targets):
                for target in targets:
                    if isinstance(target, ast.Name):
                        exact.discard(target.id)
            case ast.Assign(targets=targets):
                for target in targets:
                    exact.difference_update(_stored_names(target))
            case ast.FunctionDef() | ast.AsyncFunctionDef() | ast.ClassDef():
                exact.discard(statement.name)
            case ast.Import(names=aliases):
                exact.difference_update(alias.asname or alias.name.split(".")[0] for alias in aliases)
            case ast.ImportFrom(names=aliases):
                if any(alias.name == "*" for alias in aliases):
                    exact.clear()
                else:
                    exact.difference_update(alias.asname or alias.name for alias in aliases)
            case (
                ast.If()
                | ast.While()
                | ast.For()
                | ast.AsyncFor()
                | ast.With()
                | ast.AsyncWith()
                | ast.Try()
                | ast.Match()
            ):
                exact.difference_update(_stored_names(statement))
            case _:
                pass


def _is_intersection(node: ast.expr, exact: set[str], shadowed: frozenset[str]) -> bool:
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitAnd):
        return _is_exact_set(node.left, exact, shadowed) and _is_exact_set(node.right, exact, shadowed)
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "intersection"
        and len(node.args) == 1
        and not node.keywords
        and _is_exact_set(node.func.value, exact, shadowed)
        and _is_exact_set(node.args[0], exact, shadowed)
    )


def _is_exact_set(node: ast.expr, exact: set[str], shadowed: frozenset[str]) -> bool:
    if isinstance(node, ast.Set | ast.SetComp):
        return True
    if isinstance(node, ast.Name):
        return node.id in exact
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in {"set", "frozenset"}
        and node.func.id not in shadowed
        and len(node.args) <= 1
        and not node.keywords
    )


def _stored_names(node: ast.AST) -> set[str]:
    return {child.id for child in ast.walk(node) if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store)}


def _named_expression_targets(node: ast.AST) -> set[str]:
    return {expression.target.id for expression in ast.walk(node) if isinstance(expression, ast.NamedExpr)}


def _argument_names(arguments: ast.arguments) -> set[str]:
    return {
        argument.arg
        for argument in (
            *arguments.posonlyargs,
            *arguments.args,
            *arguments.kwonlyargs,
            *((arguments.vararg,) if arguments.vararg is not None else ()),
            *((arguments.kwarg,) if arguments.kwarg is not None else ()),
        )
    }


def _shadowed_builtins(tree: ast.Module) -> frozenset[str]:
    shadowed: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store) and node.id in {"set", "frozenset"}:
            shadowed.add(node.id)
        elif isinstance(node, ast.arg) and node.arg in {"set", "frozenset"}:
            shadowed.add(node.arg)
        elif isinstance(node, ast.alias) and (node.asname or node.name.split(".")[0]) in {"set", "frozenset"}:
            shadowed.add(node.asname or node.name.split(".")[0])
    return frozenset(shadowed)
