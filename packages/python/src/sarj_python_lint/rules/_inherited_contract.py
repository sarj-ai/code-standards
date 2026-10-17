from __future__ import annotations

import ast


def inherited_contract(owner: ast.AST | None) -> bool:
    return isinstance(owner, ast.ClassDef) and bool(owner.bases)
