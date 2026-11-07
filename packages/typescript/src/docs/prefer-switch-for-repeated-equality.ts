/** @fileoverview prefer-switch-for-repeated-equality — the documentation and executable examples of `@sarj/prefer-switch-for-repeated-equality`. */

import type { RuleDocumentation } from "../documentation.js";

export const PREFER_SWITCH_FOR_REPEATED_EQUALITY_DOCUMENTATION = {
  defaultLevel: "error",
  summary: "Prefer switch over long if/else-if chains that compare one value for strict equality.",
  rationale: "A switch makes finite dispatch cases visually uniform and easier to extend without duplicating the discriminant.",
  remediation: "Replace three or more strict-equality branches over the same discriminant with a switch; keep if statements for ranges, guards, and heterogeneous predicates.",
  category: "maintainability",
  autofix: "safe",
  limitations: [
    "Only direct if/else-if chains with at least three strict-equality tests are reported.",
    "The discriminant must be a resolved lexical variable or parameter; unresolved globals, calls, getters, and indexed reads are excluded. Automatic conversion requires terminating compared branches and an explicit final else or type-proven open discriminant, preserving branch scopes and excluding comments, break statements, and function declarations.",
    "Case values must be primitive literals. Member references and named constants are excluded because evaluating them can observe getters or mutate the selector. Generated sources are excluded.",
    "The rule deliberately ignores compound predicates, loose equality, ranges, and chains that compare different discriminants.",
  ],
  examples: [
    { id: "switch-dispatch", title: "Make finite dispatch explicit", outcome: "no-match", files: [{ path: "src/render.ts", source: "function render(kind: string) { switch (kind) { case 'a': return 'alpha'; case 'b': return 'beta'; case 'c': return 'gamma'; default: return 'unknown'; } }" }], focusPath: "src/render.ts", expectedCount: 0, public: true },
    { id: "repeated-equality", title: "Avoid repeating the discriminant", outcome: "match", files: [{ path: "src/render.ts", source: "function render(kind: string) { if (kind === 'a') return 'alpha'; else if (kind === 'b') return 'beta'; else if (kind === 'c') return 'gamma'; return 'unknown'; }" }], focusPath: "src/render.ts", expectedCount: 1, public: true },
    { id: "escaped-middle", scenarioId: "native-discriminant", title: "Use native identifier identity", outcome: "match", files: [{ path: "src/dispatch.ts", source: "function probe(kind){if(kind==='a')return 1;else if(\\u006bind==='b')return 2;else if(kind==='c')return 3;return 0;}\nconsole.log(JSON.stringify([\"a\",\"b\",\"c\",\"d\"].map(probe)));" }], focusPath: "src/dispatch.ts", expectedCount: 1, public: true },
    { id: "different-discriminants", scenarioId: "native-discriminant", title: "Use native identifier identity", outcome: "no-match", files: [{ path: "src/dispatch.ts", source: "function probe(kind){const other=\"other\";if(kind==='a')return 1;else if(other==='b')return 2;else if(kind==='c')return 3;return 0;}\nconsole.log(JSON.stringify([\"a\",\"b\",\"c\",\"d\"].map(probe)));" }], focusPath: "src/dispatch.ts", expectedCount: 0, public: true },
    {
      id: "safe-autofix",
      title: "Apply the proven automatic correction",
      outcome: "match",
      files: [{ path: "src/autofix-example.ts", source: "function probe(kind: string) { if (kind === 'a') return 1; else if (kind === 'b') return 2; else if (kind === 'c') return 3; return 0; }" }],
      fixedFiles: [{ path: "src/autofix-example.ts", source: "function probe(kind: string) { switch (kind) {\ncase 'a': { return 1; }\ncase 'b': { return 2; }\ncase 'c': { return 3; }\n} return 0; }" }],
      focusPath: "src/autofix-example.ts",
      expectedCount: 1,
    },
  ],
} as const satisfies RuleDocumentation;
