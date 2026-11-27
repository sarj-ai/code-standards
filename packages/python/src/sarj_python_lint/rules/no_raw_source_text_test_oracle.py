from __future__ import annotations

import ast
from collections import Counter
from dataclasses import dataclass, replace
from pathlib import PurePosixPath
from types import MappingProxyType
from typing import TYPE_CHECKING, ClassVar, NamedTuple, final, override

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
from sarj_python_lint.rules._ast_index import comprehension_results, walk as walk_ast
from sarj_python_lint.rules._ast_names import root_name as _root_name
from sarj_python_lint.rules._imports import ImportIndex
from sarj_python_lint.rules._paths import is_test_path


if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rules._project_index import SourceUnit


GENERAL_SOURCE_SUFFIXES = (
    ".bash",
    ".js",
    ".jsx",
    ".json",
    ".jsonc",
    ".mjs",
    ".py",
    ".sh",
    ".sh.tftpl",
    ".sql",
    ".toml",
    ".ts",
    ".tsx",
    ".yaml",
    ".yml",
)

GENERAL_SOURCE_BASENAMES = frozenset({"Dockerfile"})
IAC_JSON_SOURCE_SUFFIXES = (".tf.json", ".tftest.json")

_EMPTY_PATH_TUPLES: Mapping[str, int] = MappingProxyType({})

_REPRESENTATION_DIRS = frozenset({"fixture", "fixtures", "golden", "goldens", "snapshot", "snapshots"})
_MAX_BAG_PROVENANCE_HOPS = 3
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
class _SourceKinds:
    suffixes: tuple[str, ...]
    basenames: frozenset[str] = frozenset()

    def matches(self, value: str) -> bool:
        lowered = value.lower()
        for suffix in IAC_JSON_SOURCE_SUFFIXES:
            if lowered.endswith(suffix):
                return suffix in self.suffixes
        return lowered.endswith(self.suffixes) or value.replace("\\", "/").rsplit("/", 1)[-1] in self.basenames


@dataclass(frozen=True, slots=True)
class _TextFlow:
    raw_names: set[str]
    path_names: set[str]
    ephemeral_path_names: set[str]
    sources: _SourceKinds
    api: _ApiProvenance
    byte_writes: set[tuple[str, str]]
    bags: set[str]
    bag_scope: _BagScope | None


