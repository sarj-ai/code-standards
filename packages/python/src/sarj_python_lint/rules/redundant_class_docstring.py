"""SARJ085: a class docstring that only re-spells the class name.

    @dataclass
    class ShipmentCreateData:
        \"\"\"Data for creating a shipment.\"\"\"

        origin: str
        weight_kg: Decimal

Every content word is already in `class ShipmentCreateData`. SARJ050 makes this
judgement for functions and never sees a class: its walker recurses *through* a
`ClassDef` to reach the methods and inspects the class's own docstring nowhere.
That blind spot is this rule.

**The fix is to delete the docstring.** A class with none is clean under this
repo's strict ruff config (D101 is off), and there is no `Returns:`/`Raises:`
analogue left stranded by the deletion.

**Never flagged**

- **Anything whose docstring becomes a published schema description.** This is
  the largest exemption and it decides most of the corpus. A pydantic model's
  class docstring is emitted as its JSON-Schema `description` — verified
  directly, not assumed:

      class ShipmentResponse(pydantic.BaseModel):
          \"\"\"Shipment response.\"\"\"
          tracking_id: str

      >>> ShipmentResponse.model_json_schema()["description"]
      'Shipment response.'

  FastAPI publishes that string in `/openapi.json`, and an LLM tool or
  structured-output schema built from the same model ships it to the model. The
  identical thing happens to an `Enum` subclass and to a `TypedDict` pydantic
  validates. Deleting the text edits an artefact someone else reads — the same
  argument SARJ050 makes for `@function_tool` and route handlers, and the same
  hard exemption. It costs **28 of the 34** otherwise-flaggable first-party
  findings, every one a request/response model, a status `StrEnum`, or a
  `TypedDict` result. Recall is not the thing to optimise when the failure mode
  is silently rewriting an API document.
- **A class whose body IS the docstring** — the whole exception-class idiom.
  Deleting it leaves an empty suite, so the advice would not compile. (A class
  that writes `pass` after the docstring keeps compiling and stays flagged;
  `django/django/contrib/sessions/exceptions.py:17` is that shape.)
- **Value markers and the nine-signal protected class** from `_comments`, so a
  one-line class docstring carrying a URL, an RFC, a status code, a unit or a
  causal connective stays.
- **Prompt / CLI / route decorators**, and the schema decorators
  (`@pydantic.dataclasses.dataclass`, `@strawberry.type`) that place a
  docstring in a schema the way a `BaseModel` base does.
- **Generated code.**
- **Base class names count as signature.** `class NotRegistered(KeyError, TaskError)`
  reads "The task is not registered" as a restatement, because every content
  word — including the `not` that the comment rules treat as a stopword and this
  family deliberately does not — is spelled in the class name or a base. A base
  that contributes a genuinely new word protects the docstring instead: under
  `class Handler(RetryPolicy)`, "retry" and "policy" are free, and anything else
  is not.

**Measured.** 34 of 1,147 first-party class docstrings (3.0%) restate their own
name. After the schema exemption **6** remain, and all 6 were read: **6 true
positives, 0 false** — four `TestX` classes documented as "Tests for X", two
plain `@dataclass` data holders.

Over 14 OSS repos the predicate finds **536** (airflow 192, prefect 108,
litellm 104, langchain 84, superset 80, django 20, dagster 17, saleor 13, celery
6, warehouse 6, mlflow 4, sentry-python 2, fastapi/zulip 0). 30 were sampled
across six of them and read: **30 true positives, 0 false**, e.g.
`celery/celery/utils/collections.py:766` ("Map of buffers." on `class BufferMap`),
`superset/superset/db_engine_specs/firebird.py:28` ("Engine for Firebird"),
`saleor/saleor/graphql/attribute/utils/type_handlers.py:678` ("Handler for Rich
Text attribute type."), `django/tests/gis_tests/test_measure.py:13` ("Testing the
Distance object"). The volume is in libraries because their model and enum
modules — the shapes first-party code writes most — are what the schema
exemption removes here.

This ships as a low-volume ratchet for first-party code, deliberately. The
precedent is SARJ051, which ships with zero Python findings: a rule that holds a
line the corpus has mostly cleared is still worth the code when it has no
failure mode surviving its exemptions.

Suppress an intentional case with `# sarj-noqa: SARJ085 — <reason>`.
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none
from sarj_python_lint.rules._ast_index import nodes
from sarj_python_lint.rules._comments import is_protected, split_identifier
from sarj_python_lint.rules._docstrings import (
    PROMPT_DECORATOR_MARKERS,
    VALUE_MARKER_RE,
    decorator_markers,
    identifier_stems,
    restates,
)
from sarj_python_lint.rules._paths import is_generated


if TYPE_CHECKING:
    from pathlib import Path


# Bases whose subclass docstring is emitted into a machine-readable schema —
# pydantic's JSON Schema `description`, hence FastAPI's OpenAPI document and any
# LLM tool/structured-output schema built from the same model. Matched on the
# final dotted part, so `pydantic.BaseModel` and a bare `BaseModel` import both
# hit. `Protocol` and `ABC` are absent on purpose: their docstrings are read by
# people, not by a serializer.
_SCHEMA_BASES = frozenset(
    {
        "BaseModel",
        "BaseSettings",
        "RootModel",
        "TypedDict",
        "Enum",
        "EnumMeta",
        "Flag",
        "IntEnum",
        "IntFlag",
        "ReprEnum",
        "StrEnum",
    }
)

# `@pydantic.dataclasses.dataclass` and `@strawberry.type` place the docstring in
# a schema the same way a `BaseModel` subclass does.
_SCHEMA_DECORATOR_MARKERS = frozenset({"pydantic", "strawberry", "graphene", "msgspec"})


def _base_names(node: ast.ClassDef) -> list[str]:
    """Render each base as its final dotted part.

    Returns:
        The base names, e.g. `["BaseModel"]` for `class X(pydantic.BaseModel)`.

    """
    names: list[str] = []
    for base in node.bases:
        target = base.value if isinstance(base, ast.Subscript) else base
        if isinstance(target, ast.Attribute):
            names.append(target.attr)
        elif isinstance(target, ast.Name):
            names.append(target.id)
    return names


class RedundantClassDocstring(Rule):
    """A class docstring whose every content word is already in the class name."""

    id: str = "redundant-class-docstring"
    code: str = "SARJ085"
    description: str = (
        "Class docstring only re-spells the class name — delete it, or say what "
        "the name cannot: the invariant, the lifetime, the thing it is not."
    )

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if is_generated(path, source):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        diags: list[Diagnostic] = []
        for node in nodes(tree, ast.ClassDef):
            if self._is_ceremony(node):
                expr = node.body[0]
                diags.append(
                    Diagnostic(
                        path=path,
                        line=expr.lineno,
                        col=expr.col_offset + 1,
                        code=self.code,
                        message=self.description,
                    )
                )
        return sorted(diags, key=lambda d: d.line)

    @staticmethod
    def _is_ceremony(node: ast.ClassDef) -> bool:
        docstring = ast.get_docstring(node, clean=True)
        if not docstring or VALUE_MARKER_RE.search(docstring) or is_protected(docstring):
            return False
        if len(node.body) == 1:
            return False  # the docstring IS the body; deleting it leaves a syntax error
        bases = _base_names(node)
        if _SCHEMA_BASES.intersection(bases):
            return False
        markers = decorator_markers(node)
        if markers & PROMPT_DECORATOR_MARKERS or markers & _SCHEMA_DECORATOR_MARKERS:
            return False
        known = {*identifier_stems(node.name)}
        for base in bases:
            known |= identifier_stems(base)
        known |= {part for base in bases for part in split_identifier(base)}
        return restates(docstring, known)
