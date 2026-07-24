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
     owns, or
   * class patterns over classes **defined in this module** (`case Created():`)
     — the SARJ003 local-union gate,

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
   members of the SAME class, that class is **defined in this module** with an
   `Enum`-family base (`Enum`, `StrEnum`, `IntEnum`, `Flag`, `IntFlag`,
   `ReprEnum`), and the terminal `else` is exactly `pass` / bare `return` /
   `return None`. For an imported name the rule cannot prove it is an enum
   (it could be a constants holder), so imported classes are never flagged.

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
        local_classes = frozenset(
            node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)
        )
        local_enums = _local_enum_names(tree)
        diags: list[Diagnostic] = []
        elif_nodes: set[int] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Match):
                wildcard = _silent_closed_set_wildcard(node, local_classes)
                if wildcard is not None:
                    diags.append(self._diag_match(path, wildcard))
            elif isinstance(node, ast.If):
                if len(node.orelse) == 1 and isinstance(node.orelse[0], ast.If):
                    elif_nodes.add(id(node.orelse[0]))
                if id(node) in elif_nodes:
                    continue
                enum_name = _silent_enum_chain(node, local_enums)
                if enum_name is not None:
                    diags.append(self._diag_chain(path, node, enum_name))
        diags.sort(key=lambda d: (d.line, d.col))
        return diags

    def _diag_match(self, path: Path, wildcard: ast.match_case) -> Diagnostic:
        return Diagnostic(
            path=path,
            line=wildcard.pattern.lineno,
            col=wildcard.pattern.col_offset + 1,
            code=self.code,
            message=(
                "silent `case _:` on a closed-set match — a new variant no-ops "
                "instead of failing; use `assert_never(subject)` or raise."
            ),
        )

    def _diag_chain(self, path: Path, head: ast.If, enum_name: str) -> Diagnostic:
        return Diagnostic(
            path=path,
            line=head.lineno,
            col=head.col_offset + 1,
            code=self.code,
            message=(
                f"if/elif over `{enum_name}` members with a silent `else` — a new "
                "member no-ops instead of failing; use `assert_never` or raise "
                "(ideally as a match/case)."
            ),
        )


def _local_enum_names(tree: ast.Module) -> frozenset[str]:
    """Collect names of classes defined in this module with an Enum-family base.

    Returns:
        The set of local enum class names.

    """
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and any(_is_enum_base(b) for b in node.bases):
            names.add(node.name)
    return frozenset(names)


def _is_enum_base(base: ast.expr) -> bool:
    match base:
        case ast.Name(id=name) if name in _ENUM_BASES:
            return True
        case ast.Attribute(attr=name) if name in _ENUM_BASES:
            return True
        case _:
            return False


def _silent_closed_set_wildcard(
    node: ast.Match, local_classes: frozenset[str]
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
    if _all_one_owner_member_arms(real_arms) or _all_local_class_arms(real_arms, local_classes):
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


def _all_one_owner_member_arms(cases: list[ast.match_case]) -> bool:
    """Report whether every arm matches enum-member values of one owner class.

    Returns:
        True when all arms are `Cls.MEMBER`-style values of a single `Cls`.

    """
    owners = {_member_pattern_owner(case.pattern) for case in cases}
    return len(owners) == 1 and None not in owners


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


def _all_local_class_arms(cases: list[ast.match_case], local_classes: frozenset[str]) -> bool:
    """Report whether every arm is a class pattern over a locally-defined class.

    Returns:
        True when all arms are `LocalCls(...)`-style patterns.

    """
    return bool(local_classes) and all(
        _is_local_class_pattern(case.pattern, local_classes) for case in cases
    )


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


def _silent_enum_chain(head: ast.If, local_enums: frozenset[str]) -> str | None:
    """Parse `head` as an ==/in chain over one local enum with a silent `else`.

    Returns:
        The enum class name when the chain qualifies, else None.

    """
    if not local_enums:
        return None
    first_target: ast.expr | None = None
    enum_name: str | None = None
    arm_count = 0
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
        arm_count += 1
        orelse = current.orelse
        if len(orelse) == 1 and isinstance(orelse[0], ast.If):
            current = orelse[0]
            continue
        if arm_count < _MIN_ARMS or not orelse or not _is_silent_body(orelse):
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
