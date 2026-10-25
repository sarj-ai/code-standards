from __future__ import annotations

import ast
from dataclasses import dataclass
from io import StringIO
import re
import tokenize
from typing import TYPE_CHECKING, final

from sarj_rule_contracts import TextEdit

from sarj_python_lint.rules._closed_helpers import dynamic_namespace, stable_class
from sarj_python_lint.rules._resource_provenance import ResourceProvenance


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rule_base import Diagnostic


_MIN_MEMBERS = 2
_ARGUMENT_IGNORE = re.compile(r"#\s*(?:type:\s*ignore\[arg-type\]|pyright:\s*ignore\[reportArgumentType\])\s*\Z")


@dataclass(frozen=True, slots=True)
class _Domain:
    declaration: ast.ClassDef
    members: frozenset[str]


@final
class ExhaustivenessFixes:
    def __init__(self, context: PythonFileContext) -> None:
        self.context = context
        self.provenance = ResourceProvenance(context, require_static_namespace=True)

    def fixes(self, diagnostic: Diagnostic) -> list[TextEdit]:
        if diagnostic.code != "SARJ032" or dynamic_namespace(self.context):
            return []
        for call in self.context.nodes(ast.Call):
            if (call.lineno, call.col_offset + 1) != (diagnostic.line, diagnostic.col):
                continue
            owner = self._owner(call)
            if owner is None:
                continue
            domain = self._domain(owner, call)
            if domain is not None and self._covered(owner, domain):
                return self._comment_edit(call)
        return []

    def _owner(self, call: ast.Call) -> ast.FunctionDef | None:
        statement = self.context.parents.get(call)
        owner = self.context.parents.get(statement) if statement is not None else None
        if not isinstance(statement, ast.Expr) or not isinstance(owner, ast.FunctionDef):
            return None
        if (
            self.context.parents.get(owner) is not self.context.tree
            or owner.body[-1] is not statement
            or owner.decorator_list
            or owner.type_params
        ):
            return None
        if (call.end_lineno or call.lineno) != call.lineno or len(call.args) != 1 or call.keywords:
            return None
        qualified = self.context.imports.resolved_qualified_name(call.func)
        if qualified not in {"typing.assert_never", "typing_extensions.assert_never"}:
            return None
        return owner if self.provenance.imported(call.func, qualified) else None

    def _domain(self, owner: ast.FunctionDef, call: ast.Call) -> _Domain | None:
        arguments = owner.args
        if len(arguments.args) != 1 or arguments.posonlyargs or arguments.kwonlyargs or arguments.vararg is not None:
            return None
        if arguments.kwarg is not None or arguments.defaults:
            return None
        parameter = arguments.args[0]
        subject = call.args[0]
        if not isinstance(subject, ast.Name) or subject.id != parameter.arg:
            return None
        annotation = parameter.annotation
        if not isinstance(annotation, ast.Name):
            return None
        declaration = self.provenance.binding(annotation.id, annotation)
        if (
            not isinstance(declaration, ast.ClassDef)
            or not stable_class(self.context, declaration, self.provenance)
            or declaration.type_params
            or len(declaration.bases) != 1
        ):
            return None
        if (
            not self.provenance.imported(declaration.bases[0], "enum.StrEnum")
            or declaration.name in self.provenance.mutated
        ):
            return None
        members = self._members(declaration)
        return _Domain(declaration, members) if members else None

    def _members(self, declaration: ast.ClassDef) -> frozenset[str]:
        members: dict[str, str] = {}
        for statement in declaration.body:
            match statement:
                case ast.Assign(targets=[ast.Name(id=name)], value=ast.Constant(value=str(value))):
                    if (
                        name.startswith("_")
                        or not name.isascii()
                        or not name.isupper()
                        or name in members
                        or value in members.values()
                    ):
                        return frozenset()
                    members[name] = value
                case _:
                    return frozenset()
        return frozenset(members) if len(members) >= _MIN_MEMBERS else frozenset()

    def _covered(self, owner: ast.FunctionDef, domain: _Domain) -> bool:
        subject = owner.args.args[0].arg
        covered: set[str] = set()
        for statement in owner.body[:-1]:
            current: ast.stmt | None = statement
            while isinstance(current, ast.If):
                member = self._branch_member(current, subject, domain)
                if member is None or member in covered:
                    return False
                covered.add(member)
                if not current.orelse:
                    current = None
                elif len(current.orelse) == 1:
                    current = current.orelse[0]
                else:
                    return False
            if current is not None:
                return False
        return covered == domain.members

    def _branch_member(self, branch: ast.If, subject: str, domain: _Domain) -> str | None:
        if len(branch.body) != 1:
            return None
        returned = branch.body[0]
        if not isinstance(returned, ast.Return) or not isinstance(returned.value, ast.Constant):
            return None
        match branch.test:
            case ast.Compare(
                left=ast.Name(id=name),
                ops=[ast.Is()],
                comparators=[ast.Attribute(value=ast.Name() as reference, attr=member)],
            ) if name == subject and member in domain.members:
                if self.provenance.binding(reference.id, reference) is domain.declaration:
                    return member
                return None
            case _:
                return None

    def _comment_edit(self, call: ast.Call) -> list[TextEdit]:
        lines = StringIO(self.context.source, newline="").readlines()
        try:
            comments = [
                token
                for token in tokenize.generate_tokens(StringIO(self.context.source, newline="").readline)
                if token.type == tokenize.COMMENT and token.start[0] == call.lineno
            ]
        except IndentationError, tokenize.TokenError:
            return []
        if len(comments) != 1 or _ARGUMENT_IGNORE.fullmatch(comments[0].string) is None:
            return []
        comment = comments[0]
        prefix = lines[call.lineno - 1][: comment.start[1]]
        end_column = call.end_col_offset
        if end_column is None or prefix.encode("utf-8")[end_column:].strip():
            return []
        start = sum(map(len, lines[: call.lineno - 1])) + comment.start[1]
        return [TextEdit(start, start + len(comment.string), "")]
