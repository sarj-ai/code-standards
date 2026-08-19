import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule from "../../src/rules/no-dangerously-allow-svg.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const ruleTester = new RuleTester();

ruleTester.run("no-dangerously-allow-svg", rule, {
  valid: [
    { filename: "next.config.mjs", code: "export default { images: { dangerouslyAllowSVG: false } };" },
    { filename: "next.config.ts", code: "export default { images: {} };" },
    { filename: "src/options.ts", code: "export const options = { dangerouslyAllowSVG: true };" },
    { filename: "next.config.mjs", code: "export default { images: { dangerouslyAllowSVG: enabled } };" },
  ],
  invalid: [
    {
      filename: "/repo/next.config.mjs",
      code: "export default { images: { dangerouslyAllowSVG: true } };",
      errors: [{ messageId: "noDangerouslyAllowSvg" }],
    },
    {
      filename: "next.config.ts",
      code: "export default { images: { 'dangerouslyAllowSVG': true } };",
      errors: [{ messageId: "noDangerouslyAllowSvg" }],
    },
  ],
});
