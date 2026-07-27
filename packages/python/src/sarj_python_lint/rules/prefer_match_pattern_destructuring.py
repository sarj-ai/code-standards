"""SARJ069: a `case Cls():` arm that reaches back into the subject for its fields.

A class pattern that binds nothing and then reads the subject's attributes in the
body throws away the best part of structural pattern matching:

    match event:
        case AttachLiveKit():                 # binds nothing
            setup(event.config, event.room)   # reaches back for the fields

    match event:
        case AttachLiveKit(config=config, room=room):   # preferred
            setup(config, room)

Three concrete things the keyword pattern buys, all of which the reach-back form
loses:

* **A renamed field fails the match instead of blowing up at runtime.** A
  keyword pattern is a `getattr` performed *by the match*: if the attribute is
  gone the arm simply does not match (verified against CPython — a missing
  attribute in a class pattern is a match failure, not an `AttributeError`), so
  the fall-through / `assert_never` arm catches the drift. The reach-back form
  matches happily and then raises `AttributeError` deep inside the body, in
  production, on whichever request happened to take that branch. basedpyright
  checks the keyword names against the class's real fields at author time, so
  the rename is usually caught before it ever runs.
* **The body works on plain locals.** `config` is narrowed exactly once, at the
  pattern; `event.config` is re-narrowed at every mention and any intervening
  call can invalidate the narrowing.
* **The arm documents what it consumes.** `case AttachLiveKit(config=config,
  room=room):` states the arm's entire data dependency on one line. A reader
  chasing a field has to read the whole body otherwise.

Fires when ALL of these hold:

* the `match` subject is a plain name (a subject like `resolve(x)` or
  `self.state` has no name for the body to reach back through, so there is
  nothing to compare against),
* the arm's pattern is a class pattern, optionally wrapped in `as` (`case
  Foo() as evt:`); an or-pattern (`case A() | B():`) is never flagged, since
  the fields to destructure differ per alternative,
* the class is not a builtin/ABC (`case str():`, `case Mapping():` — those have
  no fields worth naming),
* the arm body or guard performs at least two plain attribute reads through the
  subject name (or the `as` alias) that the pattern does not already bind — two
  distinct fields, or one field read twice.

The message names the fields and writes the replacement `case` line out in full,
because "destructure this" without the field list is a nag. Capture names follow
the field name, except where that would collide with something the arm already
uses (`case FlowPass(flaky=flaky)` would shadow the `flaky` counter dict the arm
indexes, noura-be `integration/stats.py:67`) or shadow a builtin
(`case CustomScenario(id=id)`, bulbul `services/batch_call_service.py:206`); both
get the subject name as a prefix, `outcome_flaky` and `scenario_id`. An
`x = subj.x` line in the arm is NOT a collision — it is the statement the fix
deletes.

Corpus evidence (bulbul, noura-be, django, fastapi, celery — 286 `match`
statements, 385 class-pattern arms, 239 of them binding nothing): 84 arms reach
back into the subject, 57 after the two-read floor below (bulbul 31, noura-be
26). Zero findings in fastapi and celery, which support Python versions without
`match` and contain no `match` statement at all; django has five `match`
statements in total and, after the two-read floor, zero findings — its single
candidate is the reason that floor exists. Thirty of the 57 findings were read
against the source: no false positives.

Deliberately NOT flagged:

* **One field, read once.** `case ChoicesType(): return value.choices`
  (django `utils/choices.py:83`) and `case FlowFail(): return f"quarantined:
  {outcome.reason}"` (noura-be `integration/junit.py:54`) are whole arms. The
  pattern would grow by exactly what the body shrinks by, no local is reused,
  and there is no body to summarise, so the documentation argument is nil.
  Requiring two reads keeps the rule to the arms where destructuring actually
  pays. Two distinct fields, or one field read twice (noura-be
  `integration/junit.py:42`, which mentions `outcome.reason` in both statements
  of the arm), still fire.
* **Private and dunder attributes.** `case hamsa_stt.STT(): stt._opts.language
  = target_language` (bulbul `agent/lk/agent_tools/meta/code_switching.py:401`)
  reaches into a third-party plugin's private state and already carries an
  `SLF001` waiver; hoisting `_opts` into the pattern would drag that waiver onto
  the `case` line and dress up private access as a field contract. `__class__` /
  `__dict__` are not fields either.
* **The subject is rebound or mutated in the arm.** `event = normalise(event)`,
  `event.retries += 1`, `del event.tmp`, `for event in batch:`, a nested `def
  f(event)` — after any of those the name no longer denotes the matched object,
  or the arm mutates the very field that would have been copied out, so
  destructuring is not behaviour-preserving.
* **Method calls.** `event.serialize()` is not a field, and an attribute called
  anywhere in the arm is dropped from the field list entirely — noura-be's
  `case VisionBankAPIError():` arm (`utils/error_handler/v3.py:224`) mixes
  `error.get_primary_error_code()` with `error.service_code`, and only the
  latter is proposed. Only the *receiver* of a call is excluded, so
  `event.meta.trace_id` still counts `meta` (one level of destructuring is safe,
  two is not) and `handlers[event.kind]` still counts `kind`.
* **Or-patterns and non-class patterns.** `case [x, y]:`, `case 1 | 2:`,
  `case {"type": "attach"}:`, `case None:`. Mapping patterns have the same
  reach-back problem in principle, but across all five corpora there are six
  mapping patterns total and none of them reaches back, so the shape does not
  earn a detector.
* **Builtins and ABCs.** `case str(): return subject.strip()` is a runtime type
  probe, not a variant of an owned union; `str` has no fields to name.
* **Fields the pattern already binds.** A partly-destructured arm
  (`case ChatMessageActionItem(llm_metadata=llm_metadata):` that still reads
  `message.action`, noura-be `services/chatbot/v3/onboarding.py:365`) is the same
  shape and does fire, but only over the fields still being reached for; the
  existing bindings are not re-proposed.

An arm that ALSO uses the whole object still fires: `event` stays bound and
narrowed after a class pattern, so `case Foo(config=config):` loses nothing. An
existing `as` alias is preserved in the suggestion (`case Foo(id=scenario_id) as
scenario:`).

The rule cannot see whether an attribute is a plain field or a property with
side effects. A keyword pattern runs `getattr` while the arm is being *tried*,
which is marginally earlier than the body would have run it; for a property that
does real work, suppress with `# sarj-noqa: SARJ069 — <reason>`.

References:
- https://peps.python.org/pep-0634/#class-patterns
- https://docs.python.org/3/reference/compound_stmts.html#class-patterns

"""

