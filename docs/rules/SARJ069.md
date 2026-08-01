# SARJ069 `prefer-match-pattern-destructuring` — evidence

Behaviour is specified by [the tests](../../packages/python/tests/rules/test_prefer_match_pattern_destructuring.py); every guard below
has a named test asserting it. This file holds what a test cannot carry: the
measurements that chose each threshold, and the false-positive family each
guard exists to stop.

A class pattern that binds nothing and then reads the subject's attributes in the
body throws away the best part of structural pattern matching:

    match event:
        case AttachSession():                 # binds nothing
            setup(event.config, event.room)   # reaches back for the fields

    match event:
        case AttachSession(config=config, room=room):   # preferred
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
* **The arm documents what it consumes.** `case AttachSession(config=config,
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
uses (`case RunPass(flaky=flaky)` would shadow the `flaky` counter dict the arm
indexes — one first-party site) or shadow a builtin
(`case CustomRecord(id=id)` — a second first-party site); both
get the subject name as a prefix, `outcome_flaky` and `record_id`. An
`x = subj.x` line in the arm is NOT a collision — it is the statement the fix
deletes.

Corpus evidence (two first-party repos, django, fastapi, celery — 286 `match`
statements, 385 class-pattern arms, 239 of them binding nothing): 84 arms reach
back into the subject, 57 after the two-read floor below (repo A 31, repo B
26; repo labels are stable within this docstring only). Zero findings in fastapi
and celery, which support Python versions without
`match` and contain no `match` statement at all; django has five `match`
statements in total and, after the two-read floor, zero findings — its single
candidate is the reason that floor exists. Thirty of the 57 findings were read
against the source: no false positives.

Deliberately NOT flagged:

* **One field, read once.** `case ChoicesType(): return value.choices`
  (django `utils/choices.py:83`) and `case RunFail(): return f"quarantined:
  {outcome.reason}"` (one first-party site) are whole arms. The
  pattern would grow by exactly what the body shrinks by, no local is reused,
  and there is no body to summarise, so the documentation argument is nil.
  Requiring two reads keeps the rule to the arms where destructuring actually
  pays. Two distinct fields, or one field read twice (a sibling arm in the same
  first-party module, which mentions `outcome.reason` in both statements
  of the arm), still fire.
* **Private and dunder attributes.** `case stt_plugin.STT(): stt._opts.language
  = target_language` (one first-party site)
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
  anywhere in the arm is dropped from the field list entirely — one first-party
  `case PaymentAPIError():` arm in an error-handler module mixes
  `error.get_primary_error_code()` with `error.service_code`, and only the
  latter is proposed. Only the *receiver* of a call is excluded, so
  `event.meta.trace_id` still counts `meta` (one level of destructuring is safe,
  two is not) and `handlers[event.kind]` still counts `kind`.
* **Or-patterns and non-class patterns.** `case [x, y]:`, `case 1 | 2:`,
  `case {"type": "attach"}:`, `case None:`. Mapping patterns have the same
  reach-back problem in principle, but across the two first-party repos, django,
  fastapi and celery there are ten `MatchMapping` nodes in total — six of them the
  top-level pattern of an arm, the rest nested — every one in repo A, and none
  reaches back. The shape does not earn a detector. (An earlier draft said "six
  mapping patterns", counting arms; both numbers are given here because the
  difference is exactly the nested ones.)
* **Builtins and ABCs.** `case str(): return subject.strip()` is a runtime type
  probe, not a variant of an owned union; `str` has no fields to name.
* **Fields the pattern already binds.** A partly-destructured arm
  (`case MessageActionItem(llm_metadata=llm_metadata):` that still reaches
  for `message.action`) is the same shape and does fire, over the fields still
  being reached for. The sub-patterns it already had are **reproduced verbatim**
  in the suggestion, ahead of the new keyword captures.

  That reproduction is the whole correctness of the message, and it was missing
  until 0.26.0. Dropping an existing keyword capture proposes a pattern that
  stops binding a name the body still uses, so applying the advice raises
  `NameError`. Dropping a positional sub-pattern is worse: `case Point(0, 0)`
  rewritten keyword-only starts matching *every* `Point`, silently widening what
  the arm accepts. Positional sub-patterns are rendered back to source with
  `ast.unparse`, so `case Point(0, 0)` reading `.label` and `.color` is offered
  as `case Point(0, 0, color=color, label=label)`.

  Relatedly: the field elision is stated in prose rather than as a trailing
  `, ...` inside the parentheses. A bare `...` is a positional pattern and
  positional cannot follow keyword, so the old spelling was a syntax error — 10
  of the 76 findings across the first-party corpora emitted a suggestion that
  could not be pasted. Every suggestion is now checked to parse; the sweep that
  found this asserts it over all 76.

An arm that ALSO uses the whole object still fires: `event` stays bound and
narrowed after a class pattern, so `case Foo(config=config):` loses nothing. An
existing `as` alias is preserved in the suggestion (`case Foo(id=record_id) as
scenario:`).

The rule cannot see whether an attribute is a plain field or a property with
side effects. A keyword pattern runs `getattr` while the arm is being *tried*,
which is marginally earlier than the body would have run it; for a property that
does real work, suppress with `# sarj-noqa: SARJ069 — <reason>`.

References:
- https://peps.python.org/pep-0634/#class-patterns
- https://docs.python.org/3/reference/compound_stmts.html#class-patterns

## Implementation notes

### `_arm_uses`

The guard is scanned alongside the body because a capture is bound *before*
the guard runs, so `case Foo() if subj.x > 3:` rewrites cleanly to
`case Foo(x=x) if x > 3:`.

Bails out (returns None) the moment the arm rebinds the subject name or
writes through it, since destructuring is then not behaviour-preserving.
Only one level of attribute access is recorded: `event.meta.trace_id` counts
`meta`, because `case Foo(meta=meta)` is a safe rewrite and reaching two
levels into the pattern is not.

### `_capture_name`

`case Foo(bar=bar)` binds; `case Foo(bar=1)` constrains and binds nothing.

### `_ReachBack.binding`

`case RunPass(flaky=flaky)` would shadow a `flaky` dict the arm already
indexes, and `case CustomRecord(id=id)` shadows a builtin; both get the
subject name as a prefix instead (`outcome_flaky`, `record_id`).
