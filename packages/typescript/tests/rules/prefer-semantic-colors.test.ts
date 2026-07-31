import { Linter } from "eslint";
import { mkdirSync, mkdtempSync, writeFileSync } from "fs";
import { tmpdir } from "os";
import { join } from "path";
import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, expect, it } from "vitest";

import rule from "../../src/rules/prefer-semantic-colors.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const ruleTester = new RuleTester({
  languageOptions: { parser: tsParser, parserOptions: { ecmaFeatures: { jsx: true } } },
});

ruleTester.run("prefer-semantic-colors", rule, {
  valid: [
    // --- FP guards measured over 20,846 corpus findings (2026-07 audit) ---
    // A Radix-style 1-12 step is a theme-aware SEMANTIC step, not a Tailwind
    // palette step. 777 findings (3.7%) were this shape, and the rule was
    // self-evidently inconsistent about it: `gray-9` and `grayA-3` in the same
    // files never fired, because one digit does not match the old `\d{2,3}`.
    { code: `const x = <div className="text-gray-11 bg-gray-12" />;` },
    // A color function wrapping a CSS variable IS a token reference. 63 findings.
    { code: `const x = <div style={{ color: "hsl(var(--primary))" }} />;` },
    { code: `const x = <circle fill="hsl(var(--chart-selection))" />;` },
    { code: `const x = <div className="bg-[rgb(var(--content-error))]" />;` },
    // Intrinsic SVG shape primitives carry drawing data, whatever the wrapper is
    // called. The ancestor walk missed artwork under `<SomethingIcon>` because
    // `isSvgLikeElementName` only matches names ENDING in "svg".
    { code: `const x = <SomeIcon><circle fill="#1877F2" /><path stroke="#7c3aed" /></SomeIcon>;` },
    // react-email / react-pdf: CSS-variable tokens cannot resolve in a mail
    // client or a PDF renderer, so raw palette classes are correct there. 985
    // findings (4.7%).
    {
      code: `import { Tailwind } from "@react-email/components";\nconst x = <Tailwind><p className="text-neutral-800" /></Tailwind>;`,
    },

    // Semantic tokens pass.
    { code: `const x = <div className="bg-primary text-destructive border-border" />;` },
    { code: `const x = <div className="bg-card text-muted-foreground bg-chart-1" />;` },
    { code: `const x = <div className="bg-primary/10 text-foreground/90" />;` },
    // white/black / overlay idiom are allowed (rarely have a token equivalent).
    { code: `const x = <div className="text-white bg-black/50" />;` },
    { code: `const x = <path fill="white" />;` },
    // Non-color arbitrary values must NOT be flagged.
    { code: `const x = <div className="w-[437px] grid-cols-[auto_1fr] max-h-[80vh]" />;` },
    // CSS variables / currentColor / none.
    { code: `const x = <div style={{ color: "var(--primary)" }} />;` },
    { code: `const x = <path fill="currentColor" stroke="none" />;` },
    // SVG defs-container children carry structural fills — masking breaks without
    // literal #fff/#000, so fill/stroke inside them never fires.
    { code: `const x = <svg><clipPath id="a"><path fill="#fff" d="M0 0h1v1H0z" /></clipPath></svg>;` },
    { code: `const x = <svg><mask id="m"><rect fill="#fff" /><rect fill="#000" /></mask></svg>;` },
    // SVG artwork drawing elements (not just defs containers) carry inherent
    // illustration colors — not reusable UI tokens.
    { code: `const x = <svg><path fill="#e6e6e6" d="M0 0h1v1H0z" /></svg>;` },
    { code: `const x = <svg viewBox="0 0 20 20"><circle fill="#d0d6d7" cx="10" cy="10" r="5" /><polygon stroke="#D06B64" points="0,0 1,1" /></svg>;` },
    { code: `const x = <svg><linearGradient><stop stopColor="#D06B64" /></linearGradient></svg>;` },
    {
      code: `const x = <StyledSvg><path fill="#e7e1ec" /><path stroke="#2f1d4a" /></StyledSvg>;`,
    },
    // Icon factories often accept raw SVG path fragments rather than a literal
    // <svg> wrapper; these are still artwork colors, not component styling.
    {
      code: `export const Pin = createIcon({ path: <g><path fill="#017cee" /><path fill="#00ad46" /></g> });`,
    },
    // Neutral drawing literals are exempt on fill/stroke everywhere.
    { code: `const x = <path fill="#fff" stroke="#000" />;` },
    { code: `const x = <path fill="transparent" stroke="inherit" />;` },
    // Storybook fixtures are skipped like test files.
    {
      code: `const x = <div style={{ color: "#ff0000" }} className="bg-red-500" />;`,
      filename: "Button.stories.tsx",
    },
    // cn() with semantic tokens.
    { code: `const x = cn("bg-primary", "text-foreground", { "bg-muted": active });` },
    // NON-className strings must NOT be flagged (the scoping fix).
    { code: `const safelist = ["bg-red-500", "text-blue-600"];` },
    { code: `expect(el).toHaveClass("bg-red-500");` },
    { code: `const msg = "apply the bg-red-500 class for errors";` },
    { code: `const COLOR_MAP = { connectivity: "bg-red-500", flow: "bg-blue-500" };` },
  ],
  invalid: [
    {
      code: `const x = <div className="text-red-500" />;`,
      errors: [{ messageId: "rawPalette" }],
    },
    {
      code: `const x = <div className="bg-slate-200 hover:bg-slate-50" />;`,
      errors: [{ messageId: "rawPalette" }, { messageId: "rawPalette" }],
    },
    // border-side + placeholder prefixes.
    {
      code: `const x = <div className="border-t-red-500 placeholder-gray-400" />;`,
      errors: [{ messageId: "rawPalette" }, { messageId: "rawPalette" }],
    },
    {
      code: `const x = <div className="bg-[#fff]" />;`,
      errors: [{ messageId: "arbitraryColor" }],
    },
    {
      code: `const x = <div className="text-[rgb(0,0,0)]" />;`,
      errors: [{ messageId: "arbitraryColor" }],
    },
    // Tailwind v4 color functions.
    {
      code: `const x = <div className="bg-[oklch(0.7_0.1_200)]" />;`,
      errors: [{ messageId: "arbitraryColor" }],
    },
    // cn() args + cva variant objects.
    {
      code: `const x = cn("bg-emerald-500", "text-foreground");`,
      errors: [{ messageId: "rawPalette" }],
    },
    {
      code: `const v = cva("inline-flex", { variants: { tone: { bad: "bg-red-500" } } });`,
      errors: [{ messageId: "rawPalette" }],
    },
    // className-named variable + className-keyed property.
    {
      code: `const buttonClassName = "bg-blue-600";`,
      errors: [{ messageId: "rawPalette" }],
    },
    {
      code: `const props = { className: "bg-pink-500" };`,
      errors: [{ messageId: "rawPalette" }],
    },
    // Template literal static part.
    {
      code: "const x = <div className={`text-blue-600 ${extra}`} />;",
      errors: [{ messageId: "rawPalette" }],
    },
    // Inline style objects are real component styling — neutral literals still fire
    // there (unlike SVG fill/stroke attributes).
    {
      code: `const x = <div style={{ color: "#111827", backgroundColor: "#fff" }} />;`,
      errors: [{ messageId: "inlineColor" }, { messageId: "inlineColor" }],
    },
    {
      code: `const x = <div style={{ color: "#ff0000" }} />;`,
      errors: [{ messageId: "inlineColor" }],
    },
    // A `fill` on a COMPONENT element is a styling prop, not drawing data, so it
    // still fires. This replaces an earlier case that asserted `<path
    // fill="#7c3aed" />` reports: `<path>` is an intrinsic SVG shape primitive
    // and is now exempt wherever it sits (see SVG_SHAPE_PRIMITIVES). That case
    // only reported because the ancestor walk found no `<svg>`, which is an
    // accident of the fixture rather than a property of the code — real artwork
    // under a wrapper whose name does not end in "svg" hit the same path and was
    // the false positive the guard removes.
    {
      code: `const x = <Badge fill="#7c3aed" />;`,
      errors: [{ messageId: "inlineColor" }],
    },

    // --- Upper bounds on the four guards above, so none can silently widen ---
    // Real Tailwind palette steps still fire. Without this, narrowing the step
    // pattern any further would take the rule's whole population with it: the
    // two loudest single classes in the corpus are `border-neutral-200` (1,167)
    // and `text-neutral-500` (943), both of this shape.
    {
      code: `const x = <div className="border-neutral-200 text-neutral-500 bg-slate-50 ring-red-950" />;`,
      errors: [
        { messageId: "rawPalette" },
        { messageId: "rawPalette" },
        { messageId: "rawPalette" },
        { messageId: "rawPalette" },
      ],
    },
    // A literal color inside a color function still fires — only `var(--…)` is
    // exempt, not every `hsl(...)`.
    {
      code: `const x = <div style={{ color: "hsl(210, 40%, 98%)" }} />;`,
      errors: [{ messageId: "inlineColor" }],
    },
    // `className` and inline `style` are untouched by the SVG-primitive guard:
    // those are component styling, not drawing data, even on a primitive.
    {
      code: `const x = <circle className="fill-red-500" style={{ stroke: "#7c3aed" }} />;`,
      errors: [{ messageId: "rawPalette" }, { messageId: "inlineColor" }],
    },
    // A file that merely mentions email still fires; the exemption keys on a
    // react-email / react-pdf import, not on a filename or a word.
    {
      code: `const subject = "email";\nconst x = <div className="text-neutral-800" />;`,
      errors: [{ messageId: "rawPalette" }],
    },
  ],
});

