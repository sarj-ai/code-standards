"""SARJ402 — tests must not use raw repository source text as behavioral proof.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_source_coupled_test.py
"""

from __future__ import annotations

import ast
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, ClassVar, final, override

from sarj_python_lint.rule_base import (
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
from sarj_python_lint.rules._paths import is_generated, is_test_path


if TYPE_CHECKING:
    from pathlib import Path


GENERAL_SOURCE_SUFFIXES = (
    ".bash",
    ".js",
    ".mjs",
    ".py",
    ".sh",
    ".ts",
    ".yaml",
    ".yml",
)
_TEXT_TRANSFORMS = frozenset(
    {"casefold", "lower", "lstrip", "removeprefix", "removesuffix", "replace", "rstrip", "strip", "upper"}
)
_TEXT_ASSERTIONS = frozenset({"count", "endswith", "find", "index", "startswith"})
_REGEX_ASSERTIONS = frozenset({"findall", "finditer", "fullmatch", "match", "search"})
_TEMP_PATH_NAMES = frozenset({"tmp_path", "tmpdir", "temp_dir", "temporary_directory"})
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
class SourceCoupledTest(Rule):
    id = "source-coupled-test"
    code = "SARJ402"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="Test asserts on raw repository source text instead of parsed or executable behavior.",
        rationale="Substring and regex checks can pass on comments or unreachable configuration and fail after behavior-preserving formatting changes.",
        remediation="Parse the artifact, execute its validator, or assert on a runtime contract.",
        category=RuleCategory.TESTING,
        limitations=(
            "The rule follows local aliases, path aliases, context-managed reads, and common text normalization; interprocedural flows remain unreported.",
            "Files produced beneath recognized temporary-directory fixtures are generated artifacts, not repository source, and remain unreported.",
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
                        "def test_policy():\n    workflow = yaml.safe_load(Path('workflow.yml').read_text())\n    assert verify(workflow) == []\n",
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
                        "def test_policy():\n    source = Path('workflow.yml').read_text()\n    assert 'permissions:' in source\n",
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
        assertions = [
            assertion
            for function, unittest_style in top_level_test_functions(tree)
            for assertion in FunctionAnalyzer(GENERAL_SOURCE_SUFFIXES, unittest_style=unittest_style).analyze(function)
        ]
        return [
            Diagnostic(
                path=path,
                line=assertion.lineno,
                col=assertion.col_offset + 1,
                code=self.code,
                severity=Severity.WARNING,
                message=(
                    "raw repository source text is the test oracle; parse or execute the artifact so comments, formatting, and unreachable blocks cannot satisfy the contract."
                ),
            )
            for assertion in assertions
        ]


def top_level_test_functions(tree: ast.Module) -> list[tuple[ast.FunctionDef | ast.AsyncFunctionDef, bool]]:
    functions: list[tuple[ast.FunctionDef | ast.AsyncFunctionDef, bool]] = []
    for statement in tree.body:
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)) and statement.name.startswith("test"):
            functions.append((statement, False))
        elif isinstance(statement, ast.ClassDef):
            unittest_style = any(
                (isinstance(base, ast.Name) and base.id == "TestCase")
                or (isinstance(base, ast.Attribute) and base.attr == "TestCase")
                for base in statement.bases
            )
            functions.extend(
                (child, unittest_style)
                for child in statement.body
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name.startswith("test")
            )
    return functions


