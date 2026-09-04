from __future__ import annotations

import ast
from dataclasses import dataclass
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
    is_suppressed,
    parse_or_none,
)
from sarj_python_lint.rules._imports import ImportIndex
from sarj_python_lint.rules._paths import is_generated, is_test_path


if TYPE_CHECKING:
    from pathlib import Path


GENERAL_SOURCE_SUFFIXES = (
    ".bash",
    ".js",
    ".jsx",
    ".json",
    ".jsonc",
    ".mjs",
    ".py",
    ".sh",
    ".sql",
    ".toml",
    ".ts",
    ".tsx",
    ".yaml",
    ".yml",
)

_REPRESENTATION_DIRS = frozenset({"fixture", "fixtures", "golden", "goldens", "snapshot", "snapshots"})
_PYTEST = frozenset({"pytest"})
_UNITTEST = frozenset({"unittest"})


class TestFunction(NamedTuple):
    function: ast.FunctionDef | ast.AsyncFunctionDef
    unittest_style: bool


@dataclass(frozen=True, slots=True)
class _ApiProvenance:
    imports: ImportIndex
    shadowed: frozenset[str]


@dataclass(frozen=True, slots=True)
class _TextFlow:
    raw_names: set[str]
    path_names: set[str]
    ephemeral_path_names: set[str]
    source_suffixes: tuple[str, ...]
    api: _ApiProvenance


@dataclass(frozen=True, slots=True)
class _FlowState:
    collections: set[str]
    ephemeral_paths: set[str]
    paths: set[str]
    raw: set[str]
    raw_origins: dict[str, set[int]]


_TEXT_TRANSFORMS = frozenset(
    {"casefold", "decode", "lower", "lstrip", "removeprefix", "removesuffix", "replace", "rstrip", "strip", "upper"}
)
_TEXT_ASSERTIONS = frozenset({"count", "endswith", "find", "index", "startswith"})
_REGEX_ASSERTIONS = frozenset({"findall", "finditer", "fullmatch", "match", "search"})
_TEMP_PATH_NAMES = frozenset(
    {"tmp_path", "tmp_path_factory", "tmpdir", "tmpdir_factory", "temp_dir", "temporary_directory"}
)
_UNITTEST_ASSERTIONS = frozenset(
    {
        "assertEqual",
        "assertFalse",
        "assertGreater",
        "assertGreaterEqual",
        "assertIn",
        "assertIs",
        "assertIsNone",
        "assertIsNot",
        "assertIsNotNone",
        "assertNotEqual",
        "assertNotIn",
        "assertNotRegex",
        "assertRegex",
        "assertLess",
        "assertLessEqual",
        "assertTrue",
    }
)


