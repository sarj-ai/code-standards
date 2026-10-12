from __future__ import annotations

import ast

from sarj_python_lint.rules._ast_index import walk


def mentions_dunder_all(node: ast.AST) -> bool:
    for child in walk(node):
        match child:
            case ast.Name(id="__all__"):
                return True
            case ast.alias() if (child.asname or child.name).split(".")[0] == "__all__":
                return True
            case ast.FunctionDef() | ast.AsyncFunctionDef() | ast.ClassDef() if child.name == "__all__":
                return True
            case ast.arg(arg="__all__") | ast.ExceptHandler(name="__all__"):
                return True
            case ast.MatchAs() | ast.MatchStar() if child.name == "__all__":
                return True
            case ast.MatchMapping(rest="__all__"):
                return True
            case ast.Global() | ast.Nonlocal() if "__all__" in child.names:
                return True
            case _:
                pass
    return False
