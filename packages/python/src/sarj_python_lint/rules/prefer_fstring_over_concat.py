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
    Severity,
    parse_or_none,
)
from sarj_python_lint.rules._ast_index import nodes, walk
from sarj_python_lint.rules._logging import LOG_METHODS, is_logger_expr
from sarj_python_lint.rules._paths import is_generated


if TYPE_CHECKING:
    from pathlib import Path


# Method names that make a logger-receiver call a logging call.

# An uppercase SQL suffix marks a query fragment whose concatenation is intentional.
_SQL_RE = re.compile(
    r"^\s*(?:(?i:(?:select\b.+\bfrom|insert\s+into|update\s+\S+\s+set|delete\s+from|merge\s+into)\b|"
    r"with\s+\w+\s+as\s*\(|(?:create|alter|drop)\s+(?:table|index|view|schema|type|database)\b|"
    r"explain\s+(?:select|insert|update|delete|with)\b)|(?:FROM|JOIN|ORDER\s+BY|GROUP\s+BY|VALUES)\b)",
)

# Calls returning a lazy translation proxy or an escape-aware SafeString.
_LAZY_CALLS = frozenset(
    {
        "_",
        "lazy",
        "format_lazy",
        "gettext",
        "gettext_lazy",
        "ngettext",
        "ngettext_lazy",
        "pgettext",
        "pgettext_lazy",
        "npgettext",
        "npgettext_lazy",
        "ugettext",
        "ugettext_lazy",
        "mark_safe",
        "format_html",
    }
)

# Preserve percent-format templates instead of mixing formatting styles.
_PCT_FORMAT_RE = re.compile(r"%(?![0-9A-Fa-f]{2})(?:\([^)]*\))?[-#0+]?[0-9*.]*[hlL]?[diouxXeEfFgGcrsa%]")

# Constructors that build an ORM / SQL *expression object*, not a string.
_ORM_CALLS = frozenset({"F", "Value", "literal", "literal_column", "Concat", "RawSQL", "bindparam"})

# Roots whose attribute calls are SQLAlchemy expression constructors
# (`func.coalesce(...)`, `expression.cast(...)`, `sa.func.lower(...)`).
_ORM_ROOTS = frozenset({"func", "expression", "sa", "sqla", "sqlalchemy"})

_MAX_LITERAL_CHARACTERS = 160

# A `<expr> + "<whitespace>"` pair is a terminator, not string building.
_TERMINATOR_OPERANDS = 2

# Calls whose Python contract guarantees a concrete ``str`` result.  Keep the
# list deliberately small: user functions named ``render``/``serialize`` may
# return expression objects with an overloaded ``+``.
_STRING_CALLS = frozenset({"ascii", "bin", "chr", "format", "hex", "oct", "repr", "str"})
_STRING_METHODS = frozenset(
    {
        "capitalize",
        "casefold",
        "center",
        "expandtabs",
        "format",
        "format_map",
        "join",
        "ljust",
        "lower",
        "lstrip",
        "removeprefix",
        "removesuffix",
        "replace",
        "rjust",
        "rstrip",
        "strip",
        "swapcase",
        "title",
        "translate",
        "upper",
        "zfill",
    }
)
_REGEX_METHODS = frozenset({"compile", "findall", "finditer", "fullmatch", "match", "search", "split", "sub", "subn"})
_COMPACT_UNITS = frozenset({"em", "ms", "pt", "px", "rem", "s"})
_PRODUCER_NAMES = _STRING_CALLS | {"json", "re", "str"}


class _StringEvidence(NamedTuple):
    names: frozenset[str]
    shadowed: frozenset[str]
    modules: frozenset[str]


class _RegexBindings(NamedTuple):
    modules: frozenset[str]
    functions: frozenset[str]


