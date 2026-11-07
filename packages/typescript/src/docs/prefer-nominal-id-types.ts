/** @fileoverview prefer-nominal-id-types — the documentation and executable examples of `@sarj/prefer-nominal-id-types`. */

import type { RuleDocumentation } from "../documentation.js";

export const PREFER_NOMINAL_ID_TYPES_DOCUMENTATION = {
  defaultLevel: "error",
  summary:
    "Distinguish identifier roles sharing primitive types at callable boundaries.",
  rationale:
    "Two identifier roles represented by the same primitive accept each other's values, so swapped arguments survive type checking. Transparent aliases do not prevent this.",
  remediation:
    "Introduce distinct branded identifier types at a validated domain boundary and use them in the callable contract. Keep wire representations primitive until validation; suppress a required external signature locally with a reason.",
  category: "correctness",
  autofix: "safe",
  limitations: [
    "Automatic fixes only copy two existing distinct exported string-brand parameter types from a sole public overload into its empty ordinary implementation. The complete module must contain only those two nongeneric brands and the overload/implementation pair; comments, imports, additional declarations, defaults/rest/optional parameters and all operational bodies remain manual.",
    "Requires two distinct Id/Ids or _id/_ids parameter roles with the same proven string, number, or homogeneous array carrier. Plural names require array carriers. Scalars and arrays remain distinct; object fields, destructuring, tuples, inferred types and generic aliases are not checked.",
    "Resolves only scope-correct file-local transparent aliases, up to 16 levels. Intersections, imported types, ambiguous declarations and mixed branded/raw pairs are deliberately skipped.",
    "Generated files and request, trace, span, correlation, process, thread, timeout and interval identifiers are excluded. Raw wire object schemas are not callable boundaries; required external callable signatures need a local suppression. API and adapter paths are not blanket-excluded.",
  ],
  examples: [
    {
      id: "safe-autofix",
      title: "Reuse the existing public overload's identifier brands",
      outcome: "match",
      files: [
        {
          path: "src/ids.ts",
          source:
            "export type AccountId = string & { readonly account: unique symbol }; export type InvoiceId = string & { readonly invoice: unique symbol }; export function load(accountId: AccountId, invoiceId: InvoiceId): void; export function load(accountId: string, invoiceId: string): void {}",
        },
      ],
      fixedFiles: [
        {
          path: "src/ids.ts",
          source:
            "export type AccountId = string & { readonly account: unique symbol }; export type InvoiceId = string & { readonly invoice: unique symbol }; export function load(accountId: AccountId, invoiceId: InvoiceId): void; export function load(accountId: AccountId, invoiceId: InvoiceId): void {}",
        },
      ],
      focusPath: "src/ids.ts",
      expectedCount: 1,
    },
    {
      id: "raw-identifiers",
      title: "Do not accept interchangeable identifiers",
      outcome: "match",
      files: [
        {
          path: "src/store.ts",
          source:
            "function load(accountId: string, invoiceId: string): void {}",
        },
      ],
      focusPath: "src/store.ts",
      expectedCount: 1,
      public: true,
    },
    {
      id: "branded-identifiers",
      title: "Distinguish domain identifiers",
      outcome: "no-match",
      files: [
        {
          path: "src/store.ts",
          source:
            "type AccountId = string & { readonly account: unique symbol }; type InvoiceId = string & { readonly invoice: unique symbol }; function load(accountId: AccountId, invoiceId: InvoiceId): void {}",
        },
      ],
      focusPath: "src/store.ts",
      expectedCount: 0,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;
