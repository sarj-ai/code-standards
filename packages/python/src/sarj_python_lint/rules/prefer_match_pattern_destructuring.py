"""SARJ069 — A `case Cls():` arm that reaches back into the subject for its fields.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_prefer_match_pattern_destructuring.py
"""

from __future__ import annotations

import ast
import builtins
from dataclasses import dataclass
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none
from sarj_python_lint.rules._ast_index import walk


if TYPE_CHECKING:
    from pathlib import Path


# Destructuring has to pay for the width it adds to the `case` line. One field
# mentioned once is a wash; two reads is where the arm starts repeating itself
# or hiding more than one dependency in its body.
_MIN_READS = 2

# How many field names the message spells out before it elides the rest.
_MAX_NAMED_FIELDS = 4

# Class patterns over these are runtime type probes, not variants of an owned
# union: they have no domain fields, and `case str(x)` / `case dict()` arms read
# methods rather than attributes.
_BUILTIN_TYPE_NAMES = frozenset(
    {
        "bool",
        "bytearray",
        "bytes",
        "complex",
        "dict",
        "float",
        "frozenset",
        "int",
        "list",
        "memoryview",
        "object",
        "range",
        "set",
        "slice",
        "str",
        "tuple",
        "type",
        "Callable",
        "Collection",
        "Container",
        "Hashable",
        "Iterable",
        "Iterator",
        "Mapping",
        "MutableMapping",
        "MutableSequence",
        "Sequence",
        "Set",
    }
)

# A capture named after the field is the ideal spelling, but not when it would
# shadow a builtin: `case CustomRecord(id=id)` trips ruff's A001. Taken from
# the interpreter so the set never drifts.
_BUILTIN_NAMES = frozenset(dir(builtins))


class PreferMatchPatternDestructuring(Rule):
    id: str = "prefer-match-pattern-destructuring"
    code: str = "SARJ069"
    description: str = (
        "`case Cls():` binds nothing and the arm reaches back into the subject for "
        "its fields — destructure in the pattern so a renamed field fails the match "
        "instead of raising AttributeError in the body."
    )

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        """Flag class-pattern arms that reach back into the subject instead of destructuring."""
        tree = parse_or_none(path, source)
        if tree is None:
            return []

        diags: list[Diagnostic] = []
        for node in walk(tree):
            if not isinstance(node, ast.Match) or not isinstance(node.subject, ast.Name):
                continue
            subject = node.subject.id
            for case in node.cases:
                finding = _reach_back_arm(case, subject)
                if finding is None:
                    continue
                diags.append(
                    Diagnostic(
                        path=path,
                        line=case.pattern.lineno,
                        col=case.pattern.col_offset + 1,
                        code=self.code,
                        message=_message(finding),
                    )
                )
        diags.sort(key=lambda d: (d.line, d.col))
        return diags


@dataclass(frozen=True, slots=True)
class _ReachBack:
    """One arm that matched a class without binding, then read the subject's fields."""

    cls_name: str
    alias: str
    fields: list[str]
    taken: frozenset[str]
    aliased: bool
    # Sub-patterns the arm already had. Both must be reproduced verbatim in
    # the suggestion: dropping a positional one widens what the arm matches
    # (`case Point(0, 0)` would start matching every Point) and dropping a
    # capture makes the body raise NameError.
    kept: tuple[tuple[str, str], ...]
    positional: tuple[str, ...]

    def binding(self, field: str) -> str:
        """Choose a capture name for `field` that the arm can actually use."""
        return f"{self.alias}_{field}" if field in self.taken or field in _BUILTIN_NAMES else field


def _message(finding: _ReachBack) -> str:
    """Render the diagnostic, spelling out the pattern the arm should have used."""
    named = finding.fields[:_MAX_NAMED_FIELDS]
    elided = len(finding.fields) - len(named)
    # The elision stays OUT of the pattern text. A trailing `, ...` inside the
    # parentheses is a syntax error — a bare `...` is a positional pattern, and
    # positional cannot follow keyword — so the suggestion was un-pasteable on
    # every arm that read more fields than fit. It is stated in prose instead.
    bindings = ", ".join(f"{field}={finding.binding(field)}" for field in named)
    kept_text = ", ".join([*finding.positional, *(f"{attr}={name}" for attr, name in finding.kept)])
    if kept_text:
        bindings = f"{kept_text}, {bindings}"
    tail = f", plus the {elided} further field(s) the arm reads" if elided else ""
    suggestion = f"case {finding.cls_name}({bindings})"
    if finding.aliased:
        suggestion += f" as {finding.alias}"
    reads = ", ".join(f"`{finding.alias}.{field}`" for field in named)
    if elided:
        reads += f", and {elided} more"
    return (
        f"`case {finding.cls_name}({kept_text})` leaves {reads} unbound, so the arm reaches back "
        f"into the subject for them — write "
        f"`{suggestion}:` instead{tail}. The keyword pattern is checked against the class's real fields, "
        "so a renamed field fails the match rather than raising AttributeError inside the body, "
        "and the arm states its data dependencies on the `case` line."
    )