class PreferFstringOverConcat(Rule):
    id: str = "prefer-fstring-over-concat"
    code: str = "SARJ068"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="Prefer f-strings for short human-readable interpolation when they make the result clearer.",
        rationale="For prose-like strings, f-strings keep interpolated values and surrounding text visible together.",
        remediation=(
            "Replace the interpolation with one f-string. Preserve an explicit `str(value)` conversion as `{value!s}` "
            "and `repr(value)` as `{value!r}` when those conversion semantics matter."
        ),
        category=RuleCategory.STYLE,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Runtime operands must have concrete string evidence.",
            (
                "Logging, common direct SQL and regular-expression forms, lazy strings, ORM expressions, generated files, long "
                "literals, and punctuation-oriented fragment composition are excluded."
            ),
            "The warning is stylistic and intentionally leaves URL, path, protocol, and declarative fragments alone.",
        ),
        examples=(
            RuleExample(
                example_id="literal-string-concatenation",
                title="Known string is joined to literals",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "src/render.py", 'def greeting(name: str) -> str:\n    return "Hello, " + name + "!"\n'
                    ),
                ),
                focus_path=PurePosixPath("src/render.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="formatted-string",
                title="Interpolation uses an f-string",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "src/render.py", 'def greeting(name: str) -> str:\n    return f"Hello, {name}!"\n'
                    ),
                ),
                focus_path=PurePosixPath("src/render.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description: str = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if "+" not in source or is_generated(path, source):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []

        # One walk collects everything: the candidate chains, the inner links of
        # each chain (so a 4-operand chain reports once), and the chains sitting
        # in a context whose rewrite would be wrong.
        inner: set[int] = set()
        excluded: set[int] = set()
        adds: list[ast.BinOp] = []
        parents = {id(child): parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
        regex_bindings = _regex_bindings(tree)
        for node in nodes(tree, ast.BinOp, ast.Call, ast.JoinedStr):
            if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
                adds.append(node)
                for side in (node.left, node.right):
                    if isinstance(side, ast.BinOp) and isinstance(side.op, ast.Add):
                        inner.add(id(side))
            elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
                # `("%0" + width + "d") % args` builds a format template.
                excluded.add(id(node.left))
            elif isinstance(node, ast.Call) and _is_logging_call(node):
                arguments: list[ast.expr] = [*node.args, *(kw.value for kw in node.keywords)]
                excluded.update(id(sub) for arg in arguments for sub in walk(arg))
            elif isinstance(node, ast.Call) and _is_regex_call(node, regex_bindings):
                excluded.update(id(sub) for arg in node.args for sub in walk(arg))
            elif isinstance(node, ast.JoinedStr):
                # Rewriting a concat already nested in an f-string merely
                # trades one interpolation expression for a nested f-string.
                excluded.update(id(sub) for sub in walk(node) if isinstance(sub, ast.BinOp))

        diags: list[Diagnostic] = []
        for node in adds:
            if id(node) in inner or id(node) in excluded:
                continue
            if not _in_callable_scope(node, parents):
                continue
            message = _verdict(node, _string_evidence(node, parents))
            if message is None:
                continue
            diags.append(
                Diagnostic(
                    path=path,
                    line=node.lineno,
                    col=node.col_offset + 1,
                    code=self.code,
                    severity=Severity.WARNING,
                    message=message,
                )
            )
        diags.sort(key=lambda d: (d.line, d.col))
        return diags


def _is_logging_call(node: ast.Call) -> bool:
    func = node.func
    if not isinstance(func, ast.Attribute) or func.attr not in LOG_METHODS:
        return False
    return is_logger_expr(func.value)


def _is_regex_call(node: ast.Call, bindings: _RegexBindings) -> bool:
    func = node.func
    return (isinstance(func, ast.Name) and func.id in bindings.functions) or (
        isinstance(func, ast.Attribute)
        and isinstance(func.value, ast.Name)
        and func.value.id in bindings.modules
        and func.attr in _REGEX_METHODS
    )


def _regex_bindings(tree: ast.Module) -> _RegexBindings:
    modules = {
        alias.asname or alias.name
        for statement in tree.body
        if isinstance(statement, ast.Import)
        for alias in statement.names
        if alias.name == "re"
    }
    functions = {
        alias.asname or alias.name
        for statement in tree.body
        if isinstance(statement, ast.ImportFrom) and statement.module == "re"
        for alias in statement.names
        if alias.name in _REGEX_METHODS
    }
    return _RegexBindings(frozenset(modules), frozenset(functions))


def _in_callable_scope(node: ast.AST, parents: dict[int, ast.AST]) -> bool:
    current = node
    while (parent := parents.get(id(current))) is not None:
        if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            return True
        if isinstance(parent, ast.ClassDef):
            return False
        current = parent
    return False


def _verdict(node: ast.BinOp, evidence: _StringEvidence) -> str | None:
    literals: list[str] = []
    dynamic: list[ast.expr] = []
    operands = _flatten(node)
    for operand in operands:
        if isinstance(operand, ast.Constant):
            if not isinstance(operand.value, str):
                # A bytes/int/float literal is positive evidence this `+` is not
                # string concatenation at all.
                return None
            literals.append(operand.value)
        else:
            dynamic.append(operand)
    if not literals or not dynamic:
        return None
    if sum(len(text) for text in literals) > _MAX_LITERAL_CHARACTERS:
        return None
    # A literal is not sufficient type proof: libraries such as pandas and
    # SQLAlchemy overload reflected ``+`` on their expression objects.  Only
    # recommend an f-string when every runtime operand is provably a string.
    if not all(_is_string_expr(expr, evidence) for expr in dynamic):
        return None
    if any("{" in text or "}" in text for text in literals):
        return None
    if any(_SQL_RE.search(text) for text in literals):
        return None
    if any(_PCT_FORMAT_RE.search(text) for text in literals):
        return None
    if any(
        _is_join_call(expr) or _is_string_repetition(expr) or _is_lazy_call(expr) or _is_orm_expression(expr)
        for expr in dynamic
    ):
        return None
    if any(isinstance(expr, ast.IfExp | ast.BoolOp) for expr in dynamic):
        return None
    if len(operands) == _TERMINATOR_OPERANDS and all(not text.strip() for text in literals):
        return None
    if _is_blob_glue(operands, dynamic):
        return None
    if _is_structural_fragment(literals):
        return None
    if _is_unit_or_filename_fragment(literals):
        return None
    if _is_identifier_fragment(literals, dynamic):
        return None
    if _is_url_or_path_fragment(literals, dynamic):
        return None

    message = "short human-readable string interpolation uses `+`; write it as one f-string when that is clearer"
    if any(_is_str_call(expr) for expr in dynamic):
        message += "; preserve explicit string conversion with `{value!s}`"
    if any(_is_repr_call(expr) for expr in dynamic):
        message += "; preserve explicit representation with `{value!r}`"
    return message


def _is_structural_fragment(literals: list[str]) -> bool:
    substantive = "".join(literals)
    return bool(substantive) and (
        "\\" in substantive
        or any(marker in substantive for marker in ("(?:", "(?=", "(?!", ".*", ".+", "^", "$"))
        or not any(character.isalpha() or character.isspace() for character in substantive)
    )


def _is_url_or_path_fragment(literals: list[str], dynamic: list[ast.expr]) -> bool:
    names = {_root_name(expr).casefold() for expr in dynamic}
    path_name = any(any(word in name for word in ("base", "path", "route", "url", "uri")) for name in names)
    return any("://" in text for text in literals) or (
        path_name and any(text.startswith(("/", "?", "#", "&")) or "/" in text for text in literals)
    )


def _is_unit_or_filename_fragment(literals: list[str]) -> bool:
    compact = [normalized for text in literals if (normalized := text.strip().casefold())]
    if compact and all(text in _COMPACT_UNITS for text in compact):
        return True
    return any(re.fullmatch(r"\.[a-z0-9]{1,8}", text) for text in compact)


def _is_identifier_fragment(literals: list[str], dynamic: list[ast.expr]) -> bool:
    compact = [stripped for text in literals if (stripped := text.strip())]
    if any(text.startswith("@") or text.endswith(("_", ".")) or text == "py" for text in compact):
        return True
    roots = {_root_name(expr).casefold() for expr in dynamic}
    return any(root in {"prefix", "suffix"} for root in roots) and all(
        not any(character.isspace() for character in text) for text in compact
    )


def _flatten(node: ast.expr) -> list[ast.expr]:
    operands: list[ast.expr] = []
    stack = [node]
    while stack:
        current = stack.pop()
        if isinstance(current, ast.BinOp) and isinstance(current.op, ast.Add):
            # Push right first so the left spine is popped first and the
            # operands come out in source order.
            stack.extend((current.right, current.left))
        else:
            operands.append(current)
    return operands


def _is_join_call(expr: ast.expr) -> bool:
    return isinstance(expr, ast.Call) and isinstance(expr.func, ast.Attribute) and expr.func.attr == "join"


def _is_orm_expression(expr: ast.expr) -> bool:
    if not isinstance(expr, ast.Call):
        return False
    func = expr.func
    if isinstance(func, ast.Name) and func.id in _ORM_CALLS:
        return True
    return isinstance(func, ast.Attribute) and _root_name(func) in _ORM_ROOTS


def _root_name(expr: ast.expr) -> str:
    while True:
        if isinstance(expr, (ast.Attribute, ast.Subscript)):
            expr = expr.value
        elif isinstance(expr, ast.Call) and isinstance(expr.func, ast.Attribute):
            expr = expr.func.value
        else:
            break
    return expr.id if isinstance(expr, ast.Name) else ""


def _is_blob_glue(operands: list[ast.expr], dynamic: list[ast.expr]) -> bool:
    text = _template_text(operands)
    if not text or any(fragment.strip() for fragment in text):
        return False
    return any(_has_string_literal_argument(expr) for expr in dynamic)


def _template_text(operands: list[ast.expr]) -> list[str]:
    text: list[str] = []
    for operand in operands:
        if isinstance(operand, ast.Constant) and isinstance(operand.value, str):
            text.append(operand.value)
        elif isinstance(operand, ast.JoinedStr):
            text += [
                val for part in operand.values if isinstance(part, ast.Constant) and isinstance(val := part.value, str)
            ]
    return text


def _has_string_literal_argument(expr: ast.expr) -> bool:
    if not isinstance(expr, ast.Call):
        return False
    arguments: list[ast.expr] = [*expr.args, *(kw.value for kw in expr.keywords)]
    return any(isinstance(arg, ast.Constant) and isinstance(arg.value, str) for arg in arguments)


def _is_lazy_call(expr: ast.expr) -> bool:
    if not isinstance(expr, ast.Call):
        return False
    func = expr.func
    name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ""
    return name in _LAZY_CALLS


def _is_str_call(expr: ast.expr) -> bool:
    return isinstance(expr, ast.Call) and isinstance(expr.func, ast.Name) and expr.func.id == "str"


def _is_repr_call(expr: ast.expr) -> bool:
    return isinstance(expr, ast.Call) and isinstance(expr.func, ast.Name) and expr.func.id == "repr"


def _is_string_repetition(expr: ast.expr) -> bool:
    if not isinstance(expr, ast.BinOp) or not isinstance(expr.op, ast.Mult):
        return False
    return any(isinstance(side, ast.Constant) and isinstance(side.value, str) for side in (expr.left, expr.right))


def _string_evidence(node: ast.BinOp, parents: dict[int, ast.AST]) -> _StringEvidence:
    scope: ast.AST = node
    while not isinstance(scope, ast.Module | ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda):
        parent = parents.get(id(scope))
        if parent is None:
            return _StringEvidence(frozenset(), frozenset(), frozenset())
        scope = parent

    module = scope
    while not isinstance(module, ast.Module):
        parent = parents.get(id(module))
        if parent is None:
            return _StringEvidence(frozenset(), frozenset(), frozenset())
        module = parent
    shadowed = _shadowed_producers(module.body, None)
    modules = _imported_modules(module.body, None) - shadowed
    if not isinstance(scope, ast.Module):
        shadowed |= _scope_shadowed_producers(scope, None)

    known: set[str] = set()
    if isinstance(scope, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda):
        args = scope.args
        for arg in (*args.posonlyargs, *args.args, *args.kwonlyargs):
            if arg.annotation is not None and _annotation_is_string(arg.annotation, shadowed):
                known.add(arg.arg)
        if (
            args.vararg is not None
            and args.vararg.annotation is not None
            and _annotation_is_string(args.vararg.annotation, shadowed)
        ):
            known.add(args.vararg.arg)
        if (
            args.kwarg is not None
            and args.kwarg.annotation is not None
            and _annotation_is_string(args.kwarg.annotation, shadowed)
        ):
            known.add(args.kwarg.arg)

    body: list[ast.stmt] = []
    if isinstance(scope, ast.Module | ast.FunctionDef | ast.AsyncFunctionDef):
        body = scope.body
    for statement in body:
        if statement.lineno >= node.lineno:
            break
        if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
            if _annotation_is_string(statement.annotation, shadowed):
                known.add(statement.target.id)
            else:
                known.discard(statement.target.id)
        elif isinstance(statement, ast.Assign):
            for target in statement.targets:
                if not isinstance(target, ast.Name):
                    continue
                evidence = _StringEvidence(frozenset(known), shadowed, modules)
                if _is_string_expr(statement.value, evidence):
                    known.add(target.id)
                else:
                    known.discard(target.id)
        elif isinstance(statement, ast.AugAssign) and isinstance(statement.target, ast.Name):
            known.discard(statement.target.id)
        else:
            known.difference_update(_bound_names(statement))
    return _StringEvidence(frozenset(known), shadowed, modules)


def _annotation_is_string(annotation: ast.expr, shadowed: frozenset[str]) -> bool:
    if isinstance(annotation, ast.Name):
        return annotation.id == "str" and "str" not in shadowed
    return False


def _is_string_expr(expr: ast.expr, evidence: _StringEvidence) -> bool:
    match expr:
        case ast.Constant(value=str()) | ast.JoinedStr():
            return True
        case ast.Name(id=name):
            return name in evidence.names
        case ast.NamedExpr(value=value):
            return _is_string_expr(value, evidence)
        case ast.Subscript(value=value, slice=index):
            pass
        case ast.Call(func=ast.Name(id=name)):
            return name in _STRING_CALLS and name not in evidence.shadowed
        case ast.Call(func=ast.Attribute(value=ast.Name(id="json"), attr="dumps")):
            return "json" in evidence.modules
        case ast.Call(func=ast.Attribute(value=ast.Name(id="re"), attr="escape"), args=[argument, *_]):
            return "re" in evidence.modules and _is_string_expr(argument, evidence)
        case ast.Call(func=ast.Attribute(value=value, attr=method)):
            return method in _STRING_METHODS and _is_string_expr(value, evidence)
        case _:
            return False

    # Indexing/slicing a proven string preserves ``str`` only for integer
    # positions and slices; a mapping subscript does not inherit its
    # container's annotation.
    integer_index = (
        isinstance(index, ast.Constant) and isinstance(index.value, int) and not isinstance(index.value, bool)
    )
    return (isinstance(index, ast.Slice) or integer_index) and _is_string_expr(value, evidence)


def _shadowed_producers(statements: list[ast.stmt], before_line: int | None) -> frozenset[str]:
    shadowed: set[str] = set()
    for statement in statements:
        if before_line is not None and statement.lineno >= before_line:
            break
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound = {statement.name}
        else:
            bound = _bound_names(statement)
        if isinstance(statement, ast.Import):
            bound.difference_update(
                alias.asname or alias.name
                for alias in statement.names
                if alias.name in {"json", "re"}
            )
        shadowed.update(bound & _PRODUCER_NAMES)
    return frozenset(shadowed)


def _scope_shadowed_producers(scope: ast.AST, before_line: int | None) -> frozenset[str]:
    shadowed: set[str] = set()
    if isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
        shadowed.update(
            argument.arg
            for argument in (
                *scope.args.posonlyargs,
                *scope.args.args,
                *scope.args.kwonlyargs,
                *((scope.args.vararg,) if scope.args.vararg is not None else ()),
                *((scope.args.kwarg,) if scope.args.kwarg is not None else ()),
            )
            if argument.arg in _PRODUCER_NAMES
        )
    if isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)):
        shadowed.update(_shadowed_producers(scope.body, before_line))
    return frozenset(shadowed)


def _imported_modules(statements: list[ast.stmt], before_line: int | None) -> frozenset[str]:
    modules: set[str] = set()
    for statement in statements:
        if before_line is not None and statement.lineno >= before_line:
            break
        if isinstance(statement, ast.Import):
            modules.update(alias.asname or alias.name for alias in statement.names if alias.name in {"json", "re"})
    return frozenset(modules)


def _bound_names(node: ast.AST) -> set[str]:
    names = _stored_names(node)
    for child in ast.walk(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(child.name)
        elif isinstance(child, (ast.Import, ast.ImportFrom)):
            names.update(alias.asname or alias.name.split(".")[0] for alias in child.names)
        elif isinstance(child, ast.ExceptHandler) and child.name is not None:
            names.add(child.name)
    return names


def _stored_names(node: ast.AST) -> set[str]:
    return {
        child.id
        for child in ast.walk(node)
        if isinstance(child, ast.Name) and isinstance(child.ctx, (ast.Store, ast.Del))
    }
