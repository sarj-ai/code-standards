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
    is_suppressed,
)
from sarj_python_lint.rules._ast_index import walk, walk as walk_ast
from sarj_python_lint.rules._logging import LOG_METHODS, is_logger_expr


if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from sarj_python_lint._file_context import PythonFileContext


# Method names that make a logger-receiver call a logging call.

# An uppercase SQL suffix marks a query fragment whose concatenation is intentional.
_SQL_RE = re.compile(
    r"^\s*(?:(?i:(?:select\b.+\bfrom|insert\s+into|update\s+\S+\s+set|delete\s+from|merge\s+into)\b|"
    r"with\s+\w+\s+as\s*\(|(?:create|alter|drop)\s+(?:table|index|view|schema|type|database)\b|"
    r"explain\s+(?:select|insert|update|delete|with)\b)|(?:SELECT|FROM|JOIN|ORDER\s+BY|GROUP\s+BY|VALUES)\b|CAST\s*\()",
)
_SOURCE_FRAGMENT_RE = re.compile(
    r"(?:^|\n)[ \t]*(?:(?:async[ \t]+)?def[ \t]+\w+|class[ \t]+\w+[ \t]*[(:]|"
    r"from[ \t]+[\w.]+[ \t]+import\b|import[ \t]+[\w.]+(?:[ \t]+as[ \t]+\w+)?[ \t]*(?:\n|$)|"
    r"(?:return|yield|raise|assert)[ \t]+\w+[ \t]*\(|"
    r"\#[^\r\n]*(?:\r\n?|\n)|"
    r"(?:\#[ \t]*@generated|--[ \t]*(?:@generated|generated))\b)"
)
_CONFIG_FRAGMENT_RE = re.compile(
    r"(?m)^[ \t]*(?:[^\W\d][\w.-]*[ \t]*=|"
    r"\[{1,2}[A-Za-z_][\w.\"'-]*\]{1,2}[ \t]*(?:\n|$)|"
    r"[A-Za-z_][\w.-]*:[ \t]*[\[{])"
)
_MAPPING_FIELD_RE = re.compile(r"(?m)^[ \t]*[A-Za-z_][\w.-]*:[ \t]*(?:\S|$)")
_MIN_CONFIG_FIELDS = 2

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
_REGEX_CALL_NAMES = frozenset(f"re.{name}" for name in _REGEX_METHODS)
_COMPACT_UNITS = frozenset({"em", "ms", "pt", "px", "rem", "s"})
_PRODUCER_NAMES = _STRING_CALLS | {"json", "re", "str"}


class _StringEvidence(NamedTuple):
    names: frozenset[str]
    shadowed: frozenset[str]
    modules: frozenset[str]


class _RegexBindings(NamedTuple):
    modules: frozenset[str]
    functions: frozenset[str]
    scoped_names: frozenset[str]


class _InterpolationParts(NamedTuple):
    literals: list[str]
    dynamic: list[ast.expr]