def _reach_back_arm(case: ast.match_case, subject: str) -> _ReachBack | None:
    """Analyse one `case` arm for the reach-back shape."""
    pattern = case.pattern
    alias = subject
    aliased = False
    inner: ast.pattern = pattern
    if isinstance(pattern, ast.MatchAs) and pattern.pattern is not None:
        inner = pattern.pattern
        if pattern.name is not None:
            alias = pattern.name
            aliased = True
    if not isinstance(inner, ast.MatchClass):
        return None
    cls_name = _pattern_class_name(inner.cls)
    if cls_name is None or cls_name.rpartition(".")[2] in _BUILTIN_TYPE_NAMES:
        return None

    use = _arm_uses(case, {subject, alias})
    if use is None:
        return None
    already_bound = frozenset(inner.kwd_attrs)
    fields = sorted(
        attr for attr in use.reads if attr not in use.methods and attr not in already_bound and not attr.startswith("_")
    )
    if sum(use.reads[attr] for attr in fields) < _MIN_READS:
        return None
    positional = tuple(ast.unparse(pat) for pat in inner.patterns)
    kept = tuple((attr, ast.unparse(pat)) for attr, pat in zip(inner.kwd_attrs, inner.kwd_patterns, strict=True))
    return _ReachBack(
        cls_name=cls_name,
        alias=alias,
        fields=fields,
        taken=frozenset(use.taken),
        aliased=aliased,
        kept=kept,
        positional=positional,
    )


def _pattern_class_name(cls: ast.expr) -> str | None:
    """Render the class of a class pattern back to source text."""
    match cls:
        case ast.Name(id=name):
            return name
        case ast.Attribute(value=ast.Name(id=module), attr=name):
            return f"{module}.{name}"
        case _:
            return None


@dataclass(slots=True)
class _ArmUses:
    """How one `case` arm uses the subject name and every other name in scope."""

    reads: dict[str, int]
    methods: set[str]
    taken: set[str]
    aliases: set[str]


def _arm_uses(case: ast.match_case, names: set[str]) -> _ArmUses | None:
    """Walk the arm's guard and body once, recording every name use that matters."""
    use = _ArmUses(reads={}, methods=set(), taken=set(names), aliases=set())
    roots: list[ast.AST] = list(case.body)
    if case.guard is not None:
        roots.append(case.guard)
    for root in roots:
        for node in walk(root):
            if not _record_use(node, names, use):
                return None
    use.taken -= use.aliases
    return use


def _record_use(node: ast.AST, names: set[str], use: _ArmUses) -> bool:
    """Fold one node of the arm into `use`."""
    match node:
        case ast.Assign(targets=[ast.Name(id=bound)], value=ast.Attribute(value=ast.Name(id=owner), attr=attr)) | (
            ast.AnnAssign(target=ast.Name(id=bound), value=ast.Attribute(value=ast.Name(id=owner), attr=attr))
        ) if owner in names and attr == bound:
            # `content = msg.content` is the statement the fix deletes, so the
            # name it binds is not a collision.
            use.aliases.add(bound)
        case ast.Name(id=name, ctx=ast.Store() | ast.Del()) | ast.arg(arg=name):
            return _bind(name, names, use)
        case ast.Attribute(value=ast.Name(id=name), ctx=ast.Store() | ast.Del()) if name in names:
            return False
        case ast.Subscript(value=ast.Name(id=name), ctx=ast.Store() | ast.Del()) if name in names:
            return False
        case ast.FunctionDef(name=name) | ast.AsyncFunctionDef(name=name) | ast.ClassDef(name=name):
            return _bind(name, names, use)
        case (
            ast.ExceptHandler(name=str(name))
            | ast.MatchAs(name=str(name))
            | ast.MatchStar(name=str(name))
            | (ast.MatchMapping(rest=str(name)))
        ):
            return _bind(name, names, use)
        case ast.Global(names=declared) | ast.Nonlocal(names=declared):
            return all(_bind(name, names, use) for name in declared)
        case ast.alias(name=imported, asname=asname):
            return _bind(asname or imported.partition(".")[0], names, use)
        case ast.Call(func=ast.Attribute(value=ast.Name(id=name), attr=attr)) if name in names:
            use.methods.add(attr)
        case ast.Attribute(value=ast.Name(id=name), attr=attr, ctx=ast.Load()) if name in names:
            use.reads[attr] = use.reads.get(attr, 0) + 1
        case ast.Name(id=name, ctx=ast.Load()):
            use.taken.add(name)
        case _:
            pass
    return True


def _bind(name: str, names: set[str], use: _ArmUses) -> bool:
    """Record `name` as bound somewhere in the arm."""
    if name in names:
        return False
    use.taken.add(name)
    return True