/**
 * `requireSemanticTokens` reads the FILESYSTEM, so RuleTester cannot exercise
 * it: every one of these cases is a claim about which marker files count as
 * proof that a design system exists, and the shipped strict config turns the
 * option on. It was untested, and the untested half is what silenced whole
 * repositories.
 */
const SOURCE = `const x = <div className="text-neutral-800" />;\n`;

function countIn(root: string, relative: string): number {
  const linter = new Linter({ configType: "flat", cwd: root });
  const filename = join(root, relative);
  const messages = linter.verify(SOURCE, [
    {
      files: ["**/*.tsx"],
      plugins: { local: { rules: { "prefer-semantic-colors": rule } } },
      languageOptions: {
        parser: tsParser,
        parserOptions: { ecmaFeatures: { jsx: true } },
      },
      rules: {
        "local/prefer-semantic-colors": ["error", { requireSemanticTokens: true }],
      },
    },
  ], filename);
  return messages.filter((m) => m.ruleId).length;
}

function project(marker: string | null, contents = ""): string {
  const root = mkdtempSync(join(tmpdir(), "sarj-psc-"));
  mkdirSync(join(root, "src", "components"), { recursive: true });
  if (marker !== null) writeFileSync(join(root, marker), contents);
  return root;
}

describe("prefer-semantic-colors requireSemanticTokens gate", () => {
  it("accepts a tailwind config whose token vocabulary is not shadcn's", () => {
    // `medusa/packages/admin/dashboard/tailwind.config.cjs` exists, is in
    // DETECTION_FILES, sits well inside the depth budget — and was REJECTED
    // because Medusa names its tokens `bg-ui-button-neutral` / `text-ui-fg-subtle`.
    // The whole repository (34 findings) went silent on a vocabulary mismatch.
    const root = project(
      "tailwind.config.cjs",
      "module.exports = { theme: { extend: { colors: { 'ui-fg-subtle': 'var(--fg-subtle)' } } } };\n",
    );
    expect(countIn(root, "src/components/Thing.tsx")).toBe(1);
  });

  it("accepts a Tailwind v4 @theme stylesheet, which has no config file at all", () => {
    const root = project("src/index.css", '@import "tailwindcss";\n@theme {\n  --color-brand: #123456;\n}\n');
    expect(countIn(root, "src/components/Thing.tsx")).toBe(1);
  });

  it("still stays silent in a project with no design-system marker anywhere", () => {
    // Not a regression to fix: `twenty` and `outline` carry no tailwind config,
    // no components.json and no token stylesheet, because neither is a Tailwind
    // project. The option is documented to ask whether tokens exist, and the
    // answer there is no.
    const root = project(null);
    expect(countIn(root, "src/components/Thing.tsx")).toBe(0);
  });
});
