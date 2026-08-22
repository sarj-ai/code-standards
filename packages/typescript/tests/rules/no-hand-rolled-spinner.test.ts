import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule, { NO_HAND_ROLLED_SPINNER_DOCUMENTATION } from "../../src/rules/no-hand-rolled-spinner.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.itOnly = it.only;
RuleTester.it = it;

const RULE_TESTER = new RuleTester({
  languageOptions: {
    parser: tsParser,
    parserOptions: { ecmaFeatures: { jsx: true } },
  },
});

const COMPONENT = "/repo/src/components/loading-state.tsx";

RULE_TESTER.run("no-hand-rolled-spinner", rule, {
  valid: [
    { name: "accepts the documented shared spinner", code: NO_HAND_ROLLED_SPINNER_DOCUMENTATION.examples[0].files[0].source, filename: COMPONENT },
    {
      name: "accepts the design-system spinner",
      code: `<Spinner className="size-4" />`,
      filename: COMPONENT,
    },
    {
      name: "accepts a spinning icon",
      code: `<Loader2 className="size-4 animate-spin" />`,
      filename: COMPONENT,
    },
    {
      name: "accepts a decorative animated ring",
      code: `<div className="size-8 animate-spin rounded-full border-2" />`,
      filename: COMPONENT,
    },
    {
      name: "accepts a static bordered circle",
      code: `<span className="size-4 rounded-full border-2 border-t-transparent" />`,
      filename: COMPONENT,
    },
    {
      name: "accepts directional border width without a contrasting color",
      code: `<span className="size-4 animate-spin rounded-full border-2 border-t-2" />`,
      filename: COMPONENT,
    },
    {
      name: "accepts logical and axis border widths",
      code: `<span className="size-4 animate-spin rounded-full border-[3px] border-s-[2px] border-x-2" />`,
      filename: COMPONENT,
    },
    {
      name: "accepts an arbitrary length variable as a directional width",
      code: `<span className="size-4 animate-spin rounded-full border-(length:--ring-width) border-e-(length:--edge-width)" />`,
      filename: COMPONENT,
    },
    {
      name: "leaves dynamic classes alone",
      code: `<div className={cn("rounded-full border-2", loading && "animate-spin border-t-transparent")} />`,
      filename: COMPONENT,
    },
    {
      name: "allows the design-system implementation",
      code: `<span className="size-4 animate-spin rounded-full border-2 border-t-transparent" />`,
      filename: "/repo/src/components/ui/spinner.tsx",
    },
    {
      name: "allows spinner examples in tests",
      code: `<span className="size-4 animate-spin rounded-full border-2 border-s-transparent" />`,
      filename: "/repo/src/components/loading-state.test.tsx",
    },
    {
      name: "allows spinner variants in stories",
      code: `<span className="size-4 animate-spin rounded-full border-2 border-e-primary" />`,
      filename: "/repo/src/components/loading-state.stories.tsx",
    },
    {
      name: "allows generated spinner markup",
      code: `<span className="size-4 animate-spin rounded-full border-2 border-x-transparent" />`,
      filename: "/repo/src/generated/loading-state.tsx",
    },
  ],
  invalid: [
    { name: "reports the documented border-ring spinner", code: NO_HAND_ROLLED_SPINNER_DOCUMENTATION.examples[1].files[0].source, filename: COMPONENT, errors: [{ messageId: "handRolledSpinner" }] },
    {
      name: "rejects a div border-ring spinner",
      code: `<div className="border-border h-4 w-4 animate-spin rounded-full border-2 border-t-transparent" />`,
      filename: COMPONENT,
      errors: [{ messageId: "handRolledSpinner" }],
    },
    {
      name: "rejects a span border-ring spinner",
      code: `<span className="h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent" />`,
      filename: COMPONENT,
      errors: [{ messageId: "handRolledSpinner" }],
    },
    {
      name: "rejects a string expression className",
      code: `<div className={"size-4 animate-spin rounded-full border border-l-transparent"} />`,
      filename: COMPONENT,
      errors: [{ messageId: "handRolledSpinner" }],
    },
    {
      name: "rejects a colored directional edge",
      code: `<div className="size-4 animate-spin rounded-full border-2 border-t-primary" />`,
      filename: COMPONENT,
      errors: [{ messageId: "handRolledSpinner" }],
    },
    {
      name: "rejects a static template-literal className",
      code: "<div className={`size-4 animate-spin rounded-full border-2 border-r-[#fff]`} />",
      filename: COMPONENT,
      errors: [{ messageId: "handRolledSpinner" }],
    },
    {
      name: "rejects an arbitrary-width spinner with logical start contrast",
      code: `<div className="size-4 animate-spin rounded-full border-[3px] border-s-transparent" />`,
      filename: COMPONENT,
      errors: [{ messageId: "handRolledSpinner" }],
    },
    {
      name: "rejects a logical end contrast",
      code: `<div className="size-4 animate-spin rounded-full border-2 border-e-primary" />`,
      filename: COMPONENT,
      errors: [{ messageId: "handRolledSpinner" }],
    },
    {
      name: "rejects an axis contrast",
      code: `<div className="size-4 animate-spin rounded-full border-2 border-x-transparent" />`,
      filename: COMPONENT,
      errors: [{ messageId: "handRolledSpinner" }],
    },
    {
      name: "rejects an arbitrary axis color contrast",
      code: `<div className="size-4 animate-spin rounded-full border-2 border-y-[#fff]" />`,
      filename: COMPONENT,
      errors: [{ messageId: "handRolledSpinner" }],
    },
  ],
});
