import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule from "../../src/rules/no-hand-rolled-spinner.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.itOnly = it.only;
RuleTester.it = it;

const ruleTester = new RuleTester({
  languageOptions: {
    parser: tsParser,
    parserOptions: { ecmaFeatures: { jsx: true } },
  },
});

const COMPONENT = "/repo/src/components/loading-state.tsx";

ruleTester.run("no-hand-rolled-spinner", rule, {
  valid: [
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
      name: "leaves dynamic classes alone",
      code: `<div className={cn("rounded-full border-2", loading && "animate-spin border-t-transparent")} />`,
      filename: COMPONENT,
    },
    {
      name: "allows the design-system implementation",
      code: `<span className="size-4 animate-spin rounded-full border-2 border-t-transparent" />`,
      filename: "/repo/src/components/ui/spinner.tsx",
    },
  ],
  invalid: [
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
  ],
});
