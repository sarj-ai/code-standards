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
    { name: "string contents", code: "const source = '// comments remain literal fixture data';" },
    { name: "template contents", code: "const source = `/* comments remain fixture data */`;" },
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
    { name: "inline block keeps token boundary", code: "const value = left/* test explanation */+right;", output: "const value = left +right;", errors: [{ messageId: "testComment" }] },
    { name: "multiline block preserves ASI", code: "function f() { return/* explain\nwhy */value; }", output: "function f() { return\nvalue; }", errors: [{ messageId: "testComment" }] },
    { name: "test fixture path", filename: "tests/fixtures/request.ts", code: "// Explain\nconst value = 1;", output: "\nconst value = 1;", errors: [{ messageId: "testComment" }] },
    { name: "trailing comment removes adjacent padding", code: "expect(value).toBe(1);  // Check the value\n", output: "expect(value).toBe(1);\n", errors: [{ messageId: "testComment" }] },
    { name: "ambiguous test basename with actual runner import", filename: "src/request-test.ts", code: "import { test } from 'vitest';\n// Check the request\ntest('request', run);", output: "import { test } from 'vitest';\n\ntest('request', run);", errors: [{ messageId: "testComment" }] },
  ],
});
