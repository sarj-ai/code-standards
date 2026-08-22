import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule from "../../src/rules/no-production-browser-source-maps.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const RULE_TESTER = new RuleTester();

RULE_TESTER.run("no-production-browser-source-maps", rule, {
  valid: [
    { filename: "next.config.mjs", code: "export default { productionBrowserSourceMaps: false };" },
    { filename: "next.config.ts", code: "export default {};" },
    { filename: "src/options.ts", code: "export const options = { productionBrowserSourceMaps: true };" },
    { filename: "next.config.mjs", code: "export default { productionBrowserSourceMaps: enabled };" },
  ],
  invalid: [
    {
      filename: "/repo/next.config.mjs",
      code: "export default { productionBrowserSourceMaps: true };",
      errors: [{ messageId: "noProductionBrowserSourceMaps" }],
    },
    {
      filename: "next.config.ts",
      code: "export default { 'productionBrowserSourceMaps': true };",
      errors: [{ messageId: "noProductionBrowserSourceMaps" }],
    },
  ],
});
