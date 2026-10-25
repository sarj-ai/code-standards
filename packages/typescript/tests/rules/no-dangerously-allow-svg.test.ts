// vitest: shared-module-graph
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
    {filename:"next.config.mjs", code:"const example={images:{dangerouslyAllowSVG:true}}; export default {images:{dangerouslyAllowSVG: false}};"},
    {filename:"next.config.mjs", code:"export default {images:{dangerouslyAllowSVG:true,dangerouslyAllowSVG: false}};"},
    {filename:"next.config.mjs", code:"export default {images:{dangerouslyAllowSVG:true},...unknown};"},
    {filename:"next.config.mjs", code:"export default {example:{dangerouslyAllowSVG:true}};"},
    {filename:"next.config.mjs", code:"const config={images:{dangerouslyAllowSVG:true}}; config.images.dangerouslyAllowSVG=false; export default config;"},
    { filename: "next.config.mjs", code: "export default { images: { dangerouslyAllowSVG: false } };" },
    { filename: "next.config.mjs", code: "export default { images: { dangerouslyAllowSVG: true, contentDispositionType: 'attachment', contentSecurityPolicy: \"default-src 'self'; script-src 'none'; sandbox;\" } };" },
    { filename: "next.config.mjs", code: "export default { images: { dangerouslyAllowSVG: true, contentSecurityPolicy: \"SCRIPT-SRC   'NONE'; SANDBOX;\" } };" },
    { filename: "next.config.mjs", code: "export default { images: { dangerouslyAllowSVG: true, contentDispositionType: `attachment`, contentSecurityPolicy: `script-src 'none'; sandbox;` } };" },
    { filename: "next.config.ts", code: "export default { images: {} };" },
    { filename: "src/options.ts", code: "export const options = { dangerouslyAllowSVG: true };" },
    { filename: "next.config.mjs", code: "export default { images: { dangerouslyAllowSVG: enabled } };" },
  ],
  invalid: [
    { name: "preserves explicit config contract 1", filename: "next.config.ts", code: "const config: {images:{dangerouslyAllowSVG:true}} = {images:{dangerouslyAllowSVG:true}}; export default config;", output: null, errors: [{messageId: "noDangerouslyAllowSvg"}] },
    { name: "preserves explicit config contract 2", filename: "next.config.ts", code: "const images = {dangerouslyAllowSVG:true} as const; const config: {images:{dangerouslyAllowSVG:true}} = {images}; export default config;", output: null, errors: [{messageId: "noDangerouslyAllowSvg"}] },
    { name: "preserves explicit config contract 3", filename: "next.config.ts", code: "export default {images:{dangerouslyAllowSVG:true}} satisfies {images:{dangerouslyAllowSVG:true}};", output: null, errors: [{messageId: "noDangerouslyAllowSvg"}] },
    { name: "preserves explicit config contract 4", filename: "next.config.ts", code: "/** @type {{images:{dangerouslyAllowSVG:true}}} */ const config = {images:{dangerouslyAllowSVG:true}}; export default config;", output: null, errors: [{messageId: "noDangerouslyAllowSvg"}] },
    {filename:"next.config.ts", code:"const config={images:{dangerouslyAllowSVG:true}} as const; export default config;", output: "const config={images:{dangerouslyAllowSVG:false}} as const; export default config;", errors:[{messageId:"noDangerouslyAllowSvg"}]},
    {filename:"next.config.cjs", code:"module.exports={images:{dangerouslyAllowSVG:true}};", output: "module.exports={images:{dangerouslyAllowSVG:false}};", errors:[{messageId:"noDangerouslyAllowSvg"}]},
    {
      filename: "/repo/next.config.mjs",
      code: "export default { images: { dangerouslyAllowSVG: true } };", output: "export default { images: { dangerouslyAllowSVG: false } };",
      errors: [{ messageId: "noDangerouslyAllowSvg" }],
    },
    {
      filename: "next.config.ts",
      code: "export default { images: { 'dangerouslyAllowSVG': true } };", output: "export default { images: { 'dangerouslyAllowSVG': false } };",
      errors: [{ messageId: "noDangerouslyAllowSvg" }],
    },
    {
      filename: "next.config.ts",
      code: "export default { images: { dangerouslyAllowSVG: true, contentDispositionType: 'inline', contentSecurityPolicy: \"script-src 'none'; sandbox;\" } };", output: "export default { images: { dangerouslyAllowSVG: false, contentDispositionType: 'inline', contentSecurityPolicy: \"script-src 'none'; sandbox;\" } };",
      errors: [{ messageId: "noDangerouslyAllowSvg" }],
    },
    {
      filename: "next.config.ts",
      code: "export default { images: { dangerouslyAllowSVG: true, contentSecurityPolicy: \"script-src 'none' https://example.com; sandbox;\" } };", output: "export default { images: { dangerouslyAllowSVG: false, contentSecurityPolicy: \"script-src 'none' https://example.com; sandbox;\" } };",
      errors: [{ messageId: "noDangerouslyAllowSvg" }],
    },
    {
      filename: "next.config.ts",
      code: "export default { images: { dangerouslyAllowSVG: true, contentSecurityPolicy: \"script-src 'none'; sandbox allow-scripts;\" } };", output: "export default { images: { dangerouslyAllowSVG: false, contentSecurityPolicy: \"script-src 'none'; sandbox allow-scripts;\" } };",
      errors: [{ messageId: "noDangerouslyAllowSvg" }],
    },
    {
      filename: "next.config.ts",
      code: "export default { images: { dangerouslyAllowSVG: true, contentSecurityPolicy: \"script-src 'none'; script-src https://example.com; sandbox;\" } };", output: "export default { images: { dangerouslyAllowSVG: false, contentSecurityPolicy: \"script-src 'none'; script-src https://example.com; sandbox;\" } };",
      errors: [{ messageId: "noDangerouslyAllowSvg" }],
    },
  ],
});
