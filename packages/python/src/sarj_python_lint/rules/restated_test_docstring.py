from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType
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
from sarj_python_lint.rules._ast_index import children
from sarj_python_lint.rules._comments import is_protected, split_identifier, stem
from sarj_python_lint.rules._docstrings import (
    VALUE_MARKER_RE,
    docstring_expression,
    restates,
    sections,
    signature_stems,
)
from sarj_python_lint.rules._imports import ImportIndex
from sarj_python_lint.rules._paths import is_generated, is_test_path


if TYPE_CHECKING:
    from collections.abc import Iterator


# The vocabulary a test docstring spends on *being a test*.
_TEST_CEREMONY = (
    "assert",
    "asserted",
    "asserts",
    "behavior",
    "behaviour",
    "case",
    "cases",
    "check",
    "checked",
    "checking",
    "checks",
    "confirm",
    "confirmed",
    "confirms",
    "correctly",
    "coverage",
    "covered",
    "covers",
    "ensure",
    "ensured",
    "ensures",
    "ensuring",
    "exercise",
    "exercises",
    "expect",
    "expected",
    "expects",
    "happy",
    "integration",
    "path",
    "properly",
    "regression",
    "scenario",
    "scenarios",
    "successful",
    "successfully",
    "test",
    "tested",
    "testing",
    "tests",
    "unit",
    "validate",
    "validated",
    "validates",
    "verified",
    "verifies",
    "verify",
    "verifying",
)

_CEREMONY_STEMS = frozenset(stem(word) for word in _TEST_CEREMONY)

# Sections other than the summary are SARJ086/087's subject.
_SUMMARY_ONLY = frozenset({"summary"})
_GETATTR_MIN_ARGS = 2
_PYTEST = frozenset({"pytest"})
_MESSAGE = (
    "this collected test docstring only repeats names and visible code; delete it or retain only non-obvious "
    "regression context"
)


# The keyword singletons.
_SINGLETONS = MappingProxyType({None: "none", True: "true", False: "false"})


@dataclass(slots=True)
class _ScanContext:
    path: Path
    source_lines: list[str]
    consumed_nodes: set[int]
    imports: ImportIndex
    module_opt_outs: frozenset[str]
    diagnostics: list[Diagnostic]


def _body_stems(node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    tokens: list[str] = []
    for child in _lexical_body_nodes(node):
        match child:
            case ast.Name():
                tokens.extend(split_identifier(child.id))
            case ast.Attribute():
                tokens.extend(split_identifier(child.attr))
            case ast.keyword(arg=str(arg)):
                tokens.extend(split_identifier(arg))
            case ast.arg():
                tokens.extend(split_identifier(child.arg))
            case ast.FunctionDef() | ast.AsyncFunctionDef() | ast.ClassDef():
                tokens.extend(split_identifier(child.name))
            case ast.Constant():
                word = next((w for key, w in _SINGLETONS.items() if child.value is key), None)
                if word is not None:
                    tokens.append(word)
            case _:
                continue
    return {stem(token) for token in tokens}


def _lexical_body_nodes(node: ast.FunctionDef | ast.AsyncFunctionDef) -> Iterator[ast.AST]:
    pending: list[ast.AST] = list(node.body)
    while pending:
        current = pending.pop()
        yield current
        if isinstance(current, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef | ast.Lambda):
            continue
        pending.extend(children(current))


def _is_collectible_test_class(
    node: ast.ClassDef,
    imports: ImportIndex,
    module_opt_outs: frozenset[str],
) -> bool:
    return (
        node.name.startswith("Test")
        and node.name not in module_opt_outs
        and not node.bases
        and not node.keywords
        and _has_only_safe_pytest_marks(node.decorator_list, imports)
        and not _class_opts_out(node)
        and not any(
            isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef) and child.name in {"__init__", "__new__"}
            for child in node.body
        )
    )


def _has_only_safe_pytest_marks(
    decorators: list[ast.expr],
    imports: ImportIndex,
    shadowed: frozenset[str] = frozenset(),
) -> bool:
    return all(_is_pytest_mark(decorator, imports, shadowed) for decorator in decorators)