class PreferFstringOverConcat(Rule):
    id: str = "prefer-fstring-over-concat"
    code: str = "SARJ068"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        default_level=Severity.ERROR,
        summary="Prefer f-strings for short human-readable interpolation when they make the result clearer.",
        rationale="For prose-like strings, f-strings keep interpolated values and surrounding text visible together.",
        remediation=(
            "Use one f-string when it preserves the required conversion and operator semantics. Preserve an explicit "
            "`str(value)` conversion as `{value!s}` "
            "and `repr(value)` as `{value!r}` when those conversion semantics matter. Retain required custom "
            "concatenation or formatting behavior; a `str` annotation alone does not prove equivalence."
        ),
        category=RuleCategory.STYLE,
        autofix=AutofixPolicy.SAFE,
        limitations=(
            "Safe fixes require every runtime operand to be an explicit unshadowed builtin str, repr or ascii conversion of a proven exact native primitive. Bare strings, subclasses, custom operators and formatting contracts remain review-only.",
            "Runtime operands must have concrete string evidence.",
            "Unique literal-string bindings and aliases supply surrounding text, including module prefixes. Rebinding, global/nonlocal writers, conditional assignments, imported values, and unresolved scopes are not inferred.",
            "String evidence alone does not prove custom concatenation and formatting equivalence; only exact-native-primitive builtin-conversion subsets are fixed.",
            (
                "Logging, source and configuration fragments, generated headers, common direct SQL and regular-expression forms, lazy strings, ORM expressions, generated files, long "
                "literals, and punctuation-oriented fragment composition are excluded."
            ),
            "The policy is stylistic and intentionally leaves URL, path, protocol and declarative fragments alone. Stable aliases of join-built strings retain the fragment-composition exclusion; unresolved or rebound values are not inferred.",
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
            RuleExample(
                example_id="named-literal-prefix",
                scenario="literal-prefix",
                title="A literal prefix still participates in interpolation",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "src/render.py",
                        'PREFIX = "Question: "\ndef render(value: str) -> str:\n    return PREFIX + value\n',
                    ),
                ),
                focus_path=PurePosixPath("src/render.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="formatted-literal-prefix",
                scenario="literal-prefix",
                title="The prefix and value share one f-string",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "src/render.py",
                        'PREFIX = "Question: "\ndef render(value: str) -> str:\n    return f"{PREFIX}{value}"\n',
                    ),
                ),
                focus_path=PurePosixPath("src/render.py"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="safe-autofix-subset",
                title="A proven subset has a convergent automatic fix",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/service.py", ('def label(value):\n    return "The value is " + str(len(value)) + "!"\n')
                    ),
                ),
                fixed_files=(
                    ExampleFile.python(
                        "app/service.py", ("def label(value):\n    return f'The value is {len(value)!s}!'\n")
                    ),
                ),
                focus_path=PurePosixPath("app/service.py"),
                expected_count=1,
            ),
        ),
    )
    description: str = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        path = context.path
        source = context.source
        if "+" not in source or context.generated:
            return []
        tree = context.tree
        if tree is None:
            return []

        # One walk collects everything: the candidate chains, the inner links of
        # each chain (so a 4-operand chain reports once), and the chains sitting
        # in a context whose rewrite would be wrong.
        inner: set[int] = set()
        excluded: set[int] = set()
        adds: list[ast.BinOp] = []
        parents = context.parents
        regex_bindings = _regex_bindings(context)
        for node in context.nodes(ast.BinOp, ast.Call, ast.JoinedStr):
            _classify_concat_context(node, inner, excluded, adds, regex_bindings, context=context)

        diags: list[Diagnostic] = []
        module_evidence: _StringEvidence | None = None
        scope_shadowing: dict[ast.AST, frozenset[str]] = {}
        for node in adds:
            if id(node) in inner or id(node) in excluded:
                continue
            if is_suppressed(context.source_lines, node.lineno, self.code):
                continue
            if not _in_callable_scope(node, parents):
                continue
            if module_evidence is None:
                shadowed = _shadowed_producers(tree.body, None)
                module_evidence = _StringEvidence(frozenset(), shadowed, _imported_modules(tree.body, None) - shadowed)
            message = _verdict(node, _string_evidence(node, parents, module_evidence, scope_shadowing), context)
            if message is None:
                continue
            diags.append(
                Diagnostic(
                    path=path,
                    line=node.lineno,
                    col=node.col_offset + 1,
                    code=self.code,
                    severity=Severity.ERROR,
                    message=message,
                )
            )
        diags.sort(key=lambda d: (d.line, d.col))
        return diags


def _classify_concat_context(
    node: ast.BinOp | ast.Call | ast.JoinedStr,
    inner: set[int],
    excluded: set[int],
    adds: list[ast.BinOp],
    regex_bindings: _RegexBindings,
    *,
    context: PythonFileContext,
) -> None:
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        _collect_add_chain(node, adds, inner)
    elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
        # `("%0" + width + "d") % args` builds a format template.
        excluded.add(id(node.left))
    elif isinstance(node, ast.Call) and _is_logging_call(node):
        _exclude_call_chains(node, excluded)
    elif isinstance(node, ast.Call) and _is_regex_call(node, regex_bindings, context):
        _exclude_regex_chains(node, excluded, context)
    elif isinstance(node, ast.JoinedStr):
        # Nested f-strings would merely replace one existing interpolation expression with another.
        excluded.update(id(sub) for sub in walk(node) if isinstance(sub, ast.BinOp))


def _is_logging_call(node: ast.Call) -> bool:
    func = node.func
    if not isinstance(func, ast.Attribute) or func.attr not in LOG_METHODS:
        return False
    return is_logger_expr(func.value)


def _is_regex_call(node: ast.Call, bindings: _RegexBindings, context: PythonFileContext) -> bool:
    func = node.func
    if isinstance(func, ast.Name) and func.id in bindings.functions:
        return True
    if (
        isinstance(func, ast.Attribute)
        and isinstance(func.value, ast.Name)
        and func.value.id in bindings.modules
        and func.attr in _REGEX_METHODS
    ):
        return True
    root = func.value if isinstance(func, ast.Attribute) else func
    if not isinstance(root, ast.Name) or root.id not in bindings.scoped_names:
        return False
    return _proven_regex_call(node, context)


