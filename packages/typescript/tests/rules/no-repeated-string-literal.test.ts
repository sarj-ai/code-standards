import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule from "../../src/rules/no-repeated-string-literal.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const ruleTester = new RuleTester({
  languageOptions: {
    parser: tsParser,
  },
});

const COLUMNS = "id, ashby_candidate_id, dataset_id, status, expires_at";

ruleTester.run("no-repeated-string-literal", rule, {
  valid: [
    // FP guard, corpus: react-router/integration/single-fetch-test.ts:1482 — a
    // tagged template is an invocation; the tag decides what the text means.
    {
      code: [
        'const a = js`export default function Component() {\n  return null;\n}`;',
        'function one() { return js`export default function Component() {\n  return null;\n}`; }',
        'function two() { return js`export default function Component() {\n  return null;\n}`; }',
      ].join("\n"),
    },
    // Corpus: query/packages/query-devtools/src/Devtools.tsx:398 — a `css` block.
    {
      code: [
        'const base = css`\n  min-width: min-content;\n  display: flex;\n`;',
        'function a() { return css`\n  min-width: min-content;\n  display: flex;\n`; }',
        'function b() { return css`\n  min-width: min-content;\n  display: flex;\n`; }',
      ].join("\n"),
    },
    // --- Unstructured prose is never flagged, even when repeated: two messages
    // that happen to be equal have different intent, and a shared constant would
    // wrongly couple them. ---
    {
      code: [
        "function a() { return 'the requested candidate could not be found here'; }",
        "function b() { return 'the requested candidate could not be found here'; }",
        "function c() { return 'the requested candidate could not be found here'; }",
      ].join("\n"),
    },
    // --- Lower-case prose containing SQL words is prose, not SQL. ---
    {
      code: [
        "function a() { return 'pick the fields you want from the list of columns'; }",
        "function b() { return 'pick the fields you want from the list of columns'; }",
        "function c() { return 'pick the fields you want from the list of columns'; }",
      ].join("\n"),
    },
    // --- Two uses inside ONE function: edited together, so hoisting them buys
    // no drift protection. The distinct-scope filter, not a count of
    // occurrences, is what carries precision here. ---
    {
      code: [
        "function only() {",
        `  const x = \`SELECT ${COLUMNS} FROM candidates\`;`,
        `  const y = \`SELECT ${COLUMNS} FROM candidates\`;`,
        "  return [x, y];",
        "}",
      ].join("\n"),
    },
    // --- Under the length threshold. ---
    {
      code: [
        "function a() { return 'SELECT id FROM runs'; }",
        "function b() { return 'SELECT id FROM runs'; }",
        "function c() { return 'SELECT id FROM runs'; }",
      ].join("\n"),
    },
    // --- All occurrences inside ONE function: they are edited together, so
    // hoisting buys no drift protection and only costs locality. ---
    {
      code: [
        "function a() {",
        `  const x = \`SELECT ${COLUMNS} FROM candidates\`;`,
        `  const y = \`SELECT ${COLUMNS} FROM candidates\`;`,
        `  const z = \`SELECT ${COLUMNS} FROM candidates\`;`,
        "  return [x, y, z];",
        "}",
      ].join("\n"),
    },
    // --- Template literals WITH substitutions are fragments, not reusable values. ---
    {
      code: [
        `function a(t) { return \`SELECT ${COLUMNS} FROM \${t}\`; }`,
        `function b(t) { return \`SELECT ${COLUMNS} FROM \${t}\`; }`,
        `function c(t) { return \`SELECT ${COLUMNS} FROM \${t}\`; }`,
      ].join("\n"),
    },
    // --- Already extracted to a module-level constant: the drift is gone. ---
    {
      code: [
        `const CANDIDATE_QUERY = \`SELECT ${COLUMNS} FROM candidates\`;`,
        "function a() { return CANDIDATE_QUERY; }",
        "function b() { return CANDIDATE_QUERY; }",
        "function c() { return CANDIDATE_QUERY; }",
      ].join("\n"),
    },
    // --- Test files repeat fixture payloads by design. ---
    {
      filename: "/repo/test/repo.test.ts",
      code: [
        `function a() { return \`SELECT ${COLUMNS} FROM candidates\`; }`,
        `function b() { return \`SELECT ${COLUMNS} FROM candidates\`; }`,
        `function c() { return \`SELECT ${COLUMNS} FROM candidates\`; }`,
      ].join("\n"),
    },
    // --- ...including the `-test.ts` / `_test.ts` spellings. All 5 of this
    // rule's hits over the 2,186-file third-party corpus were react-router
    // `*-test.ts` source-transform fixtures that the exemption already intended
    // to cover; `_paths.isTestFile` only knew the `.test.ts` spelling. ---
    {
      filename: "/repo/vite/remove-exports-test.ts",
      code: [
        `function a() { return \`SELECT ${COLUMNS} FROM candidates\`; }`,
        `function b() { return \`SELECT ${COLUMNS} FROM candidates\`; }`,
      ].join("\n"),
    },
    {
      filename: "/repo/vite/remove_exports_test.ts",
      code: [
        `function a() { return \`SELECT ${COLUMNS} FROM candidates\`; }`,
        `function b() { return \`SELECT ${COLUMNS} FROM candidates\`; }`,
      ].join("\n"),
    },
  ],
  invalid: [
    // --- CROSS-PACKAGE PARITY with Python's SARJ024. "Two distinct enclosing
    // functions" is the ONLY count threshold, in BOTH packages. This rule
    // carried an abandoned three-occurrence gate, so a literal used exactly
    // twice fired in `.py` and was clean in `.ts`. Minimized from
    // `noura-be/.../modules/onboarding/store.py:631`, where one
    // `SELECT stage ... FOR UPDATE` is repeated between two store methods.
    // If this fails, someone re-introduced a total-occurrence threshold —
    // re-run both corpus sweeps before changing the test. ---
    {
      code: [
        `function submitFinancialInfo() { return \`SELECT ${COLUMNS} FROM candidates\`; }`,
        `function submitLegalInfo() { return \`SELECT ${COLUMNS} FROM candidates\`; }`,
      ].join("\n"),
      errors: [{ messageId: "noRepeatedStringLiteral" }],
    },
    // A repeated column list / query across three functions: the drift hazard.
    {
      code: [
        `function read() { return \`SELECT ${COLUMNS} FROM candidates WHERE id = ?\`; }`,
        `function readAll() { return \`SELECT ${COLUMNS} FROM candidates WHERE id = ?\`; }`,
        `function readOne() { return \`SELECT ${COLUMNS} FROM candidates WHERE id = ?\`; }`,
      ].join("\n"),
      errors: [
        { messageId: "noRepeatedStringLiteral" },
        { messageId: "noRepeatedStringLiteral" },
      ],
    },
    // A repeated multi-line prompt template.
    {
      code: [
        "function a() { return 'You are a triage bot.\\nAnswer in one sentence.\\nBe terse.'; }",
        "function b() { return 'You are a triage bot.\\nAnswer in one sentence.\\nBe terse.'; }",
        "function c() { return 'You are a triage bot.\\nAnswer in one sentence.\\nBe terse.'; }",
      ].join("\n"),
      errors: [
        { messageId: "noRepeatedStringLiteral" },
        { messageId: "noRepeatedStringLiteral" },
      ],
    },
    // A repeated bare identifier (a constraint / index name reused across writes).
    {
      code: [
        "function a() { return 'github_commit_email_by_login_and_email_idx'; }",
        "function b() { return 'github_commit_email_by_login_and_email_idx'; }",
        "function c() { return 'github_commit_email_by_login_and_email_idx'; }",
      ].join("\n"),
      errors: [
        { messageId: "noRepeatedStringLiteral" },
        { messageId: "noRepeatedStringLiteral" },
      ],
    },
    // Class methods count as distinct scopes.
    {
      code: [
        "class Repo {",
        `  read() { return \`SELECT ${COLUMNS} FROM candidates WHERE id = ?\`; }`,
        `  readAgain() { return \`SELECT ${COLUMNS} FROM candidates WHERE id = ?\`; }`,
        `  readOnce() { return \`SELECT ${COLUMNS} FROM candidates WHERE id = ?\`; }`,
        "}",
      ].join("\n"),
      errors: [
        { messageId: "noRepeatedStringLiteral" },
        { messageId: "noRepeatedStringLiteral" },
      ],
    },
  ],
});