class FunctionAnalyzer(ast.NodeVisitor):
    """Track raw text inside one test without leaking into nested lexical scopes."""

    _source_suffixes: tuple[str, ...]
    _unittest_style: bool

    def __init__(self, source_suffixes: tuple[str, ...], *, unittest_style: bool = False) -> None:
        self._source_suffixes = source_suffixes
        self._unittest_style = unittest_style
        self._collections: set[str] = set()
        self._ephemeral_paths: set[str] = set()
        self._paths: set[str] = set()
        self._raw: set[str] = set()
        self._raw_origins: dict[str, set[int]] = {}
        self._reported_origins: set[int] = set()
        self._assertions: list[ast.Assert | ast.Call] = []

    def analyze(self, function: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.Assert | ast.Call]:
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
            if isinstance(item.optional_vars, ast.Name) and _is_source_open(
                item.context_expr, self._paths, self._ephemeral_paths, self._source_suffixes
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
        if _raw_text_oracle(node.test, self._raw, self._paths, self._ephemeral_paths, self._source_suffixes):
            origins = _expression_origins(
                node.test, self._raw_origins, self._paths, self._ephemeral_paths, self._source_suffixes
            ) or {node.lineno}
            if not origins.issubset(self._reported_origins):
                self._assertions.append(node)
                self._reported_origins.update(origins)
        self.generic_visit(node)

    @override
    def visit_Call(self, node: ast.Call) -> None:
        if self._unittest_style and _unittest_raw_text_oracle(
            node, self._raw, self._paths, self._ephemeral_paths, self._source_suffixes
        ):
            origins = _expression_origins(
                node, self._raw_origins, self._paths, self._ephemeral_paths, self._source_suffixes
            ) or {node.lineno}
            if not origins.issubset(self._reported_origins):
                self._assertions.append(node)
                self._reported_origins.update(origins)
        self.generic_visit(node)

    @override
    def visit_For(self, node: ast.For) -> None:
        self._visit_for(node)

    @override
    def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
        self._visit_for(node)

    def _visit_for(self, node: ast.For | ast.AsyncFor) -> None:
        self.visit(node.iter)
        if isinstance(node.target, ast.Name) and isinstance(node.iter, ast.Name) and node.iter.id in self._collections:
            self._paths.add(node.target.id)
        for statement in [*node.body, *node.orelse]:
            self.visit(statement)

    def _record_target(self, target: ast.expr, value: ast.expr) -> None:
        if not isinstance(target, ast.Name):
            return
        raw_origins = _expression_origins(
            value, self._raw_origins, self._paths, self._ephemeral_paths, self._source_suffixes
        )
        # Reassignment kills stale taint before adding the new value's state.
        self._paths.discard(target.id)
        self._raw.discard(target.id)
        self._raw_origins.pop(target.id, None)
        self._collections.discard(target.id)
        self._ephemeral_paths.discard(target.id)
        if _ephemeral_path_expression(value, self._ephemeral_paths):
            self._ephemeral_paths.add(target.id)
        if _source_path_collection(value, self._paths, self._source_suffixes):
            self._collections.add(target.id)
        if _source_path_expression(value, self._paths, self._source_suffixes):
            self._paths.add(target.id)
        if _raw_text_expression(value, self._raw, self._paths, self._ephemeral_paths, self._source_suffixes):
            self._raw.add(target.id)
            self._raw_origins[target.id] = raw_origins or {value.lineno}


def _is_source_open(
    node: ast.expr,
    path_names: set[str],
    ephemeral_path_names: set[str],
    source_suffixes: tuple[str, ...],
) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "open"
        and bool(node.args)
        and _source_path_expression(node.args[0], path_names, source_suffixes)
        and not _ephemeral_path_expression(node.args[0], ephemeral_path_names)
    )


def _source_path_expression(node: ast.AST, path_names: set[str], source_suffixes: tuple[str, ...]) -> bool:
    match node:
        case ast.Name(id=name):
            return name in path_names
        case ast.Constant(value=str(value)):
            return value.lower().endswith(source_suffixes)
        case ast.JoinedStr(values=values):
            return any(_source_path_expression(value, path_names, source_suffixes) for value in values)
        case ast.BinOp() | ast.Call() | ast.Attribute() | ast.Subscript():
            return any(
                _source_path_expression(child, path_names, source_suffixes) for child in ast.iter_child_nodes(node)
            )
        case _:
            return False


def _ephemeral_path_expression(node: ast.AST, ephemeral_path_names: set[str]) -> bool:
    return any(isinstance(child, ast.Name) and child.id in ephemeral_path_names for child in ast.walk(node))


def _source_path_collection(node: ast.AST, path_names: set[str], source_suffixes: tuple[str, ...]) -> bool:
    return (
        isinstance(node, (ast.List, ast.Set, ast.Tuple))
        and bool(node.elts)
        and all(_source_path_expression(element, path_names, source_suffixes) for element in node.elts)
    )


def _raw_source_read(
    node: ast.expr,
    path_names: set[str],
    ephemeral_path_names: set[str],
    source_suffixes: tuple[str, ...],
) -> bool:
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
        return False
    if node.func.attr == "read_text":
        return _source_path_expression(node.func.value, path_names, source_suffixes) and not _ephemeral_path_expression(
            node.func.value, ephemeral_path_names
        )
    return node.func.attr == "read" and _is_source_open(
        node.func.value, path_names, ephemeral_path_names, source_suffixes
    )


