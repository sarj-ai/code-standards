import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule, { EXCESSIVE_COMMENTARY_DOCUMENTATION } from "../../src/rules/excessive-commentary.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

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
  ],
  invalid: [
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
    {
      code: [
        "/* This block narrates the implementation in considerable detail.",
        "It explains the first internal step without adding a constraint.",
        "It explains the second internal step without adding a contract.",
        "It also explains the return even though the code already does so. */",
        "return buildResult();",
      ].join("\n"),
      errors: [{ messageId: "excessive" }],
    },
  ],
});
