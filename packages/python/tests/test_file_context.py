from __future__ import annotations

import ast
import gc
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, final, override
import weakref

from sarj_python_lint.__main__ import analyze, check_source
from sarj_python_lint._analysis_session import AnalysisSession
from sarj_python_lint._file_context import PythonFileContext
from sarj_python_lint.rule_base import Rule
from sarj_python_lint.rules import REGISTRY
from sarj_python_lint.rules._ast_index import nodes, parent_map, walk
from sarj_python_lint.rules._project_index import ProjectIndexSet


if TYPE_CHECKING:
    from collections.abc import Iterator

    from sarj_python_lint.rule_base import Diagnostic


def test_file_facts_are_lazy_and_preserve_breadth_first_queries() -> None:
    context = PythonFileContext(Path("app.py"), "class Outer:\n    def inner(self):\n        return len([])\n")
    assert "tree" not in vars(context)
    assert "generated" not in vars(context)
    tree = context.tree
    assert tree is not None
    expected = [node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.Call))]
    assert context.nodes(ast.FunctionDef, ast.Call) == expected
    assert context.tree is tree
    assert context.node_index is context.node_index
    assert context.nodes(ast.AST) == list(ast.walk(tree))
    # Callers cannot mutate the index by changing a query result.
    context.nodes(ast.Call).clear()
    assert len(context.nodes(ast.Call)) == 1


def test_import_modes_preserve_local_shadowing_distinction() -> None:
    context = PythonFileContext(Path("app.py"), "from typing import Any\ndef scoped(Any):\n    return Any\n")
    name = ast.Name(id="Any")
    assert context.module_imports.resolved_qualified_name(name) == "typing.Any"
    assert context.imports.resolved_qualified_name(name) is None
    assert context.imports is context.imports
    assert context.module_imports is context.module_imports


def test_syntax_errors_do_not_poison_the_next_context() -> None:
    path = Path("app.py")
    assert PythonFileContext(path, "def broken(:").tree is None
    assert PythonFileContext(path, "answer = 42\n").tree is not None


def test_context_and_ast_are_collectable_after_file_checks() -> None:
    context = PythonFileContext(Path("app.py"), "import typing\nvalue: typing.Any = None\n")
    tree = context.tree
    assert tree is not None
    context.nodes(ast.AST)
    assert context.imports is context.imports
    assert context.module_imports is context.module_imports
    assert context.fastapi.tree is tree
    assert context.parents is context.parents
    context_ref, tree_ref = weakref.ref(context), weakref.ref(tree)
    del context, tree  # sarj-noqa: SARJ442 -- release strong references to test fact lifetime.
    gc.collect()
    assert context_ref() is None
    assert tree_ref() is None


def test_generated_markers_refresh_between_analysis_invocations(tmp_path: Path) -> None:
    path = tmp_path / "output" / "app.py"
    path.parent.mkdir()
    path.write_text("__all__ = ['value']\nvalue = 1\n", encoding="utf-8")
    rules = ["no-dunder-all"]
    assert analyze(rules, [path])
    marker = tmp_path / "codegen.yml"
    marker.write_text("generator: fixture\n", encoding="utf-8")
    assert analyze(rules, [path]) == []
    marker.unlink()
    assert analyze(rules, [path])


def _file_examples() -> Iterator[tuple[Path, str]]:
    selected = (
        "fastapi-explicit-openapi-contract",
        "fastapi-class-router-contract",
        "docstring-returns-restate-signature",
        "no-docstring-type-restatement",
    )
    for rule_id in selected:
        for example in REGISTRY[rule_id].public_examples():
            if len(example.files) == 1:
                yield Path(example.focus_path), example.focus_file.source


def test_shared_facts_preserve_findings_and_rule_order() -> None:
    selected = (
        "fastapi-explicit-openapi-contract",
        "fastapi-class-router-contract",
        "docstring-returns-restate-signature",
        "no-docstring-type-restatement",
    )
    rules = [REGISTRY[rule_id]() for rule_id in selected]
    total_findings = 0
    for path, source in _file_examples():
        # Fresh per-rule contexts provide an independent comparison to shared facts.
        separate = sorted(finding.format() for rule in rules for finding in rule.check(path, source))
        context = PythonFileContext(path, source)
        shared = sorted(finding.format() for rule in rules for finding in rule.check_context(context))
        assert shared == separate
        total_findings += len(shared)
        forward = sorted(finding.format() for finding in check_source(rules, path, source))
        reverse = sorted(finding.format() for finding in check_source(list(reversed(rules)), path, source))
        assert forward == reverse
    assert total_findings > 0