def _proven_regex_call(node: ast.Call, context: PythonFileContext) -> bool:
    arguments: list[ast.expr] = [*node.args, *(keyword.value for keyword in node.keywords)]
    if not any(isinstance(part, ast.BinOp) and isinstance(part.op, ast.Add) for arg in arguments for part in walk(arg)):
        return False
    return context.static_resource_provenance.runtime_import_name(node.func) in _REGEX_CALL_NAMES


def _exclude_regex_chains(node: ast.Call, excluded: set[int], context: PythonFileContext) -> None:
    if node.keywords and _proven_regex_call(node, context):
        _exclude_call_chains(node, excluded)
    else:
        excluded.update(id(sub) for arg in node.args for sub in walk(arg))


def _regex_bindings(context: PythonFileContext) -> _RegexBindings:
    imports = context.nodes(ast.Import, ast.ImportFrom)
    module_imports = [node for node in imports if context.parents[node] is context.tree]
    modules = {
        alias.asname or alias.name
        for statement in module_imports
        if isinstance(statement, ast.Import)
        for alias in statement.names
        if alias.name == "re"
    }
    functions = _regex_function_bindings(module_imports)
    return _RegexBindings(frozenset(modules), frozenset(functions), _scoped_regex_names(context, imports))


def _regex_function_bindings(imports: Sequence[ast.Import | ast.ImportFrom]) -> set[str]:
    return {
        alias.asname or alias.name
        for statement in imports
        if isinstance(statement, ast.ImportFrom) and statement.module == "re"
        for alias in statement.names
        if alias.name in _REGEX_METHODS
    }


def _scoped_regex_names(context: PythonFileContext, imports: Sequence[ast.Import | ast.ImportFrom]) -> frozenset[str]:
    return frozenset(
        alias.asname or alias.name
        for node in imports
        if context.parents[node] is not context.tree
        for alias in node.names
        if (isinstance(node, ast.Import) and alias.name == "re")
        or (
            isinstance(node, ast.ImportFrom)
            and node.module == "re"
            and node.level == 0
            and alias.name in _REGEX_METHODS
        )
    )


def _in_callable_scope(node: ast.AST, parents: Mapping[ast.AST, ast.AST]) -> bool:
    current = node
    while (parent := parents.get(current)) is not None:
        match parent:
            case ast.FunctionDef() | ast.AsyncFunctionDef() | ast.Lambda():
                return True
            case ast.ClassDef():
                return False
            case _:
                pass
        current = parent
    return False


def _verdict(node: ast.BinOp, evidence: _StringEvidence, context: PythonFileContext) -> str | None:
    operands = _flatten(node)
    parts = _interpolation_parts(operands, evidence, context)
    if parts is None:
        return None
    literals, dynamic = parts
    if _unsupported_interpolation_operands(literals, dynamic, evidence) or _has_bound_join(dynamic, context):
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


def _interpolation_parts(
    operands: list[ast.expr], evidence: _StringEvidence, context: PythonFileContext
) -> _InterpolationParts | None:
    literals: list[str] = []
    dynamic: list[ast.expr] = []
    inline_literal = any(isinstance(operand, ast.Constant) and isinstance(operand.value, str) for operand in operands)
    for operand in operands:
        literal = (
            None
            if inline_literal and not isinstance(operand, ast.Constant) and _is_string_expr(operand, evidence)
            else _literal_string(operand, context)
        )
        if literal is not None:
            literals.append(literal)
        elif isinstance(operand, ast.Constant):
            # A bytes/int/float literal is positive evidence this `+` is not
            # string concatenation at all.
            return None
        else:
            dynamic.append(operand)
    return _InterpolationParts(literals, dynamic)


def _literal_string(expression: ast.expr, context: PythonFileContext) -> str | None:
    value = _bound_value(expression, context)
    return value.value if isinstance(value, ast.Constant) and isinstance(value.value, str) else None


def _bound_value(expression: ast.expr, context: PythonFileContext) -> ast.expr | None:
    seen: set[ast.AST] = set()
    while isinstance(expression, ast.Name):
        provenance = context.static_resource_provenance
        if provenance.dynamic_namespace:
            return None
        binding = provenance.runtime_binding(expression.id, expression)
        if not isinstance(binding, ast.Name) or binding in seen:
            return None
        seen.add(binding)
        value = provenance.assignment_value(binding, expression)
        if value is None:
            return None
        expression = value
    return expression


def _has_bound_join(dynamic: list[ast.expr], context: PythonFileContext) -> bool:
    if not any(_is_join_call(call) for call in context.nodes(ast.Call)):
        return False
    return any(_is_join_call(_bound_value(expression, context)) for expression in dynamic)


