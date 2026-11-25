import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";
import stylelint from "stylelint";

const PACKAGE = fileURLToPath(new URL("../", import.meta.url));
const CONFIG = fileURLToPath(
  new URL("../../standards/src/sarj_standards/configs/stylelint.strict.json", import.meta.url),
);

async function warnings(code: string): Promise<readonly string[]> {
  const report = await stylelint.lint({ code, configFile: CONFIG, configBasedir: PACKAGE });
  return report.results.flatMap((result) => result.warnings.map((warning) => warning.rule));
}

describe("managed CSS guidance", () => {
  it.each([
    ["timeline reset", ".a { animation-timeline: scroll(); animation: reveal linear both; }"],
    ["escaped timeline", ".a { animation-\\74imeline: scroll(); animation: reveal 1s; }"],
    [
      "escaped transition",
      ".a { transition-behavior: allow-discrete; tran\\73ition: display 1s; }",
    ],
    ["mixed timeline list", ".a { animation-timeline: auto, scroll(); animation: reveal 1s; }"],
    [
      "partially reset behaviors",
      ".a { transition-behavior: allow-discrete, allow-discrete; transition: display 1s allow-discrete, visibility 1s; }",
    ],
    [
      "repeating discrete behavior",
      ".a { transition-behavior: allow-discrete; transition: display 1s allow-discrete, visibility 1s; }",
    ],
    ["range reset", ".a { animation-range: entry 0% cover 50%; animation: reveal linear both; }"],
    [
      "discrete behavior reset",
      ".a { transition-behavior: allow-discrete; transition: display 1s; }",
    ],
  ])("reports %s", async (_label, css) => {
    expect(await warnings(css)).toContain("@sarj/no-modern-shorthand-reset");
  });

  it.each([
    ["timeline restored", ".a { animation: reveal linear both; animation-timeline: scroll(); }"],
    [
      "escaped restoration",
      ".a { animation-timeline: scroll(); animation: reveal 1s; animation-\\74imeline: view(); }",
    ],
    ["initial range with spaces", ".a { animation-range: normal   normal; animation: reveal 1s; }"],
    [
      "initial range with a comment",
      ".a { animation-range: normal\t/* start */ normal; animation: reveal 1s; }",
    ],
    ["initial timeline list", ".a { animation-timeline: auto, auto; animation: reveal 1s; }"],
    [
      "initial behavior list",
      ".a { transition-behavior: normal, normal; transition: display 1s; }",
    ],
    [
      "restored behavior by index",
      ".a { transition-behavior: normal, allow-discrete; transition: opacity 1s, display 1s allow-discrete; }",
    ],
    [
      "unused discrete behavior",
      ".a { transition-behavior: normal, allow-discrete; transition: opacity 1s; }",
    ],
    [
      "range restored",
      ".a { animation-range: entry; animation: reveal linear both; animation-range: exit; }",
    ],
    [
      "range restored as longhands",
      ".a { animation-range: entry; animation: reveal 1s; animation-range-start: entry 0%; animation-range-end: exit 100%; }",
    ],
    ["important longhand", ".a { animation-timeline: scroll() !important; animation: reveal 1s; }"],
    ["rule revert", ".a { animation-timeline: scroll(); animation: revert-rule; }"],
    ["inherited timeline", ".a { animation-timeline: INHERIT; animation: reveal 1s; }"],
    ["escaped inherited timeline", ".a { animation-timeline: \\69nherit; animation: reveal 1s; }"],
    [
      "variable shorthand",
      ".a { transition-behavior: allow-discrete; transition: var(--transition); }",
    ],
    [
      "escaped variable shorthand",
      ".a { transition-behavior: allow-discrete; transition: v\\61r(--transition); }",
    ],
    [
      "escaped environment shorthand",
      ".a { animation-timeline: scroll(); animation: e\\6ev(--animation); }",
    ],
    ["initial timeline", ".a { animation-timeline: auto; animation: reveal 1s; }"],
    ["escaped initial timeline", ".a { animation-timeline: \\61uto; animation: reveal 1s; }"],
    ["disabled animation", ".a { animation-timeline: scroll(); animation: none; }"],
    ["escaped disabled animation", ".a { animation-timeline: scroll(); animation: \\6eone; }"],
    [
      "explicit discrete shorthand",
      ".a { transition-behavior: allow-discrete; transition: display 1s allow-discrete; }",
    ],
    [
      "escaped discrete shorthand",
      ".a { transition-behavior: allow-discrete; transition: display 1s allow-\\64iscrete; }",
    ],
    ["separate cascade", ".a { animation-timeline: scroll(); } .b { animation: reveal 1s; }"],
    [
      "Tailwind media tokens",
      "@utility container { @media (width >= --theme(--breakpoint-sm)) { max-width: none; } }",
    ],
    ["mixed typography", ".a { font-size: clamp(1rem, 1rem + 1vw, 2rem); }"],
    ["mixed calculation", ".a { font-size: calc(1rem + 2px); }"],
    ["zero and relative text", ".a { font-size: 0px; } .b { font-size: 120%; }"],
    [
      "Tailwind syntax",
      '@import "tailwindcss"; @theme { --color-brand: #123456; } .a { @apply flex; color: var(--color-brand); }',
    ],
    [
      "modern CSS",
      ".a { display: grid; grid-template-columns: subgrid; text-wrap: balance; interpolate-size: allow-keywords; & > p { color: light-dark(black, white); } }",
    ],
  ])("preserves %s", async (_label, css) => {
    expect(await warnings(css)).toEqual([]);
  });

  it("ignores an invalid transition behavior", async () => {
    expect(
      await warnings(".a { transition-behavior: sometimes; transition: display 1s; }"),
    ).not.toContain("@sarj/no-modern-shorthand-reset");
  });

  it.each([
    ["declaration-property-value-disallowed-list", ".a { font-size: 16px; }"],
    [
      "declaration-block-no-shorthand-property-overrides",
      ".a { animation-duration: 2s; animation: reveal 1s; }",
    ],
    ["keyframe-declaration-no-important", "@keyframes reveal { to { opacity: 1 !important; } }"],
    ["named-grid-areas-no-invalid", '.a { grid-template-areas: "a a" "a b"; }'],
    ["media-query-no-invalid", "@media (min-width >= 30rem) { .a { color: red; } }"],
    ["custom-property-no-missing-var-function", ".a { --brand: red; color: --brand; }"],
  ])("uses upstream %s", async (id, css) => {
    expect(await warnings(css)).toContain(id);
  });
});
