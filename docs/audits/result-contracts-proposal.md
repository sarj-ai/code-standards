# Recoverable failure contract rule proposal

Use existing typed outcome unions and native exhaustiveness checks first. Add a
small, symbol-aware check for discarded Results. Enforce precise error domains
only where the API owner has established a closed set of actionable outcomes.
Keep exception, sentinel and translation discovery advisory.

The intended contract is success carrying `T`, or failure carrying a domain
`E`. A caller may handle, propagate or translate that failure. Propagating an
entire `E` is deliberate handling; every forwarding function need not enumerate
its variants. A boundary that selects behavior by variant must remain complete
when `E` grows.

The initial research inspected code-standards revision
`c21be326fb8c6ee3059e1703c255f95542bcd517`. The publication recheck inspected
`55a9fe717916abec15533f5d6f272908714624b8`. This is a proposal, not a rule
registration or release. Historical source links below are pinned to the
initial revision; the publication section records changes relevant to any
implementation.
Source examples were checked against a pinned, already-local `<private-corpus>`.
Private source locations and its revision belong in the separate owner-readable
evidence report. Examples here are synthetic reproductions, not copied private
source. Seven scenario groups establish both useful targets and exclusions;
they are a targeted review, not a fleet precision estimate.

## Ranked recommendations

| Rank | Proposed policy | Initial enforcement | Value and implementation cost |
| --- | --- | --- | --- |
| 1 | Exhaustive terminal handling of closed domain errors | Existing compiler and native typed-lint errors; a narrow Python catch-all advisory only after a pilot | Adding a variant exposes incomplete adapters. Low cost for native checks; medium cost for the Python advisory. |
| 2 | Consume Results and avoid unproven success extraction | New symbol-aware discard check at warning; unsafe extraction remains review-only until a supported Result API is present | Prevents success being assumed after a rejected mutation. Medium cost in TypeScript; higher and deliberately narrower in Python. |
| 3 | Preserve the declared domain error contract | Extend existing modeling and widening advisories; deterministic checking only for explicitly designated closed contracts | Keeps retry, repair, conflict and rejection decisions available. Medium cost in TypeScript; higher in Python. |
| 4 | Review hidden failures and lossy boundaries | Advisory audit with evidence, no blocking lint | Finds migration candidates without redefining legitimate absence, recovery or infrastructure handling. Highest judgment and analysis cost. |

Ship rank 1 configuration and regression evidence before introducing a new
detector. Prototype the narrow discard portion of rank 2 next. Revise ranks 3
and 4 through domain review. Do not register speculative rules or reserve
identifiers before the normal authoring workflow admits their implementation.

## Publication recheck and current implementation owners