def _is_pytest_mark(decorator: ast.expr, imports: ImportIndex, shadowed: frozenset[str]) -> bool:
    target = decorator.func if isinstance(decorator, ast.Call) else decorator
    root = _root_name(target)
    return (
        root is not None
        and root not in shadowed
        and isinstance(target, ast.Attribute)
        and imports.resolves(target.value, sources=_PYTEST, symbol="mark")
    )


def _root_name(node: ast.expr) -> str | None:
    current = node
    while isinstance(current, ast.Attribute):
        current = current.value
    return current.id if isinstance(current, ast.Name) else None


def _class_opts_out(node: ast.ClassDef) -> bool:
    for statement in _lexical_statements(node.body):
        match statement:
            case ast.Assign(targets=targets, value=value) if any(
                isinstance(target, ast.Name) and target.id == "__test__" for target in targets
            ):
                if not _is_literal_true(value):
                    return True
            case ast.AnnAssign(target=ast.Name(id="__test__"), value=value):
                if not _is_literal_true(value):
                    return True
            case _:
                continue
    return False


def _is_literal_true(node: ast.expr | None) -> bool:
    return isinstance(node, ast.Constant) and node.value is True


class RestatedTestDocstring(Rule):
    id: str = "restated-test-docstring"
    code: str = "SARJ088"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="Collected test docstring only repeats names and visible code.",
        rationale="A docstring that narrates visible test code creates duplicate prose that can drift without explaining the regression or contract.",
        remediation=(
            "Delete only the restatement and put the scenario and expected outcome in the test name. Keep concise "
            "non-obvious regression, constraint, or contract context in the docstring or a local comment."
        ),
        category=RuleCategory.TESTING,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only module-level test* functions and methods of base-free, constructor-free Test* classes in recognized test files are checked; import-proven pytest marks are allowed, while other decorators abstain.",
            "Structured, protected, value-bearing, generated, runtime-consumed, and lexically non-restating docstrings are preserved; semantic paraphrases are not inferred.",
            "Literal or ambiguous __test__ opt-outs are excluded; repository-specific pytest collection-name overrides are not inferred.",
        ),
        examples=(
            RuleExample(
                example_id="test-name-restatement",
                title="Docstring repeats the test name",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_widget.py",
                        'def test_widget_renders():\n    """Verify that the widget renders correctly."""\n    assert render(widget)\n',
                    ),
                ),
                focus_path=PurePosixPath("tests/test_widget.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="test-regression-context",
                title="Docstring records a hidden failure mode",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_widget.py",
                        'def test_widget_renders():\n    """Without the stable key, retries would render the widget twice."""\n    assert render(widget)\n',
                    ),
                ),
                focus_path=PurePosixPath("tests/test_widget.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description: str = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if is_generated(path, source) or not is_test_path(path):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        source_lines = source.splitlines()
        consumed_nodes = _consumed_docstring_owners(tree)
        diags: list[Diagnostic] = []
        context = _ScanContext(
            path=path,
            source_lines=source_lines,
            consumed_nodes=consumed_nodes,
            imports=ImportIndex.from_tree(tree, module_scope_only=True),
            module_opt_outs=_attribute_test_opt_outs(tree.body),
            diagnostics=diags,
        )
        self._walk(tree, None, context)
        return sorted(diags, key=lambda diag: diag.line)

    def _walk(self, node: ast.AST, owner: ast.ClassDef | None, context: _ScanContext) -> None:
        for child in children(node):
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                opt_outs = context.module_opt_outs if owner is None else _attribute_test_opt_outs(owner.body)
                shadowed: frozenset[str] = frozenset() if owner is None else _class_bindings_before(owner, child)
                if (
                    child.name.startswith("test")
                    and child.name not in opt_outs
                    and _has_only_safe_pytest_marks(child.decorator_list, context.imports, shadowed)
                ):
                    self._check_function(child, owner.name if owner is not None else None, context)
            elif isinstance(child, ast.ClassDef):
                if owner is None and _is_collectible_test_class(child, context.imports, context.module_opt_outs):
                    self._check_class(child, context)
                    self._walk(child, child, context)
            else:
                self._walk(child, owner, context)

    def _check_class(self, node: ast.ClassDef, context: _ScanContext) -> None:
        if id(node) in context.consumed_nodes:
            return
        docstring = ast.get_docstring(node, clean=True)
        if not docstring or not self._is_plain_summary(docstring):
            return
        class_stems = {stem(part) for part in split_identifier(node.name)} | _CEREMONY_STEMS
        candidates = [class_stems]
        candidates.extend(
            class_stems | signature_stems(child, node.name)
            for child in node.body
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef)
        )
        if not any(restates(docstring, known) for known in candidates):
            return
        expr = docstring_expression(node)
        if expr is None:
            return
        if _is_docstring_suppressed(context.source_lines, expr, self.code):
            return
        context.diagnostics.append(
            Diagnostic(
                path=context.path,
                line=expr.lineno,
                col=expr.col_offset + 1,
                code=self.code,
                message=_MESSAGE,
                severity=Severity.WARNING,
            )
        )

    @staticmethod
    def _is_plain_summary(docstring: str) -> bool:
        if frozenset(sections(docstring)) != _SUMMARY_ONLY:
            return False
        return not is_protected(docstring) and not VALUE_MARKER_RE.search(docstring)

    def _check_function(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        class_name: str | None,
        context: _ScanContext,
    ) -> None:
        if id(node) in context.consumed_nodes:
            return
        docstring = ast.get_docstring(node, clean=True)
        if not docstring or not self._is_plain_summary(docstring):
            return
        known = signature_stems(node, class_name) | _body_stems(node) | _CEREMONY_STEMS
        if not restates(docstring, known):
            return
        expr = docstring_expression(node)
        if expr is None:
            return
        if _is_docstring_suppressed(context.source_lines, expr, self.code):
            return
        context.diagnostics.append(
            Diagnostic(
                path=context.path,
                line=expr.lineno,
                col=expr.col_offset + 1,
                code=self.code,
                message=_MESSAGE,
                severity=Severity.WARNING,
            )
        )


