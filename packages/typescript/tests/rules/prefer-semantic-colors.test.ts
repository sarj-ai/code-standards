import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

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
    { code: `const classification = "bg-red-500";` },
    { code: `const classroom = "bg-blue-600";` },
    { code: `const x = <div className="bg-[hsl(var(--primary))]" />;` },
    { code: `const x = <link rel="mask-icon" color="#5bbad5" />;` },
    { code: `const x = <path fill="#7c3aed" />;` },
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
  ],
});