@dataclass(frozen=True, slots=True)
class _FlowState:
    collections: set[str]
    ephemeral_paths: set[str]
    paths: set[str]
    raw: set[str]
    raw_origins: dict[str, set[int]]
    byte_writes: set[tuple[str, str]]
    bags: set[str]
    bag_origins: dict[str, set[int]]


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
class NoRawSourceTextTestOracle(ProjectRule):
    id = "no-raw-source-text-test-oracle"
    code = "SARJ402"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        default_level=Severity.WARNING,
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
            "A literal module-level __test__ = False disables pytest collection. Later bindings in eager module expressions or explicitly global class scopes clear that proof; class-local names, deferred bodies, and annotation-only names do not rebind it.",
            "The rule recognizes source-like suffixes, shell templates ending in .sh.tftpl, and the exact Dockerfile basename; it follows local aliases, context-managed reads, and common normalization.",
            "Direct generator/list-comprehension reads unpacked from stable module-level path tuples are followed; mutable collections, rebinding, filtered comprehensions, and other interprocedural flows remain unreported; a one-hop helper that flattens ast.walk(ast.parse(...)) string constants of a source-like project path or of first-party inspect source is followed, and third-party library source is not.",
            "Literal shebang startswith checks are representation contracts and remain unreported; other text compatibility sentinels require an exact suppression.",
            "Files produced beneath recognized temporary-directory fixtures are generated artifacts, not repository source, and remain unreported.",
            "Paths beneath fixture, golden, and snapshot directories are treated as deliberate representation contracts and remain unreported.",
            "When raw representation is genuinely the contract (for example a golden or compatibility sentinel), use an exact line suppression with the reason.",
            "Lambda bodies and unconsumed generators are separate scopes. Proven builtin all/any consumption follows generator and comprehension bindings; pattern captures clear prior source provenance. Empty literal iterations and literal false filters are not treated as source oracles.",
            "Exact byte-copy checks against proven temporary outputs, and same-path byte preservation after a visible named write_bytes value, are representation contracts. Local value/path rebinding, intervening path writes, and conditional writes invalidate that proof; equality to fixed repository-source bytes still requires an exact suppression.",
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
            RuleExample(
                example_id="disabled-module-source-oracle",
                scenario="module-collection",
                title="An explicitly disabled module has no collected source oracle",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_policy.py",
                        "__test__ = False\nfrom pathlib import Path\ndef test_policy():\n"
                        "    source = Path('workflow.yml').read_text()\n    assert 'permissions:' in source\n",
                    ),
                ),
                focus_path=PurePosixPath("tests/test_policy.py"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="enabled-module-source-oracle",
                scenario="module-collection",
                title="An enabled module still needs a parsed source contract",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_policy.py",
                        "__test__ = True\nfrom pathlib import Path\ndef test_policy():\n"
                        "    source = Path('workflow.yml').read_text()\n    assert 'permissions:' in source\n",
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
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        path = context.path
        if not is_test_path(path) or context.generated:
            return []
        tree = context.tree
        if not isinstance(tree, ast.Module):
            return []
        imports = context.module_imports
        source_lines = context.source_lines
        module_tuples = module_source_path_tuples(
            tree, imports, GENERAL_SOURCE_SUFFIXES, source_basenames=GENERAL_SOURCE_BASENAMES
        )
        string_bags = _StringBags(context)
        assertions = [
            assertion
            for function, unittest_style in top_level_test_functions(tree, imports)
            for assertion in FunctionAnalyzer(
                GENERAL_SOURCE_SUFFIXES,
                source_basenames=GENERAL_SOURCE_BASENAMES,
                module_path_tuples=module_tuples,
                imports=imports,
                suppression_code=self.code,
                suppression_lines=source_lines,
                unittest_style=unittest_style,
            ).analyze(function, string_bags=string_bags)
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
    if _module_collection_disabled(tree):
        return []
    resolved_imports = imports or ImportIndex.from_tree(tree, module_scope_only=True)
    opted_out = _module_test_opt_outs(tree)
    functions: list[TestFunction] = []
    for statement in tree.body:
        match statement:
            case ast.FunctionDef() | ast.AsyncFunctionDef() if (
                statement.name.startswith("test")
                and statement.name not in opted_out
                and _safe_pytest_decorators(statement.decorator_list, resolved_imports)
            ):
                functions.append(TestFunction(statement, unittest_style=False))
            case ast.ClassDef():
                functions.extend(_class_test_functions(statement, resolved_imports, opted_out))
            case _:
                pass
    return functions


def _module_collection_disabled(tree: ast.Module) -> bool:
    disabled = False
    for statement in tree.body:
        match statement:
            case ast.Assign(targets=targets) if any(
                isinstance(target, ast.Name) and target.id == "__test__" for target in targets
            ):
                disabled = _assignment_disables_module_tests(statement)
            case ast.AnnAssign(target=ast.Name(id="__test__"), value=value):
                if value is not None:
                    disabled = isinstance(value, ast.Constant) and value.value is False
            case _:
                if disabled and _eagerly_binds_module_test(statement):
                    disabled = False
    return disabled


def _assignment_disables_module_tests(statement: ast.Assign) -> bool:
    value = statement.value
    if not isinstance(value, ast.Constant) or value.value is not False:
        return False
    return not any(
        _eagerly_binds_module_test(target) for target in statement.targets if not isinstance(target, ast.Name)
    )


def _eagerly_binds_module_test(node: ast.AST) -> bool:
    pending = [(node, True)]
    while pending:
        current, module_scope = pending.pop()
        if module_scope and _eager_node_binds_test(current):
            return True
        if isinstance(current, ast.ClassDef):
            class_module_scope = _class_declares_global_test(current)
            pending.extend((child, class_module_scope) for child in current.body)
        pending.extend((child, module_scope) for child in _eager_scope_children(current))
    return False


def _eager_node_binds_test(node: ast.AST) -> bool:
    match node:
        case (
            ast.FunctionDef(name="__test__")
            | ast.AsyncFunctionDef(name="__test__")
            | ast.ClassDef(name="__test__")
            | ast.TypeAlias(name=ast.Name(id="__test__"))
            | ast.ExceptHandler(name="__test__")
            | ast.MatchAs(name="__test__")
            | ast.MatchStar(name="__test__")
            | ast.MatchMapping(rest="__test__")
            | ast.Name(id="__test__", ctx=(ast.Store() | ast.Del()))
        ):
            return True
        case ast.Import(names=aliases) | ast.ImportFrom(names=aliases):
            return any((alias.asname or alias.name.partition(".")[0]) in {"__test__", "*"} for alias in aliases)
        case _:
            return False


def _eager_scope_children(node: ast.AST) -> list[ast.AST]:
    match node:
        case ast.FunctionDef() | ast.AsyncFunctionDef():
            return [*node.decorator_list, *_eager_argument_defaults(node.args)]
        case ast.ClassDef():
            return [*node.decorator_list, *node.bases, *(keyword.value for keyword in node.keywords)]
        case ast.Lambda():
            return _eager_argument_defaults(node.args)
        case ast.ListComp() | ast.SetComp() | ast.DictComp():
            return _comprehension_eager_children(node)
        case ast.GeneratorExp():
            return [node.generators[0].iter]
        case ast.TypeAlias() | ast.Import() | ast.ImportFrom():
            return []
        case ast.AnnAssign():
            return _annotated_assignment_eager_children(node)
        case _:
            return list(ast.iter_child_nodes(node))


def _eager_argument_defaults(arguments: ast.arguments) -> list[ast.AST]:
    return [*arguments.defaults, *filter(None, arguments.kw_defaults)]


def _comprehension_eager_children(node: ast.ListComp | ast.SetComp | ast.DictComp) -> list[ast.AST]:
    children: list[ast.AST] = [node.key, node.value] if isinstance(node, ast.DictComp) else [node.elt]
    children.extend(generator.iter for generator in node.generators)
    children.extend(condition for generator in node.generators for condition in generator.ifs)
    return children


def _annotated_assignment_eager_children(node: ast.AnnAssign) -> list[ast.AST]:
    if node.value is None:
        return [] if isinstance(node.target, ast.Name) else [node.target]
    return [node.target, node.value]


def _class_declares_global_test(node: ast.ClassDef) -> bool:
    pending: list[ast.AST] = list(node.body)
    while pending:
        current = pending.pop()
        match current:
            case ast.Global() if "__test__" in current.names:
                return True
            case ast.FunctionDef() | ast.AsyncFunctionDef() | ast.ClassDef() | ast.Lambda():
                continue
            case _:
                pass
        pending.extend(ast.iter_child_nodes(current))
    return False


def _class_test_functions(
    statement: ast.ClassDef, resolved_imports: ImportIndex, opted_out: frozenset[str]
) -> list[TestFunction]:
    unittest_style = any(
        resolved_imports.resolves(base, sources=_UNITTEST, symbol="TestCase") for base in statement.bases
    )
    pytest_style = _collectible_pytest_class(statement, resolved_imports, opted_out)
    if not unittest_style and not pytest_style:
        return []
    return [
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
    ]


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
    start = getattr(  # sarj-noqa: SARJ557 -- Generic AST markers may omit optional suppression-range source locations.
        node, "lineno", 0
    )
    end = (
        getattr(  # sarj-noqa: SARJ557 -- Generic AST markers may omit optional suppression-range source locations.
            node, "end_lineno", None
        )
        or start
    )
    return any(is_suppressed(source_lines, line, code) for line in range(start, end + 1))


class FunctionAnalyzer(ast.NodeVisitor):
    _imports: ImportIndex | None
    _module_path_tuples: Mapping[str, int]
    _sources: _SourceKinds
    _suppression_code: str | None
    _suppression_lines: list[str] | None
    _unittest_style: bool

    def __init__(
        self,
        source_suffixes: tuple[str, ...],
        *,
        source_basenames: frozenset[str] = frozenset(),
        module_path_tuples: Mapping[str, int] = _EMPTY_PATH_TUPLES,
        imports: ImportIndex | None = None,
        suppression_code: str | None = None,
        suppression_lines: list[str] | None = None,
        unittest_style: bool = False,
    ) -> None:
        self._bag_scope: _BagScope | None = None
        self._bags: set[str] = set()
        self._bag_origins: dict[str, set[int]] = {}
        self._sources = _SourceKinds(source_suffixes, source_basenames)
        self._module_path_tuples = module_path_tuples
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
        self._byte_writes: set[tuple[str, str]] = set()
        self._reported_origins: set[int] = set()
        self._assertions: list[ast.Assert | ast.Call] = []

    def analyze(
        self, function: ast.FunctionDef | ast.AsyncFunctionDef, *, string_bags: _StringBags | None = None
    ) -> list[ast.Assert | ast.Call]:
        imports = self._imports or ImportIndex.from_tree(ast.Module(body=[], type_ignores=[]))
        self._api = _ApiProvenance(imports, _function_bound_names(function))
        if string_bags is not None:
            self._bag_scope = _BagScope(string_bags, function, self._provenance, string_bags.unit)
        arguments = [*function.args.posonlyargs, *function.args.args, *function.args.kwonlyargs]
        self._ephemeral_paths.update(argument.arg for argument in arguments if argument.arg in _TEMP_PATH_NAMES)
        for statement in function.body:
            self.visit(statement)
        return self._assertions

    @override
    def generic_visit(self, node: ast.AST) -> None:
        match node:
            case ast.FunctionDef(name=name) | ast.AsyncFunctionDef(name=name) | ast.ClassDef(name=name):
                self._bags.discard(name)
                return
            case ast.Lambda():
                return
            case ast.Name(id=name, ctx=(ast.Store() | ast.Del())):
                self._bags.discard(name)
            case ast.Import() | ast.ImportFrom():
                self._bags.difference_update(_lexical_bound_names(node))
            case ast.ListComp() | ast.SetComp() | ast.DictComp() | ast.GeneratorExp():
                self._invalidate_comprehension_writes(node)
                return
            case _:
                pass
        super().generic_visit(node)

    def _invalidate_comprehension_writes(self, node: ast.expr) -> None:
        for child in walk_ast(node):
            if isinstance(child, ast.NamedExpr):
                self._clear_target(child.target)

    @override
    def visit_Assign(self, node: ast.Assign) -> None:
        self.visit(node.value)
        for target in node.targets:
            self._record_target(target, node.value, plain=True)

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
                item.context_expr, self._paths, self._ephemeral_paths, self._sources, self._provenance
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
            origins = self._oracle_origins(node.test, node.lineno)
            if not origins.issubset(self._reported_origins):
                self._assertions.append(node)
                self._reported_origins.update(origins)
        self.generic_visit(node)

    @override
    def visit_Call(self, node: ast.Call) -> None:
        self._remember_byte_write(node)
        if (
            self._unittest_style
            and not self._suppressed(node)
            and _unittest_raw_text_oracle(
                node,
                self._flow,
            )
        ):
            origins = self._oracle_origins(node, node.lineno)
            if not origins.issubset(self._reported_origins):
                self._assertions.append(node)
                self._reported_origins.update(origins)
        self.generic_visit(node)

    def _oracle_origins(self, node: ast.expr, fallback: int) -> set[int]:
        original = replace(self._flow, bags=set(), bag_scope=None)
        if _raw_text_oracle(node, original) or (
            self._unittest_style and isinstance(node, ast.Call) and _unittest_raw_text_oracle(node, original)
        ):
            return _expression_origins(node, self._raw_origins, original) or {fallback}
        origins = _expression_origins(node, self._raw_origins | self._bag_origins, self._flow) or {fallback}
        return {-origin for origin in origins}

    def _remember_byte_write(self, node: ast.Call) -> None:
        if not isinstance(node.func, ast.Attribute) or not isinstance(node.func.value, ast.Name):
            return
        path = node.func.value.id
        if path not in self._paths | self._ephemeral_paths or node.func.attr in {"read_bytes", "read_text"}:
            return
        self._byte_writes = {write for write in self._byte_writes if write[1] != path}
        if node.func.attr == "write_bytes" and not node.keywords and len(node.args) == 1:
            value = node.args[0]
            if isinstance(value, ast.Name) and value.id != path:
                self._byte_writes.add((value.id, path))

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
            for name in _pattern_bound_names(case.pattern):
                self._clear_name(name)
            if case.guard is not None:
                self.visit(case.guard)
            for statement in case.body:
                self.visit(statement)
            exits.append(self._snapshot())
        merged = exits[0]
        for state in exits[1:]:
            merged = _intersect_flow_states(merged, state)
        self._restore(merged)

    def _record_target(self, target: ast.expr, value: ast.expr, *, plain: bool = False) -> None:
        self._clear_target(target)
        if isinstance(target, ast.Tuple | ast.List):
            self._record_unpacked_read(target, value)
            return
        if not isinstance(target, ast.Name):
            return
        raw_origins = _expression_origins(value, self._raw_origins, self._flow)
        if _ephemeral_path_expression(value, self._ephemeral_paths):
            self._ephemeral_paths.add(target.id)
        if _source_path_collection(value, self._paths, self._sources, self._provenance):
            self._collections.add(target.id)
        if _source_path_expression(value, self._paths, self._sources, self._provenance):
            self._paths.add(target.id)
        if plain and _source_string_bag(value, self._flow):
            self._bags.add(target.id)
            self._bag_origins[target.id] = _expression_origins(
                value, self._raw_origins | self._bag_origins, self._flow
            ) or {value.lineno}
        if _raw_text_expression(value, self._flow):
            self._raw.add(target.id)
            self._raw_origins[target.id] = raw_origins or {value.lineno}

    def _record_unpacked_read(self, target: ast.Tuple | ast.List, value: ast.expr) -> None:
        if not isinstance(value, ast.GeneratorExp | ast.ListComp) or len(value.generators) != 1:
            return
        generator = value.generators[0]
        if (
            generator.is_async
            or generator.ifs
            or not isinstance(generator.target, ast.Name)
            or not isinstance(generator.iter, ast.Name)
        ):
            return
        if (
            generator.iter.id in self._provenance.shadowed
            or self._module_path_tuples.get(generator.iter.id) != len(target.elts)
            or not all(isinstance(element, ast.Name) for element in target.elts)
            or any(isinstance(child, ast.NamedExpr) for child in walk_ast(value.elt))
        ):
            return
        flow = _TextFlow(
            self._raw - {generator.target.id},
            self._paths | {generator.target.id},
            self._ephemeral_paths - {generator.target.id},
            self._sources,
            _ApiProvenance(self._provenance.imports, self._provenance.shadowed | {generator.target.id}),
            self._byte_writes,
            self._bags,
            self._bag_scope,
        )
        if not _raw_text_expression(value.elt, flow):
            return
        raw_origins = {name: origins for name, origins in self._raw_origins.items() if name != generator.target.id}
        origins = _expression_origins(value.elt, raw_origins, flow) or {value.elt.lineno}
        for element in target.elts:
            if isinstance(element, ast.Name):
                self._raw.add(element.id)
                self._raw_origins[element.id] = set(origins)

    def _clear_target(self, target: ast.expr) -> None:
        for child in walk_ast(target):
            if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store):
                self._clear_name(child.id)

    def _clear_name(self, name: str) -> None:
        self._byte_writes = {write for write in self._byte_writes if name not in write}
        self._paths.discard(name)
        self._raw.discard(name)
        self._bags.discard(name)
        self._bag_origins.pop(name, None)
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
            set(self._byte_writes),
            set(self._bags),
            {name: set(origins) for name, origins in self._bag_origins.items()},
        )

    def _restore(self, state: _FlowState) -> None:
        self._collections = set(state.collections)
        self._ephemeral_paths = set(state.ephemeral_paths)
        self._paths = set(state.paths)
        self._raw = set(state.raw)
        self._bags = set(state.bags)
        self._bag_origins = {name: set(origins) for name, origins in state.bag_origins.items()}
        self._raw_origins = {name: set(origins) for name, origins in state.raw_origins.items()}
        self._byte_writes = set(state.byte_writes)

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
            self._sources,
            self._provenance,
            self._byte_writes,
            self._bags,
            self._bag_scope,
        )