@final
class NoRawSourceTextTestOracle(Rule):
    id = "no-raw-source-text-test-oracle"
    code = "SARJ402"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="Test uses raw text from a source-like project path as its oracle.",
        rationale="Substring and regex checks can pass on comments or unreachable configuration and fail after behavior-preserving formatting changes.",
        remediation=(
            "Parse the artifact, execute its validator, or assert on a runtime contract. If exact bytes or text are "
            "the deliberate compatibility contract, use an exact line suppression with the reason."
        ),
        category=RuleCategory.TESTING,
        autofix=AutofixPolicy.NONE,
        aliases=("source-coupled-test",),
        limitations=(
            "The rule follows local aliases, path aliases, context-managed reads, and common text normalization from source-like code or configuration suffixes; interprocedural flows remain unreported.",
            "Files produced beneath recognized temporary-directory fixtures are generated artifacts, not repository source, and remain unreported.",
            "Paths beneath fixture, golden, and snapshot directories are treated as deliberate representation contracts and remain unreported.",
            "When raw representation is genuinely the contract (for example a golden or compatibility sentinel), use an exact line suppression with the reason.",
        ),
        examples=(
            RuleExample(
                example_id="parsed-workflow-contract",
                title="Assert on parsed workflow behavior",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_policy.py",
                        "from pathlib import Path\n\nimport yaml\n\ndef test_policy():\n    workflow = yaml.safe_load(Path('workflow.yml').read_text())\n    assert workflow['permissions']['contents'] == 'read'\n",
                    ),
                ),
                focus_path=PurePosixPath("tests/test_policy.py"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="workflow-substring-contract",
                title="Do not prove workflow behavior with a substring",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_policy.py",
                        "from pathlib import Path\n\ndef test_policy():\n    source = Path('workflow.yml').read_text()\n    assert 'permissions:' in source\n",
                    ),
                ),
                focus_path=PurePosixPath("tests/test_policy.py"),
                expected_count=1,
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
        if not isinstance(tree, ast.Module):
            return []
        imports = ImportIndex.from_tree(tree, module_scope_only=True)
        source_lines = source.splitlines()
        assertions = [
            assertion
            for function, unittest_style in top_level_test_functions(tree, imports)
            for assertion in FunctionAnalyzer(
                GENERAL_SOURCE_SUFFIXES,
                imports=imports,
                suppression_code=self.code,
                suppression_lines=source_lines,
                unittest_style=unittest_style,
            ).analyze(function)
        ]
        return [
            Diagnostic(
                path=path,
                line=assertion.lineno,
                col=assertion.col_offset + 1,
                code=self.code,
                severity=Severity.WARNING,
                message=(
                    "raw text from a source-like project path is the test oracle; parse or execute the artifact, or "
                    "use an exact SARJ402 suppression when representation is the deliberate contract"
                ),
            )
            for assertion in assertions
        ]


def top_level_test_functions(tree: ast.Module, imports: ImportIndex | None = None) -> list[TestFunction]:
    resolved_imports = imports or ImportIndex.from_tree(tree, module_scope_only=True)
    opted_out = _module_test_opt_outs(tree)
    functions: list[TestFunction] = []
    for statement in tree.body:
        if (
            isinstance(statement, ast.FunctionDef | ast.AsyncFunctionDef)
            and statement.name.startswith("test")
            and statement.name not in opted_out
            and _safe_pytest_decorators(statement.decorator_list, resolved_imports)
        ):
            functions.append(TestFunction(statement, unittest_style=False))
        elif isinstance(statement, ast.ClassDef):
            unittest_style = any(
                resolved_imports.resolves(base, sources=_UNITTEST, symbol="TestCase") for base in statement.bases
            )
            pytest_style = _collectible_pytest_class(statement, resolved_imports, opted_out)
            if not unittest_style and not pytest_style:
                continue
            functions.extend(
                TestFunction(child, unittest_style)
                for child in statement.body
                if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef)
                and child.name.startswith("test")
                and (
                    unittest_style
                    or _safe_pytest_decorators(
                        child.decorator_list,
                        resolved_imports,
                        shadowed=_class_bound_names_before(statement, child),
                    )
                )
            )
    return functions


def _collectible_pytest_class(
    node: ast.ClassDef,
    imports: ImportIndex,
    module_opt_outs: frozenset[str],
) -> bool:
    return (
        node.name.startswith("Test")
        and node.name not in module_opt_outs
        and not node.bases
        and not node.keywords
        and _safe_pytest_decorators(node.decorator_list, imports)
        and not _class_opts_out(node)
        and not any(
            isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef) and child.name in {"__init__", "__new__"}
            for child in node.body
        )
    )


def _safe_pytest_decorators(
    decorators: list[ast.expr],
    imports: ImportIndex,
    *,
    shadowed: frozenset[str] = frozenset(),
) -> bool:
    return all(_is_pytest_mark(decorator, imports, shadowed) for decorator in decorators)


def _is_pytest_mark(decorator: ast.expr, imports: ImportIndex, shadowed: frozenset[str]) -> bool:
    target = decorator.func if isinstance(decorator, ast.Call) else decorator
    return (
        isinstance(target, ast.Attribute)
        and _root_name(target.value) not in shadowed
        and imports.resolves(target.value, sources=_PYTEST, symbol="mark")
    )


def _class_bound_names_before(
    owner: ast.ClassDef,
    method: ast.FunctionDef | ast.AsyncFunctionDef,
) -> frozenset[str]:
    names: set[str] = set()
    for statement in owner.body:
        if statement is method:
            break
        names.update(_lexical_bound_names(statement))
    return frozenset(names)


