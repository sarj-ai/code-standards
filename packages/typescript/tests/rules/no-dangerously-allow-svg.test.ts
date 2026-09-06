import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule from "../../src/rules/no-dangerously-allow-svg.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const RULE_TESTER = new RuleTester();

RULE_TESTER.run("no-dangerously-allow-svg", rule, {
  valid: [
    {filename:"next.config.mjs", code:"const example={images:{dangerouslyAllowSVG:true}}; export default {images:{dangerouslyAllowSVG:false}};"},
    {filename:"next.config.mjs", code:"export default {images:{dangerouslyAllowSVG:true,dangerouslyAllowSVG:false}};"},
    {filename:"next.config.mjs", code:"export default {images:{dangerouslyAllowSVG:true},...unknown};"},
    {filename:"next.config.mjs", code:"export default {example:{dangerouslyAllowSVG:true}};"},
    {filename:"next.config.mjs", code:"const config={images:{dangerouslyAllowSVG:true}}; config.images.dangerouslyAllowSVG=false; export default config;"},
    { filename: "next.config.mjs", code: "export default { images: { dangerouslyAllowSVG: false } };" },
    { filename: "next.config.ts", code: "export default { images: {} };" },
    { filename: "src/options.ts", code: "export const options = { dangerouslyAllowSVG: true };" },
    { filename: "next.config.mjs", code: "export default { images: { dangerouslyAllowSVG: enabled } };" },
  ],
  invalid: [
    {filename:"next.config.ts", code:"const config={images:{dangerouslyAllowSVG:true}} as const; export default config;", errors:[{messageId:"noDangerouslyAllowSvg"}]},
    {filename:"next.config.cjs", code:"module.exports={images:{dangerouslyAllowSVG:true}};", errors:[{messageId:"noDangerouslyAllowSvg"}]},
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