def _intersect_flow_states(left: _FlowState, right: _FlowState) -> _FlowState:
    raw = left.raw & right.raw
    bags = left.bags & right.bags
    return _FlowState(
        left.collections & right.collections,
        left.ephemeral_paths & right.ephemeral_paths,
        left.paths & right.paths,
        raw,
        {name: left.raw_origins.get(name, set()) | right.raw_origins.get(name, set()) for name in raw},
        left.byte_writes & right.byte_writes,
        bags,
        {name: left.bag_origins[name] | right.bag_origins[name] for name in bags},
    )


def module_source_path_tuples(
    tree: ast.Module,
    imports: ImportIndex,
    source_suffixes: tuple[str, ...],
    *,
    source_basenames: frozenset[str] = frozenset(),
) -> dict[str, int]:
    sources = _SourceKinds(source_suffixes, source_basenames)
    api = _ApiProvenance(imports, frozenset())
    tuples: dict[str, int] = {}
    for statement in tree.body:
        match statement:
            case ast.Assign(targets=[target], value=value) | ast.AnnAssign(target=target, value=value):
                pass
            case _:
                continue
        if (
            isinstance(target, ast.Name)
            and isinstance(value, ast.Tuple)
            and _source_path_collection(value, set(), sources, api)
        ):
            tuples[target.id] = len(value.elts)
    if not tuples:
        return {}
    bindings = Counter(_enclosing_scope_bindings(tree.body))
    if bindings["*"]:
        return {}
    global_names = {name for node in walk_ast(tree) if isinstance(node, ast.Global) for name in node.names}
    return {name: size for name, size in tuples.items() if bindings[name] == 1 and name not in global_names}


