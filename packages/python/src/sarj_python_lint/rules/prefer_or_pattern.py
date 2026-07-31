"""SARJ070: adjacent `case` arms with identical bodies — merge them into one or-pattern.

`match` grew the `|` or-pattern precisely so that several shapes sharing one
handler are written as one arm. Splitting them into consecutive arms that
repeat the same body is the copy-paste form of the same dispatch: the reader has
to diff two blocks character by character to learn they are the same, and the
next person who edits one arm has no signal that the sibling arm must change
too. Merging is not a taste call — for adjacent unguarded arms it is a
*provably* semantics-preserving rewrite, because `P1 | P2` tries its
alternatives left to right in exactly the order the two separate arms were
tried.

    # flagged
    match tts:
        case CartesiaTTSSettings(voice=voice):
            tts_voice = voice
        case DeepgramTTSSettings(voice=voice):
            tts_voice = voice
        case InHouseTTSSettings(voice=voice):
            tts_voice = voice

    # preferred
        case (
            CartesiaTTSSettings(voice=voice)
            | DeepgramTTSSettings(voice=voice)
            | InHouseTTSSettings(voice=voice)
        ):
            tts_voice = voice

Corpus evidence. A survey of every `match` statement in six codebases — 329 of
them (repo A 161, repo B 120, this repo 43, django 5, celery 0, fastapi 0;
repo labels are stable within this docstring only) — produced 15 findings:
repo A 4, repo B 1, this repo 10, django 0, celery 0,
fastapi 0. All 15 were read at the cited line and classified by hand; all 15
were true positives, a 0% false-positive rate on a 100% sample.

Widening to 20 corpora (the six above plus three more first-party repos and 14
OSS repos — airflow, dagster, litellm, saleor, mlflow, langchain, superset,
zulip, prefect, warehouse, sentry-python, django, fastapi, celery), 42,732 files
in all, gives 31 findings and still no false positive: dagster 11, this repo 11,
repo A 4, mlflow 2, repo B 1, repo C 1, superset 1. Ten of the eleven
findings in this repo are on rule modules that predate this rule (`stepdown.py`,
`prefer_module_level_constant.py`, and so on) and the eleventh is on a rule
module added alongside it; all are genuine and none is fixed here, so the rule
currently reports on its own repository.

The strongest evidence is that the offending files *already know the idiom*.
One first-party observability setup module opens the very same `match` with
`case OpenAITTSSettings(voice=voice) | GroqTTSSettings(voice=voice):` and
`case AzureTTSSettings() | AWSTTSSettings():`, then four arms later spells out
four further providers one per arm with the identical
`tts_voice = voice` body. The same file does it again for STT
(two in-house STT settings classes, both `stt_model = None`)
directly below a five-way or-pattern. This rule enforces a
convention the codebase picked and then applied unevenly, which is why it does
not read as an imported opinion. Ten further findings are in this repo's own
rule modules — `stepdown.py:588` and `no_isinstance_union_chain.py:221` both
spell `case ast.Name(id="TYPE_CHECKING"):` / `case ast.Attribute(...):` as two
arms returning `True`.

The zeros are honest, not a gap in reach: fastapi and celery contain no `match`
statement at all (both still support Python versions without it), and django's
entire tree holds five, none with a repeated body.

Fires when a `match` contains two or more **consecutive** `case` arms where ALL
of these hold:

* neither arm carries a `guard` — a guard belongs to the whole merged pattern,
  so merging a guarded arm changes which subjects reach the body,
* neither arm's pattern is irrefutable (`case _:` or a bare `case name:`) —
  those are the fallthrough, and folding one into an or-pattern is either
  illegal or turns the whole `match` into a single arm,
* the arm bodies are structurally identical as ASTs,
* the arms bind exactly the same set of names — Python *requires* every
  alternative of an or-pattern to bind the same names, so a run that fails this
  has no legal merge.

Deliberately NOT flagged:

* **arms whose bodies carry different comments.** One first-party analytics
  site dispatches `TimePeriod.WEEK` and
  `TimePeriod.MONTH` to the same `granularity = TimeGranularity.DAY`, but each
  line ends in a different trailing comment (`# 7 data points` /
  `# 30-31 data points`) explaining why that period lands on that granularity.
  The bodies are identical *code* and different *documentation*; merging would
  force one of the two comments to be deleted. Any difference between the
  comment text inside the two arm spans therefore suppresses the diagnostic.
  Ablating this guard is the only thing that changes the six-codebase result at
  all: it takes that sweep from 15 findings to 16, and the extra one is exactly
  this site — without the guard the rule would ship at a 6% FP rate (1 in 16)
  instead of 0%. Re-measured over all 20 corpora the guard costs no true
  positive and suppresses exactly two sites, 31 findings becoming 33: the
  first-party one above and `litellm/litellm/proxy/_experimental/mcp_server/auth/
  user_api_key_auth_mcp.py:776`, where `SessionBearerInvalid()` and
  `NotSessionBearer()` both `raise _aggregate_gateway_dcr_challenge(...)` but the
  second arm carries a two-line comment recording that it is unreachable and
  kept for exhaustiveness. Both are documentation that merging would destroy,
* **a comment sitting between the two arms.** A line comment in the gap before
  a `case` is the author grouping the arms on purpose ("providers that do not
  expose a model:"); the separation is load-bearing documentation. The gap is
  the lines strictly between the two arms — a comment on the first arm's last
  body line or on the second arm's own `case` line belongs to an arm and is
  compared by the previous guard instead. This guard changes nothing on any of
  the 20 corpora in either direction; like the empty-body guard below it is a
  deliberate scope limit, not a measured FP class,
* **non-adjacent arms with the same body.** Reordering arms across an
  intervening pattern can change which arm wins, so a rule that hoisted arms
  together would not be a safe rewrite. Only runs that are already consecutive
  are reported,
* **arms whose bodies match only after renaming a captured name.** The next arm
  after that merged Cartesia/Deepgram run is
  `case UpstreamTTSSettings(speaker=speaker): tts_voice = speaker` — the same body
  modulo `voice` -> `speaker`. Merging demands renaming the capture, and the
  author named it `speaker` because that is what the upstream speech provider
  calls the field; the rename destroys that. Eight such alpha-renamable pairs exist across
  the corpora and none is reported: the rule only ever proposes a rewrite that
  moves no other code,
* **arms whose shared body is a bare `pass` / `...`.** Enumerating variants that
  are deliberately ignored, one per line, is a readable exhaustiveness ledger,
  and there is nothing to de-duplicate when the "shared handler" is empty. This
  guard fires on nothing in the corpora — it is a deliberate scope limit, not a
  measured FP class,
* **`case` arms in different `match` statements**, and arms nested at different
  depths — only sibling arms inside one `match` are compared,
* **a run where the arms bind different names.** `case Foo() as f:` beside
  `case Bar() as b:` is not a legal or-pattern — Python requires every
  alternative to bind the same names — so the rule stays silent rather than
  proposing code that will not compile. `prefer_module_level_constant.py:575`
  is the live example: the `MatchAs`/`MatchStar` arm binds `bound` and the
  `MatchMapping` arm below it binds `rest`, so only the first pair is reported.

Suppress a deliberate split with `# sarj-noqa: SARJ070 — <reason>` on the first
arm's `case` line.

References:
- https://peps.python.org/pep-0634/#or-patterns
- https://docs.python.org/3/reference/compound_stmts.html#or-patterns

"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none
from sarj_python_lint.rules._ast_index import nodes, walk


if TYPE_CHECKING:
    from pathlib import Path


# A run must contain at least this many arms before merging buys anything.
_MIN_RUN = 2

# Patterns are rendered back into the message; long ones are elided so a single
# diagnostic stays readable on one terminal line.
_MAX_RENDERED_PATTERN = 48

# Statement shapes that make an arm body empty. Merging empty arms de-duplicates
# nothing and destroys the one-line-per-variant ledger the author wrote.
_EMPTY_BODY_NODES = (ast.Pass,)


class PreferOrPattern(Rule):
    """Consecutive `case` arms with identical bodies — write one `A() | B():` arm."""

    id: str = "prefer-or-pattern"
    code: str = "SARJ070"
    description: str = (
        "consecutive `case` arms repeating an identical body — merge them into a "
        "single `|` or-pattern so the shared handler is written once."
    )

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        """Flag runs of adjacent `case` arms that duplicate one body.

        Returns:
            One diagnostic per mergeable run, at the first arm, sorted by position.

        """
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        lines = source.splitlines()
        diags = [
            Diagnostic(
                path=path,
                line=run[0].pattern.lineno,
                col=run[0].pattern.col_offset + 1,
                code=self.code,
                message=(
                    f"{len(run)} consecutive `case` arms repeat an identical body — merge them "
                    f"into one or-pattern (`case {_render(run[0].pattern)} | "
                    f"{_render(run[1].pattern)}:`) so the shared handling is written once."
                ),
            )
            for node in nodes(tree, ast.Match)
            for run in _mergeable_runs(node, lines)
        ]
        diags.sort(key=lambda d: (d.line, d.col))
        return diags


def _mergeable_runs(node: ast.Match, lines: list[str]) -> list[list[ast.match_case]]:
    """Group the match's arms into maximal runs of adjacent, mergeable arms.

    A run is extended only while the next arm is mergeable with the arm directly
    before it, so a single non-mergeable arm always breaks the run rather than
    being skipped over.

    Returns:
        Every run of `_MIN_RUN` or more mergeable arms.

    """
    runs: list[list[ast.match_case]] = []
    current: list[ast.match_case] = []
    for case in node.cases:
        if current and _is_mergeable_arm(case) and _arms_merge(current[-1], case, lines):
            current.append(case)
            continue
        if len(current) >= _MIN_RUN:
            runs.append(current)
        current = [case] if _is_mergeable_arm(case) else []
    if len(current) >= _MIN_RUN:
        runs.append(current)
    return runs


def _is_mergeable_arm(case: ast.match_case) -> bool:
    """Report whether an arm can ever take part in an or-pattern merge.

    Returns:
        True for an unguarded, refutable arm with a non-empty body.

    """
    if case.guard is not None:
        return False
    if _is_irrefutable(case.pattern):
        return False
    return not _is_empty_body(case.body)


def _is_irrefutable(pattern: ast.pattern) -> bool:
    """Report whether `pattern` matches everything (`case _:` or `case name:`).

    Returns:
        True for a capture or wildcard pattern with no sub-pattern.

    """
    return isinstance(pattern, ast.MatchAs) and pattern.pattern is None


def _is_empty_body(body: list[ast.stmt]) -> bool:
    """Report whether the arm body does nothing at all.

    `pass` and a bare `...` are the two spellings of "this variant is knowingly
    ignored"; a run of them is a per-variant ledger, not duplicated handling.

    Returns:
        True when the body is a single no-op statement.

    """
    if len(body) != 1:
        return False
    stmt = body[0]
    if isinstance(stmt, _EMPTY_BODY_NODES):
        return True
    return isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant) and stmt.value.value is Ellipsis


def _arms_merge(first: ast.match_case, second: ast.match_case, lines: list[str]) -> bool:
    """Report whether two adjacent arms can be folded into one or-pattern.

    Returns:
        True when the bodies are identical code, the bindings match, and no
        comment distinguishes the two arms.

    """
    if _bound_names(first.pattern) != _bound_names(second.pattern):
        return False
    if not _bodies_equal(first.body, second.body):
        return False
    if _comments_in(lines, first.pattern.lineno, _arm_end(first)) != _comments_in(
        lines, second.pattern.lineno, _arm_end(second)
    ):
        return False
    # A comment in the gap groups the arms deliberately.
    return not _comments_in(lines, _arm_end(first) + 1, second.pattern.lineno - 1)


def _arm_end(case: ast.match_case) -> int:
    """Return the last source line the arm occupies.

    Returns:
        The 1-based end line of the arm's final statement.

    """
    return case.body[-1].end_lineno or case.body[-1].lineno


def _bodies_equal(first: list[ast.stmt], second: list[ast.stmt]) -> bool:
    """Compare two statement blocks structurally, ignoring source positions.

    Returns:
        True when the two blocks are the same code.

    """
    if len(first) != len(second):
        return False
    return all(ast.dump(a) == ast.dump(b) for a, b in zip(first, second, strict=True))


def _bound_names(pattern: ast.pattern) -> frozenset[str]:
    """Collect every name the pattern binds.

    Python requires all alternatives of an or-pattern to bind the same names, so
    two arms with different binding sets have no legal merge.

    Returns:
        The set of names bound anywhere in the pattern.

    """
    names: set[str] = set()
    for node in walk(pattern):
        match node:
            case ast.MatchAs(name=str() as name) | ast.MatchStar(name=str() as name):
                names.add(name)
            case ast.MatchMapping(rest=str() as rest):
                names.add(rest)
            case _:
                pass
    return frozenset(names)


def _comments_in(lines: list[str], start: int, end: int) -> tuple[str, ...]:
    """Collect the `#` tails on the 1-based inclusive line range `start..end`.

    A `#` inside a string literal is read as a comment here. That only ever makes
    the comparison stricter — two arms holding the same literal still produce the
    same tuple — so it costs a rare missed report, never a false one.

    Returns:
        The stripped comment fragments in source order.

    """
    found: list[str] = []
    for index in range(max(start, 1), min(end, len(lines)) + 1):
        _, sep, tail = lines[index - 1].partition("#")
        if sep:
            found.append(tail.strip())
    return tuple(found)


def _render(pattern: ast.pattern) -> str:
    """Render a pattern back to source for the diagnostic message.

    Returns:
        The unparsed pattern, elided past `_MAX_RENDERED_PATTERN` characters, or
        `...` when it cannot be rendered at all.

    """
    try:
        text = ast.unparse(pattern)
    except ValueError, AttributeError, TypeError, RecursionError:
        return "..."
    if len(text) > _MAX_RENDERED_PATTERN:
        return f"{text[:_MAX_RENDERED_PATTERN].rstrip()}..."
    return text
