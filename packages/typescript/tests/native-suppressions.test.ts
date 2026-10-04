import { expect, it } from "vitest";
import { stockLint } from "./_stock-cli.js";

const CASES = [
  ["no-comment-cruft", "// =====\nconst value = 1;", "ts"],
  ["no-silent-promise-catch", "p.catch(\n  () => null,\n);", "ts"],
  [
    "prefer-node-fs-promises",
    "import { readFileSync, writeFileSync } from 'node:fs';",
    "ts",
  ],
  [
    "prefer-nominal-id-types",
    "function load(accountId: string, invoiceId: string) {}",
    "ts",
  ],
  ["require-button-accessible-name", "<button><svg /></button>", "tsx"],
  [
    "no-excessive-cognitive-complexity",
    `function sample() { ${"if (ready) work();".repeat(21)} }`,
    "ts",
  ],
] as const;

it.each(CASES)(
  "%s uses stock native inline suppression",
  (name, source, extension) => {
    const positive = stockLint(name, source, extension);
    expect(positive.status).toBe(1);
    expect(positive.diagnostics).toHaveLength(1);
    const suppressed = stockLint(
      name,
      `// oxlint-disable-next-line @sarj/${name} -- reviewed source exception\n${source}`,
      extension,
    );
    expect(suppressed.status).toBe(0);
    expect(suppressed.diagnostics).toEqual([]);
  },
);

it("one native directive does not hide a different function", () => {
  const functionBody = "if (ready) work();".repeat(21);
  const result = stockLint(
    "no-excessive-cognitive-complexity",
    `// oxlint-disable-next-line @sarj/no-excessive-cognitive-complexity -- reviewed dispatch\nfunction first() { ${functionBody} }\nfunction second() { ${functionBody} }`,
  );
  expect(result.status).toBe(1);
  expect(result.diagnostics).toHaveLength(1);
});