def _lexical_bound_names(node: ast.AST) -> set[str]:
    names: set[str] = set()
    pending = [node]
    while pending:
        current = pending.pop()
        match current:
            case ast.FunctionDef(name=name) | ast.AsyncFunctionDef(name=name) | ast.ClassDef(name=name):
                names.add(name)
                continue
            case ast.Lambda() | ast.ListComp() | ast.SetComp() | ast.DictComp() | ast.GeneratorExp():
                continue
            case ast.Import(names=aliases) | ast.ImportFrom(names=aliases):
                names.update(alias.asname or alias.name.partition(".")[0] for alias in aliases)
                continue
            case ast.Name(id=name, ctx=(ast.Store() | ast.Del())):
                names.add(name)
            case _:
                pass
        pending.extend(ast.iter_child_nodes(current))
    return names


def _class_opts_out(node: ast.ClassDef) -> bool:
    for statement in node.body:
        match statement:
            case ast.Assign(targets=targets, value=value) if any(
                isinstance(target, ast.Name) and target.id == "__test__" for target in targets
            ):
                if not _literal_true(value):
                    return True
            case ast.AnnAssign(target=ast.Name(id="__test__"), value=value):
                if not _literal_true(value):
                    return True
            case _:
                continue
    return False


def _module_test_opt_outs(tree: ast.Module) -> frozenset[str]:
    names: set[str] = set()
    for statement in tree.body:
        match statement:
            case ast.Assign(targets=targets, value=value):
                for target in targets:
                    if (name := _test_attribute_owner(target)) and not _literal_true(value):
                        names.add(name)
            case ast.AnnAssign(target=target, value=value):
                if (name := _test_attribute_owner(target)) and not _literal_true(value):
                    names.add(name)
            case _:
                continue
    return frozenset(names)


def _test_attribute_owner(node: ast.expr) -> str | None:
    if isinstance(node, ast.Attribute) and node.attr == "__test__" and isinstance(node.value, ast.Name):
        return node.value.id
    return None


def _literal_true(node: ast.expr | None) -> bool:
    return isinstance(node, ast.Constant) and node.value is True


def _node_is_suppressed(source_lines: list[str], node: ast.AST, code: str) -> bool:
    start = getattr(node, "lineno", 0)
    end = getattr(node, "end_lineno", None) or start
    return any(is_suppressed(source_lines, line, code) for line in range(start, end + 1))


