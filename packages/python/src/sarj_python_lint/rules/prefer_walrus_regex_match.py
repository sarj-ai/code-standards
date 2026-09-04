from __future__ import annotations

import ast
from pathlib import Path, PurePosixPath
import re
from typing import ClassVar, NamedTuple, override

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
from sarj_python_lint.rules._ast_index import children, nodes, walk
from sarj_python_lint.rules._paths import is_generated, is_test_path


class _RegexImports(NamedTuple):
    modules: frozenset[str]
    compile_functions: frozenset[str]


class _RegexEnvironment(NamedTuple):
    modules: frozenset[str]
    compile_functions: frozenset[str]
    compiled_names: frozenset[str]


class _AnalysisContext(NamedTuple):
    environment: _RegexEnvironment
    module_body: list[ast.stmt]
    module_non_imports: frozenset[str]
    parents: dict[ast.AST, ast.AST]
    source: str
    source_lines: list[str]
    path: Path
    code: str


class _BodyState(NamedTuple):
    environment: _RegexEnvironment
    annotated_names: frozenset[str]
    binding_counts: dict[str, int]


_CALL_CANDIDATE_RE = re.compile(r"\.(?:search|match|fullmatch)\s*\(")
_MATCH_METHODS = frozenset({"search", "match", "fullmatch"})
_MAX_REWRITE_COLUMNS = 100