The [current authoring skill](https://github.com/sarj-ai/code-standards/blob/55a9fe717916abec15533f5d6f272908714624b8/plugins/sarj-skills/skills/lint-rule-generator/SKILL.md)
requires Oxlint `createOnce` rules, separate `src/docs` declarations and Oxlint
RuleTester cases. The initial snapshot used ESLint. Implement new TypeScript
work through the existing
[tsrs services](https://github.com/sarj-ai/code-standards/blob/55a9fe717916abec15533f5d6f272908714624b8/packages/typescript/src/utils/tsrs-services.ts),
which batch type and symbol requests against snapshots in one compiler process
per lint run. Use its native type flags and awaited-type facilities; do not
introduce another compiler process or an ESLint parser-services dependency.
The ESLint API references in the historical analysis are descriptions of that
snapshot, not the target integration for new code.

The [current strict preset](https://github.com/sarj-ai/code-standards/blob/55a9fe717916abec15533f5d6f272908714624b8/packages/standards/src/sarj_standards/configs/oxlint.strict.mts)
enables type-aware analysis, type checking and
`typescript/switch-exhaustiveness-check`. Port the planned completeness and
discard fixtures to its pinned Oxlint/tsrs toolchain before implementation;
the old compiler-probe specifications do not qualify the current engine.
The [current Python runner](https://github.com/sarj-ai/code-standards/blob/55a9fe717916abec15533f5d6f272908714624b8/packages/standards/src/sarj_standards/libs/linting/external.py)
still bounds reported diagnostics to selected files, and its Pyright policy
still enables exhaustive match checking while disabling general unused-call
results. The whole-project coverage requirement remains relevant.

Two newer controls narrow the proposed additions:

- [TypeScript discarded validation results](https://github.com/sarj-ai/code-standards/blob/55a9fe717916abec15533f5d6f272908714624b8/packages/typescript/src/docs/no-discarded-validation-result.ts)
  already warn on ignored import-proven Zod safe-parse outcomes and selected
  output-changing parse results. [Python SARJ519](https://github.com/sarj-ai/code-standards/blob/55a9fe717916abec15533f5d6f272908714624b8/packages/python/src/sarj_python_lint/rules/no_discarded_validation_result.py)
  already checks source-resolved value-producing validators with an explicit
  raise, subject to conservative exclusions. Reuse those resolution facts and
  establish diagnostic precedence. Rank 2 concerns registered domain Results
  beyond these validation-specific contracts; it must not duplicate them.
- [Python SARJ542](https://github.com/sarj-ai/code-standards/blob/55a9fe717916abec15533f5d6f272908714624b8/packages/python/src/sarj_python_lint/rules/no_custom_control_flow_exception.py)
  already advises reviewing directly raised marker or fixed-message custom
  exceptions for typed outcomes, while preserving framework validation,
  cancellation and unwinding. Rank 4 should reuse this advisory and add only
  separately justified audit evidence. A second marker-exception rule is
  redundant.

The current `require-assert-never` implementation also has a scoped empty-default
fix. Evaluate that existing fix under its own closed conditions before adding
any broader rewrite. Its existence does not justify inventing recovery branches
or replacing exceptions with returned errors automatically.

The [current repository instructions](https://github.com/sarj-ai/code-standards/blob/55a9fe717916abec15533f5d6f272908714624b8/AGENTS.md)
allow a complete successful exact-head `Native make verify` workflow job to
satisfy the repository verification requirement when local admission is
delayed. The draft's live qualification status belongs in the PR; it does not
retroactively turn the initial unrun compiler probes into passing evidence.

## Existing owners and demonstrated gaps

The following inventory records the initial research snapshot. The owning
repository is code-standards: these findings require source,
configuration, symbol and control-flow semantics. They do not depend on a
filename merely existing in the Git tree.

| Existing control | What it already does | Remaining gap |
| --- | --- | --- |
| [Strict Pyright policy](https://github.com/sarj-ai/code-standards/blob/c21be326fb8c6ee3059e1703c255f95542bcd517/packages/standards/src/sarj_standards/configs/pyright.strict.json) and [BasedPyright additions](https://github.com/sarj-ai/code-standards/blob/c21be326fb8c6ee3059e1703c255f95542bcd517/packages/standards/src/sarj_standards/configs/basedpyright.strict.json) | Reject unknown and Any leakage, bad member access and incompatible returns; enable `reportMatchNotExhaustive`. | `reportUnusedCallResult` is intentionally disabled because fluent APIs produce noise. A wildcard match is exhaustive even when it silently accepts future domain errors. Exceptions are not an effect in a Python return annotation. |
| [TypeScript base config](https://github.com/sarj-ai/code-standards/blob/c21be326fb8c6ee3059e1703c255f95542bcd517/packages/tsconfig/base.json) and [typed ESLint preset](https://github.com/sarj-ai/code-standards/blob/c21be326fb8c6ee3059e1703c255f95542bcd517/packages/standards/src/sarj_standards/configs/eslint.strict.mjs) | Enable strict null checks, exact optional properties, unsafe-access and assertion rules, `no-floating-promises` with `ignoreVoid: false`, and `switch-exhaustiveness-check`. | Awaiting `Promise<Result<T,E>>` handles the Promise but may discard the resolved Result. An open string tag cannot be checked as a finite domain. Arbitrary `if`/`else` dispatch is not made exhaustive by strict mode. |
| [`require-assert-never`](https://github.com/sarj-ai/code-standards/blob/c21be326fb8c6ee3059e1703c255f95542bcd517/packages/typescript/src/rules/require-assert-never.ts) | Checks certain no-op defaults of already exhaustive finite switches. | It is not a general Result handler validator. It permits runtime work in defaults and intentionally abstains on incomplete switches; upstream typed switch checking owns those missing cases. |
| [`prefer-match-assert-never` SARJ032](https://github.com/sarj-ai/code-standards/blob/c21be326fb8c6ee3059e1703c255f95542bcd517/packages/python/src/sarj_python_lint/rules/prefer_match_assert_never.py) | Rejects some silent dispatch on locally annotated enums and certain ignores on import-proven `assert_never` calls. | It excludes imported domains and class-pattern unions; raising an arbitrary exception does not establish compile-time completeness. |
| [`prefer-discriminated-union`](https://github.com/sarj-ai/code-standards/blob/c21be326fb8c6ee3059e1703c255f95542bcd517/packages/typescript/src/rules/prefer-discriminated-union.ts) and [`prefer-discriminated-model-union` SARJ510](https://github.com/sarj-ai/code-standards/blob/c21be326fb8c6ee3059e1703c255f95542bcd517/packages/python/src/sarj_python_lint/rules/prefer_discriminated_model_union.py) | Advise on correlated tags and payloads where the current flat model loses their relationship. | They do not prove that all business errors should form a finite union. Neither makes every optional field invalid. |
| [`no-broad-return-type`](https://github.com/sarj-ai/code-standards/blob/c21be326fb8c6ee3059e1703c255f95542bcd517/packages/typescript/src/rules/no-broad-return-type.ts), [`no-known-value-widening`](https://github.com/sarj-ai/code-standards/blob/c21be326fb8c6ee3059e1703c255f95542bcd517/packages/typescript/src/rules/no-known-value-widening.ts), and [`typed-error-reasons` SARJ435](https://github.com/sarj-ai/code-standards/blob/c21be326fb8c6ee3059e1703c255f95542bcd517/packages/python/src/sarj_python_lint/rules/typed_error_reasons.py) | Detect selected known-value erasure and advise on exception constructors that join string reasons. | A precise outer Result can still contain an erased `E`. SARJ435 deliberately treats finite reason identities as a domain question. |
| [`no-sentinel-return-on-catch`](https://github.com/sarj-ai/code-standards/blob/c21be326fb8c6ee3059e1703c255f95542bcd517/packages/typescript/src/rules/no-sentinel-return-on-catch.ts), [`no-silent-promise-catch`](https://github.com/sarj-ai/code-standards/blob/c21be326fb8c6ee3059e1703c255f95542bcd517/packages/typescript/src/rules/no-silent-promise-catch.ts), [`no-log-only-catch`](https://github.com/sarj-ai/code-standards/blob/c21be326fb8c6ee3059e1703c255f95542bcd517/packages/typescript/src/rules/no-log-only-catch.ts), and strict Ruff | Cover selected swallowed failures and poor exception handling. | Logging can satisfy a rule while caller-visible distinctions remain lost. Conversely, a fallback can be the correct contract. These controls do not justify banning catches. |
| [`duplicate-adjacent-exception-handler` SARJ488](https://github.com/sarj-ai/code-standards/blob/c21be326fb8c6ee3059e1703c255f95542bcd517/packages/python/src/sarj_python_lint/rules/duplicate_adjacent_exception_handler.py) | Identifies equivalent neighboring exception translations. | Equivalent adjacent handlers are not evidence that all callers need one global translation or that exceptions must become Results. |
| [`no-swallowed-asyncio-cancellation`](https://github.com/sarj-ai/code-standards/blob/c21be326fb8c6ee3059e1703c255f95542bcd517/packages/python/src/sarj_python_lint/rules/no_swallowed_asyncio_cancellation.py) and [`require-explicit-psycopg-transaction`](https://github.com/sarj-ai/code-standards/blob/c21be326fb8c6ee3059e1703c255f95542bcd517/packages/python/src/sarj_python_lint/rules/require_explicit_psycopg_transaction.py) | Preserve selected cancellation paths and explicit transaction ownership. | Neither proves a return-for-raise migration preserves rollback, savepoints, cleanup or retry semantics. |

The [Python file context](https://github.com/sarj-ai/code-standards/blob/c21be326fb8c6ee3059e1703c255f95542bcd517/packages/python/src/sarj_python_lint/_file_context.py)
shares AST, parent and import facts. Its
[project index](https://github.com/sarj-ai/code-standards/blob/c21be326fb8c6ee3059e1703c255f95542bcd517/packages/python/src/sarj_python_lint/rules/_project_index.py)
supports bounded source resolution, not a general checker type API. TypeScript
rules already use `ESLintUtils.getParserServices` and the compiler checker;
reuse that program instead of starting one compiler per file or rule.

The [external runner](https://github.com/sarj-ai/code-standards/blob/c21be326fb8c6ee3059e1703c255f95542bcd517/packages/standards/src/sarj_standards/libs/linting/external.py)
runs BasedPyright per project, parses JSON diagnostics and filters them to
selected files. Therefore checking only a changed error definition can omit
errors in unchanged handlers. The TypeScript route invokes typed ESLint for
selected files; it is not a replacement for the repository's complete `tsc`
gate. Whole-project checker evidence is required for contract changes, alongside
the relevant typed ESLint coverage. Fix this at invocation scope if the pilot
shows missing CI coverage; do not build another exhaustiveness engine.

## What the consumer examples establish

| Evidence group | Observed behavior | Useful conclusion |
| --- | --- | --- |
| E1 | A Python service returns several named success and failure variants; HTTP handlers and another service match them and use `assert_never`. | The semantic Result pattern already works. Preserve these unions and make growth visible; wrapping them in another Result adds no value. |
| E2 | Another helper returns a success object while normal permission and direction rejections escape as domain exceptions. Their transport handlers are separately registered. | The signature omits expected outcomes. This is a candidate for a reviewed internal contract change with the current public exception adapter retained. |
| E3 | A failure model carries optional operation context and an arbitrary reason. Producers include validation rejection, booking collision and a concurrent race described as retryable. | Some reasons may justify distinct variants if the caller needs different action. The contextual string and nullable record alone do not prove a defect. |
| E4 | A server-action wrapper reduces structured HTTP failures, response-validation failures and other thrown values to one message-only failure. Its current UI callers mostly display the message. | A closed error union would enable deliberate field repair, conflict and retry handling. It should be introduced only where those decisions are owned; display-only boundaries can legitimately stay coarse. |
| E5 | A credential service catches specific provider failures and translates them; broad catches used for cleanup rethrow. Its HTTP adapter has a finite exception-to-status table and rethrows unknown domain exceptions. | Preserve cleanup and unknown-failure propagation. A typed translation function would expose a newly added expected variant that a runtime dictionary cannot enumerate statically. |
| E6 | A page loads several sources independently, retains each failure status and renders it, while a separate projection returns nullable data. A shared streaming wrapper reports failure and exposes only ready/error. | Preserve independent outcomes and presentation-level redaction. A nullable projection or coarse display error is not necessarily information loss. |
| E7 | A store isolates a conflicting row in a savepoint before continuing. Another operation returns primary success after a failed ancillary settlement is logged and deferred to existing recovery. | Changing unwinding can change commits. Primary success plus independently recoverable follow-up is a legitimate outcome; do not relabel it as total failure. |

No ignored Result or unsafe unwrap was identified in these selected call paths.
Rank 2 is supported by existing consequential contracts plus a reproducible
checker gap, not a claim of an observed production incident. The review did
not establish that every message string should become an enum or that the
observed transport differences are bugs.

## Representations and scope

For TypeScript, reuse the consumer's discriminated outcome unions or installed
Result library. An illustrative contract is:

```typescript
type Result<T, E> =
  | { readonly ok: true; readonly value: T }
  | { readonly ok: false; readonly error: E };

type SaveError =
  | { readonly kind: "duplicate"; readonly existingId: string }
  | { readonly kind: "invalid_transition" }
  | { readonly kind: "rate_limited"; readonly retryAfterSeconds: number };
```

Only carry `existingId` or a delay if a real caller needs it and the boundary
permits disclosure. Do not add blanket `message`, `cause`, `requestId`,
`retryable`, or optional payload fields to every error. A payload may itself be
nullable when null has a domain meaning. A string literal union is precise;
an arbitrary string used as error identity is not.

[`neverthrow`](https://github.com/supermacro/neverthrow) supplies Result and
ResultAsync. Its associated
[`must-use-result` implementation](https://github.com/mdbetancourt/eslint-plugin-neverthrow/blob/b7df2e53c39ef49b22ebaa011a4e8e8b86209c74/src/rules/must-use-result.ts)
recognizes a method-shaped surface, accepts `_unsafeUnwrap` as consumption and
can accept any handled reference rather than proving every path. It is a
reuse candidate for consumers already using that library, subject to modern
ESLint compatibility tests. It is not an enforcement guarantee for arbitrary
local unions or safe extraction. No such dependency was found in the inspected
consumer scopes and lockfiles; do not introduce it just to enable a rule.

For Python, preserve the existing nominal outcome unions. Where generic
composition is actually needed, an ordinary generic union can express the
same contract without checker plugins:

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class Success[T]:
    value: T


@dataclass(frozen=True)
class Failure[E]:
    error: E


type Result[T, E] = Success[T] | Failure[E]
```

This is an idiom illustration, not a proposed second Result package.
[`result`](https://github.com/rustedpy/result) uses an `Ok[T] | Err[E]` alias,
but its upstream is archived and explicitly unmaintained; it is not the default
new dependency recommendation.
[`returns`](https://returns.readthedocs.io/en/latest/pages/result.html) provides
Success/Failure and composition, but documents mypy-plugin requirements for
decorator typing. Validate its exact used APIs with BasedPyright before reuse;
do not infer full compatibility from a pattern-matching example. Avoid a broad
`@safe` conversion to `Result[T, Exception]`.

For native ecosystems, keep their conventions. Rust already provides
[`Result<T,E>`, `?` and `unused_must_use`](https://doc.rust-lang.org/std/result/).
Use a domain enum and ordinary compiler exhaustiveness at terminal boundaries;
`?` can propagate or translate an error without locally enumerating it. Wildcard
handling and `let _ = ...` remain deliberate escape points, not proof of useful
handling. Kotlin's native
[`Result<T>`](https://kotlinlang.org/api/core/kotlin-stdlib/kotlin/-result/)
has a Throwable failure, not an independently parameterized domain `E`; where a
closed domain is needed, use the project's existing sealed outcome or typed
Either convention. Do not claim native Result alone supplies that guarantee or
add a language engine solely for symmetry with this proposal.

Expected outcomes are defined by the operation and its callers: duplicate,
not found, forbidden and invalid transition often qualify. Failed invariants,
miswired internal operations, unexpected decoder defects and unclassified
infrastructure outages do not automatically qualify. A provider timeout can
be a domain outcome when the contract owns bounded retry; an arbitrary network
failure need not be. Python cancellation, process exit, framework redirect and
other native control flow retain their existing semantics. No infallible
function needs a Result, and ordinary lookup absence remains `T | None` or
`T | null` when no caller needs a failure reason.

## Rank 1 Exhaustive terminal handlers

**Motivation and benefit.** E1 already uses exhaustive service and transport
handlers. E5 has a runtime translation table whose keys are not checked against
a closed error set. Adding a recoverable variant should identify the handlers
whose retry, repair or HTTP decision is incomplete.

**Detection and owner.** Require complete-project type checking for designated
contract changes. Keep BasedPyright `reportMatchNotExhaustive` at error. Keep
typed ESLint `switch-exhaustiveness-check` at error and test that
`considerDefaultExhaustiveForUnions` remains false. TypeScript `never` and
Python `typing.assert_never` check the residual after control-flow narrowing;
the compiler resolves aliases, imports, generics and reachable branches.
Unchecked success-member access stays owned by the native checker.

For a small Python pilot, consider extending SARJ032 only when a dispatch is
explicitly designated as a terminal handler of a registered outcome contract.
Resolve the accepted nominal union and exact imported variants through the
project index; inspect a `match` on that parameter or a directly bound failure
payload. A wildcard that returns a constant, does nothing or merely raises a
generic exception is a review finding unless it delegates the residual to an
approved typed translator or an import-proven `assert_never`. The advisory
identifies missing static proof; it does not calculate type exhaustiveness.
Skip aliases, nested patterns, guards, mutation and decorators the resolver
cannot prove. Keep arbitrary application matches and partial projections out
of scope. Do not expand SARJ032 to class-pattern unions by guessing class names.

**Positive and correction.** A handler that retains `default: return "failed"`
after adding a variant is incomplete for a designated closed boundary. Enumerate
the current relevant cases and leave a typed residual assertion:

```typescript
function renderError(error: SaveError): string {
  switch (error.kind) {
    case "duplicate": return `Use ${error.existingId}`;
    case "invalid_transition": return "Choose an allowed transition";
    case "rate_limited": return `Retry in ${error.retryAfterSeconds}s`;
    default: return assertNever(error);
  }
}
```

Here `assertNever` is the project's existing helper with a `never` parameter;
the miniature reproduction supplies that signature. Python can match the
failure payload as its own nominal union and finish with
`case _ as residual: assert_never(residual)`. Checking only Success/Failure
does not enumerate the nested `E`.

**Legitimate negatives.** `return result`, a typed `mapErr`/translation, or an
explicit union of several cases sharing one action is valid. A display adapter
that intentionally accepts all present and future errors can remain coarse
outside designated terminal handlers. A raw provider string has no closed set
to enumerate. Tests, generated clients and optional lookup projections do not
become terminal handlers merely because they use a match.

**Proof and limits.** The checker proves type coverage, not that each response
is sensible. A wildcard satisfies Python match coverage; a generic failure
callback covers `E` without selecting every variant; an if/else with a total
fallback can type-check. The opt-in boundary designation is domain judgment.
Mutation and escaping aliases can invalidate simple narrowing assumptions.
Unknown and Any must first be eliminated by existing checks or parsing.

**Severity, scope, cost and fix.** Retain existing native errors. Start the
narrow Python expansion as a warning on a few internal boundaries; its main
false-positive risk is an intentionally coarse handler designated incorrectly.
Native checks reuse current programs; bounded source resolution adds medium
engineering cost. Add explicit branches or delegate to an existing complete
translator. No automatic insertion of `assert_never`, dummy branches or
throwing defaults: each can conceal a required business decision or change
runtime behavior. No casts or ignores to satisfy the residual check.

## Rank 2 Consume a Result before assuming success

**Motivation and benefit.** E1 contains mutation APIs that can return a
not-pending or disabled outcome. A discarded call followed by a success
response loses the rejection even though the transport await completed. The
small reproduction replaces the existing caller's match with a discard; no
ignored Result is asserted to exist in the original source.

**Precise first detector.** On an expression statement, resolve the resulting
value after any explicit `await`. Report when it is a registered Result type,
including registered direct outcome unions. Also report a `void` expression
discarding that type, or assignment to an intentionally unused binding when
the binding's references prove there is no subsequent read or escape. For
TypeScript use resolved declaration identity, instantiated type arguments and
the compiler's awaited type. A foreign object merely named Result or exposing
methods named `match` and `unwrap` is not registered by shape alone. Follow
stable import aliases and reexports. A union that includes a Result has a
discardable failure path; never erase it during recognition.

For Python, support only direct module functions, imported aliases and final
methods whose source return annotation resolves unambiguously to a registered
union. Distinguish async function annotations from coroutine values and await
exactly as required. Reject unsupported resolution as analysis-incomplete or
advisory evidence; never silently claim all Python Results were checked.
Unknown decorators, dynamic dispatch, monkeypatching, overload ambiguity and
unresolved generic substitutions are deliberate blind spots. Reuse the
project index and SARJ483's symbol-resolution precedent, not method spelling.

```typescript
await cancelJob(id); // Promise handled; Result discarded: report
const result = await cancelJob(id);
return translateCancellation(result); // typed consumption: accept
```

A local assignment is not automatically complete handling. A later prototype
may track a stable local binding through a bounded control-flow graph and
report a path to exit or overwrite without consumption. Enumerate supported
statement forms, track aliases and merges, and abstain at escapes. Reading
`.ok`, logging the object or calling `mapErr` with its returned Result ignored
does not establish handling. Passing it to an arbitrary function transfers
analysis ownership, not proof of recovery; inspect only registered consumers
within a closed analyzed scope. Do not advertise linear or whole-program
must-use enforcement.

**Unsafe extraction.** Native checkers already reject `.value` on a union
without success narrowing. For an installed library that exposes throwing
unwrap methods, a future companion check can resolve the exact method and
receiver's narrowed type at that point. Warn if a possible failure remains;
accept a locally proven success or a reviewed invariant/termination adapter.
Calls to unrelated methods named unwrap are negatives. A prior `isOk()` call
whose result is discarded is not a guard, and a mutable alias or intervening
write invalidates a purely syntactic dominance argument. With no such unwrap
in the inspected paths, defer this companion implementation.

**Legitimate negatives.** Return/propagation, complete translation, assignment
later used by a handler, generic combinators that preserve `E`, a deliberate
absence value, and an ordinary fluent builder are accepted. `pytest.raises`
and framework termination tests require semantic fixtures rather than blanket
test exclusions. Independent results collected for later rendering are valid.

**Proof and limits.** The initial check proves a recognized returned failure
channel is discarded; it does not prove the operation failed at runtime. It
does not prove that a consumed Result was handled correctly on every path.
Escapes into fields, collections and callbacks remain outside the initial
closed scope. This includes a Result implicitly returned by a callback whose
consumer discards its return value, such as a `forEach` callback; use that as
an explicit false-negative fixture before extending contextual-return analysis.
Never enable global `reportUnusedCallResult` just to approximate a
Result-specific rule.

**Severity, scope, cost and fix.** Warning first, then error only for calibrated
exact-symbol discards. Scope starts with a few consequential mutation APIs,
not every Result-looking object. Main false-positive risks are deliberate
best-effort operations, test assertions and incorrectly registered fluent APIs.
TypeScript checker reuse is medium cost; general Python return-type inference
would be high cost and is not proposed. The smallest correction is return the
Result when the enclosing signature permits it, or bind it and handle the
needed failures. No automatic assignment, deletion, unwrap, broad catch or
success fallback; those edits cannot choose the caller's policy safely.

## Rank 3 Preserve precise domain errors

**Motivation and benefit.** E3 has race, collision and validation reasons in one
string-bearing failure. E4 flattens HTTP/domain rejections and unexpected thrown
values to a message; E5 already makes different HTTP decisions for named domain
exceptions. Preserve these distinctions where an actual caller chooses retry,
repair, conflict resolution or authorization behavior. If all callers only
render one message, splitting a string does not yet earn a mandatory rule.

**Detection.** Extend existing modeling advisories before adding a separate
engine. At explicitly designated closed-domain producer signatures or
translator outputs, resolve the registered Result and instantiated `E`.
Report a declared `E` of Any/unknown/object, Exception/BaseException/Error,
an unconstrained error-identity string or an unknown-valued dictionary. Resolve
type aliases and substitutions; retain a parameterized `E` for a generic
combinator that forwards it without erasure. A `never` failure channel is not
weak; whether its wrapper is useful is a separate design question.

For discriminated object variants, require a finite required literal/enum
discriminant and unambiguous members where this closed contract is designated.
Diagnose an open `kind: string` or an optional discriminant; retain ordinary
typed context strings. Reuse the existing advisory when producers/validators
demonstrate tag-specific required payloads but the declaration has optional
fields. Do not reject every optional field or insist every error be a record:
a finite literal union or a single nominal domain error can be sufficient.

```typescript
// Positive only at a designated domain boundary: distinctions erased.
function erase(error: SaveError): Result<number, unknown> {
  return { ok: false, error };
}

// Smallest representation correction when this is the intended contract.
function preserve(error: SaveError): Result<number, SaveError> {
  return { ok: false, error };
}
```

**Legitimate negatives.** `unknown` at unparsed input and in catch variables,
arbitrary user text as context, a typed provider diagnostic kept privately,
`Result<T,E>` generic propagation, a precise validation library error with
typed issues, intentionally opaque telemetry storage, and an output-only UI
failure with no decision beyond rendering. Independent partial success may
need multiple outcomes; it is not an optional-field violation by default.

**Proof and domain judgment.** Types reveal erased distinctions and impossible
tag/payload combinations only within supported cases. They do not prove which
variants the business needs, that every present variant is actionable, or that
a particular field is unnecessary. Before a closed contract is designated,
list its real producer cases, caller actions and minimum per-case data. Do not
derive an enum from today's message literals, HTTP statuses or caught class
names without that review. Provider details may need deliberate redaction.

**Severity, scope, cost and fix.** Retain upstream Any diagnostics and give them
precedence over a duplicate contract finding. Start modeling/widening additions
at warning; make only violation of an explicitly established closed contract
eligible for later error. Scope one operation family and its boundary adapters.
Type graph normalization is medium cost in TypeScript; Python must initially
limit itself to resolvable source annotations rather than claim access to
BasedPyright internals. Risks include intentional opaque boundaries, generics
and a coarse but sufficient single error. Preserve a known `E` or introduce the
smallest domain-reviewed split and update handlers. No automatic optional-field
removal, annotation narrowing or string-to-enum migration: external callers,
serialization and control flow can depend on the old representation.

## Rank 4 Review hidden failures and translation loss

**Motivation and benefit.** E2's expected rejection is absent from its return
type. E4 loses distinctions across a broad catch. E5 translates a finite group
of provider exceptions to one domain exception while retaining its cause.
The right result may be a clearer return contract, a shared adapter, or keeping
the current boundary. The audit should expose those choices concretely.

**Bounded discovery conditions.** In configured source roots and operation
families, resolve direct call edges and exception class identities. Group two
or more call sites that catch the same resolved exception from a try region
containing a single known operation; report the number and the actual handler
outcomes. Ambiguous multi-operation try blocks are lower-confidence leads.
Also identify directly reachable domain raises, error/success sentinel overlap,
and flat status/payload declarations already covered by existing advisories.
An exception suffix or function name alone cannot emit a contract violation.

For the sentinel lead, compare return expressions in the same function scope:
`None`/null, false, an empty literal or a resolved stable constant returned by
both a caught-failure path and an ordinary path. Resolve shadowed names, omit
nested functions, and record the guarding condition and caught exception.
Unknown calls, dynamic constants and multi-operation try regions do not prove
overlap. Even literal overlap is advisory: absence and idempotency may be the
intended public outcome.

For information loss, compare simple handler control flow: a catch/known
failure arm returns success, normal absence, a constant message or a generic
error while ignoring typed context that another reviewed caller consumes.
Distinguish rethrow, cause chaining, cleanup followed by rethrow, an approved
fallback, recovery and logging. Logging is observable but does not restore the
caller's missing distinction. A Result failure changed to apparent success is
a review candidate even when the exception is logged.

For boundaries, compare equivalent operations' translations of resolved
failure variants to transport responses and domain outputs. Include framework
exception handlers and generated transports when establishing ownership.
Different audiences, authorization scopes or APIs may intentionally produce
different mappings. A domain call that invokes a provider without translation
is only a possible leak unless the provider's declared exception contract or
a reviewed reproduction proves what can escape. Python and TypeScript do not
offer a complete checked-exception graph; do not invent one from an AST walk.

```python
try:
    return Success(await provider.create(request))
except ProviderDuplicate as error:
    return Failure(Duplicate(error.existing_id))
except ProviderRateLimited as error:
    return Failure(RateLimited(error.retry_after_seconds))
```

The snippet is valid only at the reviewed provider adapter. It intentionally
does not convert every Exception into a domain Failure. A broad catch returning
`Success(None)` is a positive review example; explicit idempotent deletion of
an already absent record is a negative when absence is defined as success.

**Counterexamples.** Lookup absence, parse predicates, a health snapshot whose
individual failed sources remain visible, caller-independent suboperations,
retry loops that preserve their exception policy, cleanup and rethrow,
redaction before a public response, and post-commit recovery that reports the
primary operation honestly. E6 and E7 are required negative fixtures.
Several callers catching an exception is a discovery signal, not a mandate.

**Proof, severity, cost and fix.** The audit can show a resolved catch, repeated
translation or lost syntactic use. Expectedness, equivalent policies, necessary
information and correctness of a fallback require domain judgment. Keep it
advisory, outside blocking lint. Bound call graph traversal to selected roots
and known operations; full effect inference would be high cost and unreliable.
False positives are highest here. The smallest correction may be retain a
typed reason, delegate to an existing translator, or keep the catch and document
its recovery contract. Representation changes require reviewed codemods and
behavioral evidence. No automatic exception-to-Result conversion.

## Migration safety

Freeze the public contract and failure behavior before editing a producer.
Enumerate all callers in the analyzed scope, framework handlers and provider
adapters. Introduce the internal typed contract, retain the current external
exception/HTTP adapter, and change callers together. An unconverted external
caller must observe the same status, body, headers and disclosure policy.
An intended change to those behaviors belongs in a separate behavior change.

Exception unwinding can be part of the transaction protocol. Psycopg
[transaction contexts](https://www.psycopg.org/psycopg3/docs/basic/transactions.html#transaction-contexts)
commit on normal exit and roll back on exceptional exit. Returning a Failure
from inside one can commit earlier writes. Preserve the old exception until
the owning transaction/savepoint has unwound, then translate outside it:

```python
async def save_result(request: SaveRequest) -> Result[Saved, SaveError]:
    try:
        return Success(await save_legacy(request))
    except DuplicateName as error:
        return Failure(Duplicate(error.existing_id))
```

This adapter is safe with respect to rollback only if `save_legacy` owns and
exits the relevant transaction before the exception is translated. If its
caller owns an outer transaction, keep unwinding through that owner or use
the explicitly reviewed rollback protocol there. Moving the catch just outside
an inner helper does not prove safety. Preserve E7's per-row savepoint and its
independent commit semantics. A returned error is not a database rollback.

`finally` still runs on return, but context-manager exit arguments and the
path after cleanup change. Trace cleanup ordering, resource release, exception
suppression and caller side effects. Preserve retry exception filters,
attempt counts, deadlines, idempotency keys and backoff; a retry decorator may
stop retrying when an exception becomes an ordinary returned value. Preserve
required logging/reporting without leaking provider payloads into domain or
public errors. Keep error construction free of unrelated effects.

Python [`CancelledError`](https://docs.python.org/3/library/asyncio-exceptions.html#asyncio.CancelledError)
is a BaseException and generally must be re-raised after cleanup. Never absorb
it through a bare catch, `BaseException` conversion, a broad library decorator,
or a Result combinator. Preserve SystemExit/KeyboardInterrupt and framework
termination. In TypeScript, classify cancellation before mapping thrown values;
do not assume an exception named AbortError is always an expected business
rejection. Scoped timeout-to-domain conversion requires a deliberate contract.

No proposed lint autofix changes signatures, inserts unwraps, drops calls,
adds generic catches, manufactures defaults, casts or suppressions. A reviewed
codemod must analyze a closed caller set and demonstrate equivalent transaction,
cleanup, retry, logging and side-effect traces. Run it twice: the second pass
must make no changes. If semantic safety cannot be established, the operation
remains a manual migration.

## Detection tests and qualification

Use the existing executable RuleDocumentation/RuleExample contracts and the
owning Python or typed ESLint test harness. Keep diagnostics deterministic,
give existing native errors precedence, and do not count a parser-service
failure as a clean lint result. A required typed invocation must expose missing
project coverage as incomplete analysis; syntax-only standalone use may abstain
without claiming semantic verification.

| Area | Meaningful positive tests | Required negative and interaction tests |
| --- | --- | --- |
| Exhaustiveness | Add one error variant across two files; unchanged terminal handler fails. Python match without a catch-all fails; residual `assert_never` fails for the added member. TypeScript switch fails even with a generic default. | Complete updated handler passes; shared explicit cases pass; generic propagation passes. Guarded cases do not falsely count as full coverage. Test nested failure payloads, imported aliases, shadowed assertion helpers, and that changed-file-only invocation cannot claim full caller coverage. |
| Discards | Direct sync call, awaited Result, `void`, unused underscore binding, overwritten local, ignored `mapErr` output, and one branch exiting without consumption in the later CFG prototype. | Ordinary builders, `None`/void returns, optional lookup, same-name unrelated Result/unwrap, complete translator, returned Result and preserved generic `E`. Test imported/reexported symbols, overloads, asynchronous callbacks and escaped collections; unsupported forms must abstain or report incomplete scope. |
| Unsafe extraction | A supported real library's unwrap on an unresolved Result; checking status without branching; alias mutation between guard and extraction. | Type-proven success, checked immutable local, unrelated unwrap method, and an explicit reviewed defect/termination boundary. Do not test with a fake method surface as a substitute for the actual package declarations. |
| Error precision | Alias hides unknown/Any `E`; known finite error widened to Error/string; optional/open discriminant; invalid tag/payload state accepted by the old model. | Unparsed unknown input, message as context, a precise validation library error, finite literal E, generic forwarding, single nominal error, meaningful nullable payload and independent outcomes. Test SARJ510 and TypeScript modeling precedence rather than duplicate reports. |
| Advisory boundaries | Same resolved operation caught by several callers; finite provider failures reduced to a constant; known failure returned as apparent success; mapper omits a newly added domain variant. | Distinct audiences, access-before-disclosure, cleanup/rethrow, logged fallback with retained status, primary success plus deferred follow-up, precise provider translation and ordinary absence. Do not mark all these leads as confirmed defects. |

For each representation migration, retain before/after type-checker diagnostics
and public behavior snapshots. Test database state after rejection and after
success, a competing writer/savepoint conflict, cancellation at every await
that can follow a write, cleanup exactly once, retry count/backoff and recovery
after an ancillary failure. Compare ordered effects, not only final return
values. These integration tests are required for a migration touching those
behaviors; a documentation proposal does not need to execute an application
database matrix.

For an autofix-free rule, the fix-idempotence assertion is that fix mode emits
no edit on both passes. For an explicit codemod, require first-pass semantic
equivalence and a byte-identical second pass. A narrower compiler annotation
that introduces new errors is evidence for review, not a reason to insert a
cast. Reject transformations that change exception causes, order or rollback.

The companion compiler probes use the installed TypeScript 6.0.2 API,
typescript-eslint 8.71.2 / ESLint 10.12.0 and BasedPyright 1.40.2. They compare
old, extended and corrected error unions; unchecked access; synchronous,
awaited and explicit discards; erased error types; generic forwarding; and
ordinary absence. Their result table belongs with the reproducible evidence.
They establish checker behavior, not precision, runtime performance or the
correctness of a proposed custom detector.

The required before/after observations are:

| Reproduction | Before | After extending the error union | After updating the handler |
| --- | --- | --- | --- |
| TypeScript switch with a residual `never` assertion | No relevant error | Argument-type error at the residual and typed switch diagnostic | No relevant error |
| Python match with a residual `assert_never` | No relevant error | Argument-type error naming the unhandled variant | No relevant error |
| Python partial match without wildcard | Complete match accepted | `reportMatchNotExhaustive` | Complete match accepted |
| Broad generic fallback | Accepted by the compiler | Still accepted by the compiler; TypeScript's finite switch rule can reject it | Explicit cases restore a useful completeness guarantee |
| Discarded awaited Result | Accepted by Promise/coroutine checks | Still accepted; no failure contract has been consumed | A typed handler or propagation preserves the outcome |

These are qualification expectations for the supplied probe fixtures until
their actual diagnostics are recorded. A passing custom rule must reject the
seeded bad cases as well as accept the corrected ones; the checker alone does
not establish the discard policy.

The 26-case compiler probe and `make verify` were queued under the required
shared supervisor but did not receive admission. Both were stopped while
still waiting; neither executed or passed. Their fixtures and interrupted
verification record are preserved in the private evidence artifacts. The
proposal's builtin source analysis and Markdown placement checks passed.

A separate stdlib context-manager model passed four observations: an exception
unwinds through rollback and cleanup; returning a failure inside the scope
instead commits; translation outside the owning scope preserves rollback;
and cancellation bypasses an `except Exception` adapter. This verifies the
language protocol hazard, not PostgreSQL integration or an application migration.

Before a rule can ship, run labeled positive/negative/near-miss examples,
focused rule tests, owning lint and type checks, combined dogfood, and
`make verify`. Evaluate pinned diverse corpora using the existing isolated
runner and private overlay. Review every pilot finding, or state the unbiased
sample and seed; report TP/FP/FN, duplicate diagnostics and abstentions. Measure
cold/warm combined-run overhead against a baseline and preserve the runner's
bounded batches. No fleet counts or detector performance are inferred from the
targeted review or the compiler probes.

## Gradual rollout

1. Retain current native rules and document the terminal contracts selected
   from E1/E5. Prove that changing their error union exposes unchanged handlers
   through whole-project checker and typed-lint jobs. Close an invocation gap
   at its existing owner before implementing another analyzer.
2. Pilot exact-symbol Result discard warnings on the selected consequential
   APIs. Publish the supported resolution forms and incomplete-analysis count.
   Fix real ignored outcomes explicitly; exclude only reviewed legitimate
   contracts, never every test or every builder by name.
3. Review E2/E3/E4 per operation family. Agree on expected variants, useful
   caller actions, minimum data and boundary translation. Prefer reuse of
   existing domain unions. Introduce an internal contract behind current public
   adapters, keeping behavior changes separate.
4. Publish one warning release and examine downstream findings before any
   severity promotion. Keep heuristic discovery advisory permanently. Promote
   only exact contract violations with no known false positives, stable
   diagnostics, adequate checker evidence and measured acceptable overhead;
   follow the existing separate metadata promotion workflow.
5. Release and use the established rollout controller for consumer changes
   only when implementation and publication are separately authorized. Adoption
   is per contract family, not a fleet-wide requirement that every function
   return a Result.

The completion criterion is that a relevant new expected outcome reaches a
typed contract and makes incomplete decision-making visible. A count of
Result wrappers, annotations or error enum members is not a success metric.
