"""SARJ032: silent fall-through on closed-set dispatch — prefer `assert_never`.

Dispatch over a closed set of variants that quietly does nothing for "anything
else" is the highest-volume exhaustiveness bug in review feedback: a new variant
is added, no branch handles it, and the code silently no-ops instead of failing
loudly. `typing.assert_never` (or a `raise`) in the fallthrough turns the missed
variant into a pyright error / instant crash. The TS linter enforces the same
invariant via require-assert-never.

Two deterministic detectors, mirroring SARJ003's corroboration discipline (no
type inference is available, so each detector demands structural proof that the
dispatch is over a CLOSED set — corpus validation showed that without this
gate, matches over open-set data such as external API strings and free-form
payload shapes dominate and are deliberate fall-throughs, not bugs):

1. **Silent `case _:` in a closed-set `match`.** A `match` with at least two
   real, unguarded `case` arms that are all either

   * enum-member values of ONE owner class (`case Kind.A:` / `case Kind.A |
     Kind.B:`) — dotted members of a single class are a closed set someone
     owns. The owner name must be bound by a module-scope `class` statement in
     this file or by a `from x import Kind` binding: those are the shapes that
     name a class. Attribute access on a name bound by `import constants`
     (a module of loose constants) or on a plain variable (`cfg.A`) is NOT
     member access on a closed set and never qualifies, or
   * class patterns over classes **defined at module scope of this module**
     (`case Created():`) — the SARJ003 local-union gate. Classes defined
     inside some function elsewhere in the file are invisible here and do not
     make an unrelated match closed,

   whose final `case _:` (bare wildcard, no guard, no capture name) body is
   exactly `pass`, bare `return`, or `return None`. String/number literal
   cases, mapping/sequence patterns, and imported class patterns never qualify:
   they routinely match open-set data where ignoring the rest is the intended
   behavior. `case _: return False` and other value-returning defaults are also
   not flagged — a predicate's default answer is a legitimate result.

   One further corpus-validated exemption: when EVERY real arm's body is purely
   assignments (`x = ...` refinement), the match is the default-then-refine
   idiom — defaults are set before the match and the silent wildcard means
   "keep the defaults", which is defined behavior, not a swallowed variant. The
   detector fires only when at least one arm *does* something (a call, return,
   raise), because that is what a missed variant silently skips.

        # flagged
        match kind:
            case Kind.A: ...
            case Kind.B: ...
            case _:
                pass          # new Kind member silently ignored

        # preferred
            case _:
                assert_never(kind)

2. **`if/elif` chain over a local enum with a silent `else`.** Every arm
   compares the SAME variable via `==` (or `in` over a tuple/list/set) against
   members of the SAME class, that class is **defined at module scope of this
   module** with an `Enum`-family base (`Enum`, `StrEnum`, `IntEnum`, `Flag`,
   `IntFlag`, `ReprEnum`), and the terminal `else` is exactly `pass` / bare
   `return` / `return None`. For an imported name the rule cannot prove it is
   an enum (it could be a constants holder), so imported classes are never
   flagged. A chain whose head is NOT an enum comparison (e.g. a null-check
   first: `if x is None: ... elif x == Status.A: ...`) does not shield the
   enum sub-chain that starts at the first enum arm — that sub-chain is
   checked on its own. The default-then-refine exemption applies here exactly
   as in detector 1: when EVERY arm body is purely assignments, the silent
   `else` means "keep the pre-set defaults" and is not flagged.

        # flagged
        class Status(StrEnum):
            OPEN = "open"
            CLOSED = "closed"

        if status == Status.OPEN:
            ...
        elif status == Status.CLOSED:
            ...
        else:
            return None       # new Status member silently ignored

A deliberate ignore-the-rest dispatch (e.g. classifying external ids where the
provider can add values at any time) is suppressed with
`# sarj-noqa: SARJ032 — <reason>`.

References:
- https://docs.python.org/3/library/typing.html#typing.assert_never
- https://typing.python.org/en/latest/spec/narrowing.html#assert-never-and-exhaustiveness-checking

"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none


if TYPE_CHECKING:
    from pathlib import Path


# A dispatch needs at least this many real (non-wildcard) arms to be flagged.
_MIN_ARMS = 2

_ENUM_BASES = frozenset({"Enum", "StrEnum", "IntEnum", "Flag", "IntFlag", "ReprEnum"})


class PreferMatchAssertNever(Rule):
    """Silent fallthrough on closed-set dispatch — raise or `assert_never` instead."""

    id: str = "prefer-match-assert-never"
    code: str = "SARJ032"
    description: str = (
        "silent `case _:` / silent `else` on closed-set dispatch — a new variant "
        "no-ops instead of failing; use assert_never (or raise) in the fallthrough."
    )

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        module_classdefs = _module_scope_classdefs(tree)
        local_classes = frozenset(node.name for node in module_classdefs)
        local_enums = frozenset(
            node.name
            for node in module_classdefs
            if any(
                (isinstance(b, ast.Name) and b.id in _ENUM_BASES)
                or (isinstance(b, ast.Attribute) and b.attr in _ENUM_BASES)
                for b in node.bases
            )
        )
        member_owners = local_classes | _importfrom_bound_names(tree)
        diags: list[Diagnostic] = []
        consumed_elifs: set[int] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Match):
                wildcard = _silent_closed_set_wildcard(node, local_classes, member_owners)
                if wildcard is not None:
                    diags.append(
                        Diagnostic(
                            path=path,
                            line=wildcard.pattern.lineno,
                            col=wildcard.pattern.col_offset + 1,
                            code=self.code,
                            message=(
                                "silent `case _:` on a closed-set match — a new variant no-ops "
                                "instead of failing; use `assert_never(subject)` or raise."
                            ),
                        )
                    )
            elif isinstance(node, ast.If):
                if id(node) in consumed_elifs:
                    continue
                enum_name = _silent_enum_chain(node, local_enums, consumed_elifs)
                if enum_name is not None:
                    diags.append(
                        Diagnostic(
                            path=path,
                            line=node.lineno,
                            col=node.col_offset + 1,
                            code=self.code,
                            message=(
                                f"if/elif over `{enum_name}` members with a silent `else` — a new "
                                "member no-ops instead of failing; use `assert_never` or raise "
                                "(ideally as a match/case)."
                            ),
                        )
                    )
        diags.sort(key=lambda d: (d.line, d.col))
        return diags


def _module_scope_classdefs(tree: ast.Module) -> list[ast.ClassDef]:
    """Collect class definitions at module scope (including class-nested ones).

    Deliberately does NOT descend into function bodies: a class defined inside
    some unrelated function is not visible where a `match` elsewhere in the
    file dispatches, so it must not make that match look closed-set.

    Returns:
        The module-scope ClassDef nodes.

    """
    found: list[ast.ClassDef] = []
    stack: list[ast.stmt] = list(tree.body)
    while stack:
        stmt = stack.pop()
        if isinstance(stmt, ast.ClassDef):
            found.append(stmt)
            stack.extend(stmt.body)
    return found


def _importfrom_bound_names(tree: ast.Module) -> frozenset[str]:
    """Collect names bound by `from x import Name [as Alias]` statements.

    A `from`-imported name is the shape that binds a class directly, so
    `Kind.MEMBER` on such a name can be member access on a closed set. Names
    bound by plain `import module` are module objects — attribute access on
    them (`constants.CREATED`) reaches loose module-level constants, never an
    owned member set — so they are deliberately NOT collected.

    Returns:
        The set of from-import bound names.

    """
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name != "*":
                    names.add(alias.asname or alias.name)
    return frozenset(names)


def _silent_closed_set_wildcard(
    node: ast.Match, local_classes: frozenset[str], member_owners: frozenset[str]
) -> ast.match_case | None:
    """Return the final `case _:` when it silently swallows a closed-set dispatch.

    Requires >= 2 real unguarded closed-set arms before it, a bare unguarded
    uncaptured wildcard, and a wildcard body that is exactly `pass` / bare
    `return` / `return None`.

    Returns:
        The offending wildcard case, or None when the match does not qualify.

    """
    if len(node.cases) < _MIN_ARMS + 1:
        return None
    last = node.cases[-1]
    pattern = last.pattern
    if not (isinstance(pattern, ast.MatchAs) and pattern.pattern is None and pattern.name is None):
        return None
    if last.guard is not None or not _is_silent_body(last.body):
        return None
    real_arms = node.cases[:-1]
    if any(case.guard is not None for case in real_arms):
        # A guarded arm deliberately lets its own pattern fall through.
        return None
    if all(_is_assignment_only(case.body) for case in real_arms):
        # Default-then-refine: the wildcard keeps pre-set defaults, by design.
        return None
    all_local_class_arms = bool(local_classes) and all(
        _is_local_class_pattern(case.pattern, local_classes) for case in real_arms
    )
    if _all_one_owner_member_arms(real_arms, member_owners) or all_local_class_arms:
        return last
    return None


def _is_assignment_only(body: list[ast.stmt]) -> bool:
    return all(isinstance(stmt, (ast.Assign, ast.AnnAssign, ast.AugAssign)) for stmt in body)


def _is_silent_body(body: list[ast.stmt]) -> bool:
    """Report whether `body` is exactly one None-shaped no-op statement.

    Only `pass`, bare `return`, and `return None` qualify. A value-returning
    default (`return False`, `return ""`) is a legitimate answer, and any other
    statement (log call, raise, assignment) is deliberate handling.

    Returns:
        True when the body silently produces nothing.

    """
    if len(body) != 1:
        return False
    match body[0]:
        case ast.Pass():
            return True
        case ast.Return(value=None):
            return True
        case ast.Return(value=ast.Constant(value=None)):
            return True
        case _:
            return False


def _all_one_owner_member_arms(
    cases: list[ast.match_case], member_owners: frozenset[str]
) -> bool:
    """Report whether every arm matches enum-member values of one owner class.

    The owner must be a name that can actually bind a class here: defined by a
    module-scope `class` statement or bound by `from x import Cls`. A plain
    variable or a name bound by `import constants` (a module object) never
    counts.

    Returns:
        True when all arms are `Cls.MEMBER`-style values of a single `Cls`.

    """
    owners = {_member_pattern_owner(case.pattern) for case in cases}
    if len(owners) != 1 or None in owners:
        return False
    (owner,) = owners
    return owner in member_owners


def _member_pattern_owner(pattern: ast.pattern) -> str | None:
    """Resolve the owner class of a `Cls.MEMBER` value pattern (or an or-pattern of them).

    Returns:
        The owner class name, or None when the pattern is not member-shaped.

    """
    match pattern:
        case ast.MatchValue(value=ast.Attribute(value=ast.Name(id=owner))):
            return owner
        case ast.MatchOr(patterns=subpatterns):
            owners = {_member_pattern_owner(sub) for sub in subpatterns}
            if len(owners) == 1 and None not in owners:
                return owners.pop()
            return None
        case _:
            return None


def _is_local_class_pattern(pattern: ast.pattern, local_classes: frozenset[str]) -> bool:
    match pattern:
        case ast.MatchClass(cls=ast.Name(id=name)):
            return name in local_classes
        case ast.MatchAs(pattern=ast.pattern() as inner):
            return _is_local_class_pattern(inner, local_classes)
        case ast.MatchOr(patterns=subpatterns):
            return all(_is_local_class_pattern(sub, local_classes) for sub in subpatterns)
        case _:
            return False


def _silent_enum_chain(
    head: ast.If, local_enums: frozenset[str], consumed_elifs: set[int]
) -> str | None:
    """Parse `head` as an ==/in chain over one local enum with a silent `else`.

    Each nested `elif` that genuinely continues the chain (same target, same
    enum) is recorded in `consumed_elifs` so the caller does not re-check it as
    a chain head of its own. An `elif` that does NOT continue the chain (or any
    `elif` behind a non-matching head) is deliberately left unconsumed: the
    sub-chain starting there is a dispatch in its own right and gets its own
    check — a null-check head must not shield the enum chain behind it.

    Returns:
        The enum class name when the chain qualifies, else None.

    """
    if not local_enums:
        return None
    first_target: ast.expr | None = None
    enum_name: str | None = None
    arm_bodies: list[list[ast.stmt]] = []
    current = head
    while True:
        parsed = _enum_comparison(current.test, local_enums)
        if parsed is None:
            return None
        target, cls_name = parsed
        if first_target is None:
            first_target = target
            enum_name = cls_name
        elif ast.dump(target) != ast.dump(first_target) or cls_name != enum_name:
            return None
        if current is not head:
            consumed_elifs.add(id(current))
        arm_bodies.append(current.body)
        orelse = current.orelse
        if len(orelse) == 1 and isinstance(orelse[0], ast.If):
            current = orelse[0]
            continue
        if len(arm_bodies) < _MIN_ARMS or not orelse or not _is_silent_body(orelse):
            return None
        if all(_is_assignment_only(body) for body in arm_bodies):
            # Default-then-refine: the silent else keeps pre-set defaults, by design.
            return None
        return enum_name


def _enum_comparison(test: ast.expr, local_enums: frozenset[str]) -> tuple[ast.expr, str] | None:
    """Parse `test` as `x == Cls.MEMBER` or `x in (Cls.A, Cls.B, ...)`.

    Every compared value must be a member attribute of the SAME local enum class.

    Returns:
        The (target, class_name) pair, or None when `test` is not such a comparison.

    """
    if not (isinstance(test, ast.Compare) and len(test.ops) == 1):
        return None
    target = test.left
    comparator = test.comparators[0]
    match test.ops[0]:
        case ast.Eq():
            cls_name = _enum_member_class(comparator, local_enums)
        case ast.In():
            cls_name = _enum_member_container_class(comparator, local_enums)
        case _:
            return None
    if cls_name is None:
        return None
    return target, cls_name


def _enum_member_class(expr: ast.expr, local_enums: frozenset[str]) -> str | None:
    match expr:
        case ast.Attribute(value=ast.Name(id=cls_name)) if cls_name in local_enums:
            return cls_name
        case _:
            return None


def _enum_member_container_class(expr: ast.expr, local_enums: frozenset[str]) -> str | None:
    if not isinstance(expr, (ast.Tuple, ast.List, ast.Set)) or not expr.elts:
        return None
    names = {_enum_member_class(elt, local_enums) for elt in expr.elts}
    if len(names) != 1:
        return None
    return names.pop()