class PreferWalrusRegexMatch(Rule):
    id: str = "prefer-walrus-regex-match"
    code: str = "SARJ081"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="A proven regex Match-or-None result is assigned only for the following condition.",
        rationale="A named expression can keep a short regex operation with its only condition while preserving access to the result.",
        remediation=(
            "For a truthy check, use `if (match := pattern.search(text)):`. "
            "For an explicit None check, preserve it as `if (match := pattern.search(text)) is not None:`."
        ),
        category=RuleCategory.STYLE,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only a short, single-line assignment physically followed by a truthy or `is not None` check is analyzed.",
            "The receiver must resolve to an imported `re` or `regex` module, a unique compile binding, or a parameter annotated as its Pattern type.",
            "Tests, generated files, comments or blank lines between statements, rewrites over 100 columns, rebindings, and later result uses are excluded.",
        ),
        examples=(
            RuleExample(
                example_id="assigned-regex-result",
                title="Regex result is assigned before its condition",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/parser.py",
                        "import re\n\n"
                        "def first_number(text: str) -> str | None:\n"
                        '    match = re.search(r"\\d+", text)\n'
                        "    if match:\n"
                        "        return match.group(0)\n"
                        "    return None\n",
                    ),
                ),
                focus_path=PurePosixPath("app/parser.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="conditional-regex-binding",
                title="Regex result is bound in its condition",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/parser.py",
                        "import re\n\n"
                        "def first_number(text: str) -> str | None:\n"
                        '    if (match := re.search(r"\\d+", text)):\n'
                        "        return match.group(0)\n"
                        "    return None\n",
                    ),
                ),
                focus_path=PurePosixPath("app/parser.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description: str = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if _CALL_CANDIDATE_RE.search(source) is None or is_test_path(path) or is_generated(path, source):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []

        source_lines = source.splitlines()
        diags: list[Diagnostic] = []
        parents = {child: parent for parent in nodes(tree, ast.AST) for child in children(parent)}
        regex_imports = _regex_imports(tree.body)
        module_non_imports = _scope_non_import_bindings(tree.body)
        module_names = regex_imports.modules - module_non_imports
        compile_functions = regex_imports.compile_functions - module_non_imports
        module_compiled = _compiled_bindings(
            tree.body,
            module_names,
            compile_functions,
            binding_counts=_scope_binding_counts(tree.body),
        )
        context = _AnalysisContext(
            _RegexEnvironment(module_names, compile_functions, module_compiled),
            tree.body,
            module_non_imports,
            parents,
            source,
            source_lines,
            path,
            self.code,
        )

        for node in walk(tree):
            raw_body = getattr(node, "body", None)
            if not isinstance(raw_body, list):
                continue
            body: list[ast.stmt] = [st for st in raw_body if isinstance(st, ast.stmt)]  # pyright: ignore[reportUnknownVariableType]
            diags.extend(_check_body(node, body, context))

        return sorted(diags, key=lambda d: (d.line, d.col))


def _check_body(node: ast.AST, body: list[ast.stmt], context: _AnalysisContext) -> list[Diagnostic]:
    owner = _lexical_owner(node, context.parents)
    state = _body_state(node, owner, body, context)
    diagnostics: list[Diagnostic] = []
    for index in range(len(body) - 1):
        diagnostic = _diagnostic_for_pair(body, index, state, context)
        if diagnostic is not None:
            diagnostics.append(diagnostic)
    return diagnostics


def _body_state(
    node: ast.AST,
    owner: ast.Module | ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef,
    body: list[ast.stmt],
    context: _AnalysisContext,
) -> _BodyState:
    shadowed = (
        _owner_bindings(owner)
        if isinstance(owner, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        else context.module_non_imports
    )
    environment = context.environment
    if isinstance(owner, ast.ClassDef) or (isinstance(owner, ast.Module) and node is owner):
        inherited = _RegexEnvironment(frozenset(), frozenset(), frozenset())
    elif isinstance(owner, ast.Module):
        inherited = _module_environment_before(node, context)
    else:
        inherited = _RegexEnvironment(
            environment.modules - shadowed,
            environment.compile_functions - shadowed,
            environment.compiled_names - shadowed,
        )
    return _BodyState(
        inherited,
        _annotated_pattern_parameters(owner, inherited.modules),
        _scope_binding_counts(body),
    )


def _module_environment_before(node: ast.AST, context: _AnalysisContext) -> _RegexEnvironment:
    top_level = node
    while not isinstance(context.parents.get(top_level), ast.Module):
        parent = context.parents.get(top_level)
        if parent is None:  # pragma: no cover - node is known to be below the parsed module.
            return _RegexEnvironment(frozenset(), frozenset(), frozenset())
        top_level = parent
    index = next(i for i, statement in enumerate(context.module_body) if statement is top_level)
    prefix = context.module_body[:index]
    imports = _regex_imports(prefix)
    non_imports = _scope_non_import_bindings(prefix)
    modules = imports.modules - non_imports
    compile_functions = imports.compile_functions - non_imports
    compiled_names = _compiled_bindings(
        prefix,
        modules,
        compile_functions,
        binding_counts=_scope_binding_counts(context.module_body),
    )
    return _RegexEnvironment(modules, compile_functions, compiled_names)


def _diagnostic_for_pair(
    body: list[ast.stmt],
    index: int,
    state: _BodyState,
    context: _AnalysisContext,
) -> Diagnostic | None:
    assignment, condition = body[index], body[index + 1]
    if not (
        isinstance(assignment, ast.Assign)
        and len(assignment.targets) == 1
        and isinstance(assignment.targets[0], ast.Name)
        and isinstance(condition, ast.If)
    ):
        return None
    name = assignment.targets[0].id
    if not _is_compact_physical_pair(assignment, condition, name, context.source, context.source_lines):
        return None
    environment = _environment_before(body, index, state)
    if not _is_regex_call(
        assignment.value,
        module_names=environment.modules,
        compiled_names=environment.compiled_names,
        annotated_names=state.annotated_names,
    ):
        return None
    if _is_name_used_after(body, index + 2, name) or is_suppressed(context.source_lines, assignment.lineno, context.code):
        return None
    return Diagnostic(
        path=context.path,
        line=assignment.lineno,
        col=assignment.col_offset + 1,
        code=context.code,
        message=(
            f"Regex result `{name}` is assigned only for the following condition — "
            "bind it there with a named expression while preserving the same test."
        ),
    )


def _is_regex_call(
    node: ast.AST,
    *,
    module_names: frozenset[str],
    compiled_names: frozenset[str],
    annotated_names: frozenset[str],
) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    return (
        isinstance(func, ast.Attribute)
        and func.attr in _MATCH_METHODS
        and isinstance(func.value, ast.Name)
        and func.value.id in module_names | compiled_names | annotated_names
    )


def _is_name_used_after(stmts: list[ast.stmt], start_idx: int, name: str) -> bool:
    class UsageVisitor(ast.NodeVisitor):
        used: bool = False

        def visit_Name(self, node: ast.Name) -> None:
            if node.id == name:
                self.used = True
            self.generic_visit(node)

    visitor = UsageVisitor()
    for st in stmts[start_idx:]:
        visitor.visit(st)
        if visitor.used:
            return True
    return False


def _environment_before(body: list[ast.stmt], index: int, state: _BodyState) -> _RegexEnvironment:
    prefix = body[:index]
    local_imports = _regex_imports(prefix)
    non_imports = _scope_non_import_bindings(prefix)
    modules = state.environment.modules | (local_imports.modules - non_imports)
    compile_functions = state.environment.compile_functions | (local_imports.compile_functions - non_imports)
    compiled_names = state.environment.compiled_names | _compiled_bindings(
        prefix,
        modules,
        compile_functions,
        binding_counts=state.binding_counts,
    )
    return _RegexEnvironment(modules, compile_functions, compiled_names)


def _regex_imports(body: list[ast.stmt]) -> _RegexImports:
    modules: set[str] = set()
    functions: set[str] = set()
    for statement in body:
        match statement:
            case ast.Import(names=names):
                modules.update(alias.asname or alias.name for alias in names if alias.name in {"re", "regex"})
            case ast.ImportFrom(module=module, level=0, names=names) if module in {"re", "regex"}:
                functions.update(alias.asname or alias.name for alias in names if alias.name == "compile")
            case _:
                continue
    return _RegexImports(frozenset(modules), frozenset(functions))


def _compiled_bindings(
    body: list[ast.stmt],
    regex_modules: frozenset[str],
    compile_functions: frozenset[str],
    *,
    binding_counts: dict[str, int],
) -> frozenset[str]:
    assignments: dict[str, list[ast.expr]] = {}
    for statement in body:
        match statement:
            case (
                ast.Assign(targets=[ast.Name(id=name)], value=value)
                | ast.AnnAssign(target=ast.Name(id=name), value=ast.expr() as value)
            ) if _is_compile_call(value, regex_modules, compile_functions):
                assignments.setdefault(name, []).append(value)
            case _:
                continue
    if not assignments:
        return frozenset()
    return frozenset(name for name, values in assignments.items() if binding_counts.get(name) == 1 and len(values) == 1)


def _owner_bindings(node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> frozenset[str]:
    names = set(_scope_binding_counts(node.body))
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        args = node.args
        names.update(argument.arg for argument in (*args.posonlyargs, *args.args, *args.kwonlyargs))
        if args.vararg is not None:
            names.add(args.vararg.arg)
        if args.kwarg is not None:
            names.add(args.kwarg.arg)
    return frozenset(names)


def _lexical_owner(
    node: ast.AST,
    parents: dict[ast.AST, ast.AST],
) -> ast.Module | ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef:
    current = node
    while True:
        if isinstance(current, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            return current
        parent = parents.get(current)
        if parent is None:  # pragma: no cover - every walked node belongs to the parsed module.
            msg = "AST node has no lexical owner"
            raise RuntimeError(msg)
        current = parent


def _annotated_pattern_parameters(
    owner: ast.Module | ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef,
    module_names: frozenset[str],
) -> frozenset[str]:
    if not isinstance(owner, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return frozenset()
    args = owner.args
    parameters = (*args.posonlyargs, *args.args, *args.kwonlyargs)
    return frozenset(
        parameter.arg
        for parameter in parameters
        if parameter.annotation is not None and _is_pattern_annotation(parameter.annotation, module_names)
    )


def _is_pattern_annotation(annotation: ast.expr, module_names: frozenset[str]) -> bool:
    value = annotation.value if isinstance(annotation, ast.Subscript) else annotation
    return (
        isinstance(value, ast.Attribute)
        and value.attr == "Pattern"
        and isinstance(value.value, ast.Name)
        and value.value.id in module_names
    )


def _is_compact_physical_pair(
    assignment: ast.Assign,
    condition: ast.If,
    name: str,
    source: str,
    source_lines: list[str],
) -> bool:
    if assignment.end_lineno != assignment.lineno or condition.lineno != assignment.lineno + 1:
        return False
    kind = _condition_kind(condition.test, name)
    if kind is None:
        return False
    value = ast.get_source_segment(source, assignment.value)
    if value is None:
        return False
    line = source_lines[assignment.lineno - 1]
    end_col = assignment.end_col_offset
    if end_col is not None and "#" in line[end_col:]:
        return False
    suffix = " is not None" if kind == "not-none" else ""
    proposed = f"{' ' * condition.col_offset}if ({name} := {value}){suffix}:"
    return len(proposed) <= _MAX_REWRITE_COLUMNS


def _condition_kind(test_node: ast.AST, var_name: str) -> str | None:
    if isinstance(test_node, ast.Name) and test_node.id == var_name:
        return "truthy"
    if (
        isinstance(test_node, ast.Compare)
        and isinstance(test_node.left, ast.Name)
        and test_node.left.id == var_name
        and len(test_node.ops) == 1
        and isinstance(test_node.ops[0], ast.IsNot)
    ):
        right = test_node.comparators[0]
        if isinstance(right, ast.Constant) and right.value is None:
            return "not-none"
    return None


def _scope_binding_counts(body: list[ast.stmt]) -> dict[str, int]:
    counts: dict[str, int] = {}

    def record(name: str) -> None:
        counts[name] = counts.get(name, 0) + 1

    stack: list[ast.AST] = list(body)
    while stack:
        node = stack.pop()
        match node:
            case ast.FunctionDef() | ast.AsyncFunctionDef() | ast.ClassDef():
                record(node.name)
                continue
            case ast.Lambda():
                continue
            case ast.Name(id=name, ctx=ast.Store() | ast.Del()):
                record(name)
            case ast.alias(name=name, asname=asname):
                record(asname or name.split(".", maxsplit=1)[0])
            case ast.ExceptHandler() | ast.MatchAs() | ast.MatchStar():
                if node.name is not None:
                    record(node.name)
            case ast.MatchMapping(rest=str() as name):
                record(name)
            case _:
                pass
        stack.extend(ast.iter_child_nodes(node))
    return counts


def _scope_non_import_bindings(body: list[ast.stmt]) -> frozenset[str]:
    names: set[str] = set()
    stack: list[ast.AST] = list(body)
    while stack:
        node = stack.pop()
        match node:
            case ast.FunctionDef() | ast.AsyncFunctionDef() | ast.ClassDef():
                names.add(node.name)
                continue
            case ast.Lambda() | ast.alias():
                continue
            case ast.Name(id=name, ctx=ast.Store() | ast.Del()):
                names.add(name)
            case ast.ExceptHandler() | ast.MatchAs() | ast.MatchStar():
                if node.name is not None:
                    names.add(node.name)
            case ast.MatchMapping(rest=str() as name):
                names.add(name)
            case _:
                pass
        stack.extend(ast.iter_child_nodes(node))
    return frozenset(names)


def _is_compile_call(
    value: ast.expr,
    regex_modules: frozenset[str],
    compile_functions: frozenset[str],
) -> bool:
    if not isinstance(value, ast.Call):
        return False
    func = value.func
    if isinstance(func, ast.Name):
        return func.id in compile_functions
    return (
        isinstance(func, ast.Attribute)
        and func.attr == "compile"
        and isinstance(func.value, ast.Name)
        and func.value.id in regex_modules
    )
