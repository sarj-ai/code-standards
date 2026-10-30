// vitest: shared-module-graph
import * as parser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule, { NO_TEST_COMMENTS_DOCUMENTATION } from "../../src/rules/no-test-comments.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;
const TESTER = new RuleTester({ languageOptions: { parser }, defaultFilenames: { ts: "src/request.test.ts", tsx: "src/request.test.tsx" } });

TESTER.run("no-test-comments", rule, {
  valid: [
    NO_TEST_COMMENTS_DOCUMENTATION.examples[1].files[0].source,
    { name: "production prose", filename: "src/request.ts", code: "// Preserve the wire contract\nconst value = 1;" },
    { name: "production implementation with ambiguous basename", filename: "src/rules/source-coupled-test.ts", code: "// This module implements a test-quality rule\nexport const value = 1;" },
    { name: "production token validation in integration directory", filename: "products/platform/apps/web/src/lib/integration/token-validation.ts", code: "export const token = source; // Preserve the source token for validation\n" },
    { name: "production adapter in e2e directory", filename: "src/e2e/adapter.ts", code: "// Preserve the external adapter contract\nexport const adapter = source;" },
    { name: "type-only framework declaration does not claim integration ownership", filename: "src/integration/context.ts", code: "import type { TestContext } from 'vitest';\n// Preserve the public context contract\nexport type Context = TestContext;" },
    { name: "type-only framework specifier does not claim e2e ownership", filename: "src/e2e/context.ts", code: "import { type TestContext } from 'vitest';\n// Preserve the public context contract\nexport type Context = TestContext;" },
    { name: "string contents", code: "const source = '// comments remain literal fixture data';" },
    { name: "template contents", code: "const source = `/* comments remain fixture data */`;" },
    { name: "scanner pragma string stays literal", code: "const source = '// pragma: allowlist secret';" },
    ...[
      "// pragma: allowlist secret",
      "//pragma:allowlist-secret",
      "// pragma: whitelist secret",
      "// pragma: whitelist-secret -- fixture value",
      "// pragma: allowlist secrets retain the native suffix grammar",
      "/* pragma: allowlist secret */",
      "/* pragma: whitelist-secret -- fixture value */",
      "const value = 1; // pragma: allowlist secret -- fixture value",
      "const value = 1; /* pragma: allowlist-secret -- fixture value */",
      "// context # pragma: allowlist secret -- fixture value",
      "// context ' pragma: whitelist-secret",
      "// context -- pragma: allowlist secret",
      "// context <!-- pragma: allowlist secret",
      "// context <!--#\tpragma: allowlist-secret -->",
      "/* context\n# pragma: allowlist secret\n*/",
      "// pragma: allowlist nextline secret\nconst value = 1;",
      "\t//pragma:allowlist-nextline-secret -- fixture value\nconst value = 1;",
      "/* pragma: allowlist-nextline secret -- fixture value */\nconst value = 1;",
      "/* pragma: allowlist secret\u2028fixture rationale */",
      "/* pragma: allowlist secret\u2029fixture rationale */",
      "/* pragma: allowlist secret */\u2028",
      "// context /* pragma: allowlist secret */\u0085",
      "// pragma: allowlist-nextline-secret\rconst value = 1;",
      "// pragma: allowlist-nextline-secret\r\nconst value = 1;",
    ].map(code => ({ name: `retains executable scanner pragma ${code}`, code })),
    { name: "complete contiguous legal notice", code: "// MIT License\n// Copyright 2026 Example\n// Permission is hereby granted to reuse this source.\nconst value = 1;" },
    { name: "JavaScript type contract", filename: "tests/request.test.js", code: "/** @type {string} */\nconst value = 'request';" },
    { name: "generated artifact", filename: "src/generated/request.test.ts", code: "// Test explanation\nexpect(run()).toBe(true);" },
    ...[
      "// vitest: shared-module-graph", "// @ts-expect-error -- malformed input exercises validation",
      "/* v8 ignore next */", "/* istanbul ignore next */", "/* eslint no-console: 'error' */",
      "/* Copyright 2026 Example */", "/* SPDX-License-Identifier: MIT */", "/// <reference types='node' />",
      "/*#__PURE__*/", "// prettier-ignore", "// @vitest-environment node",
    ].map(code => ({ name: `retains directive ${code}`, code })),
    { name: "local suppression", code: "// eslint-disable-next-line @rule-tester/no-test-comments -- legal review requires this exact rationale\n// Retained contractual explanation\nexpect(run()).toBe(true);" },
  ],
  invalid: [
    { name: "standalone line", code: "// Check the value\nexpect(value).toBe(1);", output: "\nexpect(value).toBe(1);", errors: [{ messageId: "testComment" }] },
    ...[
      "// Pragma: allowlist secret",
      "// pragma: Allowlist secret",
      "// pragma : allowlist secret",
      "// pragma:  allowlist secret",
      "// pragma:\tallowlist secret",
      "//\tpragma: allowlist secret",
      "// pragma: allowlist  secret",
      "// pragma: allowlist--secret",
      "// context pragma: allowlist secret",
      "// pragma: whitelist-nextline-secret",
      "// context # pragma: allowlist-nextline-secret",
      "// context <!--\tpragma: allowlist secret",
      "// pragma: this is ordinary commentary",
    ].map(code => ({ name: `rejects non-executable scanner prose ${code}`, code: `${code}\n`, output: "\n", errors: [{ messageId: "testComment" as const }] })),
    { name: "inline nextline pragma is not executable", code: "const value = 1; // pragma: allowlist nextline secret\n", output: "const value = 1;\n", errors: [{ messageId: "testComment" }] },
    { name: "block-interior prose lacks a native delimiter", code: "/*\n * pragma: allowlist secret\n */", output: "\n\n", errors: [{ messageId: "testComment" }] },
    { name: "nextline block retains raw trailing Unicode line separator", code: "/* pragma: allowlist-nextline-secret */\u2028\nconst value = 1;", output: "\u2028\nconst value = 1;", errors: [{ messageId: "testComment" }] },
    { name: "Python rstrip does not remove a trailing BOM", code: "// context /* pragma: allowlist secret */\uFEFF\n", output: "\n", errors: [{ messageId: "testComment" }] },
    { name: "Unicode separator does not hide code before a native nextline pragma", code: "const value = 1;\u2028// pragma: allowlist-nextline-secret\n", output: "const value = 1;\u2028\n", errors: [{ messageId: "testComment" }] },
    { name: "same-line block pragma requires the native physical-line ending", code: "const value = 1; /* pragma: allowlist secret */ value++;", output: "const value = 1;  value++;", errors: [{ messageId: "testComment" }] },
    { name: "pragma in a string does not exempt a separate comment", code: "const source = '// pragma: allowlist secret'; // Ordinary prose\n", output: "const source = '// pragma: allowlist secret';\n", errors: [{ messageId: "testComment" }] },
    { name: "pragma block does not exempt a separate ordinary block", code: "/* pragma: allowlist secret */ /* Ordinary prose */", output: "/* pragma: allowlist secret */", errors: [{ messageId: "testComment" }] },
    { name: "later pragma does not exempt an earlier ordinary block", code: "/* Ordinary pragma: prose */ /* pragma: allowlist secret */", output: " /* pragma: allowlist secret */", errors: [{ messageId: "testComment" }] },
    { name: "fix keeps the nextline pragma attached to the same physical target", code: "// Ordinary prose\n// pragma: allowlist-nextline-secret -- fixture value\nconst value = 1; // Ordinary prose\n", output: "\n// pragma: allowlist-nextline-secret -- fixture value\nconst value = 1;\n", errors: [{ messageId: "testComment" }, { messageId: "testComment" }] },
    { name: "inline block keeps token boundary", code: "const value = left/* test explanation */+right;", output: "const value = left +right;", errors: [{ messageId: "testComment" }] },
    { name: "multiline block preserves ASI", code: "function f() { return/* explain\nwhy */value; }", output: "function f() { return\nvalue; }", errors: [{ messageId: "testComment" }] },
    { name: "test fixture path", filename: "tests/fixtures/request.ts", code: "// Explain\nconst value = 1;", output: "\nconst value = 1;", errors: [{ messageId: "testComment" }] },
    ...["src/request.integration.ts", "src/request.e2e.ts", "src/integration/request.test.ts", "src/e2e/request.spec.ts", "tests/integration/request.ts", "test/e2e/request.ts", "__tests__/integration/request.ts", "__fixtures__/integration/request.ts"].map(filename => ({ name: `explicit test ownership ${filename}`, filename, code: "// Explain\nconst value = 1;", output: "\nconst value = 1;", errors: [{ messageId: "testComment" as const }] })),
    { name: "integration directory with runtime runner import", filename: "src/integration/request.ts", code: "import { test } from 'vitest';\n// Check the request\ntest('request', run);", output: "import { test } from 'vitest';\n\ntest('request', run);", errors: [{ messageId: "testComment" }] },
    { name: "e2e directory with side-effect runner import", filename: "src/e2e/setup.ts", code: "import '@playwright/test';\n// Configure the test runtime\nconfigure();", output: "import '@playwright/test';\n\nconfigure();", errors: [{ messageId: "testComment" }] },
    { name: "trailing comment removes adjacent padding", code: "expect(value).toBe(1);  // Check the value\n", output: "expect(value).toBe(1);\n", errors: [{ messageId: "testComment" }] },
    { name: "ambiguous test basename with actual runner import", filename: "src/request-test.ts", code: "import { test } from 'vitest';\n// Check the request\ntest('request', run);", output: "import { test } from 'vitest';\n\ntest('request', run);", errors: [{ messageId: "testComment" }] },
  ],
});