class FunctionAnalyzer(ast.NodeVisitor):
    _imports: ImportIndex | None
    _source_suffixes: tuple[str, ...]
    _suppression_code: str | None
    _suppression_lines: list[str] | None
    _unittest_style: bool

    def __init__(
        self,
        source_suffixes: tuple[str, ...],
        *,
        imports: ImportIndex | None = None,
        suppression_code: str | None = None,
        suppression_lines: list[str] | None = None,
        unittest_style: bool = False,
    ) -> None:
        self._source_suffixes = source_suffixes
        self._unittest_style = unittest_style
        self._imports = imports
        self._suppression_code = suppression_code
        self._suppression_lines = suppression_lines
        self._api: _ApiProvenance | None = None
        self._collections: set[str] = set()
        self._ephemeral_paths: set[str] = set()
        self._paths: set[str] = set()
        self._raw: set[str] = set()
        self._raw_origins: dict[str, set[int]] = {}
        self._reported_origins: set[int] = set()
        self._assertions: list[ast.Assert | ast.Call] = []

    def analyze(self, function: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.Assert | ast.Call]:
        imports = self._imports or ImportIndex.from_tree(ast.Module(body=[], type_ignores=[]))
        self._api = _ApiProvenance(imports, _function_bound_names(function))
        arguments = [*function.args.posonlyargs, *function.args.args, *function.args.kwonlyargs]
        self._ephemeral_paths.update(argument.arg for argument in arguments if argument.arg in _TEMP_PATH_NAMES)
        for statement in function.body:
            self.visit(statement)
        return self._assertions

    @override
    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        del node  # A nested helper owns a separate scope and is intentionally not inferred.

    @override
    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        del node

    @override
    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        del node

    @override
    def visit_Lambda(self, node: ast.Lambda) -> None:
        del node

    @override
    def visit_Assign(self, node: ast.Assign) -> None:
        self.visit(node.value)
        for target in node.targets:
            self._record_target(target, node.value)

    @override
    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value is None:
            return
        self.visit(node.value)
        self._record_target(node.target, node.value)

    @override
    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
        self.visit(node.value)
        self._record_target(node.target, node.value)

    @override
    def visit_With(self, node: ast.With | ast.AsyncWith) -> None:
        for item in node.items:
            self.visit(item.context_expr)
            if item.optional_vars is not None:
                self._clear_target(item.optional_vars)
            if isinstance(item.optional_vars, ast.Name) and _is_source_open(
                item.context_expr, self._paths, self._ephemeral_paths, self._source_suffixes, self._provenance
            ):
                self._raw.add(item.optional_vars.id)
                self._raw_origins[item.optional_vars.id] = {item.context_expr.lineno}
        for statement in node.body:
            self.visit(statement)

    @override
    def visit_AsyncWith(self, node: ast.AsyncWith) -> None:
        self.visit_With(node)

    @override
    def visit_Assert(self, node: ast.Assert) -> None:
        if _raw_text_oracle(node.test, self._flow) and not self._suppressed(node):
            origins = _expression_origins(node.test, self._raw_origins, self._flow) or {node.lineno}
            if not origins.issubset(self._reported_origins):
                self._assertions.append(node)
                self._reported_origins.update(origins)
        self.generic_visit(node)

    @override
    def visit_Call(self, node: ast.Call) -> None:
        if (
            self._unittest_style
            and not self._suppressed(node)
            and _unittest_raw_text_oracle(
                node,
                self._flow,
            )
        ):
            origins = _expression_origins(node, self._raw_origins, self._flow) or {node.lineno}
            if not origins.issubset(self._reported_origins):
                self._assertions.append(node)
                self._reported_origins.update(origins)
        self.generic_visit(node)

    @override
    def visit_If(self, node: ast.If) -> None:
        self.visit(node.test)
        initial = self._snapshot()
        for statement in node.body:
            self.visit(statement)
        body = self._snapshot()
        self._restore(initial)
        for statement in node.orelse:
            self.visit(statement)
        otherwise = self._snapshot()
        self._restore(_intersect_flow_states(body, otherwise))

    @override
    def visit_For(self, node: ast.For) -> None:
        self._visit_for(node)

    @override
    def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
        self._visit_for(node)

    @override
    def visit_While(self, node: ast.While) -> None:
        self.visit(node.test)
        initial = self._snapshot()
        for statement in node.body:
            self.visit(statement)
        self._restore(_intersect_flow_states(initial, self._snapshot()))
        for statement in node.orelse:
            self.visit(statement)
        self._restore(_intersect_flow_states(initial, self._snapshot()))

    def _visit_for(self, node: ast.For | ast.AsyncFor) -> None:
        self.visit(node.iter)
        initial = self._snapshot()
        self._clear_target(node.target)
        if isinstance(node.target, ast.Name) and isinstance(node.iter, ast.Name) and node.iter.id in self._collections:
            self._paths.add(node.target.id)
        for statement in node.body:
            self.visit(statement)
        after_body = self._snapshot()
        self._restore(_intersect_flow_states(initial, after_body))
        for statement in node.orelse:
            self.visit(statement)
        self._restore(_intersect_flow_states(initial, self._snapshot()))

    @override
    def visit_Try(self, node: ast.Try) -> None:
        self._visit_try(node)

    @override
    def visit_TryStar(self, node: ast.TryStar) -> None:
        self._visit_try(node)

    def _visit_try(self, node: ast.Try | ast.TryStar) -> None:
        initial = self._snapshot()
        for statement in node.body:
            self.visit(statement)
        for statement in node.orelse:
            self.visit(statement)
        exits = [self._snapshot()]
        for handler in node.handlers:
            self._restore(initial)
            if handler.name is not None:
                self._clear_name(handler.name)
            for statement in handler.body:
                self.visit(statement)
            exits.append(self._snapshot())
        merged = exits[0]
        for state in exits[1:]:
            merged = _intersect_flow_states(merged, state)
        self._restore(merged)
        for statement in node.finalbody:
            self.visit(statement)

    @override
    def visit_Match(self, node: ast.Match) -> None:
        self.visit(node.subject)
        initial = self._snapshot()
        exits = [initial]
        for case in node.cases:
            self._restore(initial)
            if case.guard is not None:
                self.visit(case.guard)
            for statement in case.body:
                self.visit(statement)
            exits.append(self._snapshot())
        merged = exits[0]
        for state in exits[1:]:
            merged = _intersect_flow_states(merged, state)
        self._restore(merged)

    def _record_target(self, target: ast.expr, value: ast.expr) -> None:
        self._clear_target(target)
        if not isinstance(target, ast.Name):
            return
        raw_origins = _expression_origins(value, self._raw_origins, self._flow)
        if _ephemeral_path_expression(value, self._ephemeral_paths):
            self._ephemeral_paths.add(target.id)
        if _source_path_collection(value, self._paths, self._source_suffixes, self._provenance):
            self._collections.add(target.id)
        if _source_path_expression(value, self._paths, self._source_suffixes, self._provenance):
            self._paths.add(target.id)
        if _raw_text_expression(value, self._flow):
            self._raw.add(target.id)
            self._raw_origins[target.id] = raw_origins or {value.lineno}

    def _clear_target(self, target: ast.expr) -> None:
        for child in ast.walk(target):
            if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store):
                self._clear_name(child.id)

    def _clear_name(self, name: str) -> None:
        self._paths.discard(name)
        self._raw.discard(name)
        self._raw_origins.pop(name, None)
        self._collections.discard(name)
        self._ephemeral_paths.discard(name)

    def _snapshot(self) -> _FlowState:
        return _FlowState(
            set(self._collections),
            set(self._ephemeral_paths),
            set(self._paths),
            set(self._raw),
            {name: set(origins) for name, origins in self._raw_origins.items()},
        )

    def _restore(self, state: _FlowState) -> None:
        self._collections = set(state.collections)
        self._ephemeral_paths = set(state.ephemeral_paths)
        self._paths = set(state.paths)
        self._raw = set(state.raw)
        self._raw_origins = {name: set(origins) for name, origins in state.raw_origins.items()}

    def _suppressed(self, node: ast.AST) -> bool:
        return (
            self._suppression_code is not None
            and self._suppression_lines is not None
            and _node_is_suppressed(self._suppression_lines, node, self._suppression_code)
        )

    @property
    def _provenance(self) -> _ApiProvenance:
        if self._api is None:
            msg = "function analysis provenance is unavailable"
            raise RuntimeError(msg)
        return self._api

    @property
    def _flow(self) -> _TextFlow:
        return _TextFlow(
            self._raw,
            self._paths,
            self._ephemeral_paths,
            self._source_suffixes,
            self._provenance,
        )


