/** @fileoverview prefer-coded-error-result — documentation and executable contract examples. */

import type { RuleDocumentation } from "../documentation.js";

export const PREFER_CODED_ERROR_RESULT_DOCUMENTATION = {
  summary:
    "Return a stable error code and typed context instead of only a rendered failure message.",
  defaultLevel: "warning",
  rationale:
    "A message-only or opaque failure hides the identity needed for repair, conflict handling, localization and exhaustive dispatch. Preserve a finite error code and the minimum handling context; let the consumer format its message. Reuse the native no-explicit-any rule, compiler narrowing and type-aware exhaustiveness checks.",
  remediation:
    "Use the existing Result or outcome union with a finite error code and variant-specific context. Preserve public behavior through a presentation adapter, and handle or propagate each relevant variant without parsing message text.",
  category: "correctness",
  autofix: "none",
  limitations: [
    "Accepting an inferred producer does not prove a finite inferred contract: object payloads or errAsync can widen a code to string. Annotate the existing Result/ResultAsync return when necessary. Native assignability, narrowing and exhaustive-handler checks remain authoritative.",
    "Checks source-resolved local unions with required literal ok/success booleans, or status/state/kind/type/tag values ok/success versus err/error/failure/failed (case insensitive). Conflicting outcome tags abstain. A shared outcome tag does not also count as a domain error code. Named and namespace neverthrow Result/ResultAsync imports establish their generic error position.",
    "Presence-selected unions require an error property on every failure branch and the same single required non-control value property on every success branch. Optional error/value fields, multiple value keys, loading states and error branches carrying the success value abstain. Required errorMessage and Error-suffixed failure channels are also reviewed; multiple custom channels abstain and a primary error payload retains precedence.",
    "Broad string and unknown error channels, unshadowed native Error-family types and open string/unknown code fields receive review. Explicit Any stays with the existing no-explicit-any rule. Finite literal codes need no invented payload. Imported domain errors, validation-library errors, generic error parameters, ordinary formatters, legitimate absence and redacted failure states remain valid.",
    "Local aliases, unmerged interfaces without inheritance and generic substitutions are bounded to 16 resolution levels, 64 union members and 256 traversal steps. Transparent aliases retain the proven neverthrow Result/ResultAsync error position, including renamed/namespace imports, generic defaults and unshadowed native Promise/PromiseLike wrappers. Imported local declarations, conditional/intersection/mapped types and unresolved contracts abstain. Optional discriminants, independent success/error payloads and partial-data failures are excluded.",
    "Required code/kind/type/tag fields of unresolved or imported type defer to the type checker; a finite code does not prove that its cases or payloads are useful. Generic error parameters are retained rather than guessed. Ordinary string formatters, absence, validation-library errors and redacted failure states without a string payload are not flagged.",
    "A directly returned failure object, neverthrow err/errAsync call or new Err with an interpolated template or proven string concatenation receives review. Without a code, the diagnostic asks for a domain contract; with a literal code, it asks for consumer formatting. Literal-only compositions, including earlier stable local constants, remain valid codes. Nested plain error objects, expression-bodied arrows and one direct await are supported. Import identity and value-space shadowing are checked; arbitrary aliases, spreads, accessors, computed keys, helper formatting calls and nonliteral codes abstain. This proves formatting ownership, not which context the domain must expose; presentation adapters remain a reviewed exception.",
    "This warning requests domain review: an infrastructure adapter may intentionally retain unknown/Error, and a final presentation boundary may accept every failure and render one message. Neither proves a recoverable domain rejection. No fix invents error codes, fields, handlers or changes serialization, exception unwinding, transactions, retries or logging.",
  ],
  references: [
    "https://www.typescriptlang.org/docs/handbook/2/narrowing.html#discriminated-unions",
    "https://github.com/supermacro/neverthrow",
  ],
  examples: [
    {
      id: "aliased-library-message",
      scenarioId: "aliased-library-error",
      title: "A transparent alias must preserve the library error contract",
      outcome: "match",
      files: [
        {
          path: "app/result.ts",
          source:
            "import type { Result as NativeResult } from 'neverthrow'; type Saved<T, E> = Promise<NativeResult<T, E>>; export type Output = Saved<number, string>;",
        },
      ],
      focusPath: "app/result.ts",
      expectedCount: 1,
      public: true,
    },
    {
      id: "aliased-library-domain-error",
      scenarioId: "aliased-library-error",
      title: "Keep a finite error code and only the context its consumer needs",
      outcome: "no-match",
      files: [
        {
          path: "app/result.ts",
          source:
            "import type { Result as NativeResult } from 'neverthrow'; type Saved<T, E> = Promise<NativeResult<T, E>>; export type Output = Saved<number, { code: 'duplicate'; name: string } | { code: 'denied' }>;",
        },
      ],
      focusPath: "app/result.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "presence-selected-message",
      scenarioId: "presence-selected-result",
      title: "An error-presence check still needs a useful error contract",
      outcome: "match",
      files: [
        {
          path: "app/result.ts",
          source:
            "export type Outcome<T> = { value: T } | { error: string; field?: 'name' };",
        },
      ],
      focusPath: "app/result.ts",
      expectedCount: 1,
      public: true,
    },
    {
      id: "presence-selected-domain-error",
      scenarioId: "presence-selected-result",
      title: "Retain the existing presence check with a finite error union",
      outcome: "no-match",
      files: [
        {
          path: "app/result.ts",
          source:
            "type SaveError = { code: 'duplicate'; name: string } | { code: 'denied' }; export type Outcome<T> = { value: T } | { error: SaveError };",
        },
      ],
      focusPath: "app/result.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "string-outcome-tag",
      scenarioId: "string-outcome",
      title:
        "An outcome tag distinguishes success from failure, not the failure's cause",
      outcome: "match",
      files: [
        {
          path: "app/result.ts",
          source:
            "export type Outcome<T> = { kind: 'ok'; value: T } | { kind: 'error'; message: string };",
        },
      ],
      focusPath: "app/result.ts",
      expectedCount: 1,
      public: true,
    },
    {
      id: "string-outcome-domain-code",
      scenarioId: "string-outcome",
      title: "Preserve the established string tag and add the actionable error",
      outcome: "no-match",
      files: [
        {
          path: "app/result.ts",
          source:
            "export type Outcome<T> = { kind: 'ok'; value: T } | { kind: 'error'; error: { code: 'duplicate'; name: string } };",
        },
      ],
      focusPath: "app/result.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "opaque-error-channel",
      scenarioId: "opaque-error",
      title:
        "Unknown preserves the need to narrow but hides the domain's cases",
      outcome: "match",
      files: [
        {
          path: "app/result.ts",
          source:
            "type Result<T, E> = { ok: true; value: T } | { ok: false; error: E }; export type Saved = Result<number, unknown>;",
        },
      ],
      focusPath: "app/result.ts",
      expectedCount: 1,
      public: true,
    },
    {
      id: "specific-error-channel",
      scenarioId: "opaque-error",
      title: "Expose the domain's rejection case without inventing context",
      outcome: "no-match",
      files: [
        {
          path: "app/result.ts",
          source:
            "type Result<T, E> = { ok: true; value: T } | { ok: false; error: E }; export type Saved = Result<number, { code: 'unavailable' }>;",
        },
      ],
      focusPath: "app/result.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "named-error-carrier",
      scenarioId: "named-error-channel",
      title: "A failure-only Error-suffixed field can still erase its cases",
      outcome: "match",
      files: [
        {
          path: "app/result.ts",
          source:
            "export type Outcome<T> = { ok: true; value: T } | { ok: false; fallbackError: string };",
        },
      ],
      focusPath: "app/result.ts",
      expectedCount: 1,
      public: true,
    },
    {
      id: "typed-named-error-carrier",
      scenarioId: "named-error-channel",
      title: "Preserve the existing field name with the required context",
      outcome: "no-match",
      files: [
        {
          path: "app/result.ts",
          source:
            "export type Outcome<T> = { ok: true; value: T } | { ok: false; fallbackError: { code: 'unsupported'; requestedKind: string } };",
        },
      ],
      focusPath: "app/result.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "library-error-constructor",
      scenarioId: "library-error-presentation",
      title:
        "A proven Result constructor does not make formatted text actionable",
      outcome: "match",
      files: [
        {
          path: "app/result.ts",
          source:
            "import { err } from 'neverthrow'; export function reject(name: string) { return err(`Missing ${name}`); }",
        },
      ],
      focusPath: "app/result.ts",
      expectedCount: 1,
      public: true,
    },
    {
      id: "library-domain-constructor",
      scenarioId: "library-error-presentation",
      title: "Reuse the established Result library with a typed domain error",
      outcome: "no-match",
      files: [
        {
          path: "app/result.ts",
          source:
            "import { err, type Result } from 'neverthrow'; type Missing = { code: 'missing'; name: string }; export function reject(name: string): Result<never, Missing> { return err({ code: 'missing', name }); }",
        },
      ],
      focusPath: "app/result.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "message-only-result",
      title: "A failure erases identity into a message",
      outcome: "match",
      files: [
        {
          path: "app/result.ts",
          source:
            "export type Result<T> = { ok: true; data: T } | { ok: false; message: string };",
        },
      ],
      focusPath: "app/result.ts",
      expectedCount: 1,
      public: true,
    },
    {
      id: "code-and-context",
      title: "The consumer can choose behavior and format context",
      outcome: "no-match",
      files: [
        {
          path: "app/result.ts",
          source:
            "type Error = { code: 'duplicate'; name: string } | { code: 'invalid_transition' }; export type Result<T> = { ok: true; data: T } | { ok: false; error: Error };",
        },
      ],
      focusPath: "app/result.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "generic-error-instantiation",
      scenarioId: "generic-error",
      title: "A concrete generic error channel erases its identity",
      outcome: "match",
      files: [
        {
          path: "app/result.ts",
          source:
            "type Result<T, E> = { ok: true; value: T } | { ok: false; error: E }; export type Saved = Result<number, string>;",
        },
      ],
      focusPath: "app/result.ts",
      expectedCount: 1,
      public: true,
    },
    {
      id: "finite-error-codes",
      scenarioId: "generic-error",
      title: "An error code needs no invented payload",
      outcome: "no-match",
      files: [
        {
          path: "app/result.ts",
          source:
            "type Result<T, E> = { ok: true; value: T } | { ok: false; error: E }; export type Saved = Result<number, 'duplicate' | 'invalid_transition'>;",
        },
      ],
      focusPath: "app/result.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "exclusive-message-outcome",
      scenarioId: "partial-data",
      title: "An exclusive failure still needs an actionable identity",
      outcome: "match",
      files: [
        {
          path: "app/result.ts",
          source:
            "export type Outcome<T> = { ok: true; data: T } | { ok: false; error: string };",
        },
      ],
      focusPath: "app/result.ts",
      expectedCount: 1,
      public: true,
    },
    {
      id: "independent-partial-outcomes",
      scenarioId: "partial-data",
      title: "Partial data and its independent error remain separate outcomes",
      outcome: "no-match",
      files: [
        {
          path: "app/result.ts",
          source:
            "export type Partial<T> = { ok: true; data: T; error?: string } | { ok: false; data: T; error: string };",
        },
      ],
      focusPath: "app/result.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "exclusive-error-state",
      scenarioId: "absence-state",
      title: "Conventional success and failure tags establish one Result",
      outcome: "match",
      files: [
        {
          path: "app/result.ts",
          source:
            "export type Outcome<T> = { status: 'success'; value: T } | { status: 'failure'; reason: string };",
        },
      ],
      focusPath: "app/result.ts",
      expectedCount: 1,
      public: true,
    },
    {
      id: "legitimate-unconfigured-state",
      scenarioId: "absence-state",
      title: "A loading report can preserve an unconfigured absence state",
      outcome: "no-match",
      files: [
        {
          path: "app/result.ts",
          source:
            "export type Source<T> = { status: 'loaded'; value: T } | { status: 'failed' | 'unconfigured'; reason: string };",
        },
      ],
      focusPath: "app/result.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "producer-renders-context",
      scenarioId: "consumer-formatting",
      title: "A code alone does not move message formatting to the consumer",
      outcome: "match",
      files: [
        {
          path: "app/result.ts",
          source:
            "export function reject(name: string) { return { ok: false, code: 'duplicate', message: `Duplicate ${name}` }; }",
        },
      ],
      focusPath: "app/result.ts",
      expectedCount: 1,
      public: true,
    },
    {
      id: "consumer-renders-context",
      scenarioId: "consumer-formatting",
      title: "Retain the typed context and format after handling the code",
      outcome: "no-match",
      files: [
        {
          path: "app/result.ts",
          source:
            "type Duplicate = { code: 'duplicate'; name: string }; export function reject(name: string): { ok: false; error: Duplicate } { return { ok: false, error: { code: 'duplicate', name } }; } export function format(error: Duplicate): string { return `Duplicate ${error.name}`; }",
        },
      ],
      focusPath: "app/result.ts",
      expectedCount: 0,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;