def _is_docstring_suppressed(source_lines: list[str], expression: ast.Expr, code: str) -> bool:
    end = expression.end_lineno or expression.lineno
    return any(is_suppressed(source_lines, line, code) for line in range(expression.lineno, end + 1))


def _attribute_test_opt_outs(statements: list[ast.stmt]) -> frozenset[str]:
    opted_out: set[str] = set()
    for statement in _lexical_statements(statements):
        match statement:
            case ast.Assign(targets=targets, value=value):
                for target in targets:
                    if (name := _test_attribute_owner(target)) and not _is_literal_true(value):
                        opted_out.add(name)
            case ast.AnnAssign(target=target, value=value):
                if (name := _test_attribute_owner(target)) and not _is_literal_true(value):
                    opted_out.add(name)
            case _:
                continue
    return frozenset(opted_out)


def _test_attribute_owner(node: ast.expr) -> str | None:
    if isinstance(node, ast.Attribute) and node.attr == "__test__" and isinstance(node.value, ast.Name):
        return node.value.id
    return None


def _lexical_statements(statements: list[ast.stmt]) -> Iterator[ast.stmt]:
    pending = list(reversed(statements))
    while pending:
        current = pending.pop()
        yield current
        if isinstance(current, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            continue
        nested = [child for child in children(current) if isinstance(child, ast.stmt)]
        pending.extend(reversed(nested))


def _class_bindings_before(
    owner: ast.ClassDef,
    target: ast.FunctionDef | ast.AsyncFunctionDef,
) -> frozenset[str]:
    bound: set[str] = set()
    for statement in _lexical_statements(owner.body):
        if statement is target:
            break
        bound.update(_direct_bound_names(statement))
    return frozenset(bound)


def _consumed_docstring_owners(tree: ast.Module) -> set[int]:
    bindings: dict[str, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef | None] = {}
    binding_counts: dict[str, int] = {}
    consumed: set[int] = set()
    for statement in _lexical_statements(tree.body):
        for expression in _direct_expressions(statement):
            for name in _docstring_reader_names(expression):
                owner = bindings.get(name)
                if owner is not None:
                    consumed.add(id(owner))
        alias_owner: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef | None = None
        if isinstance(statement, ast.Assign | ast.AnnAssign) and isinstance(statement.value, ast.Name):
            alias_owner = bindings.get(statement.value.id)
        for name in _direct_bound_names(statement):
            binding_counts[name] = binding_counts.get(name, 0) + 1
            bindings[name] = None
        match statement:
            case ast.FunctionDef() | ast.AsyncFunctionDef() | ast.ClassDef():
                bindings[statement.name] = statement
            case ast.Assign(targets=targets):
                for target in targets:
                    if isinstance(target, ast.Name) and alias_owner is not None:
                        bindings[target.id] = alias_owner
            case ast.AnnAssign(target=ast.Name(id=alias)) if alias_owner is not None:
                bindings[alias] = alias_owner
            case _:
                continue
    for scope in ast.walk(tree):
        if isinstance(scope, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            local_names = _scope_bound_names(scope)
            for name in _scope_docstring_reader_names(scope):
                owner = bindings.get(name)
                if name not in local_names and binding_counts.get(name) == 1 and owner is not None:
                    consumed.add(id(owner))
    return consumed


def _scope_bound_names(scope: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> set[str]:
    bound: set[str] = set()
    if isinstance(scope, ast.FunctionDef | ast.AsyncFunctionDef):
        args = scope.args
        bound.update(
            argument.arg
            for argument in (*args.posonlyargs, *args.args, *args.kwonlyargs, args.vararg, args.kwarg)
            if argument is not None
        )
    for statement in _lexical_statements(scope.body):
        bound.update(_direct_bound_names(statement))
    return bound


def _scope_docstring_reader_names(scope: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> set[str]:
    names: set[str] = set()
    for statement in _lexical_statements(scope.body):
        for expression in _direct_expressions(statement):
            names.update(_docstring_reader_names(expression))
    return names


def _direct_expressions(statement: ast.stmt) -> Iterator[ast.expr]:
    yield from (child for child in children(statement) if isinstance(child, ast.expr))


def _docstring_reader_names(expression: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(expression):
        if isinstance(node, ast.Attribute) and node.attr == "__doc__" and isinstance(node.value, ast.Name):
            names.add(node.value.id)
        elif isinstance(node, ast.Call) and _is_docstring_reader(node) and isinstance(node.args[0], ast.Name):
            names.add(node.args[0].id)
    return names


def _direct_bound_names(statement: ast.stmt) -> set[str]:
    match statement:
        case ast.FunctionDef() | ast.AsyncFunctionDef() | ast.ClassDef():
            return {statement.name}
        case ast.Import(names=names) | ast.ImportFrom(names=names):
            return {alias.asname or alias.name.partition(".")[0] for alias in names}
        case ast.Assign(targets=targets):
            return {name for target in targets for name in _target_names(target)}
        case ast.AnnAssign(target=target) | ast.AugAssign(target=target) | ast.For(
            target=target
        ) | ast.AsyncFor(target=target):
            return _target_names(target)
        case ast.With(items=items) | ast.AsyncWith(items=items):
            return {
                name for item in items if item.optional_vars is not None for name in _target_names(item.optional_vars)
            }
        case _:
            return set()


def _target_names(node: ast.expr) -> set[str]:
    if isinstance(node, ast.Name):
        return {node.id}
    if isinstance(node, ast.Tuple | ast.List):
        return {name for element in node.elts for name in _target_names(element)}
    return set()


def _terminal_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _is_docstring_reader(node: ast.Call) -> bool:
    if not node.args:
        return False
    function = node.func
    if isinstance(function, ast.Name) and function.id == "help":
        return True
    if isinstance(function, ast.Attribute) and function.attr in {"getdoc", "render_doc"}:
        return True
    return (
        isinstance(function, ast.Name)
        and function.id == "getattr"
        and len(node.args) >= _GETATTR_MIN_ARGS
        and isinstance(node.args[1], ast.Constant)
        and node.args[1].value == "__doc__"
    )