def _intersect_flow_states(left: _FlowState, right: _FlowState) -> _FlowState:
    raw = left.raw & right.raw
    return _FlowState(
        left.collections & right.collections,
        left.ephemeral_paths & right.ephemeral_paths,
        left.paths & right.paths,
        raw,
        {name: left.raw_origins.get(name, set()) | right.raw_origins.get(name, set()) for name in raw},
    )


def _function_bound_names(function: ast.FunctionDef | ast.AsyncFunctionDef) -> frozenset[str]:
    args = function.args
    names = {
        argument.arg
        for argument in (*args.posonlyargs, *args.args, *args.kwonlyargs, args.vararg, args.kwarg)
        if argument is not None
    }
    pending: list[ast.AST] = list(function.body)
    while pending:
        current = pending.pop()
        match current:
            case ast.FunctionDef() | ast.AsyncFunctionDef() | ast.ClassDef():
                names.add(current.name)
                continue
            case ast.Lambda() | ast.ListComp() | ast.SetComp() | ast.DictComp() | ast.GeneratorExp():
                continue
            case ast.Import(names=aliases) | ast.ImportFrom(names=aliases):
                names.update(alias.asname or alias.name.partition(".")[0] for alias in aliases)
                continue
            case ast.Name(id=name, ctx=(ast.Store() | ast.Del())):
                names.add(name)
            case _:
                pass
        pending.extend(ast.iter_child_nodes(current))
    return frozenset(names)


