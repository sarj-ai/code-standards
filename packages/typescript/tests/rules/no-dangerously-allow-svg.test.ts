// vitest: shared-module-graph
import rule from "../../src/rules/no-dangerously-allow-svg.js";
import { ruleTester } from "./_tester.js";

const RULE_TESTER = ruleTester();

const NO_DANGEROUSLY_ALLOW_SVG_DOCUMENTATION = {
  examples: [
    {
      id: "svg-disabled",
      title: "Keep active SVG delivery disabled",
      outcome: "no-match",
      files: [{ path: "next.config.mjs", source: "export default { images: { dangerouslyAllowSVG: false } };\n" }],
      focusPath: "next.config.mjs",
      expectedCount: 0,
      public: true,
    },
    {
      id: "svg-enabled",
      title: "SVG opt-in requires explicit hardening under this policy",
      outcome: "match",
      files: [{ path: "next.config.mjs", source: "export default { images: { dangerouslyAllowSVG: true } };\n" }],
      focusPath: "next.config.mjs",
      expectedCount: 1,
      public: true,
    },
    {
      id: "safe-autofix",
      title: "Disable SVG delivery to satisfy this policy",
      outcome: "match",
      files: [{ path: "next.config.ts", source: "export default { images: { dangerouslyAllowSVG: true } };" }],
      fixedFiles: [{ path: "next.config.ts", source: "export default { images: { dangerouslyAllowSVG: false } };" }],
      focusPath: "next.config.ts",
      expectedCount: 1,
    },
    {
      id: "svg-explicit-hardening",
      scenarioId: "explicit-hardening",
      title: "Allow SVG delivery with explicit hardening",
      outcome: "no-match",
      files: [{ path: "next.config.mjs", source: "export default { images: { dangerouslyAllowSVG: true, contentDispositionType: \"attachment\", contentSecurityPolicy: \"script-src 'none'; sandbox;\" } };\n" }],
      focusPath: "next.config.mjs",
      expectedCount: 0,
      public: true,
    },
    {
      id: "svg-unsafe-first-directive",
      scenarioId: "explicit-hardening",
      title: "A later duplicate cannot replace the effective policy",
      outcome: "match",
      files: [{ path: "next.config.mjs", source: "export default { images: { dangerouslyAllowSVG: true, contentDispositionType: \"attachment\", contentSecurityPolicy: \"script-src 'unsafe-inline'; script-src 'none'; sandbox;\" } };\n" }],
      focusPath: "next.config.mjs",
      expectedCount: 1,
      public: true,
    },
  ],
} as const;

function svgConfig(policy: string, enabled = true): string {
  return `export default {images:{dangerouslyAllowSVG:${enabled},contentSecurityPolicy:${JSON.stringify(policy)}}};`;
}

RULE_TESTER.run("no-dangerously-allow-svg", rule, {
  valid: [
    { name: "preserves a safe-first policy", filename: "./next.config.mjs", code: svgConfig("script-src 'none'; script-src 'unsafe-inline'; sandbox; sandbox allow-scripts;") },
    { name: "converges after disabling an unsafe-first opt-in (the matching invalid case's fixed config lints clean)", filename: "./next.config.mjs", code: svgConfig("script-src 'unsafe-inline'; script-src 'none'; sandbox;", false) },
    ...[
      "script-src 'none'; script-src https://example.com; sandbox;",
      "script-src 'none'; sandbox; sandbox allow-scripts;",
      "ScRiPt-SrC\t'NONE'; SCRIPT-SRC 'unsafe-inline'; SANDBOX;",
      "\t\n\f\r script-src\t\n\f\r 'none'\t\n\f\r ;\t\n\f\r sandbox\t\n\f\r ;",
      "img-src https:; img-src data:; script-src 'none'; sandbox;",
      "\u00a0script-src 'unsafe-inline'; script-src 'none'; sandbox;",
      "scrípt-src 'unsafe-inline'; script-src 'none'; sandbox;",
      "script-src 'none'; \u00a0sandbox allow-scripts; sandbox;",
    ].map((policy) => ({ name: `accepts effective recognized hardening: ${JSON.stringify(policy)}`, filename: "next.config.mjs", code: svgConfig(policy) })),
    { filename: "next.config.mjs", code: NO_DANGEROUSLY_ALLOW_SVG_DOCUMENTATION.examples[3].files[0].source },
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
    { name: "requires explicit recognized policy for a dynamic CSP", filename: "next.config.mjs", code: "export default {images:{dangerouslyAllowSVG:true,contentSecurityPolicy:policy}};", output: "export default {images:{dangerouslyAllowSVG:false,contentSecurityPolicy:policy}};", errors: [{ messageId: "noDangerouslyAllowSvg" }] },
    ...[
      "script-src 'unsafe-inline'; script-src 'none'; sandbox;",
      "script-src 'none'; sandbox allow-scripts; sandbox;",
      "script-src; script-src 'none'; sandbox;",
      "script-src 'none'; sandbox allow-same-origin; sandbox;",
      "script-src\u00a0'none'; sandbox;",
      "script-src\v'none'; sandbox;",
      "script-src\u2003'none'; sandbox;",
      "\u00a0script-src 'none'; sandbox;",
      "script-src 'none'\u00a0; sandbox;",
      "script-src 'none'; \u00a0sandbox;",
      "script-src 'none'; sandbox\u00a0;",
    ].map((policy) => ({
      name: `requires explicit recognized hardening: ${JSON.stringify(policy)}`,
      filename: "next.config.mjs",
      code: svgConfig(policy),
      output: svgConfig(policy, false),
      errors: [{ messageId: "noDangerouslyAllowSvg" as const }],
    })),
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
    { filename: "next.config.mjs", code: NO_DANGEROUSLY_ALLOW_SVG_DOCUMENTATION.examples[4].files[0].source, output: NO_DANGEROUSLY_ALLOW_SVG_DOCUMENTATION.examples[4].files[0].source.replace("dangerouslyAllowSVG: true", "dangerouslyAllowSVG: false"), errors: [{ messageId: "noDangerouslyAllowSvg" }] },
  ],
});
