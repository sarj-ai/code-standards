/** @fileoverview prefer-coded-error-result — documentation and executable contract examples. */

import type { RuleDocumentation } from "../documentation.js";

export const PREFER_CODED_ERROR_RESULT_DOCUMENTATION = {
  summary:
    "Return a stable error code and typed context instead of only a rendered failure message.",
  defaultLevel: "warning",
  rationale:
    "A message-only failure hides the identity needed for repair, conflict handling, localization and exhaustive dispatch. Preserve a finite error code and the minimum handling context; let the consumer format its message.",
  remediation:
    "Use the existing Result or outcome union with a finite error code and variant-specific context. Preserve public behavior through a presentation adapter, and handle or propagate each relevant variant without parsing message text.",
  category: "correctness",
  autofix: "none",
  limitations: [
    "Checks source-resolved local unions with required literal ok/success true and false branches, and named neverthrow Result/ResultAsync imports. Broad string error/message/reason payloads and open string code fields are review candidates. String literal error-code unions remain valid.",
    "Local aliases, unmerged interfaces without inheritance and generic substitutions are bounded to 16 resolution levels, 64 union members and 256 traversal steps. Imported local declarations, namespace imports, conditional/intersection/mapped types and unresolved contracts abstain. Optional discriminants, independent success/error payloads and partial-data failures are excluded.",
    "Required code/kind/type/tag fields of unresolved or imported type defer to the type checker; a finite code does not prove that its cases or payloads are useful. Generic error parameters are retained rather than guessed. Ordinary string formatters, absence, validation-library errors and redacted failure states without a string payload are not flagged.",
    "A directly returned plain object with literal ok/success false and a literal string code/kind/type/tag also receives review when its message/reason is an interpolated template or proven string concatenation. Nested plain error objects and expression-bodied arrows are supported. Spreads, accessors, computed keys, helper formatting calls and nonliteral codes abstain. This proves formatting ownership, not which context the domain must expose; presentation adapters remain a reviewed exception.",
    "This warning requests domain review: a final presentation boundary may intentionally accept every failure and render one message. No fix invents error codes, fields, handlers or changes serialization, exception unwinding, transactions, retries or logging.",
  ],
  references: [
    "https://www.typescriptlang.org/docs/handbook/2/narrowing.html#discriminated-unions",
    "https://github.com/supermacro/neverthrow",
  ],
  examples: [
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
