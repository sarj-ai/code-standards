// vitest: shared-module-graph
import rule from "../../src/rules/no-repeated-string-literal.js";
import { ruleTester } from "./_tester.js";

const NO_REPEATED_STRING_LITERAL_DOCUMENTATION = {
  summary:
    "Disallow a long structured string literal repeated across functions; the copies drift when one is edited. Extract a module-level constant.",
  rationale:
    "Independent copies of a query, route template, or identifier can diverge and silently change behavior.",
  remediation:
    "Extract the repeated value to one module-level constant and reference it from each function.",
  category: "maintainability",
  autofix: "safe",
  limitations: [
    "Test files, short strings, prose, substitutions, module sources, JSX attributes, and repetition within one function are excluded.",
    "Automatic edits only reuse an already authored and already read private const primitive string declared first in an otherwise declaration-only explicit module. All ordinary zero-argument functions must directly return that constant or the identical literal. Imports, comments, annotations on the constant, other statements or uses, callbacks, shadowing, generics and initialization effects remain manual; no domain name is invented.",
  ],
  examples: [
    {
      id: "shared-constant",
      title: "Share one structured value",
      outcome: "no-match",
      files: [
        {
          path: "src/queries.ts",
          source:
            "const QUERY = 'SELECT id, status, created_at FROM candidates';\nfunction one() { return QUERY; }\nfunction two() { return QUERY; }",
        },
      ],
      focusPath: "src/queries.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "repeated-query",
      title: "Do not copy a structured value across functions",
      outcome: "match",
      files: [
        {
          path: "src/queries.ts",
          source:
            "function one() { return 'SELECT id, status, created_at FROM candidates'; }\nfunction two() { return 'SELECT id, status, created_at FROM candidates'; }",
        },
      ],
      focusPath: "src/queries.ts",
      expectedCount: 1,
      public: true,
    },
    {
      id: "safe-autofix",
      title: "Reuse the existing primitive constant",
      outcome: "match",
      files: [
        {
          path: "src/queries.ts",
          source:
            "const QUERY = 'SELECT id, status, created_at FROM candidates';\nexport function current() { return QUERY; }\nexport function one() { return 'SELECT id, status, created_at FROM candidates'; }\nexport function two() { return 'SELECT id, status, created_at FROM candidates'; }",
        },
      ],
      fixedFiles: [
        {
          path: "src/queries.ts",
          source:
            "const QUERY = 'SELECT id, status, created_at FROM candidates';\nexport function current() { return QUERY; }\nexport function one() { return QUERY; }\nexport function two() { return QUERY; }",
        },
      ],
      focusPath: "src/queries.ts",
      expectedCount: 2,
    },
  ],
} as const;

const RULE_TESTER = ruleTester();

const COLUMNS = "id, ashby_candidate_id, dataset_id, status, expires_at";