from __future__ import annotations

import ast
import builtins
from dataclasses import dataclass
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none


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
# shadow a builtin: `case CustomScenario(id=id)` trips ruff's A001. Taken from
# the interpreter so the set never drifts.
_BUILTIN_NAMES = frozenset(dir(builtins))


class PreferMatchPatternDestructuring(Rule):
    """A `case Cls():` arm that reads the subject's fields should bind them in the pattern."""

    id: str = "prefer-match-pattern-destructuring"
    code: str = "SARJ069"
    description: str = (
        "`case Cls():` binds nothing and the arm reaches back into the subject for "
        "its fields — destructure in the pattern so a renamed field fails the match "
        "instead of raising AttributeError in the body."
    )

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        """Flag class-pattern arms that reach back into the subject instead of destructuring.

        Returns:
            One diagnostic per un-destructured arm, sorted by position.

        """
        tree = parse_or_none(path, source)
        if tree is None:
            return []

        diags: list[Diagnostic] = []
        for node in ast.walk(tree):
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

    def binding(self, field: str) -> str:
        """Choose a capture name for `field` that the arm can actually use.

        `case FlowPass(flaky=flaky)` would shadow a `flaky` dict the arm already
        indexes, and `case CustomScenario(id=id)` shadows a builtin; both get the
        subject name as a prefix instead (`outcome_flaky`, `scenario_id`).

        Returns:
            The capture name to suggest.

        """
        return f"{self.alias}_{field}" if field in self.taken or field in _BUILTIN_NAMES else field


def _message(finding: _ReachBack) -> str:
    """Render the diagnostic, spelling out the pattern the arm should have used.

    Returns:
        The message text, naming the reached-for fields and the suggested `case`.

    """
    named = finding.fields[:_MAX_NAMED_FIELDS]
    elided = len(finding.fields) - len(named)
    bindings = ", ".join(f"{field}={finding.binding(field)}" for field in named)
    if elided:
        bindings += ", ..."
    suggestion = f"case {finding.cls_name}({bindings})"
    if finding.aliased:
        suggestion += f" as {finding.alias}"
    reads = ", ".join(f"`{finding.alias}.{field}`" for field in named)
    if elided:
        reads += f", and {elided} more"
    return (
        f"`case {finding.cls_name}()` binds nothing, then the arm reaches back for {reads} — write "
        f"`{suggestion}:` instead. The keyword pattern is checked against the class's real fields, "
        "so a renamed field fails the match rather than raising AttributeError inside the body, "
        "and the arm states its data dependencies on the `case` line."
    )


def _reach_back_arm(case: ast.match_case, subject: str) -> _ReachBack | None:
    """Analyse one `case` arm for the reach-back shape.

    Returns:
        The finding, or None when the arm does not qualify.

    """
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
    return _ReachBack(cls_name=cls_name, alias=alias, fields=fields, taken=frozenset(use.taken), aliased=aliased)


def _pattern_class_name(cls: ast.expr) -> str | None:
    """Render the class of a class pattern back to source text.

    Returns:
        `Foo` or `mod.Foo`, or None for a class expression that is neither.

    """
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
    """Walk the arm's guard and body once, recording every name use that matters.

    The guard is scanned alongside the body because a capture is bound *before*
    the guard runs, so `case Foo() if subj.x > 3:` rewrites cleanly to
    `case Foo(x=x) if x > 3:`.

    Bails out (returns None) the moment the arm rebinds the subject name or
    writes through it, since destructuring is then not behaviour-preserving.
    Only one level of attribute access is recorded: `event.meta.trace_id` counts
    `meta`, because `case Foo(meta=meta)` is a safe rewrite and reaching two
    levels into the pattern is not.

    Returns:
        The recorded uses, or None when the arm disqualifies itself.

    """
    use = _ArmUses(reads={}, methods=set(), taken=set(names), aliases=set())
    roots: list[ast.AST] = list(case.body)
    if case.guard is not None:
        roots.append(case.guard)
    for root in roots:
        for node in ast.walk(root):
            if not _record_use(node, names, use):
                return None
    use.taken -= use.aliases
    return use


def _record_use(node: ast.AST, names: set[str], use: _ArmUses) -> bool:
    """Fold one node of the arm into `use`.

    Returns:
        False when the node disqualifies the arm (a rebinding of, or a write
        through, the subject name), True otherwise.

    """
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
    """Record `name` as bound somewhere in the arm.

    Returns:
        False when the bound name is the subject (or its alias), True otherwise.

    """
    if name in names:
        return False
    use.taken.add(name)
    return True
