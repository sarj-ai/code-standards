from __future__ import annotations

import ast
from pathlib import PurePosixPath
import re
from typing import TYPE_CHECKING, ClassVar, NamedTuple, override

from sarj_python_lint.rule_base import (
    AutofixPolicy,
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    Rule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
    parse_or_none,
)
from sarj_python_lint.rules._paths import is_generated


if TYPE_CHECKING:
    from pathlib import Path


type _Func = ast.FunctionDef | ast.AsyncFunctionDef


class _InheritedMethod(NamedTuple):
    owner: ast.ClassDef
    method: _Func


class _ClassAlias(NamedTuple):
    name: str
    target: ast.ClassDef


_FUNC_TYPES = (ast.FunctionDef, ast.AsyncFunctionDef)


def _methods(node: ast.ClassDef) -> dict[str, _Func]:
    return {child.name: child for child in node.body if isinstance(child, _FUNC_TYPES)}


def _is_overload(node: _Func) -> bool:
    for decorator in node.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        name = target.attr if isinstance(target, ast.Attribute) else getattr(target, "id", "")
        if name == "overload":
            return True
    return False


class NoCopiedInheritedDocstring(Rule):
    id: str = "no-copied-inherited-docstring"
    code: str = "SARJ084"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="Override must not copy a docstring already inherited from a local base method.",
        rationale="Inherited documentation is already discoverable, while a duplicate adds a second copy that can drift.",
        remediation=(
            "Delete the copied docstring. If author-controlled override code is unclear, clarify names or extract a "
            "helper; keep behavior-specific differences as a concise comment near the divergent code."
        ),
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        aliases=("duplicated-override-docstring",),
        limitations=(
            (
                "Only methods inherited through a local base name, parameterized local base, or simple local class "
                "alias declared earlier in the same lexical body are compared; imported and dynamic bases are excluded."
            ),
            "Transitive local ancestors are followed in declared base order without guessing across lexical scopes.",
            "Overloads, generated files, undocumented bases, and methods whose docstring is their entire body are excluded.",
        ),
        examples=(
            RuleExample(
                example_id="copied-override-docstring",
                title="Override repeats its base method documentation",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/store.py",
                        "class Store:\n"
                        "    def get(self, key: str) -> str:\n"
                        '        """Get a value by key."""\n'
                        "        return key\n\n"
                        "class MemoryStore(Store):\n"
                        "    def get(self, key: str) -> str:\n"
                        '        """Get a value by key."""\n'
                        "        return key\n",
                    ),
                ),
                focus_path=PurePosixPath("app/store.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="override-specific-docstring",
                title="Override relies on the base contract",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/store.py",
                        "class Store:\n"
                        "    def get(self, key: str) -> str:\n"
                        '        """Get a value by key."""\n'
                        "        return key\n\n"
                        "class MemoryStore(Store):\n"
                        "    def get(self, key: str) -> str:\n"
                        "        return key\n",
                    ),
                ),
                focus_path=PurePosixPath("app/store.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description: str = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if is_generated(path, source):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        graph: dict[ast.ClassDef, tuple[ast.ClassDef, ...]] = {}
        _collect_local_bases(tree, graph)
        diags: list[Diagnostic] = []
        for node in graph:
            self._compare(node, _inherited_methods(node, graph), path, diags)
        return sorted(diags, key=lambda d: d.line)

    def _compare(
        self,
        node: ast.ClassDef,
        inherited: dict[str, _InheritedMethod],
        path: Path,
        diags: list[Diagnostic],
    ) -> None:
        for name, child in _methods(node).items():
            resolved = inherited.get(name)
            if resolved is None:
                continue
            parent, base_method = resolved
            if _is_overload(child) or _is_overload(base_method):
                continue
            if len(child.body) == 1:
                continue  # the docstring IS the body; deleting it leaves a syntax error
            docstring = _normalized_docstring(child)
            if not docstring or docstring != _normalized_docstring(base_method):
                continue
            expr = child.body[0]
            diags.append(
                Diagnostic(
                    path=path,
                    line=expr.lineno,
                    col=expr.col_offset + 1,
                    code=self.code,
                    message=(
                        f"Docstring is a verbatim copy of {parent.name}.{name}'s — delete it; "
                        "`help()`, `inspect.getdoc` and every editor already read the base's."
                    ),
                )
            )


def _collect_local_bases(
    owner: ast.Module | ast.ClassDef,
    graph: dict[ast.ClassDef, tuple[ast.ClassDef, ...]],
) -> None:
    visible: dict[str, ast.ClassDef] = {}
    for statement in owner.body:
        alias = _local_class_alias(statement, visible)
        if alias is not None:
            visible[alias[0]] = alias[1]
            continue
        if not isinstance(statement, ast.ClassDef):
            continue
        graph[statement] = tuple(
            parent
            for base in statement.bases
            if (name := _base_name(base)) is not None and (parent := visible.get(name)) is not None
        )
        _collect_local_bases(statement, graph)
        visible[statement.name] = statement


def _normalized_docstring(method: _Func) -> str:
    docstring = ast.get_docstring(method, clean=True) or ""
    return re.sub(r"\s+", " ", docstring).strip().removesuffix(".")


def _base_name(base: ast.expr) -> str | None:
    while isinstance(base, ast.Subscript):
        base = base.value
    return base.id if isinstance(base, ast.Name) else None


def _local_class_alias(
    statement: ast.stmt,
    visible: dict[str, ast.ClassDef],
) -> _ClassAlias | None:
    if isinstance(statement, ast.Assign) and len(statement.targets) == 1:
        target = statement.targets[0]
    elif isinstance(statement, ast.AnnAssign):
        target = statement.target
    else:
        return None
    if not isinstance(target, ast.Name) or not isinstance(statement.value, ast.Name):
        return None
    parent = visible.get(statement.value.id)
    return _ClassAlias(target.id, parent) if parent is not None else None


def _inherited_methods(
    node: ast.ClassDef,
    graph: dict[ast.ClassDef, tuple[ast.ClassDef, ...]],
) -> dict[str, _InheritedMethod]:
    inherited: dict[str, _InheritedMethod] = {}
    for base in graph[node]:
        for name, resolved in _class_methods(base, graph).items():
            inherited.setdefault(name, resolved)
    return inherited


def _class_methods(
    node: ast.ClassDef,
    graph: dict[ast.ClassDef, tuple[ast.ClassDef, ...]],
) -> dict[str, _InheritedMethod]:
    resolved = {name: _InheritedMethod(node, method) for name, method in _methods(node).items()}
    for base in graph[node]:
        for name, inherited in _class_methods(base, graph).items():
            resolved.setdefault(name, inherited)
    return resolved
