import { Linter } from "eslint";
import { mkdirSync, mkdtempSync, writeFileSync } from "fs";
import { tmpdir } from "os";
import { dirname, join } from "path";
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
    {
      name: "allows Radix semantic steps outside Tailwind's palette scale",
      code: `const x = <div className="text-gray-11 bg-gray-12" />;`,
    },
    {
      name: "allows CSS variables wrapped in color functions",
      code: `const x = <div style={{ color: "hsl(var(--primary))" }} />;`,
    },
    { code: `const x = <circle fill="hsl(var(--chart-selection))" />;` },
    { code: `const x = <div className="bg-[rgb(var(--content-error))]" />;` },
    // Intrinsic SVG shapes carry artwork colors under any wrapper.
    { code: `const x = <SomeIcon><circle fill="#1877F2" /><path stroke="#7c3aed" /></SomeIcon>;` },
    {
      name: "skips react-email files whose output cannot resolve CSS variables",
      code: `import { Tailwind } from "@react-email/components";\nconst x = <Tailwind><p className="text-neutral-800" /></Tailwind>;`,
    },
    {
      name: "skips react-pdf files whose output cannot resolve CSS variables",
      code: `import { View } from "@react-pdf/renderer";\nconst x = <View style={{ color: "#111827" }} />;`,
    },
    {
      name: "skips CommonJS react-pdf files",
      code: `const { View } = require("@react-pdf/renderer");\nconst x = <View style={{ color: "#111827" }} />;`,
    },
    {
      name: "skips dynamically imported react-email files",
      code: `const renderer = import("@react-email/components");\nconst x = <p className="text-neutral-800" />;`,
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
    {
      name: "allows semantic tokens in every supported class helper",
      code: `const x = [cn("bg-primary"), clsx("text-foreground"), cva("bg-muted"), tv("text-accent"), cx("border-border"), twMerge("ring-ring"), classnames("fill-primary"), classNames("stroke-primary")];`,
    },
    // NON-className strings must NOT be flagged (the scoping fix).
    { code: `const safelist = ["bg-red-500", "text-blue-600"];` },
    { code: `expect(el).toHaveClass("bg-red-500");` },
    { code: `const msg = "apply the bg-red-500 class for errors";` },
    { code: `const COLOR_MAP = { connectivity: "bg-red-500", flow: "bg-blue-500" };` },
  ],
  invalid: [
    {
      code: `const x = <div className="text-red-500" />;`,
      output: null,
      errors: [{ messageId: "rawPalette" }],
    },
    {
      name: "reports palette opacity modifiers",
      code: `const x = <div className="bg-slate-200/50" />;`,
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
    {
      code: `const x = clsx("bg-red-500", active && "text-blue-600");`,
      errors: [{ messageId: "rawPalette" }, { messageId: "rawPalette" }],
    },
    {
      code: `const styles = tv({ base: "bg-red-500", variants: { tone: { bad: "text-blue-600" } } });`,
      errors: [{ messageId: "rawPalette" }, { messageId: "rawPalette" }],
    },
    {
      name: "reports every supported class helper",
      code: `const x = [cx("bg-red-500"), twMerge("text-blue-600"), classnames("border-rose-500"), classNames("ring-amber-500")];`,
      errors: [
        { messageId: "rawPalette" },
        { messageId: "rawPalette" },
        { messageId: "rawPalette" },
        { messageId: "rawPalette" },
      ],
    },
    {
      name: "recurses through class arrays and conditional branches",
      code: `const x = cn([active ? "bg-red-500" : "bg-blue-500", { warning: "text-amber-500" }]);`,
      errors: [
        { messageId: "rawPalette" },
        { messageId: "rawPalette" },
        { messageId: "rawPalette" },
      ],
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
    {
      name: "reports non-exact class-named object properties",
      code: `const props = { activeClass: "text-rose-500" };`,
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
    // Component fill props are styling; intrinsic SVG fill attributes are artwork.
    {
      code: `const x = <Badge fill="#7c3aed" />;`,
      errors: [{ messageId: "inlineColor" }],
    },

    // Tailwind's actual palette steps remain reportable.
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
    {
      name: "does not skip a file that only mentions a renderer module",
      code: `const renderer = "@react-pdf/renderer";\nconst x = <div className="text-neutral-800" />;`,
      errors: [{ messageId: "rawPalette" }],
    },
  ],
});

/** Filesystem-backed gate tests use real temporary projects. */
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

/** Build an isolated project tree so module-level caches cannot cross test cases. */
function tree(files: Readonly<Record<string, string>>): string {
  const root = mkdtempSync(join(tmpdir(), "sarj-psc-"));
  for (const [relative, contents] of Object.entries(files)) {
    const absolute = join(root, relative);
    mkdirSync(dirname(absolute), { recursive: true });
    writeFileSync(absolute, contents);
  }
  return root;
}

/** A shadcn-shaped Tailwind v3 theme. */
const TAILWIND_CONFIG =
  'export default { theme: { extend: { colors: { primary: "hsl(var(--primary))" } } } };\n';

describe("prefer-semantic-colors requireSemanticTokens gate", () => {
  it("accepts a tailwind config whose token vocabulary is not shadcn's", () => {
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
    const root = project(null);
    expect(countIn(root, "src/components/Thing.tsx")).toBe(0);
  });

  it("finds a token config in a SIBLING workspace package", () => {
    const root = tree({
      "apps/web/app/(dashboard)/settings/badge.tsx": SOURCE,
      "apps/web/package.json": '{"name":"web"}\n',
      "package.json": '{"name":"root","workspaces":["apps/*","packages/*"]}\n',
      "packages/tailwind-config/package.json": '{"name":"tailwind-config"}\n',
      "packages/tailwind-config/tailwind.config.ts": TAILWIND_CONFIG,
    });
    expect(countIn(root, "apps/web/app/(dashboard)/settings/badge.tsx")).toBe(1);
  });

  it("finds a sibling token config declared through pnpm-workspace.yaml", () => {
    const root = tree({
      "apps/site/src/badge.tsx": SOURCE,
      "packages/ui/components.json": '{"style":"default"}\n',
      "pnpm-workspace.yaml": "packages:\n  - 'apps/*'\n  - 'packages/*'\n",
    });
    expect(countIn(root, "apps/site/src/badge.tsx")).toBe(1);
  });

  it("reaches a marker more than eight directories up", () => {
    const deep = "a/b/c/d/e/f/g/h/i/badge.tsx";
    const root = tree({ [deep]: SOURCE, "components.json": '{"style":"default"}\n' });
    expect(countIn(root, deep)).toBe(1);
  });

  it("gives the same answer whichever file is linted first", () => {
    const deep = "a/b/c/d/e/f/g/h/i/deep.tsx";
    const shallow = "a/b/c/shallow.tsx";
    const files = {
      [deep]: SOURCE,
      [shallow]: SOURCE,
      "components.json": '{"style":"default"}\n',
    };

    const deepFirstRoot = tree(files);
    const deepFirst = countIn(deepFirstRoot, deep);
    countIn(deepFirstRoot, shallow);

    const shallowFirstRoot = tree(files);
    countIn(shallowFirstRoot, shallow);
    const deepAfterShallow = countIn(shallowFirstRoot, deep);

    expect(deepFirst).toBe(deepAfterShallow);
    expect(deepFirst).toBe(1);
  });
});

/** Exercise filesystem detection and its process-wide caches with real paths. */

const RULE_ID = "sarj/prefer-semantic-colors";

/** A component with exactly one raw palette class, so counts are unambiguous. */
const RAW_PALETTE_COMPONENT = `export const Badge = () => <span className="text-red-500" />;`;

interface Options {
  readonly requireSemanticTokens?: boolean;
}

function lintFile(root: string, filename: string, options: Options = {}): string[] {
  // Assert harness noise so a configuration miss cannot masquerade as a clean lint.
  const linter = new Linter({ cwd: root });
  const messages = linter.verify(
    RAW_PALETTE_COMPONENT,
    {
      files: ["**/*.tsx"],
      plugins: { sarj: { rules: { "prefer-semantic-colors": rule as never } } },
      languageOptions: { parser: tsParser as never, parserOptions: { ecmaFeatures: { jsx: true } } },
      rules: { [RULE_ID]: ["error", options] },
    } as never,
    filename,
  );
  const noise = messages.filter((message) => message.ruleId !== RULE_ID);
  expect(noise, `harness produced non-rule messages: ${JSON.stringify(noise)}`).toEqual([]);
  return messages.map((message) => message.messageId ?? "?");
}

/** Create a temp tree; every scenario gets a fresh root so the module cache cannot bleed. */
function makeRepo(files: Readonly<Record<string, string>>): string {
  const root = mkdtempSync(join(tmpdir(), "sarj-semantic-"));
  for (const [rel, contents] of Object.entries(files)) {
    const abs = join(root, rel);
    mkdirSync(dirname(abs), { recursive: true });
    writeFileSync(abs, contents, "utf8");
  }
  return root;
}

const SHADCN_CSS = `:root { --background: 0 0% 100%; --foreground: 222 47% 11%; }`;

describe("requireSemanticTokens gates on a real design system", () => {
  it("suppresses the rule when the option is on and no design system exists", () => {
    const root = makeRepo({ "src/badge.tsx": "" });
    expect(lintFile(root, join(root, "src/badge.tsx"), { requireSemanticTokens: true })).toEqual([]);
  });

  it("still reports in that same tree when the option is off", () => {
    const root = makeRepo({ "src/badge.tsx": "" });
    expect(lintFile(root, join(root, "src/badge.tsx"), {})).toEqual(["rawPalette"]);
    expect(lintFile(root, join(root, "src/badge.tsx"), { requireSemanticTokens: false })).toEqual([
      "rawPalette",
    ]);
  });

  it("reports when the option is on and a design system does exist", () => {
    const root = makeRepo({ "components.json": "{}", "src/badge.tsx": "" });
    expect(lintFile(root, join(root, "src/badge.tsx"), { requireSemanticTokens: true })).toEqual([
      "rawPalette",
    ]);
  });
});

describe("design-system detection covers systems that are not shadcn's", () => {
  const detected: Readonly<Record<string, Readonly<Record<string, string>>>> = {
    // Config presence counts even when a preset owns the vocabulary.
    "a tailwind.config.js with only a preset": {
      "tailwind.config.js": `module.exports = { presets: [require("@medusajs/ui-preset")] };`,
    },
    "a tailwind.config.ts": { "tailwind.config.ts": `export default {};` },
    "a tailwind.config.mjs": { "tailwind.config.mjs": `export default {};` },
    "a tailwind.config.mts": { "tailwind.config.mts": `export default {};` },
    "a tailwind.config.cts": { "tailwind.config.cts": `export default {};` },
    "components.json": { "components.json": "{}" },
    "medusa-style ui tokens in a stylesheet": {
      "app/globals.css": `.x { @apply bg-ui-bg-base text-ui-fg-subtle; }`,
    },
    "medusa-style custom properties": { "app/globals.css": `:root { --fg-base: #000; }` },
    "dub-style content/default tokens": {
      "src/styles/globals.css": `:root { --content-error: 1 2 3; } .y { @apply bg-default; }`,
    },
    "shadcn custom properties": { "app/globals.css": SHADCN_CSS },
    // Tailwind v4 is CSS-first: no config file exists to find.
    "a Tailwind v4 @theme block": {
      "src/index.css": `@import "tailwindcss";\n@theme {\n  --color-brand: oklch(0.7 0.1 200);\n}`,
    },
  };

  it.each(Object.entries(detected))("detects %s", (_name, files) => {
    const root = makeRepo({ ...files, "src/app/badge.tsx": "" });
    expect(lintFile(root, join(root, "src/app/badge.tsx"), { requireSemanticTokens: true })).toEqual([
      "rawPalette",
    ]);
  });

  it("does not treat a stylesheet without tokens as a design system", () => {
    const root = makeRepo({
      "app/globals.css": `body { margin: 0; font-family: system-ui; }`,
      "src/app/badge.tsx": "",
    });
    expect(lintFile(root, join(root, "src/app/badge.tsx"), { requireSemanticTokens: true })).toEqual([]);
  });
});

describe("workspace detection", () => {
  it("scans default package directories when a workspace declares no globs", () => {
    const root = makeRepo({
      "apps/web/src/badge.tsx": "",
      "packages/ui/tailwind.config.ts": "export default {};",
      "turbo.json": "{}",
    });
    expect(
      lintFile(root, join(root, "apps/web/src/badge.tsx"), { requireSemanticTokens: true }),
    ).toEqual(["rawPalette"]);
  });
});

describe("the resolved-answer cache is order-independent", () => {
  // Each order gets a fresh tree because cache keys are absolute paths.
  const layout = {
    "components.json": "{}",
    "src/shallow.tsx": "",
    "src/features/nested/deep.tsx": "",
  };
  const relatives = ["src/shallow.tsx", "src/features/nested/deep.tsx"] as const;

  function lintInOrder(order: readonly string[]): Record<string, string[]> {
    const root = makeRepo(layout);
    const out: Record<string, string[]> = {};
    for (const rel of order) {
      out[rel] = lintFile(root, join(root, rel), { requireSemanticTokens: true });
    }
    return out;
  }

  it("gives every file the same answer whichever file warms the cache first", () => {
    const forward = lintInOrder(relatives);
    const reversed = lintInOrder([...relatives].reverse());

    expect(forward).toEqual(reversed);
    // Equality alone would also accept two incorrect empty results.
    for (const rel of relatives) {
      expect(forward[rel], `${rel} in forward order`).toEqual(["rawPalette"]);
      expect(reversed[rel], `${rel} in reverse order`).toEqual(["rawPalette"]);
    }
  });

  it("keeps a negative answer stable across repeated lints", () => {
    const root = makeRepo({ "src/a.tsx": "", "src/b.tsx": "" });
    expect(lintFile(root, join(root, "src/a.tsx"), { requireSemanticTokens: true })).toEqual([]);
    expect(lintFile(root, join(root, "src/b.tsx"), { requireSemanticTokens: true })).toEqual([]);
    expect(lintFile(root, join(root, "src/a.tsx"), { requireSemanticTokens: true })).toEqual([]);
    // Positive control: the tree really was lintable, the rule really was inert.
    expect(lintFile(root, join(root, "src/a.tsx"), {})).toEqual(["rawPalette"]);
  });
});