def _api_resolves(
    node: ast.expr,
    api: _ApiProvenance,
    *,
    sources: frozenset[str],
    symbol: str,
) -> bool:
    root = _root_name(node)
    return root is not None and root not in api.shadowed and api.imports.resolves(node, sources=sources, symbol=symbol)


def _root_name(node: ast.expr) -> str | None:
    current = node
    while isinstance(current, ast.Attribute):
        current = current.value
    return current.id if isinstance(current, ast.Name) else None


def _is_source_open(
    node: ast.expr,
    path_names: set[str],
    ephemeral_path_names: set[str],
    source_suffixes: tuple[str, ...],
    api: _ApiProvenance,
) -> bool:
    if not isinstance(node, ast.Call):
        return False
    if (
        isinstance(node.func, ast.Name)
        and node.func.id == "open"
        and node.args
        and "open" not in api.shadowed
        and api.imports.builtin_is_unshadowed("open")
    ):
        path = node.args[0]
    elif isinstance(node.func, ast.Attribute) and node.func.attr == "open":
        if node.args and _api_resolves(node.func, api, sources=frozenset({"io"}), symbol="open"):
            path = node.args[0]
        else:
            path = node.func.value
    else:
        return False
    return _source_path_expression(path, path_names, source_suffixes, api) and not _ephemeral_path_expression(
        path, ephemeral_path_names
    )


def _source_path_expression(
    node: ast.AST,
    path_names: set[str],
    source_suffixes: tuple[str, ...],
    api: _ApiProvenance,
) -> bool:
    if _representation_fixture_path(node):
        return False
    match node:
        case ast.Name(id=name):
            return name in path_names
        case ast.Constant(value=str(value)):
            return value.lower().endswith(source_suffixes)
        case ast.Attribute(attr="__file__"):
            return ".py" in source_suffixes
        case ast.Call(func=function, args=[path, *_]) if _api_resolves(
            function, api, sources=frozenset({"pathlib"}), symbol="Path"
        ):
            return _source_path_expression(path, path_names, source_suffixes, api)
        case ast.Call(func=function) if _api_resolves(function, api, sources=frozenset({"inspect"}), symbol="getfile"):
            return ".py" in source_suffixes
        case ast.JoinedStr(values=values):
            return any(_source_path_expression(value, path_names, source_suffixes, api) for value in values)
        case ast.Call(
            func=ast.Attribute(value=receiver, attr="with_suffix" | "with_name"),
            args=[ast.Constant(value=str(value)), *_],
        ):
            return value.lower().endswith(source_suffixes) and (
                _source_path_expression(receiver, path_names, source_suffixes, api)
                or (
                    isinstance(receiver, ast.Call)
                    and _api_resolves(receiver.func, api, sources=frozenset({"pathlib"}), symbol="Path")
                )
            )
        case ast.BinOp(left=left, right=right):
            return _source_path_expression(left, path_names, source_suffixes, api) or _source_path_expression(
                right, path_names, source_suffixes, api
            )
        case ast.Subscript(value=ast.Name(id=name)):
            return name in path_names
        case _:
            return False


def _representation_fixture_path(node: ast.AST) -> bool:
    for child in ast.walk(node):
        if not isinstance(child, ast.Constant) or not isinstance(child.value, str):
            continue
        parts = {part.lower() for part in child.value.replace("\\", "/").split("/")}
        if parts & _REPRESENTATION_DIRS:
            return True
    return False


def _ephemeral_path_expression(node: ast.AST, ephemeral_path_names: set[str]) -> bool:
    return any(isinstance(child, ast.Name) and child.id in ephemeral_path_names for child in ast.walk(node))


