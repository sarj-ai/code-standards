// vitest: shared-module-graph
import rule from "../../src/rules/directive-no-restricted-disable.js";
import { ruleTester } from "./_tester.js";

const RULE_TESTER = ruleTester();
const disallow = (ruleId: string): { messageId: string; data: { ruleId: string } } => ({ messageId: "disallow", data: { ruleId } });

RULE_TESTER.run("directive-no-restricted-disable", rule, {
  valid: [
    "/*eslint-disable*/",
    "//eslint-disable-line",
    "//eslint-disable-next-line",
    "/*eslint-disable-line*/",
    "/*eslint-disable-next-line*/",
    { code: "/*eslint-disable eqeqeq*/", options: ["no-unused-vars"] },
    { code: "/*eslint-enable eqeqeq*/", options: ["eqeqeq"] },
    { code: "/*eslint-disable eqeqeq*/", options: ["*", "!eqeqeq"] },
    { code: "/*oxlint-disable eqeqeq*/", options: ["no-unused-vars"] },
    { code: "/*eslint-disable foo/eqeqeq*/", options: ["bar/*"] },
    { code: "/*eslint-disable react-hooks/exhaustive-deps*/", options: ["react/exhaustive-deps"] },
    { code: "/*eslint-disable eqeqeq*/", options: ["# eqeqeq", ""] },
    { code: "/*eslint-disable foo/eqeqeq*/", options: ["foo/eqeqeq/"] },
  ],
  invalid: [
    { code: "/*eslint-disable eqeqeq*/", options: ["eqeqeq"], errors: [{ ...disallow("eqeqeq"), line: 1, column: 18, endLine: 1, endColumn: 24 }] },
    { code: "/*eslint-disable*/", options: ["eqeqeq"], errors: [{ ...disallow("eqeqeq"), line: 1, column: 3, endLine: 1, endColumn: 17 }] },
    { code: "//eslint-disable-line eqeqeq", options: ["eqeqeq"], errors: [disallow("eqeqeq")] },
    { code: "/*eslint-disable-line eqeqeq*/", options: ["eqeqeq"], errors: [disallow("eqeqeq")] },
    { code: "//eslint-disable-line", options: ["eqeqeq"], errors: [disallow("eqeqeq")] },
    { code: "/*eslint-disable-line*/", options: ["eqeqeq"], errors: [disallow("eqeqeq")] },
    { code: "//eslint-disable-next-line eqeqeq", options: ["eqeqeq"], errors: [disallow("eqeqeq")] },
    { code: "/*eslint-disable-next-line eqeqeq*/", options: ["eqeqeq"], errors: [disallow("eqeqeq")] },
    { code: "//eslint-disable-next-line", options: ["eqeqeq"], errors: [disallow("eqeqeq")] },
    { code: "/*eslint-disable-next-line*/", options: ["eqeqeq"], errors: [disallow("eqeqeq")] },

    { code: "/*eslint-disable eqeqeq, no-undef, no-redeclare*/", options: ["*", "!no-undef", "!no-redeclare"], errors: [disallow("eqeqeq")] },
    { code: "/*eslint-disable*/", options: ["*", "!no-undef", "!no-redeclare"], errors: [disallow("*,!no-undef,!no-redeclare")] },
    { code: "//eslint-disable-line eqeqeq, no-undef, no-redeclare", options: ["*", "!no-undef", "!no-redeclare"], errors: [disallow("eqeqeq")] },
    { code: "/*eslint-disable-line eqeqeq, no-undef, no-redeclare*/", options: ["*", "!no-undef", "!no-redeclare"], errors: [disallow("eqeqeq")] },
    { code: "//eslint-disable-line", options: ["*", "!no-undef", "!no-redeclare"], errors: [disallow("*,!no-undef,!no-redeclare")] },
    { code: "/*eslint-disable-line*/", options: ["*", "!no-undef", "!no-redeclare"], errors: [disallow("*,!no-undef,!no-redeclare")] },
    { code: "//eslint-disable-next-line eqeqeq, no-undef, no-redeclare", options: ["*", "!no-undef", "!no-redeclare"], errors: [disallow("eqeqeq")] },
    { code: "/*eslint-disable-next-line eqeqeq, no-undef, no-redeclare*/", options: ["*", "!no-undef", "!no-redeclare"], errors: [disallow("eqeqeq")] },
    { code: "//eslint-disable-next-line", options: ["*", "!no-undef", "!no-redeclare"], errors: [disallow("*,!no-undef,!no-redeclare")] },
    { code: "/*eslint-disable-next-line*/", options: ["*", "!no-undef", "!no-redeclare"], errors: [disallow("*,!no-undef,!no-redeclare")] },

    {
      code: "/*eslint-disable semi, no-extra-semi, semi-style, comma-style*/",
      options: ["*semi*"],
      errors: [disallow("semi"), disallow("no-extra-semi"), disallow("semi-style")],
    },
    {
      code: "/*eslint-disable no-undef, no-redeclare, foo/no-undef, foo/no-redeclare*/",
      options: ["foo/*"],
      errors: [disallow("foo/no-undef"), disallow("foo/no-redeclare")],
    },
    { code: "/*eslint-disable -- description*/", options: ["eqeqeq"], errors: [disallow("eqeqeq")] },
    { code: "/*oxlint-disable eqeqeq*/", options: ["eqeqeq"], errors: [{ ...disallow("eqeqeq"), line: 1, column: 18, endLine: 1, endColumn: 24 }] },
    { code: "foo(); //oxlint-disable-line", options: ["eqeqeq"], errors: [{ ...disallow("eqeqeq"), line: 1, column: 10 }] },
    { code: "// oxlint-disable-next-line @sarj/no-oxlint-directive, no-debugger\ndebugger;", options: ["@sarj/no-oxlint-directive"], errors: [{ ...disallow("@sarj/no-oxlint-directive"), column: 29 }] },
    { code: "/*eslint-disable eslint/no-console, react/no-console*/", options: ["no-console"], errors: [disallow("eslint/no-console"), disallow("react/no-console")] },
    { code: "/*eslint-disable foo/eqeqeq*/", options: ["foo/"], errors: [disallow("foo/eqeqeq")] },
    { code: "/*eslint-disable @scope/plugin/rule*/", options: ["@scope/**"], errors: [disallow("@scope/plugin/rule")] },
    { code: "/*eslint-disable foo/eqeqeq*/", options: ["foo", "!foo/eqeqeq"], errors: [disallow("foo/eqeqeq")] },
    { code: "/*eslint-disable no-console*/", options: ["/no-console"], errors: [disallow("no-console")] },
    { code: "/*eslint-disable no-consol3*/", options: ["no-consol[0-9]"], errors: [disallow("no-consol3")] },
    {
      code: "/* eslint-disable\n  no-console,\n  no-debugger\n*/",
      options: ["no-debugger"],
      errors: [{ ...disallow("no-debugger"), line: 3, column: 3, endLine: 3, endColumn: 14 }],
    },
  ],
});
