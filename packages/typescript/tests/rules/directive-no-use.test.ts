// vitest: shared-module-graph
import rule from "../../src/rules/directive-no-use.js";
import { ruleTester } from "./_tester.js";

const RULE_TESTER = ruleTester();
const disallow = (kind: string): { messageId: string; data: { kind: string } } => ({ messageId: "disallow", data: { kind } });

RULE_TESTER.run("directive-no-use", rule, {
  valid: [
    "// eslint foo",
    "// exported",
    "// global",
    "// globals",
    "// eslint-env",
    "/* just eslint in a normal comment */",
    { code: "/* eslint */", options: [{ allow: ["eslint"] }] },
    { code: "/* eslint-env */", options: [{ allow: ["eslint-env"] }] },
    { code: "/* eslint-enable */", options: [{ allow: ["eslint-enable"] }] },
    { code: "/* eslint-disable */", options: [{ allow: ["eslint-disable"] }] },
    { code: "// eslint-disable-line", options: [{ allow: ["eslint-disable-line"] }] },
    { code: "// eslint-disable-next-line", options: [{ allow: ["eslint-disable-next-line"] }] },
    { code: "/* eslint-disable-line */", options: [{ allow: ["eslint-disable-line"] }] },
    { code: "/* eslint-disable-next-line */", options: [{ allow: ["eslint-disable-next-line"] }] },
    { code: "/* exported */", options: [{ allow: ["exported"] }] },
    { code: "/* global */", options: [{ allow: ["global"] }] },
    { code: "/* globals */", options: [{ allow: ["globals"] }] },
    { code: "// oxlint-disable-next-line", options: [{ allow: ["eslint-disable-next-line"] }] },
    { code: "foo(); // oxlint-disable-line eqeqeq", options: [{ allow: ["eslint-disable-line"] }] },
    { code: "/* oxlint-disable */\n/* oxlint-enable */", options: [{ allow: ["eslint-disable", "eslint-enable"] }] },
  ],
  invalid: [
    { code: "/* eslint */", errors: [disallow("eslint")] },
    { code: "/* eslint-env */", errors: [disallow("eslint-env")] },
    { code: "/* eslint-enable */", errors: [disallow("eslint-enable")] },
    { code: "/* eslint-disable */", errors: [{ ...disallow("eslint-disable"), line: 1, column: 4, endLine: 1, endColumn: 18 }] },
    { code: "// eslint-disable-line", errors: [disallow("eslint-disable-line")] },
    { code: "// eslint-disable-next-line", errors: [disallow("eslint-disable-next-line")] },
    { code: "/* eslint-disable-line */", errors: [disallow("eslint-disable-line")] },
    { code: "/* eslint-disable-next-line */", errors: [disallow("eslint-disable-next-line")] },
    { code: "/* exported */", errors: [disallow("exported")] },
    { code: "/* global */", errors: [disallow("global")] },
    { code: "/* globals */", errors: [disallow("globals")] },
    { code: "/* eslint-disable */", options: [{ allow: ["globals"] }], errors: [disallow("eslint-disable")] },
    { code: "// eslint-disable", errors: [disallow("eslint-disable")] },
    { code: "// eslint-enable", errors: [disallow("eslint-enable")] },
    { code: "/* oxlint-disable no-console */", options: [{ allow: ["eslint-disable-next-line"] }], errors: [disallow("oxlint-disable")] },
    { code: "// oxlint-enable", errors: [disallow("oxlint-enable")] },
    { code: "// oxlint-disable-next-line", options: [{ allow: ["oxlint-disable-next-line"] }], errors: [disallow("oxlint-disable-next-line")] },
  ],
});