def _source_path_collection(
    node: ast.AST,
    path_names: set[str],
    source_suffixes: tuple[str, ...],
    api: _ApiProvenance,
) -> bool:
    return (
        isinstance(node, (ast.List, ast.Set, ast.Tuple))
        and bool(node.elts)
        and all(_source_path_expression(element, path_names, source_suffixes, api) for element in node.elts)
    )


def _raw_source_read(
    node: ast.expr,
    path_names: set[str],
    ephemeral_path_names: set[str],
    source_suffixes: tuple[str, ...],
    api: _ApiProvenance,
) -> bool:
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
        return False
    supported_reads = {"read_bytes", "read_text"}
    if node.func.attr in supported_reads:
        return _source_path_expression(
            node.func.value, path_names, source_suffixes, api
        ) and not _ephemeral_path_expression(node.func.value, ephemeral_path_names)
    return node.func.attr == "read" and _is_source_open(
        node.func.value, path_names, ephemeral_path_names, source_suffixes, api
    )


def _raw_text_expression(
    node: ast.expr,
    flow: _TextFlow,
) -> bool:
    if isinstance(node, ast.Name):
        return node.id in flow.raw_names
    if _raw_source_read(node, flow.path_names, flow.ephemeral_path_names, flow.source_suffixes, flow.api):
        return True
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        handle_reads = {"read", "readlines"}
        if node.func.attr in handle_reads and isinstance(node.func.value, ast.Name):
            return node.func.value.id in flow.raw_names
        return node.func.attr in _TEXT_TRANSFORMS and _raw_text_expression(node.func.value, flow)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _raw_text_expression(node.left, flow) or _raw_text_expression(node.right, flow)
    return False


def _raw_text_oracle(
    node: ast.expr,
    flow: _TextFlow,
) -> bool:
    if isinstance(node, ast.Compare):
        operands = [node.left, *node.comparators]
        if any(_raw_text_measurement(operand, flow) for operand in operands) and any(
            isinstance(operator, (ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE)) for operator in node.ops
        ):
            return True
        if any(_raw_text_expression(operand, flow) for operand in operands) and any(
            isinstance(operator, (ast.In, ast.NotIn, ast.Eq, ast.NotEq)) for operator in node.ops
        ):
            return True
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in {"all", "any"}
        and any(
            isinstance(argument, ast.GeneratorExp)
            and any(_raw_text_line_iteration(item.iter, flow) for item in argument.generators)
            for argument in node.args
        )
    ):
        return True
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        if node.func.attr in _TEXT_ASSERTIONS and _raw_text_expression(node.func.value, flow):
            return True
        if node.func.attr in _REGEX_ASSERTIONS and any(_raw_text_expression(argument, flow) for argument in node.args):
            return True
    return any(_raw_text_oracle(child, flow) for child in ast.iter_child_nodes(node) if isinstance(child, ast.expr))


def _raw_text_measurement(
    node: ast.expr,
    flow: _TextFlow,
) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "len"
        and len(node.args) == 1
        and _raw_text_expression(node.args[0], flow)
    )


def _raw_text_line_iteration(
    node: ast.expr,
    flow: _TextFlow,
) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "splitlines"
        and _raw_text_expression(node.func.value, flow)
    )


def _unittest_raw_text_oracle(
    node: ast.Call,
    flow: _TextFlow,
) -> bool:
    return (
        isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id in {"self", "cls"}
        and node.func.attr in _UNITTEST_ASSERTIONS
        and any(
            _raw_text_expression(argument, flow)
            or _raw_text_measurement(argument, flow)
            or _raw_text_oracle(argument, flow)
            for argument in node.args
        )
    )


def _expression_origins(
    node: ast.AST,
    raw_origins: dict[str, set[int]],
    flow: _TextFlow,
) -> set[int]:
    origins: set[int] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            origins.update(raw_origins.get(child.id, set()))
        elif isinstance(child, ast.Call) and _raw_source_read(
            child, flow.path_names, flow.ephemeral_path_names, flow.source_suffixes, flow.api
        ):
            origins.add(child.lineno)
    return origins