def _enclosing_scope_bindings(nodes: list[ast.stmt]) -> Iterator[str]:
    pending: list[ast.AST] = list(nodes)
    while pending:
        current = pending.pop()
        match current:
            case ast.FunctionDef() | ast.AsyncFunctionDef() | ast.ClassDef():
                yield current.name
                pending.extend(_definition_enclosing_expressions(current))
                continue
            case ast.Lambda():
                pending.extend(_definition_enclosing_expressions(current))
                continue
            case ast.ListComp() | ast.SetComp() | ast.DictComp() | ast.GeneratorExp():
                pending.extend(child.target for child in walk_ast(current) if isinstance(child, ast.NamedExpr))
                continue
            case ast.Import(names=aliases) | ast.ImportFrom(names=aliases):
                yield from (alias.asname or alias.name.partition(".")[0] for alias in aliases)
                continue
            case (
                ast.Name(id=name, ctx=(ast.Store() | ast.Del()))
                | ast.ExceptHandler(name=str(name))
                | ast.MatchAs(name=str(name))
                | ast.MatchStar(name=str(name))
                | ast.MatchMapping(rest=str(name))
            ):
                yield name
            case _:
                pass
        pending.extend(ast.iter_child_nodes(current))


def _definition_enclosing_expressions(
    node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef | ast.Lambda,
) -> list[ast.AST]:
    if isinstance(node, ast.ClassDef):
        return [*node.decorator_list, *node.bases, *node.keywords]
    defaults: list[ast.AST] = [
        *node.args.defaults,
        *(default for default in node.args.kw_defaults if default is not None),
    ]
    if isinstance(node, ast.Lambda):
        return defaults
    return [*node.decorator_list, *defaults]


def _function_bound_names(function: ast.FunctionDef | ast.AsyncFunctionDef) -> frozenset[str]:
    args = function.args
    names = {
        argument.arg
        for argument in (*args.posonlyargs, *args.args, *args.kwonlyargs, args.vararg, args.kwarg)
        if argument is not None
    }
    names.update(_enclosing_scope_bindings(function.body))
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