def _is_structural_fragment(literals: list[str]) -> bool:
    if any(
        _SOURCE_FRAGMENT_RE.search(text)
        or _CONFIG_FRAGMENT_RE.search(text)
        or len(_MAPPING_FIELD_RE.findall(text)) >= _MIN_CONFIG_FIELDS
        for text in literals
    ):
        return True
    substantive = "".join(literals)
    return bool(substantive) and (
        "\\" in substantive
        or any(marker in substantive for marker in ("(?:", "(?=", "(?!", ".*", ".+", "^", "$"))
        or not any(character.isalpha() for character in substantive)
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


def _unsupported_interpolation_operands(
    literals: list[str], dynamic: list[ast.expr], evidence: _StringEvidence
) -> bool:
    if not literals or not dynamic:
        return True
    if sum(len(text) for text in literals) > _MAX_LITERAL_CHARACTERS:
        return True
    # A literal is not sufficient type proof: libraries such as pandas and
    # SQLAlchemy overload reflected ``+`` on their expression objects.  Only
    # recommend an f-string when every runtime operand is provably a string.
    if not all(_is_string_expr(expr, evidence) for expr in dynamic):
        return True
    if any("{" in text or "}" in text for text in literals):
        return True
    if any(_SQL_RE.search(text) for text in literals):
        return True
    if any(_PCT_FORMAT_RE.search(text) for text in literals):
        return True
    if any(
        _is_join_call(expr) or _is_string_repetition(expr) or _is_lazy_call(expr) or _is_orm_expression(expr)
        for expr in dynamic
    ):
        return True
    return bool(any(isinstance(expr, ast.IfExp | ast.BoolOp) for expr in dynamic))


def _is_join_call(expr: ast.expr | None) -> bool:
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


def _string_evidence(
    node: ast.BinOp,
    parents: Mapping[ast.AST, ast.AST],
    module_evidence: _StringEvidence,
    scope_shadowing: dict[ast.AST, frozenset[str]],
) -> _StringEvidence:
    scope: ast.AST = node
    while not isinstance(scope, ast.Module | ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda):
        parent = parents.get(scope)
        if parent is None:
            return _StringEvidence(frozenset(), frozenset(), frozenset())
        scope = parent

    shadowed = module_evidence.shadowed
    modules = module_evidence.modules
    if not isinstance(scope, ast.Module):
        local_shadowing = scope_shadowing.get(scope)
        if local_shadowing is None:
            local_shadowing = _scope_shadowed_producers(scope, None)
            scope_shadowing[scope] = local_shadowing
        shadowed |= local_shadowing
        modules -= local_shadowing

    known: set[str] = set()
    if isinstance(scope, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda):
        _collect_string_parameters(scope, shadowed, known)

    body: list[ast.stmt] = []
    if isinstance(scope, ast.Module | ast.FunctionDef | ast.AsyncFunctionDef):
        body = scope.body
    for statement in body:
        if statement.lineno >= node.lineno:
            break
        _update_string_bindings(statement, shadowed, modules, known)
    return _StringEvidence(frozenset(known), shadowed, modules)


def _annotation_is_string(annotation: ast.expr, shadowed: frozenset[str]) -> bool:
    match annotation:
        case ast.Name(id="str") | ast.Constant(value="str"):
            return "str" not in shadowed
        case _:
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
                alias.asname or alias.name for alias in statement.names if alias.name in {"json", "re"}
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
    for child in walk_ast(node):
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
        for child in walk_ast(node)
        if isinstance(child, ast.Name) and isinstance(child.ctx, (ast.Store, ast.Del))
    }


def _collect_string_parameters(
    scope: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda, shadowed: frozenset[str], known: set[str]
) -> None:
    args = scope.args
    for arg in (*args.posonlyargs, *args.args, *args.kwonlyargs):
        if arg.annotation is not None and _annotation_is_string(arg.annotation, shadowed):
            known.add(arg.arg)


def _update_string_bindings(
    statement: ast.stmt, shadowed: frozenset[str], modules: frozenset[str], known: set[str]
) -> None:
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


def _exclude_call_chains(node: ast.Call, excluded: set[int]) -> None:
    arguments: list[ast.expr] = [*node.args, *(kw.value for kw in node.keywords)]
    excluded.update(id(sub) for arg in arguments for sub in walk(arg))


def _collect_add_chain(node: ast.BinOp, adds: list[ast.BinOp], inner: set[int]) -> None:
    adds.append(node)
    for side in (node.left, node.right):
        if isinstance(side, ast.BinOp) and isinstance(side.op, ast.Add):
            inner.add(id(side))
