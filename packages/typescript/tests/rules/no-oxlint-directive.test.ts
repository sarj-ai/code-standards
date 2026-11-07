// vitest: shared-module-graph
import rule from "../../src/rules/no-oxlint-directive.js";
import { ruleTester } from "./_tester.js";

const RULE_TESTER = ruleTester();

RULE_TESTER.run("no-oxlint-directive", rule, {
  valid: [
    { name: "accepts an ESLint next-line directive", code: "// eslint-disable-next-line no-console -- the CLI prints its report\nconsole.log(1);" },
    { name: "accepts ESLint block directives", code: "/* eslint-disable no-console */\nconsole.log(1);\n/* eslint-enable no-console */" },
    { name: "ignores a prose mention", code: "// Never write oxlint-disable here.\nconsole.log(1);" },
    { name: "ignores a longer keyword", code: "// oxlint-disabled for now\nconsole.log(1);" },
    { name: "ignores an unrelated Oxlint comment", code: "// oxlint: see the config\nconsole.log(1);" },
  ],
  invalid: [
    {
      name: "rewrites a next-line directive and keeps rules and description",
      code: "// oxlint-disable-next-line no-console, eqeqeq -- the CLI prints its report\nconsole.log(1);",
      output: "// eslint-disable-next-line no-console, eqeqeq -- the CLI prints its report\nconsole.log(1);",
      errors: [{ messageId: "oxlintDirective", data: { directive: "disable-next-line" }, line: 1, column: 1, endLine: 1, endColumn: 76 }],
    },
    {
      name: "rewrites a same-line directive",
      code: "console.log(1); // oxlint-disable-line no-console",
      output: "console.log(1); // eslint-disable-line no-console",
      errors: [{ messageId: "oxlintDirective", data: { directive: "disable-line" }, line: 1, column: 17 }],
    },
    {
      name: "rewrites block disable and enable directives",
      code: "/* oxlint-disable no-console */\nconsole.log(1);\n/* oxlint-enable no-console */",
      output: "/* eslint-disable no-console */\nconsole.log(1);\n/* eslint-enable no-console */",
      errors: [
        { messageId: "oxlintDirective", data: { directive: "disable" }, line: 1 },
        { messageId: "oxlintDirective", data: { directive: "enable" }, line: 3 },
      ],
    },
    {
      name: "rewrites a directive with leading whitespace inside a block comment",
      code: "/*   oxlint-disable */\nconsole.log(1);",
      output: "/*   eslint-disable */\nconsole.log(1);",
      errors: [{ messageId: "oxlintDirective", data: { directive: "disable" } }],
    },
    {
      name: "rewrites a directive that names a plugin rule",
      code: "// oxlint-disable-next-line @sarj/no-enum -- generated contract\nenum Mode { A }",
      output: "// eslint-disable-next-line @sarj/no-enum -- generated contract\nenum Mode { A }",
      errors: [{ messageId: "oxlintDirective", data: { directive: "disable-next-line" } }],
    },
  ],
});
