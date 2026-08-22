import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule, { NO_REPEATED_STRING_LITERAL_DOCUMENTATION } from "../../src/rules/no-repeated-string-literal.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const RULE_TESTER = new RuleTester({
  languageOptions: {
    parser: tsParser,
  },
});

const COLUMNS = "id, ashby_candidate_id, dataset_id, status, expires_at";

RULE_TESTER.run("no-repeated-string-literal", rule, {
  valid: [
    { name: "accepts the documented shared constant", code: NO_REPEATED_STRING_LITERAL_DOCUMENTATION.examples[0].files[0].source },
    // Tagged templates are invocations whose tags define their meaning.
    {
      code: [
        'const a = js`export default function Component() {\n  return null;\n}`;',
        'function one() { return js`export default function Component() {\n  return null;\n}`; }',
        'function two() { return js`export default function Component() {\n  return null;\n}`; }',
      ].join("\n"),
    },
    // Styling tags are outside this rule's string-value contract.
    {
      code: [
        'const base = css`\n  min-width: min-content;\n  display: flex;\n`;',
        'function a() { return css`\n  min-width: min-content;\n  display: flex;\n`; }',
        'function b() { return css`\n  min-width: min-content;\n  display: flex;\n`; }',
      ].join("\n"),
    },
    // Equal prose can have separate intent and must remain local.
    {
      code: [
        "function a() { return 'the requested candidate could not be found here'; }",
        "function b() { return 'the requested candidate could not be found here'; }",
        "function c() { return 'the requested candidate could not be found here'; }",
      ].join("\n"),
    },
    // A leading slash does not make prose into a route template.
    {
      code: [
        "function a() { return '/api routes are intentionally described here for callers'; }",
        "function b() { return '/api routes are intentionally described here for callers'; }",
      ].join("\n"),
    },
    {
      name: "punctuation dividers are not route templates",
      code: [
        `function a() { return "${"/".repeat(45)}"; }`,
        `function b() { return "${"/".repeat(45)}"; }`,
      ].join("\n"),
    },
    // Lowercase SQL words in prose are not structured strings.
    {
      code: [
        "function a() { return 'pick the fields you want from the list of columns'; }",
        "function b() { return 'pick the fields you want from the list of columns'; }",
        "function c() { return 'pick the fields you want from the list of columns'; }",
      ].join("\n"),
    },
    // Repetition within one function remains local.
    {
      code: [
        "function only() {",
        `  const x = \`SELECT ${COLUMNS} FROM candidates\`;`,
        `  const y = \`SELECT ${COLUMNS} FROM candidates\`;`,
        "  return [x, y];",
        "}",
      ].join("\n"),
    },
    // Short structured strings remain local.
    {
      code: [
        "function a() { return 'SELECT id FROM runs'; }",
        "function b() { return 'SELECT id FROM runs'; }",
        "function c() { return 'SELECT id FROM runs'; }",
      ].join("\n"),
    },
    // Template literals with substitutions are fragments.
    {
      code: [
        `function a(t) { return \`SELECT ${COLUMNS} FROM \${t}\`; }`,
        `function b(t) { return \`SELECT ${COLUMNS} FROM \${t}\`; }`,
        `function c(t) { return \`SELECT ${COLUMNS} FROM \${t}\`; }`,
      ].join("\n"),
    },
    // An extracted constant has one source of truth.
    {
      code: [
        `const CANDIDATE_QUERY = \`SELECT ${COLUMNS} FROM candidates\`;`,
        "function a() { return CANDIDATE_QUERY; }",
        "function b() { return CANDIDATE_QUERY; }",
        "function c() { return CANDIDATE_QUERY; }",
      ].join("\n"),
    },
    // Test files repeat fixture payloads by design.
    {
      filename: "/repo/test/repo.test.ts",
      code: [
        `function a() { return \`SELECT ${COLUMNS} FROM candidates\`; }`,
        `function b() { return \`SELECT ${COLUMNS} FROM candidates\`; }`,
        `function c() { return \`SELECT ${COLUMNS} FROM candidates\`; }`,
      ].join("\n"),
    },
    // Hyphenated test filenames are also exempt.
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
    // Module scope does not count as a second function scope.
    {
      code: [
        `const query = \`SELECT ${COLUMNS} FROM candidates\`;`,
        `function read() { return \`SELECT ${COLUMNS} FROM candidates\`; }`,
      ].join("\n"),
    },
    // Module-loading sources are scaffolding, not reusable values.
    {
      code: [
        "function one() { return require('company.internal.adapters.payment_gateway'); }",
        "function two() { return require('company.internal.adapters.payment_gateway'); }",
        "async function three() { return import('company.internal.adapters.payment_gateway'); }",
        "async function four() { return import('company.internal.adapters.payment_gateway'); }",
      ].join("\n"),
    },
    // JSX attributes belong to styling and markup rules.
    {
      filename: "/repo/component.tsx",
      code: [
        'function One() { return <div data-query="SELECT id, status, created_at FROM candidates" />; }',
        'function Two() { return <div data-query="SELECT id, status, created_at FROM candidates" />; }',
      ].join("\n"),
    },
    // Quoted property keys describe an object/class shape; replacing them with
    // computed constants changes both readability and inferred types.
    {
      code: [
        "function one() { return { 'company.internal.payment_gateway.constraint': 1 }; }",
        "function two() { return { 'company.internal.payment_gateway.constraint': 2 }; }",
        "class Three { 'company.internal.payment_gateway.constraint' = 3; }",
      ].join("\n"),
    },
    {
      filename: "/repo/src/generated/queries.ts",
      code: [
        `function one() { return \`SELECT ${COLUMNS} FROM candidates\`; }`,
        `function two() { return \`SELECT ${COLUMNS} FROM candidates\`; }`,
      ].join("\n"),
    },
  ],
  invalid: [
    { name: "reports the documented repeated query", code: NO_REPEATED_STRING_LITERAL_DOCUMENTATION.examples[1].files[0].source, errors: [{ messageId: "noRepeatedStringLiteral" }] },
    // Two distinct functions is the only count threshold, matching SARJ024.
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
    // Dotted identifiers carry the same structural signal as snake_case names.
    {
      code: [
        "function a() { return 'company.internal.payment_gateway.constraint'; }",
        "function b() { return 'company.internal.payment_gateway.constraint'; }",
      ].join("\n"),
      errors: [{ messageId: "noRepeatedStringLiteral" }],
    },
    // Route templates are structured runtime values, not prose.
    {
      code: [
        "function memberships() { return '/api/v2/organizations/:organizationId/memberships'; }",
        "function replaceMemberships() { return '/api/v2/organizations/:organizationId/memberships'; }",
      ].join("\n"),
      errors: [{ messageId: "noRepeatedStringLiteral" }],
    },
    {
      name: "recognizes Next.js bracket route templates",
      code: [
        "function one() { return '/api/v2/organizations/[organizationId]/memberships'; }",
        "function two() { return '/api/v2/organizations/[organizationId]/memberships'; }",
      ].join("\n"),
      errors: [{ messageId: "noRepeatedStringLiteral" }],
    },
    // Function expressions and arrows are distinct enclosing scopes.
    {
      code: [
        `const read = function () { return \`SELECT ${COLUMNS} FROM candidates\`; };`,
        `const readAgain = () => \`SELECT ${COLUMNS} FROM candidates\`;`,
      ].join("\n"),
      errors: [{ messageId: "noRepeatedStringLiteral" }],
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
