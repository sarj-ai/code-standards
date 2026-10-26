from __future__ import annotations

import ast
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, ClassVar, final, override

from sarj_python_lint.rule_base import (
    AutofixPolicy,
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    ProjectRule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
    Severity,
    is_suppressed,
)
from sarj_python_lint.rules._ast_index import walk as walk_ast
from sarj_python_lint.rules._dict_key_views import proven_dict_key_views
from sarj_python_lint.rules._project_index import ProjectIndexSet
from sarj_python_lint.rules._set_fields import declared_set_fields


if TYPE_CHECKING:
    from pathlib import Path

    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rules._ast_index import NodeIndex


_TRACKED_BUILTINS = frozenset(
    {
        "bool",
        "dict",
        "enumerate",
        "filter",
        "frozenset",
        "list",
        "map",
        "range",
        "reversed",
        "set",
        "tuple",
        "zip",
    }
)


@final
class PreferSetIsdisjoint(ProjectRule):
    id = "prefer-set-isdisjoint"
    code = "SARJ431"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        default_level=Severity.ERROR,
        summary="Prefer `set.isdisjoint` when a built-in set intersection is used only as a boolean predicate.",
        rationale="`isdisjoint` names the overlap predicate directly and avoids allocating an intersection that is immediately discarded.",
        remediation="Use `left.isdisjoint(right)` and negate it when the condition requires overlap.",
        category=RuleCategory.STYLE,
        autofix=AutofixPolicy.SAFE,
        limitations=(
            "Safe fixes require both operands to be comment-free set literals containing only native primitive constants. Dynamic/custom elements and nonliteral operands remain review-only.",
            "Explicit unshadowed built-in bool calls are predicates even in assignments and returns. Raw stored or returned intersections remain values, not predicates.",
            "Set receivers must come from a literal, comprehension, constructor, dominating local assignment, or an unchanged parameter's directly declared first-party set/frozenset field.",
            "Dictionary key-view receivers require a literal/comprehension/constructor or one unreassigned, dominating local binding. Custom mappings and unproven parameters are excluded.",
            "Declared fields rely on the annotated contract. Unknown or union field types, properties, explicit owner/field reassignment, branch-merged bindings, stored intersections, and generated files are excluded. Captured bindings in deferred lambda/generator bodies and starred intersection arguments are excluded. The other operand must be a known iterable.",
            "Nonliteral intersections remain suggestions because short-circuiting may make custom element equality or hashing side effects observable.",
        ),
        examples=(
            RuleExample(
                example_id="discarded-intersection",
                title="A declared set field is used only for an overlap test",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile(PurePosixPath("pyproject.toml"), '[project]\nname = "example"\nversion = "0.1.0"\n'),
                    ExampleFile.python(
                        "app/policy.py",
                        "class AccessCase:\n    tags: frozenset[str]\n\ndef accepts(case: AccessCase):\n    return bool(case.tags & {'read', 'write'})\n",
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
            RuleExample(
                example_id="safe-autofix-subset",
                title="A proven subset has a convergent automatic fix",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/service.py", ("def overlaps():\n    return bool({'one', 'two'} & {'two'})\n")
                    ),
                ),
                fixed_files=(
                    ExampleFile.python(
                        "app/service.py",
                        ("def overlaps():\n    return bool((not ({'one', 'two'}).isdisjoint({'two'})))\n"),
                    ),
                ),
                focus_path=PurePosixPath("app/service.py"),
                expected_count=1,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        path = context.path
        source = context.source
        if ("&" not in source and "intersection" not in context.symbol_source) or context.generated:
            return []
        tree = context.tree
        if tree is None:
            return []
        project = context.session.project or ProjectIndexSet.single(path, source)
        fields = {
            node: declared_set_fields(node, project, context)
            for node in context.nodes(ast.FunctionDef, ast.AsyncFunctionDef)
        }
        shadowed = _shadowed_builtins(tree, node_index=context.node_index)
        scanner = _Scanner(path, context.source_lines, shadowed, fields, proven_dict_key_views(tree, shadowed))
        scanner.scan_body(tree.body, set())
        scanner.diagnostics.sort(key=lambda item: (item.line, item.col))
        return scanner.diagnostics


@final
class _Scanner:
    def __init__(
        self,
        path: Path,
        source_lines: list[str],
        shadowed: frozenset[str],
        fields: dict[ast.FunctionDef | ast.AsyncFunctionDef, set[str]],
        key_views: set[ast.Call],
    ) -> None:
        self.path = path
        self.source_lines = source_lines
        self.shadowed = shadowed
        self.diagnostics: list[Diagnostic] = []
        self.reported: set[int] = set()
        self.fields = fields
        self.key_views = key_views

    def scan_body(self, body: list[ast.stmt], exact: set[str]) -> None:
        local = set(exact)
        for statement in body:
            self._scan_statement(statement, local)
            self._update_binding(statement, local)

    def _scan_statement(self, statement: ast.stmt, exact: set[str]) -> None:
        exact.difference_update(_named_expression_targets(statement))
        if isinstance(
            statement,
            ast.If | ast.While | ast.For | ast.AsyncFor | ast.With | ast.AsyncWith | ast.Try | ast.Match,
        ):
            stored = _stored_names(statement)
            if "*" in stored:
                exact.clear()
            else:
                exact.difference_update(stored)
        match statement:
            case ast.If() | ast.While():
                self._scan_boolean(statement.test, exact)
                self._scan_embedded(statement.test, exact)
                self.scan_body(statement.body, set(exact))
                self.scan_body(statement.orelse, set(exact))
            case ast.Assert(test=test):
                self._scan_boolean(test, exact)
                self._scan_embedded(test, exact)
            case ast.FunctionDef() | ast.AsyncFunctionDef():
                self.scan_body(statement.body, self.fields.get(statement, set()))
            case ast.ClassDef():
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
                    self._scan_embedded(item.context_expr, nested)
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
            self._scan_embedded(expression.body, set())
            return
        if _is_builtin_bool_call(expression, self.shadowed) or (
            isinstance(expression, ast.UnaryOp)
            and isinstance(expression.op, ast.Not)
            and _is_builtin_bool_call(expression.operand, self.shadowed)
        ):
            self._scan_boolean(expression, exact)
        if isinstance(expression, ast.IfExp):
            self._scan_boolean(expression.test, exact)
        if isinstance(expression, ast.DictComp):
            nested = self._scan_comprehensions(expression.generators, exact)
            self._scan_embedded(expression.key, nested)
            self._scan_embedded(expression.value, nested)
            return
        if isinstance(expression, ast.GeneratorExp):
            self._scan_embedded(expression.generators[0].iter, exact)
            exact = set()
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
        if isinstance(candidate, ast.Call) and _is_builtin_bool_call(candidate, self.shadowed):
            candidate = candidate.args[0]
        if _is_intersection(candidate, safe_exact, self.shadowed, self.key_views):
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
                _invalidate_imported_bindings(aliases, exact)
            case _:
                pass


def _is_intersection(node: ast.expr, exact: set[str], shadowed: frozenset[str], key_views: set[ast.Call]) -> bool:
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitAnd):
        return (_is_exact_set(node.left, exact, shadowed) or node.left in key_views) and _is_proven_iterable(
            node.right, exact, shadowed
        )
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "intersection"
        and len(node.args) == 1
        and not isinstance(node.args[0], ast.Starred)
        and not node.keywords
        and _is_exact_set(node.func.value, exact, shadowed)
    )


