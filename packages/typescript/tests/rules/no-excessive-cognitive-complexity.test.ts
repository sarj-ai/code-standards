// vitest: shared-module-graph
import rule from "../../src/rules/no-excessive-cognitive-complexity.js";
import { ruleTester } from "./_tester.js";

const RULE_TESTER = ruleTester();
const TWENTY_ONE_GUARDS = "if (ready) work();".repeat(21);

const NESTED_DECISIONS = "function decide(a, b, c, d, e, f, g) { if (a) { if (b) { if (c) { if (d) { if (e) { if (f) { if (g) { act(); } } } } } } } }";
const GUARD_DECISIONS = "function decide(a, b, c, d, e, f, g) { if (!a) return; if (!b) return; if (!c) return; if (!d) return; if (!e) return; if (!f) return; if (!g) return; act(); }";
const DOWNLOAD_CHECK_BEFORE = "function canDownload(item: Download): boolean {\n  if (item.published) {\n    if (item.licensed) {\n      if (item.available) {\n        if (!item.quarantined) {\n          if (item.bytes > 0) {\n            if (item.bytes <= 1000000) {\n              return true;\n            }\n          }\n        }\n      }\n    }\n  }\n  return false;\n}\n";
const DOWNLOAD_CHECK_AFTER = "function canDownload(item: Download): boolean {\n  if (!item.published) return false;\n  if (!item.licensed) return false;\n  if (!item.available) return false;\n  if (item.quarantined) return false;\n  if (!(item.bytes > 0)) return false;\n  if (!(item.bytes <= 1000000)) return false;\n  return true;\n}\n";
const CATALOG_LABELS_BEFORE = "function collectLabels(catalog: Catalog): string[] {\n  const labels: string[] = [];\n  for (const section of catalog.sections) {\n    for (const shelf of section.shelves) {\n      for (const item of shelf.items) {\n        if (item.visible) {\n          if (item.inStock) {\n            if (item.label !== \"\") {\n              labels.push(item.label);\n            }\n          }\n        }\n      }\n    }\n  }\n  return labels;\n}\n";
const CATALOG_LABELS_AFTER = "function hasDisplayLabel(item: CatalogItem): boolean {\n  if (!item.visible) return false;\n  if (!item.inStock) return false;\n  if (item.label === \"\") return false;\n  return true;\n}\n\nfunction collectLabels(catalog: Catalog): string[] {\n  const labels: string[] = [];\n  for (const section of catalog.sections) {\n    for (const shelf of section.shelves) {\n      for (const item of shelf.items) {\n        if (hasDisplayLabel(item)) labels.push(item.label);\n      }\n    }\n  }\n  return labels;\n}\n";

const SCORED_BODIES = [
  ["return value;", 0],
  ["for (slots[flag ? a : b] of items) {}", 2],
  ["if (a) { if (b) { return value; } }", 3],
  ["if (!a) return; if (!b) return; return value;", 2],
  ["if (a) {} else if (b) { if (c) {} } else { if (d) {} }", 7],
  ["if (a) {} else { if (b) {} }", 4],
  ["return a && b && c;", 1],
  ["return a && (b || c) && d;", 3],
  ["return (a && b) || (c && d);", 3],
  ["return a?.b ?? other?.c;", 0],
  ["return a ? b : c ? d : e;", 3],
  ["try { work(); } catch (error) { if (retry) work(); } finally { cleanup(); }", 3],
  ["for (const item of items) { if (item) continue; }", 3],
  ["for await (const item of items) { if (item) await work(); }", 3],
  ["for (let i = 0; i < 2; i++) { while (ready) { break; } }", 3],
  ["outer: do { if (ready) break outer; } while (again);", 4],
  ["switch (value) { case 1: break; default: if (ready) work(); }", 3],
  ["function inner() { if (ready) work(); } return inner;", 0],
  ["class Inner { method() { if (ready) work(); } } return Inner;", 0],
  ["return () => ready ? value : other;", 0],
  ["return recurse(value);", 0],
] as const;

const scoreMessage = (score: number) => new RegExp(`^Cognitive complexity ${score} exceeds 20\\.`, "u");

RULE_TESTER.run("no-excessive-cognitive-complexity", rule, {
  valid: [
    GUARD_DECISIONS,
    `function sample() { ${"if (ready) work();".repeat(20)} }`,
    `function sample() { return ${Array<string>(600).fill("value").join("+")}; }`,
    { filename: "src/generated/sample.ts", code: `function sample() { ${TWENTY_ONE_GUARDS} }` },
    `// @generated\nfunction sample() { ${TWENTY_ONE_GUARDS} }`,
    { name: "keeps the published download-check-after score", code: DOWNLOAD_CHECK_AFTER },
    { name: "keeps the published catalog-labels-after scores", code: CATALOG_LABELS_AFTER },
    { name: "reports exactly the configured severity at score 20", code: `function sample() { ${"if (ready) work();".repeat(20)} }`, filename: "score-20.ts" },
  ],
  invalid: [
    { code: NESTED_DECISIONS, errors: [{ messageId: "excessiveComplexity", data: { score: 28, limit: 20, detail: "L1 +7 if; L1 +6 if; L1 +5 if" } }] },
    { code: `function sample() { ${TWENTY_ONE_GUARDS} }`, errors: [{ messageId: "excessiveComplexity", line: 1 }] },
    { filename: "tests/sample.test.ts", code: `function sample() { ${TWENTY_ONE_GUARDS} }`, errors: [{ messageId: "excessiveComplexity" }] },
    { code: `function outer() { function inner() { ${TWENTY_ONE_GUARDS} } } class Example { method() { ${TWENTY_ONE_GUARDS} } }`, errors: [{ messageId: "excessiveComplexity" }, { messageId: "excessiveComplexity" }] },
    { filename: "src/Screen.tsx", code: `function Screen() { ${TWENTY_ONE_GUARDS} return <div />; }`, errors: [{ messageId: "excessiveComplexity" }] },
    { code: `const handler = () => { ${TWENTY_ONE_GUARDS} };`, errors: [{ messageId: "excessiveComplexity" }] },
    ...SCORED_BODIES.map(([body, expected], index) => ({
      name: `scores function body ${body} as ${expected} on top of 21 flat guards (the original scored the body alone)`,
      filename: `scored-${index}.ts`,
      code: `async function sample() { ${TWENTY_ONE_GUARDS} ${body} }`,
      errors: [{ message: scoreMessage(21 + expected) }],
    })),
    ...([21, 25, 26] as const).map((score) => ({
      name: `reports exactly the configured severity at score ${score}`,
      filename: `score-${score}.ts`,
      code: `function sample() { ${"if (ready) work();".repeat(score)} }`,
      errors: [{ message: scoreMessage(score) }],
    })),
    { name: "keeps the published download-check-before score", code: DOWNLOAD_CHECK_BEFORE, errors: [{ message: scoreMessage(21) }] },
    { name: "keeps the published catalog-labels-before score", code: CATALOG_LABELS_BEFORE, errors: [{ message: scoreMessage(21) }] },
    {
      name: "reports two functions independently",
      code: `function review() { ${"if (ready) work();".repeat(25)} } function change() { ${"if (ready) work();".repeat(26)} }`,
      errors: [{ message: scoreMessage(25) }, { message: scoreMessage(26) }],
    },
  ],
});
