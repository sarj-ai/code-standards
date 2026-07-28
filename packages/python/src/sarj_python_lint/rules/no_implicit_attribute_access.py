"""SARJ055: Forbid implicit dictionary accesses on loosely-typed payloads.

The anti-pattern:
    number = ctx.participant.attributes.get("sip.phoneNumber")
    user_id = event.payload["user_id"]

Accessing unstructured `.attributes`, `.payload`, or `.meta` dictionaries bypasses
type safety and runtime validation.

Define a Pydantic model and parse the payload at the boundary instead:
    class ParticipantAttributes(BaseModel):
        sip_phone_number: str | None = Field(alias="sip.phoneNumber")

    attrs = ParticipantAttributes.model_validate(ctx.participant.attributes)
    number = attrs.sip_phone_number
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none

if TYPE_CHECKING:
    from pathlib import Path

_FORBIDDEN_PROPERTIES = {"attributes", "payload", "meta"}

class NoImplicitAttributeAccess(Rule):
    """Implicit dictionary access on payload objects — use Pydantic models."""

    id: str = "no-implicit-attribute-access"
    code: str = "SARJ055"
    description: str = "Implicit dictionary access on loosely-typed payload properties — use Pydantic models."

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if _is_test_path(path):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        
        diags: list[Diagnostic] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                # Check for `.attributes.get(...)`
                if isinstance(node.func, ast.Attribute) and node.func.attr == "get":
                    if isinstance(node.func.value, ast.Attribute) and node.func.value.attr in _FORBIDDEN_PROPERTIES:
                        diags.append(
                            Diagnostic(
                                path=path,
                                line=node.lineno,
                                col=node.col_offset + 1,
                                code=self.code,
                                message=f"Implicit `.get()` access on `.{node.func.value.attr}` bypasses validation — use a Pydantic model instead."
                            )
                        )
            elif isinstance(node, ast.Subscript):
                # Check for `.attributes[...]`
                if isinstance(node.value, ast.Attribute) and node.value.attr in _FORBIDDEN_PROPERTIES:
                    diags.append(
                        Diagnostic(
                            path=path,
                            line=node.lineno,
                            col=node.col_offset + 1,
                            code=self.code,
                            message=f"Implicit subscript access on `.{node.value.attr}` bypasses validation — use a Pydantic model instead."
                        )
                    )

        return diags

def _is_test_path(path: Path) -> bool:
    return path.name.startswith("test_") or "tests" in path.parts