def _is_builtin_bool_call(node: ast.expr, shadowed: frozenset[str]) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "bool"
        and node.func.id not in shadowed
        and len(node.args) == 1
        and not node.keywords
    )


def _is_exact_set(node: ast.expr, exact: set[str], shadowed: frozenset[str]) -> bool:
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        return f"{node.value.id}.{node.attr}" in exact
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


def _is_proven_iterable(node: ast.expr, exact: set[str], shadowed: frozenset[str]) -> bool:
    if _is_exact_set(node, exact, shadowed):
        return True
    if isinstance(
        node,
        ast.List | ast.Tuple | ast.Dict | ast.ListComp | ast.DictComp | ast.GeneratorExp | ast.Constant,
    ):
        return not isinstance(node, ast.Constant) or isinstance(node.value, str | bytes)
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"items", "keys", "values"}
        and not node.args
        and not node.keywords
    ):
        return True
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in {"dict", "enumerate", "filter", "list", "map", "range", "reversed", "tuple", "zip"}
        and node.func.id not in shadowed
    )


def _stored_names(node: ast.AST, *, node_index: NodeIndex | None = None) -> set[str]:
    names: set[str] = set()
    for child in walk_ast(node, index=node_index):
        match child:
            case (
                ast.Name(id=name, ctx=ast.Store() | ast.Del())
                | ast.arg(arg=name)
                | ast.FunctionDef(name=name)
                | ast.AsyncFunctionDef(name=name)
                | ast.ClassDef(name=name)
                | ast.ExceptHandler(name=name)
                | ast.MatchAs(name=name)
                | ast.MatchStar(name=name)
                | ast.MatchMapping(rest=name)
            ):
                if name is not None:
                    names.add(name)
            case ast.alias(name=name, asname=alias):
                names.add(alias or name.split(".")[0])
            case _:
                pass
    return names


def _named_expression_targets(node: ast.AST) -> set[str]:
    return {expression.target.id for expression in walk_ast(node) if isinstance(expression, ast.NamedExpr)}


def _shadowed_builtins(tree: ast.Module, *, node_index: NodeIndex | None = None) -> frozenset[str]:
    stored = _stored_names(tree, node_index=node_index)
    return _TRACKED_BUILTINS if "*" in stored else frozenset(stored.intersection(_TRACKED_BUILTINS))


def _invalidate_imported_bindings(aliases: list[ast.alias], exact: set[str]) -> None:
    if any(alias.name == "*" for alias in aliases):
        exact.clear()
    else:
        exact.difference_update(alias.asname or alias.name for alias in aliases)