RULE_TESTER.run("no-repeated-string-literal", rule, {
  valid: [
    {
      name: "preserves repeated multiline prompt prose",
      code: "function a() { return 'You are a triage bot.\\nAnswer in one sentence.\\nBe terse.'; } function b() { return 'You are a triage bot.\\nAnswer in one sentence.\\nBe terse.'; }",
    },
    {
      name: "newlines do not turn prose into structured identifiers",
      code: "function a() { return `Please check your details.\nThen retry this operation.`; } function b() { return `Please check your details.\nThen retry this operation.`; }",
    },
    {
      name: "expression-wrapped JSX attributes remain styling scaffolding",
      filename: "/repo/src/view.tsx",
      code: "function A() { return <div id={'a_long_structured_identifier_that_is_more_than_forty_characters'} />; } function B() { return <div id={'a_long_structured_identifier_that_is_more_than_forty_characters'} />; }",
    },
    {
      name: "accepts the documented shared constant",
      code: NO_REPEATED_STRING_LITERAL_DOCUMENTATION.examples[0].files[0]
        .source,
    },

    {
      code: [
        "const a = js`export default function Component() {\n  return null;\n}`;",
        "function one() { return js`export default function Component() {\n  return null;\n}`; }",
        "function two() { return js`export default function Component() {\n  return null;\n}`; }",
      ].join("\n"),
    },

    {
      code: [
        "const base = css`\n  min-width: min-content;\n  display: flex;\n`;",
        "function a() { return css`\n  min-width: min-content;\n  display: flex;\n`; }",
        "function b() { return css`\n  min-width: min-content;\n  display: flex;\n`; }",
      ].join("\n"),
    },

    {
      code: [
        "function a() { return 'the requested candidate could not be found here'; }",
        "function b() { return 'the requested candidate could not be found here'; }",
        "function c() { return 'the requested candidate could not be found here'; }",
      ].join("\n"),
    },

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

    {
      code: [
        "function a() { return 'pick the fields you want from the list of columns'; }",
        "function b() { return 'pick the fields you want from the list of columns'; }",
        "function c() { return 'pick the fields you want from the list of columns'; }",
      ].join("\n"),
    },

    {
      code: [
        "function only() {",
        `  const x = \`SELECT ${COLUMNS} FROM candidates\`;`,
        `  const y = \`SELECT ${COLUMNS} FROM candidates\`;`,
        "  return [x, y];",
        "}",
      ].join("\n"),
    },

    {
      code: [
        "function a() { return 'SELECT id FROM runs'; }",
        "function b() { return 'SELECT id FROM runs'; }",
        "function c() { return 'SELECT id FROM runs'; }",
      ].join("\n"),
    },

    {
      code: [
        `function a(t) { return \`SELECT ${COLUMNS} FROM \${t}\`; }`,
        `function b(t) { return \`SELECT ${COLUMNS} FROM \${t}\`; }`,
        `function c(t) { return \`SELECT ${COLUMNS} FROM \${t}\`; }`,
      ].join("\n"),
    },

    {
      code: [
        `const CANDIDATE_QUERY = \`SELECT ${COLUMNS} FROM candidates\`;`,
        "function a() { return CANDIDATE_QUERY; }",
        "function b() { return CANDIDATE_QUERY; }",
        "function c() { return CANDIDATE_QUERY; }",
      ].join("\n"),
    },

    {
      filename: "/repo/test/repo.test.ts",
      code: [
        `function a() { return \`SELECT ${COLUMNS} FROM candidates\`; }`,
        `function b() { return \`SELECT ${COLUMNS} FROM candidates\`; }`,
        `function c() { return \`SELECT ${COLUMNS} FROM candidates\`; }`,
      ].join("\n"),
    },

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

    {
      code: [
        `const query = \`SELECT ${COLUMNS} FROM candidates\`;`,
        `function read() { return \`SELECT ${COLUMNS} FROM candidates\`; }`,
      ].join("\n"),
    },

    {
      code: [
        "function one() { return require('company.internal.adapters.payment_gateway'); }",
        "function two() { return require('company.internal.adapters.payment_gateway'); }",
        "async function three() { return import('company.internal.adapters.payment_gateway'); }",
        "async function four() { return import('company.internal.adapters.payment_gateway'); }",
      ].join("\n"),
    },

    {
      filename: "/repo/component.tsx",
      code: [
        'function One() { return <div data-query="SELECT id, status, created_at FROM candidates" />; }',
        'function Two() { return <div data-query="SELECT id, status, created_at FROM candidates" />; }',
      ].join("\n"),
    },

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
    {
      name: "reuses the already read primitive constant",
      code: "const QUERY = 'SELECT id, status, created_at FROM candidates'; export function current() { return QUERY; } export function one() { return 'SELECT id, status, created_at FROM candidates'; } export function two() { return 'SELECT id, status, created_at FROM candidates'; }",
      output:
        "const QUERY = 'SELECT id, status, created_at FROM candidates'; export function current() { return QUERY; } export function one() { return QUERY; } export function two() { return QUERY; }",
      errors: [
        { messageId: "noRepeatedStringLiteral" },
        { messageId: "noRepeatedStringLiteral" },
      ],
    },
    {
      name: "preserves CRLF while reusing an existing constant",
      code: "const QUERY = 'SELECT id, status, created_at FROM candidates';\r\nexport function current() { return QUERY; } export function one() { return 'SELECT id, status, created_at FROM candidates'; } export function two() { return 'SELECT id, status, created_at FROM candidates'; }",
      output:
        "const QUERY = 'SELECT id, status, created_at FROM candidates';\r\nexport function current() { return QUERY; } export function one() { return QUERY; } export function two() { return QUERY; }",
      errors: [
        { messageId: "noRepeatedStringLiteral" },
        { messageId: "noRepeatedStringLiteral" },
      ],
    },
    {
      name: "retains imports",
      code: "import \"setup\"; const QUERY = 'SELECT id, status, created_at FROM candidates'; export function current() { return QUERY; } export function one() { return 'SELECT id, status, created_at FROM candidates'; } export function two() { return 'SELECT id, status, created_at FROM candidates'; }",
      output: null,
      errors: [
        { messageId: "noRepeatedStringLiteral" },
        { messageId: "noRepeatedStringLiteral" },
      ],
    },
    {
      name: "retains comments",
      code: "/* independent contract */ const QUERY = 'SELECT id, status, created_at FROM candidates'; export function current() { return QUERY; } export function one() { return 'SELECT id, status, created_at FROM candidates'; } export function two() { return 'SELECT id, status, created_at FROM candidates'; }",
      output: null,
      errors: [
        { messageId: "noRepeatedStringLiteral" },
        { messageId: "noRepeatedStringLiteral" },
      ],
    },
    {
      name: "retains annotated canonical constants",
      code: "const QUERY: string = 'SELECT id, status, created_at FROM candidates'; export function current() { return QUERY; } export function one() { return 'SELECT id, status, created_at FROM candidates'; } export function two() { return 'SELECT id, status, created_at FROM candidates'; }",
      output: null,
      errors: [
        { messageId: "noRepeatedStringLiteral" },
        { messageId: "noRepeatedStringLiteral" },
      ],
    },
    {
      name: "retains mutable canonical constants",
      code: "let QUERY = 'SELECT id, status, created_at FROM candidates'; export function current() { return QUERY; } export function one() { return 'SELECT id, status, created_at FROM candidates'; } export function two() { return 'SELECT id, status, created_at FROM candidates'; }",
      output: null,
      errors: [
        { messageId: "noRepeatedStringLiteral" },
        { messageId: "noRepeatedStringLiteral" },
      ],
    },
    {
      name: "requires an existing value reader",
      code: "const QUERY = 'SELECT id, status, created_at FROM candidates'; export function current() { return 'SELECT id, status, created_at FROM candidates'; } export function one() { return 'SELECT id, status, created_at FROM candidates'; } export function two() { return 'SELECT id, status, created_at FROM candidates'; }",
      output: null,
      errors: [
        { messageId: "noRepeatedStringLiteral" },
        { messageId: "noRepeatedStringLiteral" },
        { messageId: "noRepeatedStringLiteral" },
      ],
    },
    {
      name: "retains other initialization effects",
      code: "const QUERY = 'SELECT id, status, created_at FROM candidates'; export function current() { return QUERY; } export function one() { return 'SELECT id, status, created_at FROM candidates'; } export function two() { return 'SELECT id, status, created_at FROM candidates'; } observe();",
      output: null,
      errors: [
        { messageId: "noRepeatedStringLiteral" },
        { messageId: "noRepeatedStringLiteral" },
      ],
    },
    {
      name: "retains function argument shadowing",
      code: "const QUERY = 'SELECT id, status, created_at FROM candidates'; export function current() { return QUERY; } export function one(QUERY: string) { return 'SELECT id, status, created_at FROM candidates'; } export function two() { return 'SELECT id, status, created_at FROM candidates'; }",
      output: null,
      errors: [
        { messageId: "noRepeatedStringLiteral" },
        { messageId: "noRepeatedStringLiteral" },
      ],
    },
    {
      name: "retains callback observations",
      code: "const QUERY = 'SELECT id, status, created_at FROM candidates'; export function current() { consume(QUERY); return QUERY; } export function one() { return 'SELECT id, status, created_at FROM candidates'; } export function two() { return 'SELECT id, status, created_at FROM candidates'; }",
      output: null,
      errors: [
        { messageId: "noRepeatedStringLiteral" },
        { messageId: "noRepeatedStringLiteral" },
      ],
    },
    {
      name: "retains return literal assertions",
      code: "const QUERY = 'SELECT id, status, created_at FROM candidates'; export function current() { return QUERY; } export function one() { return 'SELECT id, status, created_at FROM candidates' as const; } export function two() { return 'SELECT id, status, created_at FROM candidates' as const; }",
      output: null,
      errors: [
        { messageId: "noRepeatedStringLiteral" },
        { messageId: "noRepeatedStringLiteral" },
      ],
    },
    {
      name: "retains exported canonical value contracts",
      code: "export const QUERY = 'SELECT id, status, created_at FROM candidates'; export function current() { return QUERY; } export function one() { return 'SELECT id, status, created_at FROM candidates'; } export function two() { return 'SELECT id, status, created_at FROM candidates'; }",
      output: null,
      errors: [
        { messageId: "noRepeatedStringLiteral" },
        { messageId: "noRepeatedStringLiteral" },
      ],
    },
    {
      name: "retains alias ambiguity",
      code: "const QUERY = 'SELECT id, status, created_at FROM candidates'; const OTHER = 'SELECT id, status, created_at FROM candidates'; export function current() { return QUERY; } export function one() { return 'SELECT id, status, created_at FROM candidates'; } export function two() { return 'SELECT id, status, created_at FROM candidates'; }",
      output: null,
      errors: [
        { messageId: "noRepeatedStringLiteral" },
        { messageId: "noRepeatedStringLiteral" },
        { messageId: "noRepeatedStringLiteral" },
      ],
    },
    {
      name: "reports the documented repeated query",
      code: NO_REPEATED_STRING_LITERAL_DOCUMENTATION.examples[1].files[0]
        .source,
      errors: [{ messageId: "noRepeatedStringLiteral" }],
    },

    {
      code: [
        `function submitFinancialInfo() { return \`SELECT ${COLUMNS} FROM candidates\`; }`,
        `function submitLegalInfo() { return \`SELECT ${COLUMNS} FROM candidates\`; }`,
      ].join("\n"),
      errors: [{ messageId: "noRepeatedStringLiteral" }],
    },

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

    {
      code: [
        "function a() { return 'company.internal.payment_gateway.constraint'; }",
        "function b() { return 'company.internal.payment_gateway.constraint'; }",
      ].join("\n"),
      errors: [{ messageId: "noRepeatedStringLiteral" }],
    },

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

    {
      code: [
        `const read = function () { return \`SELECT ${COLUMNS} FROM candidates\`; };`,
        `const readAgain = () => \`SELECT ${COLUMNS} FROM candidates\`;`,
      ].join("\n"),
      errors: [{ messageId: "noRepeatedStringLiteral" }],
    },

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
