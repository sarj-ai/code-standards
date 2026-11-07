// vitest: shared-module-graph
import ts from "typescript";
import { expect, it } from "vitest";

import longRule from "../../src/rules/no-long-comment.js";
import rule from "../../src/rules/excessive-commentary.js";
import { ruleTester } from "./_tester.js";

const RULE_TESTER = ruleTester();

const ADAPTER_NARRATION = [
  "/**",
  " * This file is the seam between the draft and backend models.",
  " * Everything above it uses the local application representation.",
  " * Everything below it uses a separately mirrored wire representation.",
  " * Field names use the API shape while the draft uses another shape.",
  " * This module translates every field between those representations.",
  " * The backend models changed several times during early development.",
  " * Each historical change required another edit in this adapter file.",
  " * The write half previously assembled several resources in one payload.",
  " * It now saves those resources separately through their own routes.",
  " * Clear contract types and generated clients should express this boundary.",
  " */",
  "import type { Draft } from './draft';",
].join("\n");
const PROTOCOL_CONSTRAINT = [
  "// Legacy clients send `execution_phase` until API-812 is retired.",
  "// Keep conversion in GeneratedClientAdapter.",
  "export const phase = raw.execution_phase;",
].join("\n");
const DECORATED = [
  "/**",
  " * This file is the seam between the local draft and backend models.",
  " * Everything above it uses the local application representation for each record.",
  " * Everything below it uses the separate wire representation for each record.",
  " * This module translates fields between those two representations during each request.",
  " * ++++++++",
  " * The backend models changed several times during early implementation work.",
  " * Each historical change required another edit in this local adapter module.",
  " * The write half previously assembled several records together in one operation.",
  " * It now saves each record separately through the route that owns it.",
  " * Clear contract types should express this boundary through the actual declarations.",
  " */",
  "const value = 1;",
].join("\n");
const FIXED_DECORATION = DECORATED.replace("++++++++", "");

RULE_TESTER.run("excessive-commentary", rule, {
  valid: [
    PROTOCOL_CONSTRAINT,
    "// Short rationale remains local.\nconst value = 1;",
    [
      "// First constraint.",
      "// - one mode",
      "// - another mode",
      "// - fallback mode",
      "const value = 1;",
    ].join("\n"),
    [
      "// Keep `traceparent` because RFC-812 requires propagation.",
      "// The timeout is 10 ms.",
      "// GeneratedClientAdapter owns the conversion.",
      "// Remove this with API-901.",
      "const value = 1;",
    ].join("\n"),
    [
      "// Keep this ordering because cleanup can outlive the command.",
      "// Otherwise a background task can retain the temporary directory.",
      "// The cleanup must never mask the command outcome.",
      "// This invariant also prevents a retry race.",
      "const value = 1;",
    ].join("\n"),
    {
      filename: "src/generated/client.ts",
      code: Array.from({ length: 8 }, (_, i) => `// Narrative implementation sentence number ${i}.`).join("\n"),
    },
    "/** Public API documentation remains owned by JSDoc rules. It may contain several lines. It remains typed. It stays stable. */\nexport interface Result { ok: boolean; }",
    [
      "/**",
      " * Public response shape consumed by callers across the package boundary.",
      " * The first field records whether parsing succeeded for the request.",
      " * The second field carries the parsed value when parsing succeeds.",
      " * The third field carries structured issues when parsing fails.",
      " * Callers use the discriminant before accessing either branch value.",
      " * This documentation describes the stable public contract for consumers.",
      " * It intentionally remains beside the exported interface declaration.",
      " * Package documentation links directly to this type for reference.",
      " * Changing the interface requires a separately reviewed compatibility change.",
      " * The long typed API documentation is therefore not implementation narration.",
      " */",
      "export interface ParseResult { ok: boolean; value?: string; issues?: string[] }",
    ].join("\n"),
    [
      "/**",
      " * Server side of a room-scoped event channel with a global sequence.",
      " * Every event is tagged with a room before browsers poll for updates.",
      " * Filtering preserves monotonic order while allowing harmless gaps.",
      " * A per-room counter requires a read followed by a racing write.",
      " * Server-side filtering prevents foreign traffic from blocking cursors.",
      " * The sequence is a durable protocol invariant shared with every client.",
      " * Clients advance only from identifiers present in returned event arrays.",
      " * Failed cosmetic writes never break the conversation-driving request.",
      " * These constraints are not apparent from one declaration in isolation.",
      " * Keep the protocol explanation beside the server implementation.",
      " */",
      "export const channel = createChannel();",
    ].join("\n"),
  ],
  invalid: [
    {
      name: "removes decorative volume while retaining every narrative byte",
      code: DECORATED,
      output: FIXED_DECORATION,
      errors: [{ messageId: "excessive" }],
    },
    {
      name: "preserves CRLF and comment markers",
      code: DECORATED.replaceAll("\n", "\r\n"),
      output: FIXED_DECORATION.replaceAll("\n", "\r\n"),
      errors: [{ messageId: "excessive" }],
    },
    {
      name: "retains Unicode prose before UTF16 decoration ranges",
      code: DECORATED.replace("local draft", "local draft 𝄞"),
      output: FIXED_DECORATION.replace("local draft", "local draft 𝄞"),
      errors: [{ messageId: "excessive" }],
    },
    {
      name: "removes all adjacent decorative volume atomically",
      code: DECORATED.replace(" * ++++++++\n", " * ++++++++\n * ++++++++\n"),
      output: FIXED_DECORATION.replace(" * \n", " * \n * \n"),
      errors: [{ messageId: "excessive" }],
    },
    ...["prompt", "expected", "password", "diagram", "signature"].map((context) => ({
      name: `preserves ${context} contexts`,
      code: DECORATED.replace("local draft", `local ${context}`),
      output: null,
      errors: [{ messageId: "excessive" as const }],
    })),
    {
      name: "retains decoration when the native volume finding would remain",
      code: DECORATED.replace(" */", " * The adapter keeps every stage close to the declarations it describes.\n */"),
      output: null,
      errors: [{ messageId: "excessive" }],
    },
    {
      name: "preserves Markdown structure",
      code: DECORATED.replace(" * ++++++++", " * ----\n * ++++++++"),
      output: null,
      errors: [{ messageId: "excessive" }],
    },
    {
      name: "preserves fenced literal contexts",
      code: DECORATED.replace(" * ++++++++", " * ~~~\n * ++++++++\n * ~~~"),
      output: null,
      errors: [{ messageId: "excessive" }],
    },
    {
      name: "preserves indented examples",
      code: DECORATED.replace(" * This file", " *     This file"),
      output: null,
      errors: [{ messageId: "excessive" }],
    },
    {
      code: ADAPTER_NARRATION,
      errors: [{ messageId: "excessive" }],
    },
    {
      code: [
        "/**",
        " * This file is the seam between the draft and the backend models.",
        " * Everything above it works in a local application representation.",
        " * Everything below it works in a separately mirrored wire representation.",
        " * The backend models have changed several times during development.",
        " * Each historical change required another edit in this adapter file.",
        " * The write half previously assembled several resources in one payload.",
        " * It now creates the first resource before saving the remaining sections.",
        " * That history explains several helpers that still live in this module.",
        " * The next declarations implement the conversion described by this paragraph.",
        " * Clear contract types and focused adapters should express that structure instead.",
        " */",
        "import type { Draft } from './draft';",
      ].join("\n"),
      errors: [{ messageId: "excessive" }],
    },
  ],
});

