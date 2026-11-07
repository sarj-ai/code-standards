/** @fileoverview prefer-typed-reflection — the documentation and executable examples of `@sarj/prefer-typed-reflection`. */

import type { RuleDocumentation } from "../documentation.js";

export const PREFER_TYPED_REFLECTION_DOCUMENTATION = {
  summary:
    "Prefer typed access when Reflect.get or Reflect.apply discards a known contract.",
  rationale:
    "Reflect.get and Reflect.apply can accept property or argument mistakes that normal typed access catches.",
  remediation:
    "Use direct typed property access or call the typed function, preserving receivers and evaluation semantics.",
  category: "maintainability",
  requiresTypeInformation: true,
  references: [
    "https://github.com/dmmulroy/anti-slop/blob/13909c9e07590f5a85d93c62712259fe14a883f7/src/rules/no-reflect-get.ts",
    "https://github.com/dmmulroy/anti-slop/blob/13909c9e07590f5a85d93c62712259fe14a883f7/src/rules/no-reflect-apply.ts",
  ],
  autofix: "safe",
  limitations: [
    "Requires TypeScript type information. Inspects scope-resolved global Reflect.get with a literal key (including no-substitution templates and erased TypeScript wrappers) on a closed object type, and Reflect.apply with a known call signature and a literal argument array or stable, unmodified const tuple. Stable local Reflect aliases are resolved.",
    "Dynamic keys, open dictionaries, unknown/any/generic targets, explicit Reflect.get receivers, mutated/escaping aliases, and unknown argument arrays are excluded. Expanded aliases and tuple containers remain manual. Deliberate proxy or metaprogramming calls need a local suppression. Automatic fixes cover comment-free nonoptional Reflect.get calls with a known existing property on an object. Immediate calls/tags, missing keys and Reflect.apply remain manual to preserve receiver and argument contracts.",
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
            'declare const shipment: { status: string };\nconst status = Reflect.get(shipment, "status");',
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
            "declare const shipment: { status: string };\nconst status = shipment.status;",
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
      files: [{ path: "src/autofix-example.ts", source: "declare const target: { id: string }; const id = Reflect.get(target, \"id\");" }],
      fixedFiles: [{ path: "src/autofix-example.ts", source: "declare const target: { id: string }; const id = (target)[\"id\"];" }],
      focusPath: "src/autofix-example.ts",
      expectedCount: 1,
    },
    {"id": "apply-tuple-before", "scenarioId": "apply-tuple", "title": "Keep the callable contract with a stable tuple — before", "outcome": "match", "files": [{"path": "src/example.ts", "source": "declare function lookup(id: string): string; const args: [string] = [\"u1\"]; Reflect.apply(lookup, undefined, args);"}], "focusPath": "src/example.ts", "expectedCount": 1, "public": true},
    {"id": "apply-tuple-after", "scenarioId": "apply-tuple", "title": "Keep the callable contract with a stable tuple — after", "outcome": "no-match", "files": [{"path": "src/example.ts", "source": "declare function lookup(id: string): string; const args: [string] = [\"u1\"]; lookup(...args);"}], "focusPath": "src/example.ts", "expectedCount": 0, "public": true},
    {"id": "reflect-alias-before", "scenarioId": "reflect-alias", "title": "Keep the target contract through an alias — before", "outcome": "match", "files": [{"path": "src/example.ts", "source": "declare const target: { id: string }; const reflection = Reflect; const id = reflection.get(target, \"id\");"}], "focusPath": "src/example.ts", "expectedCount": 1, "public": true},
    {"id": "reflect-alias-after", "scenarioId": "reflect-alias", "title": "Keep the target contract through an alias — after", "outcome": "no-match", "files": [{"path": "src/example.ts", "source": "declare const target: { id: string }; const id = target.id;"}], "focusPath": "src/example.ts", "expectedCount": 0, "public": true},
  ],
} as const satisfies RuleDocumentation;
