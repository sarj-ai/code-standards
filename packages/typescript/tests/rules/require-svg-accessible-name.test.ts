// vitest: shared-module-graph
import rule from "../../src/rules/require-svg-accessible-name.js";
import { ruleTester } from "./_tester.js";

const RULE_TESTER = ruleTester({ lang: "tsx" });

RULE_TESTER.run("require-svg-accessible-name", rule, {
  valid: [
    "<Graphic render={<svg />} />",
    '<div aria-hidden="true"><svg /></div>',
    '<svg aria-label="Sales trend" />',
    '<svg aria-labelledby="chart-title" />',
    '<svg><title>Sales trend</title><path d="M0 0" /></svg>',
    "<svg><title>{title}</title></svg>",
    '<svg aria-hidden="true" />',
    "<svg aria-hidden={true} />",
    { name: "preserves a shadowed undefined hidden value", code: "function render(undefined) { return <svg hidden={undefined} />; }" },
    { name: "preserves unknown hidden values and later spreads", code: "<><svg hidden={visible} /><svg hidden={undefined} {...props} /></>" },
    '<svg role="presentation" />',
    '<svg role="none" />',
    "<svg {...props}><path /></svg>",
    "<svg aria-label={label} />",
    "<Svg />",
    { code: "<svg />", filename: "/repo/src/generated/icon.tsx" },
    { code: "<svg />", filename: "/repo/src/icon.stories.tsx" },
  ],
  invalid: [
    { name: "reports unnamed SVGs with global undefined or void zero hidden props", code: "<><svg hidden={undefined} /><svg hidden={void 0} /></>", errors: [{ messageId: "missingName" }, { messageId: "missingName" }] },
    { code: "<svg />", errors: [{ messageId: "missingName" }] },
    { code: "<svg><path /></svg>", errors: [{ messageId: "missingName" }] },
    {
      code: "<svg><title> </title></svg>",
      errors: [{ messageId: "missingName" }],
    },
    {
      code: "<svg aria-hidden={false}><path /></svg>",
      errors: [{ messageId: "missingName" }],
    },
    {
      code: '<svg aria-label=""><path /></svg>',
      errors: [{ messageId: "missingName" }],
    },
    {
      code: "<svg><desc>A longer description</desc></svg>",
      errors: [{ messageId: "missingName" }],
    },
    {
      code: "<svg><g><title>Nested group name</title></g></svg>",
      errors: [{ messageId: "missingName" }],
    },
    {
      code: '<svg title="Not an SVG title element" />',
      errors: [{ messageId: "missingName" }],
    },
  ],
});