const ENDINGS = ["\n", "\r\n"];
const CONVERGED = ENDINGS.map((ending) => ({
  name: `converges with both comment rules and ${JSON.stringify(ending)} (second Linter.verifyAndFix pass)`,
  filename: "src/adapter.ts",
  code: FIXED_DECORATION.replaceAll("\n", ending),
}));
const PROTECTED = [
  DECORATED.replace("local draft", "local draft @customTag"),
  DECORATED.replace("local draft", "local copyright draft"),
  DECORATED.replace("local draft", "local draft licensed under local terms"),
];
const PROTECTED_REPORTED = [
  DECORATED.replace(" * ++++++++", " *     ++++++++"),
  `// @ts-ignore\n${DECORATED}`,
];

RULE_TESTER.run("excessive-commentary (Linter passes)", rule, {
  valid: [
    ...CONVERGED,
    ...PROTECTED.map((code, index) => ({ name: `preserves protected documentation ${index}`, filename: "src/adapter.ts", code })),
  ],
  invalid: [
    ...ENDINGS.map((ending) => ({
      name: `retains emitted JavaScript and converges with both comment rules and ${JSON.stringify(ending)}`,
      filename: "src/adapter.ts",
      code: DECORATED.replaceAll("\n", ending),
      output: FIXED_DECORATION.replaceAll("\n", ending),
      errors: [{ messageId: "excessive" }],
    })),
    ...PROTECTED_REPORTED.map((code, index) => ({
      name: `preserves protected documentation and next-line directive ownership ${index}`,
      filename: "src/adapter.ts",
      code,
      output: null,
      errors: [{ messageId: "excessive" }],
    })),
  ],
});

RULE_TESTER.run("no-long-comment beside excessive-commentary (Linter passes)", longRule, {
  valid: [
    ...CONVERGED,
    ...PROTECTED.map((code, index) => ({ name: `preserves protected documentation ${index}`, filename: "src/adapter.ts", code })),
  ],
  invalid: PROTECTED_REPORTED.map((code, index) => ({
    name: `preserves protected documentation and next-line directive ownership ${index}`,
    filename: "src/adapter.ts",
    code,
    output: null,
    errors: [{ messageId: "tooLong" }],
  })),
});

it.each(ENDINGS)("fix retains emitted JavaScript with %j", (ending) => {
  const options = { compilerOptions: { target: ts.ScriptTarget.ESNext, module: ts.ModuleKind.ESNext, removeComments: true } };
  expect(ts.transpileModule(FIXED_DECORATION.replaceAll("\n", ending), options).outputText)
    .toBe(ts.transpileModule(DECORATED.replaceAll("\n", ending), options).outputText);
});
