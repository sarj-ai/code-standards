from __future__ import annotations

import ast
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rules._resource_provenance import ResourceProvenance


def logger_imports_untouched(context: PythonFileContext, provenance: ResourceProvenance) -> bool:
    for node in context.nodes(ast.Name, ast.Attribute):
        qualified = context.imports.resolved_qualified_name(node)
        if qualified in {"loguru", "loguru.logger"} and not provenance.imported(node, qualified):
            return False
    return True