def _is_source_open(
    node: ast.expr,
    path_names: set[str],
    ephemeral_path_names: set[str],
    sources: _SourceKinds,
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
    return _source_path_expression(path, path_names, sources, api) and not _ephemeral_path_expression(
        path, ephemeral_path_names
    )


def _source_path_expression(
    node: ast.AST,
    path_names: set[str],
    sources: _SourceKinds,
    api: _ApiProvenance,
) -> bool:
    if _representation_fixture_path(node):
        return False
    match node:
        case ast.Name(id=name):
            return name in path_names
        case ast.Constant(value=str(value)):
            return sources.matches(value)
        case ast.Attribute(attr="__file__"):
            return ".py" in sources.suffixes
        case ast.Call(func=function, args=[path, *_]) if _api_resolves(
            function, api, sources=frozenset({"pathlib"}), symbol="Path"
        ):
            return _source_path_expression(path, path_names, sources, api)
        case ast.Call(func=function) if _api_resolves(function, api, sources=frozenset({"inspect"}), symbol="getfile"):
            return ".py" in sources.suffixes
        case ast.JoinedStr(values=values):
            return any(_source_path_expression(value, path_names, sources, api) for value in values)
        case ast.Call(
            func=ast.Attribute(value=receiver, attr="with_suffix" | "with_name"),
            args=[ast.Constant(value=str(value)), *_],
        ):
            return sources.matches(value) and (
                _source_path_expression(receiver, path_names, sources, api)
                or (
                    isinstance(receiver, ast.Call)
                    and _api_resolves(receiver.func, api, sources=frozenset({"pathlib"}), symbol="Path")
                )
            )
        case ast.BinOp(left=left, right=right):
            return _source_path_expression(left, path_names, sources, api) or _source_path_expression(
                right, path_names, sources, api
            )
        case ast.Subscript(value=ast.Name(id=name)):
            return name in path_names
        case _:
            return False


def _representation_fixture_path(node: ast.AST) -> bool:
    for child in walk_ast(node):
        if not isinstance(child, ast.Constant) or not isinstance(child.value, str):
            continue
        parts = {part.lower() for part in child.value.replace("\\", "/").split("/")}
        if not parts.isdisjoint(_REPRESENTATION_DIRS):
            return True
    return False


def _ephemeral_path_expression(node: ast.AST, ephemeral_path_names: set[str]) -> bool:
    return any(isinstance(child, ast.Name) and child.id in ephemeral_path_names for child in walk_ast(node))


def _source_path_collection(
    node: ast.AST,
    path_names: set[str],
    sources: _SourceKinds,
    api: _ApiProvenance,
) -> bool:
    return (
        isinstance(node, (ast.List, ast.Set, ast.Tuple))
        and bool(node.elts)
        and all(_source_path_expression(element, path_names, sources, api) for element in node.elts)
    )


def _raw_source_read(
    node: ast.expr,
    path_names: set[str],
    ephemeral_path_names: set[str],
    sources: _SourceKinds,
    api: _ApiProvenance,
) -> bool:
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
        return False
    supported_reads = {"read_bytes", "read_text"}
    if node.func.attr in supported_reads:
        return _source_path_expression(node.func.value, path_names, sources, api) and not _ephemeral_path_expression(
            node.func.value, ephemeral_path_names
        )
    return node.func.attr == "read" and _is_source_open(node.func.value, path_names, ephemeral_path_names, sources, api)


def _raw_text_expression(
    node: ast.expr,
    flow: _TextFlow,
) -> bool:
    if isinstance(node, ast.Name):
        return node.id in flow.raw_names
    if _raw_source_read(node, flow.path_names, flow.ephemeral_path_names, flow.sources, flow.api):
        return True
    match node:
        case ast.Call() if isinstance(node.func, ast.Attribute):
            handle_reads = {"read", "readlines"}
            if node.func.attr in handle_reads and isinstance(node.func.value, ast.Name):
                return node.func.value.id in flow.raw_names
            return node.func.attr in _TEXT_TRANSFORMS and _raw_text_expression(node.func.value, flow)
        case ast.BinOp() if isinstance(node.op, ast.Add):
            return _raw_text_expression(node.left, flow) or _raw_text_expression(node.right, flow)
        case _:
            pass
    return False


@dataclass(frozen=True, slots=True)
class _StringBag:
    text: ast.expr
    comprehension: ast.SetComp | ast.ListComp | ast.GeneratorExp


def _expression_names(node: ast.AST) -> set[str]:
    return {child.id for child in walk_ast(node) if isinstance(child, ast.Name)}


def _string_bag_text(node: ast.expr, api: _ApiProvenance) -> _StringBag | None:
    match node:
        case ast.Call(func=ast.Name(id=name), args=[argument], keywords=[]) if (
            name in {"frozenset", "set", "list", "tuple", "sorted"}
            and name not in api.shadowed
            and api.imports.builtin_is_unshadowed(name)
        ):
            node = argument
        case ast.Call():
            return None
        case _:
            pass
    match node:
        case (
            ast.SetComp(elt=ast.Attribute(value=ast.Name(id=name), attr="value"))
            | ast.ListComp(elt=ast.Attribute(value=ast.Name(id=name), attr="value"))
            | ast.GeneratorExp(elt=ast.Attribute(value=ast.Name(id=name), attr="value"))
        ):
            pass
        case _:
            return None
    api = _ApiProvenance(
        api.imports, api.shadowed | set[str]().union(*(_expression_names(g.target) for g in node.generators))
    )
    for generator in node.generators:
        if generator.is_async or not isinstance(generator.target, ast.Name) or generator.target.id != name:
            continue
        text = _parsed_walk_text(generator.iter, api)
        if text is not None and _filters_constant(generator.ifs, name, api):
            return _StringBag(text, node)
    return None


def _parsed_walk_text(node: ast.expr, api: _ApiProvenance) -> ast.expr | None:
    match node:
        case ast.Call(func=walk, args=[ast.Call(func=parse, args=[text, *_])]) if (
            _api_resolves(walk, api, sources=frozenset({"ast"}), symbol="walk")
            and _api_resolves(parse, api, sources=frozenset({"ast"}), symbol="parse")
            and not _expression_names(text) & api.shadowed & api.imports.bindings.keys()
        ):
            return text
        case _:
            return None


def _filters_constant(conditions: list[ast.expr], name: str, api: _ApiProvenance) -> bool:
    if "isinstance" in api.shadowed or not api.imports.builtin_is_unshadowed("isinstance"):
        return False
    pending = list(conditions)
    while pending:
        match pending.pop():
            case ast.BoolOp(op=ast.And(), values=values):
                pending.extend(values)
            case ast.Call(func=ast.Name(id="isinstance"), args=[ast.Name(id=subject), kind], keywords=[]) if (
                subject == name and _api_resolves(kind, api, sources=frozenset({"ast"}), symbol="Constant")
            ):
                return True
            case _:
                pass
    return False


class _StringBags:
    def __init__(self, context: PythonFileContext) -> None:
        self.project = context.session.project
        self.unit = self.project.unit(context.path) if self.project is not None else None
        self.tree = context.tree
        self.helpers: dict[str, _BagScope | None] = {}

    def helper(self, expression: ast.expr) -> _BagScope | None:
        key = ast.unparse(expression)
        if key in self.helpers:
            return self.helpers[key]
        unit = self.unit
        tree = self.tree
        match expression:
            case ast.Name(id=name):
                pass
            case _:
                name = None
        if (
            self.project is not None
            and self.unit is not None
            and (symbol := self.project.resolve(self.unit, expression)) is not None
        ):
            unit = self.project.source_unit(symbol.module)
            tree = unit.tree if unit is not None else None
            name = symbol.name
        self.helpers[key] = None
        if tree is None or name is None or Counter(_enclosing_scope_bindings(tree.body))[name] != 1:
            return None
        for function in tree.body:
            match function:
                case ast.FunctionDef(name=found, decorator_list=[]) if found == name:
                    api = _ApiProvenance(
                        ImportIndex.from_tree(tree, module_scope_only=True), _function_bound_names(function)
                    )
                    candidate = _BagScope(self, function, api, unit)
                    if candidate.returned_bag() is not None:
                        self.helpers[key] = candidate
                case _:
                    pass
        return self.helpers[key]


class _BagScope:
    def __init__(
        self,
        resolver: _StringBags,
        function: ast.FunctionDef | ast.AsyncFunctionDef,
        api: _ApiProvenance,
        unit: SourceUnit | None,
    ) -> None:
        self.resolver = resolver
        self.function = function
        self.api = api
        self.unit = unit
        self.values: dict[str, list[ast.expr]] = {}
        plain: dict[str, ast.expr] = {}
        pending: list[ast.AST] = list(function.body)
        while pending:
            current = pending.pop()
            match current:
                case ast.FunctionDef() | ast.AsyncFunctionDef() | ast.ClassDef() | ast.Lambda():
                    continue
                case ast.Assign(targets=[ast.Name(id=name)], value=value):
                    plain[name] = value
                    self.values.setdefault(name, []).append(value)
                case ast.Assign(targets=targets, value=value):
                    for target in targets:
                        match target:
                            case ast.Name(id=name):
                                self.values.setdefault(name, []).append(value)
                            case _:
                                pass
                case (
                    ast.AnnAssign(target=ast.Name(id=name), value=ast.expr() as value)
                    | ast.NamedExpr(target=ast.Name(id=name), value=value)
                    | ast.withitem(context_expr=value, optional_vars=ast.Name(id=name))
                ):
                    self.values.setdefault(name, []).append(value)
                case _:
                    pass
            pending.extend(ast.iter_child_nodes(current))
        counts = Counter(_enclosing_scope_bindings(function.body))
        parameters = {
            argument.arg for argument in (*function.args.posonlyargs, *function.args.args, *function.args.kwonlyargs)
        }
        self.bindings = {name: value for name, value in plain.items() if counts[name] == 1 and name not in parameters}

    def expand(self, node: ast.expr) -> ast.expr:
        seen: set[str] = set()
        while isinstance(node, ast.Name) and node.id in self.bindings and node.id not in seen:
            seen.add(node.id)
            node = self.bindings[node.id]
        return node

    def returned_bag(self) -> _StringBag | None:
        args = self.function.args
        if args.vararg or args.kwarg or args.kwonlyargs or len([*args.posonlyargs, *args.args]) > 1:
            return None
        body = self.function.body
        if ast.get_docstring(self.function, clean=False) is not None:
            body = body[1:]
        match body:
            case [*assignments, ast.Return(value=ast.expr() as returned)]:
                pass
            case _:
                return None
        used = _expression_names(returned)
        for statement in reversed(assignments):
            match statement:
                case ast.Assign(targets=[ast.Name(id=name)], value=value) if name in self.bindings and name in used:
                    used.update(_expression_names(value))
                case _:
                    return None
        return _string_bag_text(self.expand(returned), self.api)

    def inspect_roots(self, node: ast.expr, seen: frozenset[str] = frozenset()) -> list[ast.expr]:
        roots: list[ast.expr] = []
        for child in walk_ast(node):
            match child:
                case ast.Name(id=name) if name not in seen:
                    for value in self.values.get(name, ()):
                        roots.extend(self.inspect_roots(value, seen | {name}))
                case ast.Attribute(value=value, attr="__file__"):
                    roots.append(value)
                case ast.Call(func=func, args=[root, *_]) if _api_resolves(
                    func, self.api, sources=frozenset({"inspect"}), symbol="getfile"
                ):
                    roots.append(root)
                case _:
                    pass
        return roots

    def rooted(self, node: ast.expr, bindings: dict[str, ast.expr], hops: int = 0) -> set[bool]:
        match node:
            case ast.Name(id=name) if name in bindings:
                if hops >= _MAX_BAG_PROVENANCE_HOPS:
                    return {False}
                return self.rooted(bindings[name], self.bindings, hops + 1)
            case ast.Name():
                return {self.import_rooted(node)}
            case ast.Attribute(value=value):
                return self.rooted(value, bindings, hops)
            case ast.GeneratorExp() | ast.ListComp() | ast.SetComp():
                local = dict(bindings)
                for generator in node.generators:
                    match generator.target:
                        case ast.Name(id=name):
                            local[name] = generator.iter
                        case _:
                            return {False}
                return self.rooted(node.elt, local, hops)
            case ast.Call(func=func, args=args):
                if not (
                    _api_resolves(func, self.api, sources=frozenset({"importlib"}), symbol="import_module")
                    or _api_resolves(func, self.api, sources=frozenset({"pkgutil"}), symbol="iter_modules")
                ):
                    return {False}
                return set[bool]().union(*(self.rooted(argument, bindings, hops) for argument in args))
            case ast.JoinedStr(values=values):
                return set[bool]().union(
                    *(
                        self.rooted(value.value, bindings, hops)
                        for value in values
                        if isinstance(value, ast.FormattedValue)
                    )
                )
            case ast.Constant():
                return set()
            case _:
                return {False}

    def import_rooted(self, node: ast.Name) -> bool:
        project = self.resolver.project
        if (
            project is None
            or self.unit is None
            or node.id in self.api.shadowed
            or node.id not in self.unit.imports
            or node.id not in self.api.imports.bindings
        ):
            return False
        symbol = project.resolve(self.unit, node)
        if symbol is None:
            return False
        modules: set[str] = set()
        for statement in self.unit.tree.body if self.unit.tree is not None else ():
            match statement:
                case ast.Import(names=aliases):
                    modules.update(
                        alias.name for alias in aliases if (alias.asname or alias.name.partition(".")[0]) == node.id
                    )
                case _:
                    pass
        return all(project.source_unit(module) is not None for module in modules or {symbol.module})

    def source(
        self, node: ast.expr, flow: _TextFlow, bag: ast.expr, *, path: bool = False, inspect_only: bool = False
    ) -> bool:
        roots = self.inspect_roots(node)
        if path:
            raw = _source_path_expression(
                node, flow.path_names, flow.sources, flow.api
            ) and not _ephemeral_path_expression(node, flow.ephemeral_path_names)
        else:
            raw = _raw_text_expression(node, flow)
        match self.expand(node):
            case ast.Call(func=func, args=[root, *_]) if not path and _api_resolves(
                func, self.api, sources=frozenset({"inspect"}), symbol="getsource"
            ):
                roots.append(root)
            case _ if not raw:
                return False
            case _:
                pass
        if not roots:
            return raw and not inspect_only
        bindings = dict(self.bindings)
        match bag:
            case ast.SetComp() | ast.ListComp() | ast.GeneratorExp():
                bindings.update(
                    (generator.target.id, generator.iter)
                    for generator in bag.generators
                    if isinstance(generator.target, ast.Name)
                )
            case _:
                pass
        return all(self.rooted(root, bindings) == {True} for root in roots)

    def matches(self, node: ast.expr, flow: _TextFlow) -> bool:
        if (bag := _string_bag_text(node, flow.api)) is not None:
            return self.source(bag.text, flow, bag.comprehension)
        if not isinstance(node, ast.Call) or node.keywords or _root_name(node.func) in flow.api.shadowed:
            return False
        helper = self.resolver.helper(node.func)
        if helper is None or (bag := helper.returned_bag()) is None:
            return False
        parameters = [*helper.function.args.posonlyargs, *helper.function.args.args]
        if len(node.args) != len(parameters):
            return False
        if not parameters:
            return helper.source(bag.text, helper.text_flow(flow.sources), bag.comprehension, inspect_only=True)
        parameter = parameters[0].arg
        match helper.expand(bag.text):
            case ast.Name(id=name) if name == parameter:
                return self.source(node.args[0], flow, node.args[0])
            case ast.Call(func=ast.Attribute(value=ast.Name(id=receiver), attr="read_text")):
                pass
            case ast.Call(
                func=ast.Attribute(
                    value=ast.Call(func=ast.Attribute(value=ast.Name(id=receiver), attr="read_bytes")), attr="decode"
                )
            ):
                pass
            case ast.Call(
                func=ast.Attribute(
                    value=ast.Call(func=ast.Name(id="open"), args=[ast.Name(id=receiver), *_]), attr="read"
                )
            ):
                if "open" in helper.api.shadowed or not helper.api.imports.builtin_is_unshadowed("open"):
                    return False
            case _:
                return False
        return receiver == parameter and self.source(node.args[0], flow, node.args[0], path=True)

    def text_flow(self, sources: _SourceKinds) -> _TextFlow:
        flow = _TextFlow(set(), set(), set(), sources, self.api, set(), set(), self)
        for statement in self.function.body:
            match statement:
                case ast.Assign(targets=[ast.Name(id=name), *_], value=value):
                    if _source_path_expression(value, flow.path_names, sources, self.api):
                        flow.path_names.add(name)
                    if _raw_text_expression(value, flow):
                        flow.raw_names.add(name)
                case _:
                    pass
        return flow


def _source_string_bag(node: ast.expr, flow: _TextFlow) -> bool:
    match node:
        case ast.Name(id=name) if name in flow.bags:
            return True
        case _:
            return flow.bag_scope is not None and flow.bag_scope.matches(node, flow)


def _raw_text_oracle(
    node: ast.expr,
    flow: _TextFlow,
) -> bool:
    match node:
        case ast.Lambda() | ast.GeneratorExp():
            return False
        case ast.ListComp() | ast.SetComp() | ast.DictComp():
            return _comprehension_oracle(node, flow)
        case _:
            pass
    if isinstance(node, ast.Compare) and _raw_text_comparison(node, flow):
        return True
    if _consumed_generator_oracle(node, flow):
        return True
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        if (
            node.func.attr in _TEXT_ASSERTIONS
            and not _is_shebang_contract(node)
            and _raw_text_expression(node.func.value, flow)
        ):
            return True
        if node.func.attr in _REGEX_ASSERTIONS and any(_raw_text_expression(argument, flow) for argument in node.args):
            return True
    return any(_raw_text_oracle(child, flow) for child in ast.iter_child_nodes(node) if isinstance(child, ast.expr))


def _is_shebang_contract(node: ast.Call) -> bool:
    return (
        isinstance(node.func, ast.Attribute)
        and node.func.attr == "startswith"
        and not node.keywords
        and len(node.args) == 1
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
        and node.args[0].value.startswith("#!")
        and len(node.args[0].value.splitlines()) == 1
    )


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


def _consumed_generator_oracle(node: ast.expr, flow: _TextFlow) -> bool:
    match node:
        case ast.Call(func=ast.Name(id=name), args=[ast.GeneratorExp() as argument], keywords=[]) if (
            name in {"all", "any"} and name not in flow.api.shadowed and flow.api.imports.builtin_is_unshadowed(name)
        ):
            pass
        case _:
            return False
    if _comprehension_is_statically_empty(argument.generators):
        return False
    match argument.generators:
        case [ast.comprehension(target=ast.Name(id=target), iter=iterable)] if _source_string_bag(iterable, flow):
            if _string_bag_predicate(argument.elt, target):
                return True
        case _:
            pass
    return _comprehension_oracle(argument, flow, consumes_values=True)


def _string_bag_predicate(node: ast.expr, target: str) -> bool:
    match node:
        case ast.Compare(left=left, comparators=comparators, ops=ops):
            operands = [left, *comparators]
            return any(
                isinstance(operator, ast.In | ast.NotIn | ast.Eq | ast.NotEq)
                and any(
                    isinstance(operand, ast.Name) and operand.id == target for operand in operands[index : index + 2]
                )
                for index, operator in enumerate(ops)
            )
        case ast.Call(func=ast.Attribute(value=ast.Name(id=name), attr=method)):
            return name == target and method in {"startswith", "endswith"}
        case _:
            return False


def _comprehension_oracle(
    node: ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp,
    flow: _TextFlow,
    *,
    consumes_values: bool = False,
) -> bool:
    if _comprehension_is_statically_empty(node.generators):
        return False
    for generator in node.generators:
        if _raw_text_oracle(generator.iter, flow):
            return True
        flow = _bind_comprehension_target(generator, flow)
        if any(_raw_text_oracle(condition, flow) for condition in generator.ifs):
            return True
    values = comprehension_results(node)
    return any(
        _raw_text_oracle(value, flow) or (consumes_values and _raw_text_expression(value, flow)) for value in values
    )


def _comprehension_is_statically_empty(generators: list[ast.comprehension]) -> bool:
    return any(
        (isinstance(generator.iter, ast.List | ast.Tuple | ast.Set) and not generator.iter.elts)
        or (isinstance(generator.iter, ast.Dict) and not generator.iter.keys)
        or any(isinstance(condition, ast.Constant) and not condition.value for condition in generator.ifs)
        for generator in generators
    )


def _bind_comprehension_target(generator: ast.comprehension, flow: _TextFlow) -> _TextFlow:
    raw_lines = _raw_text_line_iteration(generator.iter, flow)
    names = {child.id for child in walk_ast(generator.target) if isinstance(child, ast.Name)}
    scoped = _TextFlow(
        flow.raw_names - names,
        flow.path_names - names,
        flow.ephemeral_path_names - names,
        flow.sources,
        _ApiProvenance(flow.api.imports, flow.api.shadowed | names),
        {write for write in flow.byte_writes if names.isdisjoint(write)},
        flow.bags - names,
        flow.bag_scope,
    )
    if raw_lines and isinstance(generator.target, ast.Name):
        scoped.raw_names.add(generator.target.id)
    return scoped


def _pattern_bound_names(pattern: ast.pattern) -> Iterator[str]:
    for child in walk_ast(pattern):
        match child:
            case ast.MatchAs(name=str(name)) | ast.MatchStar(name=str(name)) | ast.MatchMapping(rest=str(name)):
                yield name
            case _:
                pass


def _raw_text_line_iteration(
    node: ast.expr,
    flow: _TextFlow,
) -> bool:
    if isinstance(node, ast.List | ast.Tuple):
        return bool(node.elts) and all(_raw_text_expression(item, flow) for item in node.elts)
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
    if (
        isinstance(node.func, ast.Attribute)
        and node.func.attr in {"assertEqual", "assertNotEqual"}
        and _byte_preservation_operands(node.args, flow)
    ):
        return False
    return (
        isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id in {"self", "cls"}
        and node.func.attr in _UNITTEST_ASSERTIONS
        and (
            (
                node.func.attr in {"assertIn", "assertNotIn"}
                and len(node.args) > 1
                and _source_string_bag(node.args[1], flow)
            )
            or any(
                _raw_text_expression(argument, flow)
                or _raw_text_measurement(argument, flow)
                or _raw_text_oracle(argument, flow)
                for argument in node.args
            )
        )
    )


def _expression_origins(
    node: ast.AST,
    raw_origins: dict[str, set[int]],
    flow: _TextFlow,
) -> set[int]:
    origins: set[int] = set()
    for child in walk_ast(node):
        match child:
            case ast.Name():
                origins.update(raw_origins.get(child.id, set()))
            case ast.Call() if _raw_source_read(
                child, flow.path_names, flow.ephemeral_path_names, flow.sources, flow.api
            ):
                origins.add(child.lineno)
            case _:
                pass
    return origins


def _raw_text_comparison(node: ast.Compare, flow: _TextFlow) -> bool:
    operands = [node.left, *node.comparators]
    if (
        len(node.ops) == 1
        and isinstance(node.ops[0], ast.Eq | ast.NotEq)
        and _byte_preservation_operands(operands, flow)
    ):
        return False
    if any(_raw_text_measurement(operand, flow) for operand in operands) and any(
        isinstance(operator, (ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE)) for operator in node.ops
    ):
        return True
    if any(
        isinstance(operator, ast.In | ast.NotIn) and _source_string_bag(right, flow)
        for operator, right in zip(node.ops, node.comparators, strict=True)
    ):
        return True
    return bool(
        any(_raw_text_expression(operand, flow) for operand in operands)
        and any(isinstance(operator, (ast.In, ast.NotIn, ast.Eq, ast.NotEq)) for operator in node.ops)
    )


def _byte_preservation_operands(operands: list[ast.expr], flow: _TextFlow) -> bool:
    match operands:
        case [left, right]:
            pairs = ((left, right), (right, left))
        case _:
            return False
    for read, expected in pairs:
        if not (
            isinstance(read, ast.Call)
            and isinstance(read.func, ast.Attribute)
            and read.func.attr == "read_bytes"
            and _raw_source_read(read, flow.path_names, flow.ephemeral_path_names, flow.sources, flow.api)
        ):
            continue
        if (
            isinstance(read.func.value, ast.Name)
            and isinstance(expected, ast.Name)
            and (expected.id, read.func.value.id) in flow.byte_writes
        ):
            return True
        if (
            isinstance(expected, ast.Call)
            and isinstance(expected.func, ast.Attribute)
            and expected.func.attr == "read_bytes"
            and _ephemeral_path_expression(expected.func.value, flow.ephemeral_path_names)
        ):
            return True
    return False
