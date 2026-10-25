// vitest: shared-module-graph
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
    {filename:"next.config.mjs", code:"const example={productionBrowserSourceMaps:true}; export default {productionBrowserSourceMaps: false};"},
    {filename:"next.config.mjs", code:"export default {productionBrowserSourceMaps:true,productionBrowserSourceMaps: false};"},
    {filename:"next.config.mjs", code:"export default {productionBrowserSourceMaps:true,...unknown};"},
    {filename:"next.config.mjs", code:"export default {example:{productionBrowserSourceMaps:true}};"},
    {filename:"next.config.mjs", code:"let config={productionBrowserSourceMaps:true}; config={productionBrowserSourceMaps: false}; export default config;"},
    { filename: "next.config.mjs", code: "export default { productionBrowserSourceMaps: false };" },
    { filename: "next.config.ts", code: "export default {};" },
    { filename: "src/options.ts", code: "export const options = { productionBrowserSourceMaps: true };" },
    { filename: "next.config.mjs", code: "export default { productionBrowserSourceMaps: enabled };" },
  ],
  invalid: [
    { name: "preserves explicit config contract 1", filename: "next.config.ts", code: "const config: {productionBrowserSourceMaps: true} = {productionBrowserSourceMaps:true}; export default config;", output: null, errors: [{messageId: "noProductionBrowserSourceMaps"}] },
    { name: "preserves explicit config contract 2", filename: "next.config.ts", code: "export default {productionBrowserSourceMaps:true} satisfies {productionBrowserSourceMaps:true};", output: null, errors: [{messageId: "noProductionBrowserSourceMaps"}] },
    { name: "preserves explicit config contract 3", filename: "next.config.ts", code: "/** @type {{productionBrowserSourceMaps: true}} */ const config = {productionBrowserSourceMaps:true}; export default config;", output: null, errors: [{messageId: "noProductionBrowserSourceMaps"}] },
    {filename:"next.config.ts", code:"const config={productionBrowserSourceMaps:true} satisfies Record<string,boolean>; export default config;", output: null, errors:[{messageId:"noProductionBrowserSourceMaps"}]},
    {filename:"next.config.cjs", code:"module.exports={productionBrowserSourceMaps:true};", output: "module.exports={productionBrowserSourceMaps:false};", errors:[{messageId:"noProductionBrowserSourceMaps"}]},
    {
      filename: "/repo/next.config.mjs",
      code: "export default { productionBrowserSourceMaps: true };", output: "export default { productionBrowserSourceMaps: false };",
      errors: [{ messageId: "noProductionBrowserSourceMaps" }],
    },
    {
      filename: "next.config.ts",
      code: "export default { 'productionBrowserSourceMaps': true };", output: "export default { 'productionBrowserSourceMaps': false };",
      errors: [{ messageId: "noProductionBrowserSourceMaps" }],
    },
  ],
});
