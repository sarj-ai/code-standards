import { RuleTester } from "oxlint/plugins-dev";
import { describe, it } from "vitest";
import rule, {
  NO_VAGUE_SUPPRESSION_DESCRIPTION_DOCUMENTATION as DOC,
} from "../../src/rules/no-vague-suppression-description.js";
RuleTester.describe = describe;
RuleTester.it = it;
const tester = new RuleTester({
  languageOptions: { parserOptions: { lang: "ts" } },
});
const source = (code: string) => ({ code, filename: "src/adapter.ts" });
const invalid = (code: string, ...messageIds: string[]) => ({
  ...source(code),
  errors: messageIds.map((messageId) => ({ messageId })),
});
tester.run("@sarj/no-vague-suppression-description", rule, {
  valid: [
    source("/* eslintConfig is the retired configuration filename. */\nrun();"),
    source(
      DOC.examples.find((example) => example.outcome === "no-match")!.files[0]
        .source,
    ),
    source(
      "// oxlint-disable-next-line no-debugger -- browser integration requires a breakpoint\ndebugger;",
    ),
    source(
      "debugger; // oxlint-disable-line no-debugger -- browser integration requires a breakpoint",
    ),
    source(
      "// oxlint-disable-next-line no-debugger, no-alert -- vendor SDK requires both legacy calls\ndebugger;",
    ),
    source(
      "// oxlint-disable-next-line imaginary/no-vague-suppression-description -- vendor SDK requires this call\nrun();",
    ),
    source(
      "// oxlint-disable-next-line no-vague-suppression-description -- vendor SDK requires this call\nrun();",
    ),
    source(
      "// oxlint-disable-next-line no-console/ -- vendor SDK requires this call\nrun();",
    ),
    source("const message = 'oxlint-disable';"),
    source("// unrelated needed comment"),
    source("// @generated\n// oxlint-disable\ndebugger;"),
    source(
      "// @ts-expect-error -- vendor types omit runtime field\nvalue.field;",
    ),
  ],
  invalid: [
    invalid(
      "/* eslint no-console: off */\nconsole.log('value');",
      "legacyDirective",
    ),
    invalid(
      DOC.examples.find((example) => example.outcome === "match")!.files[0]
        .source,
      "vagueDescription",
    ),
    invalid(
      "// oxlint-disable-next-line no-debugger\ndebugger;",
      "missingDescription",
    ),
    invalid(
      "// oxlint-disable-line -- vendor SDK requires this call\ndebugger;",
      "missingRules",
    ),
    invalid(
      "// oxlint-disable-next-line\ndebugger;",
      "missingRules",
      "missingDescription",
    ),
    invalid(
      "// oxlint-disable no-debugger -- vendor SDK requires this call\ndebugger;",
      "lineOnly",
    ),
    invalid("// oxlint-enable no-debugger\ndebugger;", "lineOnly"),
    invalid(
      "// eslint-disable-next-line no-debugger -- vendor SDK requires this call\ndebugger;",
      "legacyDirective",
    ),
    invalid(
      "// oxlint-disable-next-line no-console -- vendor SDK requires this call\nconsole.log(1);",
      "restrictedRule",
    ),
    ...["imaginary/no-console", "/no-console", "first/second/no-console"].map(
      (name) =>
        invalid(
          `// oxlint-disable-next-line ${name} -- vendor SDK requires this call\nconsole.log(1);`,
          "restrictedRule",
        ),
    ),
    ...["exhaustive-deps", "imaginary/exhaustive-deps"].map((name) =>
      invalid(
        `// oxlint-disable-next-line ${name} -- library requires stable closure\nrun();`,
        "restrictedRule",
      ),
    ),
    invalid(
      "// oxlint-disable-next-line react/exhaustive-deps -- library requires stable closure\nrun();",
      "restrictedRule",
    ),
    invalid(
      "// oxlint-disable-next-line sarj-react-hooks/exhaustive-deps -- library requires stable closure\nrun();",
      "restrictedRule",
    ),
    invalid(
      "// oxlint-disable-next-line @sarj/no-vague-suppression-description -- vendor SDK requires this call\nrun();",
      "restrictedRule",
    ),
    invalid(
      "// oxlint-disable-next-line no-debugger, no-debugger -- vendor SDK requires this call\ndebugger;",
      "duplicateRule",
    ),
    ...[
      "needed",
      "Required.",
      "false positive",
      "to satisfy the type checker",
    ].map((reason) =>
      invalid(
        `// oxlint-disable-next-line no-debugger -- ${reason}\ndebugger;`,
        "vagueDescription",
      ),
    ),
    invalid(
      "// @ts-expect-error: intentional\nvalue.field;",
      "vagueDescription",
    ),
  ],
});