def _raw_text_expression(
    node: ast.expr,
    raw_names: set[str],
    path_names: set[str],
    ephemeral_path_names: set[str],
    source_suffixes: tuple[str, ...],
) -> bool:
    if isinstance(node, ast.Name):
        return node.id in raw_names
    if _raw_source_read(node, path_names, ephemeral_path_names, source_suffixes):
        return True
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        if node.func.attr == "read" and isinstance(node.func.value, ast.Name):
            return node.func.value.id in raw_names
        return node.func.attr in _TEXT_TRANSFORMS and _raw_text_expression(
            node.func.value, raw_names, path_names, ephemeral_path_names, source_suffixes
        )
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _raw_text_expression(
            node.left, raw_names, path_names, ephemeral_path_names, source_suffixes
        ) or _raw_text_expression(node.right, raw_names, path_names, ephemeral_path_names, source_suffixes)
    return False


def _raw_text_oracle(
    node: ast.expr,
    raw_names: set[str],
    path_names: set[str],
    ephemeral_path_names: set[str],
    source_suffixes: tuple[str, ...],
) -> bool:
    if isinstance(node, ast.Compare):
        operands = [node.left, *node.comparators]
        if any(
            _raw_text_measurement(operand, raw_names, path_names, ephemeral_path_names, source_suffixes)
            for operand in operands
        ) and any(isinstance(operator, (ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE)) for operator in node.ops):
            return True
        if any(
            _raw_text_expression(operand, raw_names, path_names, ephemeral_path_names, source_suffixes)
            for operand in operands
        ) and any(isinstance(operator, (ast.In, ast.NotIn, ast.Eq, ast.NotEq)) for operator in node.ops):
            return True
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in {"all", "any"}
        and any(
            isinstance(argument, ast.GeneratorExp)
            and any(
                _raw_text_line_iteration(item.iter, raw_names, path_names, ephemeral_path_names, source_suffixes)
                for item in argument.generators
            )
            for argument in node.args
        )
    ):
        return True
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        if node.func.attr in _TEXT_ASSERTIONS and _raw_text_expression(
            node.func.value, raw_names, path_names, ephemeral_path_names, source_suffixes
        ):
            return True
        if node.func.attr in _REGEX_ASSERTIONS and any(
            _raw_text_expression(argument, raw_names, path_names, ephemeral_path_names, source_suffixes)
            for argument in node.args
        ):
            return True
    return any(
        _raw_text_oracle(child, raw_names, path_names, ephemeral_path_names, source_suffixes)
        for child in ast.iter_child_nodes(node)
        if isinstance(child, ast.expr)
    )


def _raw_text_measurement(
    node: ast.expr,
    raw_names: set[str],
    path_names: set[str],
    ephemeral_path_names: set[str],
    source_suffixes: tuple[str, ...],
) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "len"
        and len(node.args) == 1
        and _raw_text_expression(node.args[0], raw_names, path_names, ephemeral_path_names, source_suffixes)
    )


def _raw_text_line_iteration(
    node: ast.expr,
    raw_names: set[str],
    path_names: set[str],
    ephemeral_path_names: set[str],
    source_suffixes: tuple[str, ...],
) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "splitlines"
        and _raw_text_expression(node.func.value, raw_names, path_names, ephemeral_path_names, source_suffixes)
    )


def _unittest_raw_text_oracle(
    node: ast.Call,
    raw_names: set[str],
    path_names: set[str],
    ephemeral_path_names: set[str],
    source_suffixes: tuple[str, ...],
) -> bool:
    return (
        isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id in {"self", "cls"}
        and node.func.attr in _UNITTEST_ASSERTIONS
        and any(
            _raw_text_expression(argument, raw_names, path_names, ephemeral_path_names, source_suffixes)
            or _raw_text_measurement(argument, raw_names, path_names, ephemeral_path_names, source_suffixes)
            or _raw_text_oracle(argument, raw_names, path_names, ephemeral_path_names, source_suffixes)
            for argument in node.args
        )
    )


def _expression_origins(
    node: ast.AST,
    raw_origins: dict[str, set[int]],
    path_names: set[str],
    ephemeral_path_names: set[str],
    source_suffixes: tuple[str, ...],
) -> set[int]:
    origins: set[int] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            origins.update(raw_origins.get(child.id, set()))
        elif isinstance(child, ast.Call) and _raw_source_read(child, path_names, ephemeral_path_names, source_suffixes):
            origins.add(child.lineno)
    return origins