def test_project_tree_is_reused_only_for_the_same_source() -> None:

    path = Path("app.py")
    source = "class Record:\n    value = 1\n"
    session = AnalysisSession()
    session.project = ProjectIndexSet.single(path, source)
    unit = session.project.unit(path)
    assert unit is not None
    assert PythonFileContext(path, source, session).tree is unit.tree
    changed = PythonFileContext(path, "value = 2\n", session)
    assert changed.tree is not unit.tree
    assert changed.tree is not None
    assert ast.unparse(changed.tree) == "value = 2"


def test_index_does_not_supply_nodes_from_another_tree() -> None:

    context = PythonFileContext(Path("app.py"), "first = 1\n")
    other = ast.parse("second = 2\n")
    assert list(walk(other, index=context.node_index)) == list(ast.walk(other))
    assert nodes(other, ast.Name, index=context.node_index) == [
        node for node in ast.walk(other) if isinstance(node, ast.Name)
    ]


@final
class _ContextObserver(Rule):
    id = "context-observer"
    code = "SARJ999"
    description = "Records weak references to verify file analysis ownership."

    def __init__(self) -> None:
        self.context_ids: list[int] = []
        self.contexts: list[weakref.ReferenceType[PythonFileContext]] = []
        self.trees: list[weakref.ReferenceType[ast.Module]] = []

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        self.context_ids.append(id(context))
        self.contexts.append(weakref.ref(context))
        tree = context.tree
        if tree is not None:
            self.trees.append(weakref.ref(tree))
            context.nodes(ast.AST)
            assert context.imports is context.imports
        return []


def test_runner_shares_then_releases_file_contexts() -> None:
    first, second = _ContextObserver(), _ContextObserver()
    assert check_source([first, second], Path("app.py"), "value = 1\n") == []
    assert first.context_ids == second.context_ids
    gc.collect()
    assert all(reference() is None for reference in (*first.contexts, *second.contexts, *first.trees, *second.trees))


def test_explicit_context_session_owns_target_policy(tmp_path: Path) -> None:
    rule = REGISTRY["prefer-match-value-dispatch"]()
    example = next(example for example in rule.public_examples() if example.expected_count > 0)
    path = tmp_path / example.focus_path
    path.parent.mkdir(parents=True)
    path.write_text(example.focus_file.source, encoding="utf-8")
    manifest = tmp_path / "pyproject.toml"
    manifest.write_text("[project]\nname = 'sample'\nversion = '0.1.0'\nrequires-python = '>=3.9'\n", encoding="utf-8")
    previous = AnalysisSession()
    rule.prepare_session(previous)
    assert previous.python_target.has_declared_support_before(path, (3, 10))
    manifest.write_text("[project]\nname = 'sample'\nversion = '0.1.0'\nrequires-python = '>=3.10'\n", encoding="utf-8")
    current = PythonFileContext(path, example.focus_file.source, AnalysisSession())
    assert len(rule.check_context(current)) == example.expected_count


def test_parent_facts_preserve_breadth_first_last_parent_for_shared_nodes() -> None:
    context = PythonFileContext(
        Path("app.py"), "first = source\ndef nested():\n    return other + source\nlast = other\n"
    )
    tree = context.tree
    assert tree is not None
    expected = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
    assert context.parents == expected
    assert context.parents is context.parents
    assert isinstance(context.parents, MappingProxyType)
    loads = [node for node in ast.walk(tree) if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)]
    assert len(loads) > 1
    assert all(node.ctx is loads[0].ctx for node in loads)
    assert context.parents[loads[0].ctx] is loads[-1]
    assert tree not in context.parents


def test_parent_facts_do_not_reuse_another_files_tree() -> None:
    first = PythonFileContext(Path("app.py"), "first = source\n")
    second = PythonFileContext(Path("app.py"), "second = source\n")
    second_tree = second.tree
    assert second_tree is not None
    assert first.parents is not second.parents
    assert parent_map(second_tree, index=first.node_index) == second.parents
    assert not any(isinstance(node, ast.Name) and node.id == "first" for node in second.parents)
