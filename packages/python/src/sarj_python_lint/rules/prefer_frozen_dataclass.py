from __future__ import annotations

import ast
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, final, override

from sarj_python_lint._fixes import python_source_hash
from sarj_python_lint.rule_base import (
    AutofixPolicy,
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    Fix,
    ProjectRule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
    Severity,
    TextEdit,
)
from sarj_python_lint.rules._annotation_origins import AnnotationOrigins
from sarj_python_lint.rules._annotation_semantics import module_rebindings, scope_bound_names
from sarj_python_lint.rules._ast_index import walk as walk_ast
from sarj_python_lint.rules._paths import is_generated, is_test_path, is_test_support_path
from sarj_python_lint.rules._project_index import ProjectIndexSet


if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rules._project_index import SourceUnit


_MUTATION_BUILTINS = frozenset({"delattr", "setattr", "vars"})
_MUTATION_ATTRIBUTES = _MUTATION_BUILTINS | {"__delattr__", "__dict__", "__setattr__"}
_MUTABLE_TYPES = frozenset(
    {
        "builtins.bytearray",
        "builtins.dict",
        "builtins.list",
        "builtins.set",
        "collections.Counter",
        "collections.defaultdict",
        "collections.deque",
        "collections.OrderedDict",
        "collections.abc.MutableMapping",
        "collections.abc.MutableSequence",
        "collections.abc.MutableSet",
        "typing.Dict",
        "typing.List",
        "typing.Set",
        "typing.Deque",
        "typing.DefaultDict",
        "typing.MutableMapping",
        "typing.MutableSequence",
        "typing.MutableSet",
        "asyncio.Lock",
        "asyncio.LifoQueue",
        "asyncio.PriorityQueue",
        "asyncio.Queue",
        "queue.LifoQueue",
        "queue.PriorityQueue",
        "queue.Queue",
        "queue.SimpleQueue",
        "threading.Lock",
        "_thread.LockType",
        "threading.RLock",
    }
)
_NON_FIELDS = frozenset({"dataclasses.KW_ONLY", "typing.ClassVar", "typing_extensions.ClassVar"})
_CUSTOM_INIT = frozenset({"__init__", "__post_init__", "__setattr__", "__delattr__"})
_EXAMPLE = "from dataclasses import dataclass\n\n@dataclass(eq=False)\nclass _CallMedia:\n    audio_input_enabled: bool\n    audio_output_enabled: bool\n"
_FIXED_EXAMPLE = _EXAMPLE.replace("@dataclass(", "@dataclass(frozen=True, ")


