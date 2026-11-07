// vitest: shared-module-graph
import rule from "../../src/rules/no-vague-suppression-description.js";
import { ruleTester } from "./_tester.js";

const RULE_TESTER = ruleTester();

RULE_TESTER.run("no-vague-suppression-description", rule, {
  valid: [
    "// eslint-disable-next-line no-console -- CLI output is the public interface\nconsole.log(value);",
    "// @ts-expect-error -- vendor declaration omits the runtime overload added in v4\nlegacy.call(value);",
    "// @ts-expect-error vendor declaration omits the runtime overload added in v4\nlegacy.call(value);",
    "// @ts-expect-error: generated SDK types model this nullable response as required\nread(value);",
    "// false positive in prose, not a directive\nconst value = 1;",
    "// Unlike @ts-expect-error -- needed, this prose does not suppress anything\nconst value = 1;",
    "/* Unlike @ts-expect-error -- needed, this block is prose. */\nconst value = 1;",
    "/* @ts-ignore -- intentional */\nlegacy.call(value);",
    "// @ts-expect-error\nlegacy.call(value);",
    "// eslint-disable-next-line no-console\nconsole.log(value);",
    "// oxlint-disable-next-line no-console -- CLI output is the public interface\nconsole.log(value);",
    "/* @ts-expect-error -- vendor declaration omits the runtime overload */\nlegacy.call(value);",
  ],
  invalid: [
    { name: "reports its own vague eslint-disable-line (valid under ESLint; Oxlint's RuleTester ignores disable directives)", code: "const value = 1; // eslint-disable-line @rule-tester/no-vague-suppression-description -- needed", errors: [{ messageId: "vagueDescription" }] },
    ...["same", "n/a", "legacy"].map((reason) => ({
      code: `// @ts-expect-error -- ${reason}\ncall();`,
      errors: [{ messageId: "vagueDescription" as const }],
    })),
    {
      filename: "/repo/src/generated/client.ts",
      code: "// @generated\n// @ts-expect-error -- needed\ncall();",
      errors: [{ messageId: "vagueDescription" }],
    },
    {
      code: "// eslint-disable-next-line no-console -- needed\nconsole.log(value);",
      errors: [{ messageId: "vagueDescription" }],
    },
    {
      code: "// eslint-disable-next-line no-console -- false positive\nconsole.log(value);",
      errors: [{ messageId: "vagueDescription" }],
    },
    {
      code: "// oxlint-disable-next-line no-console -- needed\nconsole.log(value);",
      errors: [{ messageId: "vagueDescription" }],
    },
    {
      code: "/* oxlint-disable no-console -- legacy */\nconsole.log(value);",
      errors: [{ messageId: "vagueDescription" }],
    },
    {
      code: "// @ts-expect-error: to satisfy linter\nlegacy.call(value);",
      errors: [{ messageId: "vagueDescription" }],
    },
    {
      code: "// @ts-expect-error needed\nlegacy.call(value);",
      errors: [{ messageId: "vagueDescription" }],
    },
    {
      code: "/* @ts-expect-error -- intentional */\nlegacy.call(value);",
      errors: [{ messageId: "vagueDescription" }],
    },
    {
      code: "// eslint-disable-next-line @rule-tester/no-vague-suppression-description -- needed\nconst value = 1;",
      errors: [{ messageId: "vagueDescription" }],
    },
  ],
});

ruleTester().run("no-vague-suppression-description", rule, {
  valid: [
    { name: "missing description is upstream-only (only this rule's silence is checked under Oxlint)", filename: "src/ownership.ts", code: "// eslint-disable-next-line no-console\nconsole.log(value);" },
    { name: "concrete description is accepted by both owners", filename: "src/ownership.ts", code: "// eslint-disable-next-line no-console -- CLI output is the public interface\nconsole.log(value);" },
    { name: "ts-ignore is upstream-only (only this rule's silence is checked under Oxlint)", filename: "src/ownership.ts", code: "// @ts-ignore -- intentional\nconst value: string = 1;" },
    { name: "directive mention in prose belongs to neither", filename: "src/ownership.ts", code: "// Unlike @ts-ignore -- needed, this prose suppresses nothing.\nconst value = 1;" },
  ],
  invalid: [
    { name: "vague present description is custom-only", filename: "src/ownership.ts", code: "// eslint-disable-next-line no-console -- needed\nconsole.log(value);", errors: [{ messageId: "vagueDescription" }] },
  ],
});
