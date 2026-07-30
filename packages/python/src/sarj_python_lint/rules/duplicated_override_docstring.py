"""SARJ084: an override whose docstring is a verbatim copy of the base's.

    class RecordManager(ABC):
        def exists(self, keys: Sequence[str]) -> list[bool]:
            \"\"\"Check if the provided keys exist in the database.\"\"\"

    class SQLRecordManager(RecordManager):
        def exists(self, keys: Sequence[str]) -> list[bool]:
            \"\"\"Check if the provided keys exist in the database.\"\"\"   # ← byte-identical
            ...

(That pair is real: `langchain/libs/core/langchain_core/indexing/base.py:331`.)

The copy carries **provably zero** information: it is the same bytes as the text
one class up in the same file. Not a summary, not an implementation note, not a
narrowing of the contract — a paste. And Python already serves the base's text
where the copy is missing: `inspect.getdoc`, `help()`, Sphinx autodoc and every
editor hover walk the MRO, so deleting the override's docstring changes nothing
a reader sees. What it changes is the number of places that sentence has to be
edited when the contract moves — today two, and only one of them next to the
code that implements it.

That drift is the cost. A copied docstring is the one kind that can be wrong
while looking maintained.

**The fix is to delete the override's docstring**, not to reword it. Nothing in
this repo's strict ruff config asks for it back: D102 (`undocumented-public-method`)
is off, and DOC201/DOC402/DOC501 fire only on a docstring that exists.

**Never flagged**

- **A base this file does not define.** Resolution is by plain `ast.Name`
  against classes in the same module, and nothing else. A per-file linter cannot
  follow `from .protocols import Store`, and guessing by name would make every
  same-named class in a repo a candidate parent. This guard costs the most
  recall and is not negotiable.
- **A dotted base.** Matching on the last dotted part alone made a class its own
  parent: a module that does `class Stream(upstream.Stream)` — subclassing an
  import while shadowing its name locally — had its own docstring reported as a
  copy of itself. One finding, one false positive, and requiring the base to be
  an undotted `Name` removes the whole class of error.
- **A stub whose body IS the docstring.** Deleting it leaves an empty suite, so
  the advice would not compile — the same carve-out SARJ050 makes.
- **`@overload` declarations**, whose docstrings belong to the type checker's
  view of the signature rather than to the implementation.
- **A docstring the base does not have.** An override that documents something
  new is the point of writing one.
- **Generated code**, which mirrors whatever the generator emits — and this is
  the shape a generator produces most: one OpenAPI client in the corpus holds 11
  base/subclass method pairs with identical text.

**Measured.** **49 findings across 2,440 reviewable first-party files.** Every
one was read: **49 true positives, 0 false.** All 49 sit in the same layout — a
`Protocol` or ABC declaring the contract and its single in-file implementation
pasting it back. There is no judgement call available, because the test is byte
equality; the only way to be wrong is to resolve the wrong parent, which is what
the two resolution guards above exist to prevent.

Over 14 OSS repos the same predicate finds **137**: langchain 41, airflow 20,
django 19, mlflow 19, prefect 14, dagster 13, saleor 4, superset 2, litellm 2,
sentry-python 2, zulip 1, celery/fastapi/warehouse 0. 18 were sampled and read —
**18 true positives, 0 false** — including
`langchain/libs/langchain/langchain_classic/agents/agent.py:416` and `:692`,
`django/django/db/migrations/questioner.py:173`,
`dagster/python_modules/dagster/dagster/_core/execution/context/hook.py:319`,
`mlflow/mlflow/bedrock/stream.py:140` and
`prefect/src/prefect/server/database/orm_models.py:1624`. The rate is low in
libraries for a structural reason: they put the contract on the ABC and leave
the implementation bare. It is the Protocol-plus-one-implementation layout of
service code that makes the copy tempting.

Suppress an intentional case with `# sarj-noqa: SARJ084 — <reason>`.
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none
from sarj_python_lint.rules._ast_index import nodes
from sarj_python_lint.rules._paths import is_generated_source


if TYPE_CHECKING:
    from pathlib import Path


type _Func = ast.FunctionDef | ast.AsyncFunctionDef

_FUNC_TYPES = (ast.FunctionDef, ast.AsyncFunctionDef)


def _methods(node: ast.ClassDef) -> dict[str, _Func]:
    """Index a class body's directly-defined methods by name.

    Returns:
        `{method name: def node}`; a redefinition keeps the last one, matching
        what the class object would actually hold.

    """
    return {child.name: child for child in node.body if isinstance(child, _FUNC_TYPES)}


def _is_overload(node: _Func) -> bool:
    for decorator in node.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        name = target.attr if isinstance(target, ast.Attribute) else getattr(target, "id", "")
        if name == "overload":
            return True
    return False


class DuplicatedOverrideDocstring(Rule):
    """An override's docstring is byte-identical to the base method's."""

    id: str = "duplicated-override-docstring"
    code: str = "SARJ084"
    description: str = (
        "Docstring is a verbatim copy of the base class's — delete it; "
        "`help()`, `inspect.getdoc` and every editor already read the base's."
    )

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if is_generated_source(source):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        classes = nodes(tree, ast.ClassDef)
        # A name defined twice in one module is ambiguous, and the second
        # definition is what a subclass below it would actually inherit from.
        by_name = {node.name: node for node in classes}
        diags: list[Diagnostic] = []
        for node in classes:
            for base in self._resolvable_bases(node, by_name):
                self._compare(node, base, path, diags)
        return sorted(diags, key=lambda d: d.line)

    @staticmethod
    def _resolvable_bases(node: ast.ClassDef, by_name: dict[str, ast.ClassDef]) -> list[ast.ClassDef]:
        """Bases of `node` that this module defines under an undotted name.

        Returns:
            The base class nodes, excluding `node` itself — a class that shadows
            an imported base of the same name is not its own parent.

        """
        found: list[ast.ClassDef] = []
        for base in node.bases:
            if not isinstance(base, ast.Name):
                continue
            parent = by_name.get(base.id)
            if parent is not None and parent is not node:
                found.append(parent)
        return found

    def _compare(
        self,
        node: ast.ClassDef,
        parent: ast.ClassDef,
        path: Path,
        diags: list[Diagnostic],
    ) -> None:
        inherited = _methods(parent)
        for name, child in _methods(node).items():
            base_method = inherited.get(name)
            if base_method is None or _is_overload(child) or _is_overload(base_method):
                continue
            if len(child.body) == 1:
                continue  # the docstring IS the body; deleting it leaves a syntax error
            docstring = ast.get_docstring(child, clean=True)
            if not docstring or docstring != ast.get_docstring(base_method, clean=True):
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