@final
class PreferFrozenDataclass(ProjectRule):
    id = "prefer-frozen-dataclass"
    code = "SARJ607"
    documentation = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Freeze dataclass fields when their bindings are never reassigned.",
        rationale="A mutable record permits replacing one field after construction and invalidating its relationship to the other fields.",
        remediation="Set frozen=True on the dataclass and construct a replacement when its fields need to change.",
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.SAFE,
        limitations=(
            "The warning checks plain module-level dataclasses with fields. It skips inheritance, custom initialization, known mutable containers and locks, tests, and generated code.",
            "Matching attribute stores or deletes on any receiver and reflective attribute access suppress the warning. Private classes use the declaring module for write checks. Public classes use the indexed first-party project.",
            "Freezing protects field bindings. Fixes require a private class with eq=False, no slots, and a module without attribute stores or deletes.",
        ),
        examples=(
            RuleExample(
                example_id="mutable-media-configuration",
                title="A media configuration leaves its fields writable",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.python("media/__init__.py", _EXAMPLE),),
                focus_path=PurePosixPath("media/__init__.py"),
                expected_count=1,
                public=True,
                fixed_files=(ExampleFile.python("media/__init__.py", _FIXED_EXAMPLE),),
            ),
            RuleExample(
                example_id="frozen-media-configuration",
                title="A frozen media configuration preserves its field bindings",
                outcome=ExampleOutcome.NO_MATCH,
                files=(ExampleFile.python("media/__init__.py", _FIXED_EXAMPLE),),
                focus_path=PurePosixPath("media/__init__.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    def __init__(self) -> None:
        self._project_writes: dict[Path, set[str] | None] = {}

    @override
    def prepare(self, indexes: ProjectIndexSet) -> None:
        super().prepare(indexes)
        self._project_writes.clear()

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if (
            "dataclass" not in context.symbol_source
            or context.generated
            or is_test_path(context.path)
            or is_test_support_path(context.path)
        ):
            return []
        tree = context.tree
        if tree is None or context.has_wildcard_import:
            return []
        candidates = [node for node in tree.body if isinstance(node, ast.ClassDef) and _unfrozen_decorator(node)]
        project = context.session.project
        if project is None:
            candidates = [node for node in candidates if _fixes(node, node.decorator_list[0], context)]
        if not candidates:
            return []
        if project is None:
            project = ProjectIndexSet.build([context.path], {context.path: context.source})
        unit = project.unit(context.path)
        if unit is None or unit.module is None or project.source_unit(unit.module) is not unit:
            return []
        return self._findings(context, project, unit, candidates)

    def _findings(
        self,
        context: PythonFileContext,
        project: ProjectIndexSet,
        unit: SourceUnit,
        candidates: Sequence[ast.ClassDef],
    ) -> list[Diagnostic]:
        if unit.tree is None or (writes := _attribute_writes(unit.tree)) is None:
            return []
        origins = AnnotationOrigins(context)
        rebound = module_rebindings(unit.tree)
        findings: list[Diagnostic] = []
        for node in candidates:
            decorator = node.decorator_list[0]
            target = decorator.func if isinstance(decorator, ast.Call) else decorator
            if node.name in rebound or origins.qualified(target, node) != "dataclasses.dataclass":
                continue
            fields = _fields(node, context)
            if not fields or not fields.isdisjoint(writes):
                continue
            if not node.name.startswith("_") and self._has_project_write(context, project, fields):
                continue
            if project.may_be_subclassed(unit, node.name):
                continue
            findings.append(
                Diagnostic(
                    context.path,
                    node.lineno,
                    node.col_offset + 1,
                    self.code,
                    f"Set frozen=True on {node.name} to protect its field bindings after construction.",
                    severity=Severity.WARNING,
                    fixes=() if writes else _fixes(node, decorator, context),
                )
            )
        return findings

    def _has_project_write(self, context: PythonFileContext, project: ProjectIndexSet, fields: set[str]) -> bool:
        root = context.session.first_party.project_root(context.path)
        if root is None:
            return True
        if root not in self._project_writes:
            self._project_writes[root] = _project_writes(project, root)
        writes = self._project_writes[root]
        return writes is None or not fields.isdisjoint(writes)


def _unfrozen_decorator(node: ast.ClassDef) -> bool:
    if node.bases or node.keywords or len(node.decorator_list) != 1:
        return False
    decorator = node.decorator_list[0]
    if not isinstance(decorator, ast.Call):
        return True
    return not decorator.args and all(
        keyword.arg is not None
        and isinstance(keyword.value, ast.Constant)
        and type(keyword.value.value) is bool
        and (keyword.arg != "frozen" or keyword.value.value is False)
        and (keyword.arg != "init" or keyword.value.value is True)
        for keyword in decorator.keywords
    )


def _attribute_writes(tree: ast.AST) -> set[str] | None:
    writes: set[str] = set()
    for node in walk_ast(tree):
        match node:
            case ast.Attribute(attr=name) if name in _MUTATION_ATTRIBUTES:
                return None
            case ast.Attribute(attr=name, ctx=(ast.Store() | ast.Del())):
                writes.add(name)
            case ast.Name(id=name, ctx=ast.Load()) if name in _MUTATION_BUILTINS:
                return None
            case ast.ImportFrom(module="builtins", level=0, names=aliases) if any(
                alias.name in _MUTATION_BUILTINS or alias.name == "*" for alias in aliases
            ):
                return None
            case ast.Constant(value=str() as name) if name in {"__dict__", "__setattr__", "__delattr__"}:
                return None
            case _:
                pass
    return writes


def _project_writes(project: ProjectIndexSet, root: Path) -> set[str] | None:
    writes: set[str] = set()
    for unit in project.source_units:
        if root not in unit.path.parents or is_generated(unit.path, unit.source):
            continue
        if unit.tree is None or (names := _attribute_writes(unit.tree)) is None:
            return None
        writes.update(names)
    return writes


def _fields(node: ast.ClassDef, context: PythonFileContext) -> set[str] | None:
    if not _CUSTOM_INIT.isdisjoint(scope_bound_names(node.body)) or _attribute_writes(node):
        return None
    names: set[str] = set()
    for statement in node.body:
        if not isinstance(statement, ast.AnnAssign) or not isinstance(statement.target, ast.Name):
            continue
        annotation = context.annotation_semantics.resolve_alias(statement.annotation)
        if annotation is not None and _type_name(annotation, context) in _NON_FIELDS:
            continue
        members = context.annotation_semantics.transparent_members(annotation)
        types = {_type_name(member, context) for member in members}
        if not members or "dataclasses.InitVar" in types or not types.isdisjoint(_MUTABLE_TYPES):
            return None
        if isinstance(statement.value, ast.Call) and any(
            keyword.arg == "default_factory" and _type_name(keyword.value, context) in _MUTABLE_TYPES
            for keyword in statement.value.keywords
        ):
            return None
        names.add(statement.target.id)
    return names


def _type_name(expression: ast.expr, context: PythonFileContext) -> str | None:
    base = expression.value if isinstance(expression, ast.Subscript) else expression
    origins = context.module_imports
    if isinstance(base, ast.Name) and origins.builtin_is_unshadowed(base.id):
        return f"builtins.{base.id}"
    return origins.resolved_qualified_name(base)


def _fixes(node: ast.ClassDef, decorator: ast.expr, context: PythonFileContext) -> tuple[Fix, ...]:
    if not node.name.startswith("_") or not isinstance(decorator, ast.Call):
        return ()
    options = {keyword.arg: keyword for keyword in decorator.keywords}
    match options.get("eq"), options.get("slots"):
        case ast.keyword(value=ast.Constant(value=False)) as eq, None | ast.keyword(value=ast.Constant(value=False)):
            pass
        case _:
            return ()
    frozen = options.get("frozen")
    if frozen is None:
        edit = TextEdit(eq.lineno, eq.col_offset + 1, eq.lineno, eq.col_offset + 1, "frozen=True, ")
    else:
        value = frozen.value
        if value.end_lineno is None or value.end_col_offset is None:
            return ()
        edit = TextEdit(value.lineno, value.col_offset + 1, value.end_lineno, value.end_col_offset + 1, "True")
    return (Fix("Freeze dataclass fields", AutofixPolicy.SAFE, python_source_hash(context.source), (edit,)),)
