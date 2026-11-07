/** @fileoverview no-reduce-accumulator-copy — the documentation and executable examples of `@sarj/no-reduce-accumulator-copy`. */

import type { RuleDocumentation } from "../documentation.js";

export const NO_REDUCE_ACCUMULATOR_COPY_DOCUMENTATION = {
  summary:
    "Review copies of the accumulated collection inside a built-in reduce callback.",
  rationale:
    "Copying a growing accumulator at every step can make collection quadratic instead of linear in its output size.",
  remediation:
    "Use map or flatMap where their semantics match, or append into a fresh locally owned accumulator. Preserve retained snapshots and shared state.",
  category: "performance",
  requiresTypeInformation: true,
  references: ["https://github.com/dmmulroy/anti-slop/blob/13909c9e07590f5a85d93c62712259fe14a883f7/src/rules/no-reduce-accumulator-copy.ts"],
  autofix: "safe",
  limitations: [
    "Requires type information proving the built-in Array or ReadonlyArray reduce/reduceRight method, an inline callback, and a fresh empty array or object-literal seed, directly or through single-use stable const aliases.",
    "Inspects direct accumulator spreads, Object.assign with a fresh object target, Array.from, and concat/slice/toSpliced/toSorted/toReversed/with calls. Stable callback-local const accumulator aliases are resolved. Named callbacks, mutable/escaping seeds, nested functions, and loops remain outside this rule.",
    "A copy is evidence for review, not proof of growth or measured latency. Automatic edits only remove an exact identity reducer over a fresh nonempty literal-string array in a sole exported zero-argument function with an explicit string[] return. The direct literal return remains fresh on every call. Snapshots, aliases, callbacks, nonliteral values, reverse reduction, imports, comments and other control flow remain manual.",
  ],
  examples: [
    {
      id: "copy-rows",
      title: "Repeated concatenation copies prior report rows",
      outcome: "match",
      files: [
        {
          path: "src/reports.ts",
          source:
            "declare const pages: string[][];\nconst rows = pages.reduce<string[]>((acc, page) => acc.concat(page), []);",
        },
      ],
      focusPath: "src/reports.ts",
      expectedCount: 1,
      public: true,
    },
    {
      id: "flatten-rows",
      title: "Flatten report rows without copying the accumulated prefix",
      outcome: "no-match",
      files: [
        {
          path: "src/reports.ts",
          source:
            "declare const pages: string[][];\nconst rows = pages.flatMap(page => page);",
        },
      ],
      focusPath: "src/reports.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "safe-autofix",
      title: "Return the existing fresh identity collection directly",
      outcome: "match",
      files: [
        {
          path: "src/reports.ts",
          source:
            "export function collect(): string[] { return ['a', 'b'].reduce<string[]>((acc, item) => [...acc, item], []); }",
        },
      ],
      fixedFiles: [
        {
          path: "src/reports.ts",
          source: "export function collect(): string[] { return ['a', 'b']; }",
        },
      ],
      focusPath: "src/reports.ts",
      expectedCount: 1,
    },
    {"id": "reducer-aliases-before", "scenarioId": "reducer-aliases", "title": "Retain fresh seed and accumulator identities — before", "outcome": "match", "files": [{"path": "src/example.ts", "source": "declare const pages: string[][]; const seed: string[] = []; pages.reduce((acc, page) => { const previous = acc; return [...previous, ...page]; }, seed);"}], "focusPath": "src/example.ts", "expectedCount": 1, "public": true},
    {"id": "reducer-aliases-after", "scenarioId": "reducer-aliases", "title": "Retain fresh seed and accumulator identities — after", "outcome": "no-match", "files": [{"path": "src/example.ts", "source": "declare const pages: string[][]; pages.flatMap(page => page);"}], "focusPath": "src/example.ts", "expectedCount": 0, "public": true},
  ],
} as const satisfies RuleDocumentation;
