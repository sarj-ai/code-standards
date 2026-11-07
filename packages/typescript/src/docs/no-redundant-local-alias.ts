/** @fileoverview no-redundant-local-alias — the documentation and executable examples of `@sarj/no-redundant-local-alias`. */

import type { RuleDocumentation } from "../documentation.js";

export const NO_REDUNDANT_LOCAL_ALIAS_DOCUMENTATION = {
  defaultLevel: "warning",
  summary: "Pass the original local into an object field instead of creating a single-use rename.",
  rationale: "An unannotated alias used only by its matching object field adds a second name without adding a contract.",
  remediation: "Write the object property with the original binding, then remove the redundant alias. Keep annotations, captured snapshots and independently useful names.",
  category: "maintainability",
  autofix: "safe",
  limitations: [
    "Checks an unannotated local const alias of a stable parameter or earlier const. Its single read must be a shorthand property in the same function scope. Module exports, imported bindings, captures, reassignment, positional uses and typed aliases are preserved.",
    "Safe fixes are limited to a plain module-scope function with one explicitly intrinsic-primitive parameter and exactly a const alias followed by a returned object containing that sole shorthand field. The source binding must remain the same at the returned field. Generics, return annotations, optional/default parameters, destructuring, overloads, comments, eval, async/generator functions and the special __proto__ key remain manual. Other diagnostics require review.",
  ],
  examples: [
    { id: "redundant-alias", title: "The property already supplies the name", outcome: "match", files: [{ path: "src/request.ts", source: "function request(value: string) { const accountId = value; return { accountId }; }" }], focusPath: "src/request.ts", expectedCount: 1, public: true },
    { id: "direct-property", title: "Use the original binding", outcome: "no-match", files: [{ path: "src/request.ts", source: "function request(value: string) { return { accountId: value }; }" }], focusPath: "src/request.ts", expectedCount: 0, public: true },
    { id: "closed-primitive-parameter-alias", scenarioId: "closed-primitive-parameter-alias", title: "The closed primitive return preserves the data-field contract", outcome: "match", files: [{ path: "src/request.ts", source: "export {};\nfunction request(value: string) {\n  const accountId = value;\n  return { accountId };\n}\n" }], fixedFiles: [{ path: "src/request.ts", source: "export {};\nfunction request(value: string) {\n\n  return { accountId: value };\n}\n" }], focusPath: "src/request.ts", expectedCount: 1, public: true },
    { id: "closed-primitive-parameter-alias-fixed", scenarioId: "closed-primitive-parameter-alias", title: "The direct data field needs no local alias", outcome: "no-match", files: [{ path: "src/request.ts", source: "export {};\nfunction request(value: string) {\n\n  return { accountId: value };\n}\n" }], focusPath: "src/request.ts", expectedCount: 0, public: true },
  ],
} as const satisfies RuleDocumentation;
