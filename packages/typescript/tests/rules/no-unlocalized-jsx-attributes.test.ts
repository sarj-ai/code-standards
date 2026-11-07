// vitest: shared-module-graph
import rule from "../../src/rules/no-unlocalized-jsx-attributes.js";
import { ruleTester } from "./_tester.js";

const RULE_TESTER = ruleTester({ lang: "tsx" });

RULE_TESTER.run("no-unlocalized-jsx-attributes", rule, {
  valid: [
    '<input placeholder={t("search")} />',
    '<img alt="" />',
    '<div aria-labelledby="dialog-title" />',
    '<div data-testid="hello" />',
    '<input placeholder="Search" {...props} />',
    '<div translate="no"><input placeholder="Brand" /></div>',
    { code: '<input placeholder="Search" />', options: [{ enabled: false }] },
    {
      code: '<div aria-labelledby="dialog-title" />',
      options: [{ attributes: ["aria-labelledby"] }],
    },
  ],
  invalid: [
    {
      code: '<code title="Example code">token</code>',
      errors: [{ messageId: "unlocalized" }],
    },
    {
      code: '<input placeholder="Search" />',
      errors: [{ messageId: "unlocalized" }],
    },
    {
      code: '<button aria-label={"Close"} />',
      errors: [{ messageId: "unlocalized" }],
    },
    {
      code: '<img alt="A mountain" />',
      errors: [{ messageId: "unlocalized" }],
    },
    {
      code: '<input {...props} translate="yes" placeholder="Search" />',
      errors: [{ messageId: "unlocalized" }],
    },
    {
      code: '<Control caption="Welcome" />',
      options: [{ attributes: ["caption"] }],
      errors: [{ messageId: "unlocalized" }],
    },
  ],
});
