/** @fileoverview no-broad-return-type — the documentation and executable examples of `@sarj/no-broad-return-type`. */

import type { RuleDocumentation } from "../documentation.js";

export const NO_BROAD_RETURN_TYPE_DOCUMENTATION = {
  summary:
    "Report explicit broad return annotations that erase a known return value.",
  rationale:
    "An unknown, object, or unknown-valued dictionary return hides fields that the implementation already knows.",
  remediation:
    "Return the existing domain type or retain the inferred return contract. Keep unknown at unparsed input boundaries.",
  category: "maintainability",
  autofix: "safe",
  limitations: [
    "Requires TypeScript type information and an implemented function with an explicit return annotation. Checks unknown, object, and unknown-valued index-only dictionaries, including aliases and Promise results.",
    "Unparsed unknown/any values, generics, empty object literals, and declaration-only signatures are excluded. Parameter contracts are not inferred from names. Intentional opaque return boundaries require an explained local suppression. Automatic fixes remove the annotation only from an unused private function declaration in a module or block; referenced and public contracts remain manual.",
  ],
  examples: [
    {
      id: "before",
      title: "Preserve the explicit contract",
      outcome: "match",
      files: [
        {
          path: "src/example.ts",
          source:
            "type Invoice = { reference: string; total: number };\nfunction toRequest(invoice: Invoice): Record<string, unknown> { return invoice; }",
        },
      ],
      focusPath: "src/example.ts",
      expectedCount: 1,
      public: true,
    },
    {
      id: "after",
      title: "Use the direct contract",
      outcome: "no-match",
      files: [
        {
          path: "src/example.ts",
          source:
            "type Invoice = { reference: string; total: number };\nfunction toRequest(invoice: Invoice): Invoice { return invoice; }",
        },
      ],
      focusPath: "src/example.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "safe-autofix",
      title: "Apply the proven automatic correction",
      outcome: "match",
      files: [{ path: "src/autofix-example.ts", source: "export {}; function request(value: { id: string }): unknown { return value; }" }],
      fixedFiles: [{ path: "src/autofix-example.ts", source: "export {}; function request(value: { id: string }) { return value; }" }],
      focusPath: "src/autofix-example.ts",
      expectedCount: 1,
    },
  ],
} as const satisfies RuleDocumentation;
