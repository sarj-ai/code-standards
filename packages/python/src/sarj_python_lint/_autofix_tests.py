from __future__ import annotations

import ast
from io import StringIO
import tokenize
from typing import TYPE_CHECKING

from sarj_rule_contracts import TextEdit

from sarj_python_lint._autofix_docs import frame_metadata_observed
from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules._closed_helpers import dynamic_namespace
from sarj_python_lint.rules._resource_provenance import ResourceProvenance


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rule_base import Diagnostic


def fixes(context: PythonFileContext, diagnostic: Diagnostic) -> list[TextEdit]:
    if (
        diagnostic.code != "SARJ456"
        or diagnostic.severity is not Severity.ERROR
        or dynamic_namespace(context)
        or frame_metadata_observed(context)
        or not _canonical_imports(context)
    ):
        return []
    comments = {
        token.start[0]
        for token in tokenize.generate_tokens(StringIO(context.source, newline="").readline)
        if token.type == tokenize.COMMENT
    }
    for test in context.nodes(ast.AsyncFunctionDef):
        call = _assertion(test, context, diagnostic)
        if call is None:
            continue
        if any(test.lineno <= line <= (test.end_lineno or test.lineno) for line in comments):
            continue
        edit = _added_assertion(call, context.source)
        if edit is not None:
            return [edit]
    return []


def _canonical_imports(context: PythonFileContext) -> bool:
    tree = context.tree
    if tree is None:
        return False
    for statement in context.nodes(ast.Import, ast.ImportFrom):
        if not isinstance(statement, ast.ImportFrom) or statement not in tree.body or statement.level:
            return False
        if statement.module == "__future__" and all(alias.name == "annotations" for alias in statement.names):
            continue
        if statement.module != "unittest.mock" or any(alias.name != "AsyncMock" for alias in statement.names):
            return False
    return True


def _assertion(test: ast.AsyncFunctionDef, context: PythonFileContext, diagnostic: Diagnostic) -> ast.Call | None:
    if context.parents.get(test) is not context.tree or test.decorator_list or test.type_params:
        return None
    if not _empty_parameters(test.args):
        return None
    match test.body:
        case [
            ast.Assign(targets=[ast.Name(id=name)], value=ast.Call(args=[], keywords=[]) as constructor),
            ast.Expr(value=ast.Await(value=ast.Call(func=ast.Name(id=called)) as awaited)),
            ast.Expr(value=ast.Call(func=ast.Attribute(value=ast.Name(id=receiver), attr=method)) as asserted),
        ]:
            if called != name or receiver != name or method not in {"assert_called_once", "assert_called_once_with"}:
                return None
            if (asserted.lineno, asserted.col_offset + 1) != (diagnostic.line, diagnostic.col):
                return None
            if not _matching_oracle(awaited, asserted, method):
                return None
            provenance = ResourceProvenance(context, require_static_namespace=True)
            if (
                provenance.imported(constructor.func, "unittest.mock.AsyncMock")
                and not provenance.mock_namespace_patching
                and not provenance.imported_namespace_hazards
            ):
                return asserted
        case _:
            return None
    return None


def _empty_parameters(arguments: ast.arguments) -> bool:
    return not (
        arguments.posonlyargs
        or arguments.args
        or arguments.kwonlyargs
        or arguments.vararg is not None
        or arguments.kwarg is not None
    )


def _matching_oracle(awaited: ast.Call, asserted: ast.Call, method: str) -> bool:
    if method == "assert_called_once":
        return not (awaited.args or awaited.keywords or asserted.args or asserted.keywords)
    return _same_literals(awaited, asserted)


def _same_literals(awaited: ast.Call, asserted: ast.Call) -> bool:
    if any(not isinstance(value, ast.Constant) for value in (*awaited.args, *asserted.args)) or any(
        keyword.arg is None or not isinstance(keyword.value, ast.Constant)
        for keyword in (*awaited.keywords, *asserted.keywords)
    ):
        return False
    return [ast.dump(value) for value in awaited.args] == [ast.dump(value) for value in asserted.args] and [
        ast.dump(value) for value in awaited.keywords
    ] == [ast.dump(value) for value in asserted.keywords]


def _added_assertion(call: ast.Call, source: str) -> TextEdit | None:
    if call.lineno != (call.end_lineno or call.lineno) or not isinstance(call.func, ast.Attribute):
        return None
    lines = StringIO(source, newline="").readlines()
    end_line = call.end_lineno or call.lineno
    line = lines[end_line - 1]
    prefix = line[: call.col_offset]
    end_column = len(line.encode("utf-8")[: call.end_col_offset].decode("utf-8"))
    if prefix.strip() or ast.get_source_segment(source, call) is None or line[end_column:].strip():
        return None
    awaited_method = call.func.attr.replace("assert_called", "assert_awaited", 1)
    added = ast.unparse(
        ast.Call(
            func=ast.Attribute(value=call.func.value, attr=awaited_method, ctx=ast.Load()),
            args=call.args,
            keywords=call.keywords,
        )
    )
    terminated = next((part for part in reversed(lines[:end_line]) if part.endswith("\n")), "")
    newline = "\r\n" if terminated.endswith("\r\n") else "\n"
    offset = sum(map(len, lines[:end_line]))
    leading = "" if line.endswith("\n") else newline
    return TextEdit(offset, offset, leading + prefix + added + newline)
