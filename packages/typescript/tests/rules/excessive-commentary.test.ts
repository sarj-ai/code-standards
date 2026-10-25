// vitest: shared-module-graph
import { RuleTester } from "@typescript-eslint/rule-tester";
import * as parser from "@typescript-eslint/parser";
import { Linter } from "eslint";
import ts from "typescript";
import { afterAll, describe, expect, it } from "vitest";

import rule, { EXCESSIVE_COMMENTARY_DOCUMENTATION } from "../../src/rules/excessive-commentary.js";
import longRule from "../../src/rules/no-long-comment.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const DECORATED = EXCESSIVE_COMMENTARY_DOCUMENTATION.examples[2].files[0].source;
const FIXED_DECORATION = EXCESSIVE_COMMENTARY_DOCUMENTATION.examples[2].fixedFiles[0].source;

new RuleTester().run("excessive-commentary", rule, {
  valid: [
    EXCESSIVE_COMMENTARY_DOCUMENTATION.examples[1].files[0].source,
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
      code: EXCESSIVE_COMMENTARY_DOCUMENTATION.examples[0].files[0].source,
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

function apply(source: string): ReturnType<Linter["verifyAndFix"]> {
  return new Linter().verifyAndFix(source, [{
    files: ["**/*.ts"],
    languageOptions: { parser },
    plugins: { audit: { rules: { excessive: rule, long: longRule } } },
    rules: { "audit/excessive": "error", "audit/long": "error" },
  }], { filename: "src/adapter.ts" });
}

it.each(["\n", "\r\n"])("retains emitted JavaScript and converges with both comment rules and %j", (ending) => {
  const source = DECORATED.replaceAll("\n", ending);
  const first = apply(source);
  expect(first.fixed).toBe(true);
  expect(first.messages).toEqual([]);
  expect(first.output).toBe(FIXED_DECORATION.replaceAll("\n", ending));
  const second = apply(first.output);
  expect(second.fixed).toBe(false);
  expect(second.output).toBe(first.output);
  expect(second.messages).toEqual([]);
  const options = { compilerOptions: { target: ts.ScriptTarget.ESNext, module: ts.ModuleKind.ESNext, removeComments: true } };
  expect(ts.transpileModule(first.output, options).outputText).toBe(ts.transpileModule(source, options).outputText);
});

it.each([
  DECORATED.replace("local draft", "local draft @customTag"),
  DECORATED.replace("local draft", "local copyright draft"),
  DECORATED.replace("local draft", "local draft licensed under local terms"),
  DECORATED.replace(" * ++++++++", " *     ++++++++"),
  `// @ts-ignore\n${DECORATED}`,
])("preserves protected documentation and next-line directive ownership", (source) => {
  const result = apply(source);
  expect(result.fixed).toBe(false);
  expect(result.output).toBe(source);
});
