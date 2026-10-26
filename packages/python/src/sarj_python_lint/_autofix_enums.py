from __future__ import annotations

import ast
from io import StringIO
import tokenize
from typing import TYPE_CHECKING, final

from sarj_rule_contracts import TextEdit

from sarj_python_lint._autofix_parameters import ParameterFixes
from sarj_python_lint.rules._resource_provenance import ResourceProvenance


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rule_base import Diagnostic


_MIN_MATCH_CASES = 3


def _annotation_reference(node: ast.AST, context: PythonFileContext) -> bool:
    while (parent := context.parents.get(node)) is not None:
        if isinstance(parent, ast.arg | ast.AnnAssign) and parent.annotation is node:
            return True
        if isinstance(parent, ast.FunctionDef | ast.AsyncFunctionDef) and parent.returns is node:
            return True
        if isinstance(parent, ast.stmt):
            return False
        node = parent
    return False


@final
class EnumFixes:
    def __init__(self, context: PythonFileContext) -> None:
        self.context = context
        self.parameters = ParameterFixes(context)
        self.provenance = ResourceProvenance(context)

    def fixes(self, diagnostic: Diagnostic) -> list[TextEdit]:
        if diagnostic.code != "SARJ006" or not self.context.imports.builtin_is_unshadowed("str"):
            return []
        for function in self.context.nodes(ast.FunctionDef):
            argument = self._argument(function, diagnostic)
            if argument is None:
                continue
            branch = function.body[0]
            if not isinstance(branch, ast.Match):
                continue
            domain = self._domain(branch, argument)
            calls = self.parameters.closed_calls(function)
            if not domain or calls is None or not self._literal_calls(calls, argument.arg, domain):
                continue
            aliases = self._aliases(domain)
            if len(aliases) != 1:
                continue
            alias, _alias_domain = aliases[0]
            annotation = argument.annotation
            if annotation is None or self.provenance.binding(alias.name.id, annotation) is not alias.name:
                continue
            lines = StringIO(self.context.source, newline="").readlines()
            start = sum(map(len, lines[: annotation.lineno - 1])) + len(
                lines[annotation.lineno - 1].encode("utf-8")[: annotation.col_offset].decode("utf-8")
            )
            original = ast.get_source_segment(self.context.source, alias.name)
            previous = ast.get_source_segment(self.context.source, annotation)
            if original is not None and previous is not None:
                return [TextEdit(start, start + len(previous), original)]
        return []

    def _argument(self, function: ast.FunctionDef, diagnostic: Diagnostic) -> ast.arg | None:
        if (
            len(function.args.args) != 1
            or function.args.posonlyargs
            or function.args.kwonlyargs
            or function.args.defaults
        ):
            return None
        if len(function.body) != 1 or not isinstance(function.body[0], ast.Match):
            return None
        branch = function.body[0]
        if (branch.lineno, branch.col_offset + 1) != (diagnostic.line, diagnostic.col):
            return None
        argument = function.args.args[0]
        if not isinstance(argument.annotation, ast.Name) or argument.annotation.id != "str":
            return None
        return None if self._has_comments(function) else argument

    def _domain(self, branch: ast.Match, argument: ast.arg) -> frozenset[str]:
        if not isinstance(branch.subject, ast.Name) or branch.subject.id != argument.arg:
            return frozenset()
        if len(branch.cases) < _MIN_MATCH_CASES:
            return frozenset()
        domain: set[str] = set()
        for case in branch.cases[:-1]:
            literal = self._returned_case(case)
            if literal is None or literal in domain:
                return frozenset()
            domain.add(literal)
        return frozenset(domain) if self._rejecting_fallback(branch.cases[-1]) else frozenset()

    def _returned_case(self, case: ast.match_case) -> str | None:
        if case.guard is not None or len(case.body) != 1 or not isinstance(case.body[0], ast.Return):
            return None
        if not isinstance(case.body[0].value, ast.Constant) or not isinstance(case.pattern, ast.MatchValue):
            return None
        value = case.pattern.value
        return value.value if isinstance(value, ast.Constant) and isinstance(value.value, str) else None

    def _rejecting_fallback(self, case: ast.match_case) -> bool:
        if case.guard is not None or not isinstance(case.pattern, ast.MatchAs):
            return False
        if case.pattern.pattern is not None or case.pattern.name is not None or len(case.body) != 1:
            return False
        raised = case.body[0]
        return isinstance(raised, ast.Raise) and raised.cause is None and self._literal_exception(raised.exc)

    def _literal_exception(self, exception: ast.expr | None) -> bool:
        if not isinstance(exception, ast.Call) or not isinstance(exception.func, ast.Name):
            return False
        return (
            exception.func.id in {"ValueError", "TypeError", "RuntimeError"}
            and self.context.imports.builtin_is_unshadowed(exception.func.id)
            and not exception.keywords
            and all(isinstance(value, ast.Constant) and isinstance(value.value, str) for value in exception.args)
        )

    def _literal_calls(self, calls: list[ast.Call], name: str, domain: frozenset[str]) -> bool:
        for call in calls:
            values = [*call.args, *(keyword.value for keyword in call.keywords if keyword.arg == name)]
            if len(values) != 1 or not isinstance(values[0], ast.Constant) or values[0].value not in domain:
                return False
        return True

    def _aliases(self, domain: frozenset[str]) -> list[tuple[ast.TypeAlias, frozenset[str]]]:
        tree = self.context.tree
        if tree is None:
            return []
        aliases: list[tuple[ast.TypeAlias, frozenset[str]]] = []
        for alias in tree.body:
            if not isinstance(alias, ast.TypeAlias):
                continue
            literal_values = self._alias_domain(alias)
            if domain < literal_values and self._stable_alias(alias):
                aliases.append((alias, literal_values))
        return aliases

    def _alias_domain(self, alias: ast.TypeAlias) -> frozenset[str]:
        if alias.type_params or not isinstance(alias.value, ast.Subscript):
            return frozenset()
        if not any(
            self.provenance.imported(alias.value.value, name)
            for name in ("typing.Literal", "typing_extensions.Literal")
        ):
            return frozenset()
        values = alias.value.slice.elts if isinstance(alias.value.slice, ast.Tuple) else [alias.value.slice]
        literals: set[str] = set()
        for value in values:
            if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
                return frozenset()
            literals.add(value.value)
        return frozenset(literals)

    def _stable_alias(self, alias: ast.TypeAlias) -> bool:
        if any(
            bindings.get(alias.name.id, []) not in ([], [alias.name]) for bindings in self.provenance.bindings.values()
        ):
            return False
        if any(
            node.id == alias.name.id
            and isinstance(node.ctx, ast.Load)
            and not _annotation_reference(node, self.context)
            for node in self.context.nodes(ast.Name)
        ):
            return False
        return not self._has_comments(alias)

    def _has_comments(self, node: ast.FunctionDef | ast.TypeAlias) -> bool:
        return any(
            token.type == tokenize.COMMENT and node.lineno <= token.start[0] <= (node.end_lineno or node.lineno)
            for token in tokenize.generate_tokens(StringIO(self.context.source, newline="").readline)
        )
