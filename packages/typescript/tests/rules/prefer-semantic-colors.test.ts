import { mkdirSync, mkdtempSync, writeFileSync } from "fs";
import { tmpdir } from "os";
import { dirname, join } from "path";
import { describe } from "vitest";

import rule from "../../src/rules/prefer-semantic-colors.js";
import { ruleTester } from "./_tester.js";

const RULE_TESTER = ruleTester({ lang: "tsx" });

RULE_TESTER.run("prefer-semantic-colors", rule, {
  valid: [
    { name: "false class helper condition emits no class", code: "clsx({ 'bg-red-500': false });" },
    { name: "null class helper condition emits no class", code: "clsx({ 'bg-red-500': null });" },
    { name: "zero class helper condition emits no class", code: "clsx({ 'bg-red-500': 0 });" },
    { name: "empty class helper condition emits no class", code: "clsx({ 'bg-red-500': '' });" },
    { name: "class helper conditions are not class fragments", code: "clsx({ 'text-primary': 'text-red-500' });" },
    { name: "URL fragment is not a color", code: '<div style={{ fill: "url(#abc)", background: "url(image.svg#abcdef)" }} />' },
    { name: "public no-match example", filename: "src/notice.tsx", code: 'const notice = <div className="text-destructive" />;' },
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

    { code: `const x = <div className="bg-primary text-destructive border-border" />;` },
    { code: `const x = <div className="bg-card text-muted-foreground bg-chart-1" />;` },
    { code: `const x = <div className="bg-primary/10 text-foreground/90" />;` },

    { code: `const x = <div className="text-white bg-black/50" />;` },
    { code: `const x = <path fill="white" />;` },

    { code: `const x = <div className="w-[437px] grid-cols-[auto_1fr] max-h-[80vh]" />;` },

    { code: `const x = <div style={{ color: "var(--primary)" }} />;` },
    { code: `const x = <path fill="currentColor" stroke="none" />;` },

    { code: `const x = <svg><clipPath id="a"><path fill="#fff" d="M0 0h1v1H0z" /></clipPath></svg>;` },
    { code: `const x = <svg><mask id="m"><rect fill="#fff" /><rect fill="#000" /></mask></svg>;` },

    { code: `const x = <svg><path fill="#e6e6e6" d="M0 0h1v1H0z" /></svg>;` },
    { code: `const x = <svg viewBox="0 0 20 20"><circle fill="#d0d6d7" cx="10" cy="10" r="5" /><polygon stroke="#D06B64" points="0,0 1,1" /></svg>;` },
    { code: `const x = <svg><linearGradient><stop stopColor="#D06B64" /></linearGradient></svg>;` },
    {
      code: `const x = <StyledSvg><path fill="#e7e1ec" /><path stroke="#2f1d4a" /></StyledSvg>;`,
    },

    {
      code: `export const Pin = createIcon({ path: <g><path fill="#017cee" /><path fill="#00ad46" /></g> });`,
    },

    { code: `const x = <path fill="#fff" stroke="#000" />;` },
    { code: `const x = <path fill="transparent" stroke="inherit" />;` },

    {
      code: `const x = <div style={{ color: "#ff0000" }} className="bg-red-500" />;`,
      filename: "Button.stories.tsx",
    },
    {
      name: "allows semantic tokens in every supported class helper",
      code: `const x = [cn("bg-primary"), clsx("text-foreground"), cva("bg-muted"), tv("text-accent"), cx("border-border"), twMerge("ring-ring"), classnames("fill-primary"), classNames("stroke-primary")];`,
    },

    { code: `const safelist = ["bg-red-500", "text-blue-600"];` },
    { code: `expect(el).toHaveClass("bg-red-500");` },
    { code: `const msg = "apply the bg-red-500 class for errors";` },
    { code: `const COLOR_MAP = { connectivity: "bg-red-500", flow: "bg-blue-500" };` },
  ],
  invalid: [
    { name: "URL followed by a real color remains checked", code: '<div style={{ background: "url(#abc) #ff0000" }} />', errors: [{ messageId: "inlineColor" }] },
    { name: "public match example", filename: "src/notice.tsx", code: 'const notice = <div className="text-red-500" />;', errors: [{ messageId: "rawPalette" }] },
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

    {
      code: `const x = <div className="bg-[oklch(0.7_0.1_200)]" />;`,
      errors: [{ messageId: "arbitraryColor" }],
    },

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
      code: `const x = cn([active ? "bg-red-500" : "bg-blue-500", { "text-amber-500": warning }]);`,
      errors: [
        { messageId: "rawPalette" },
        { messageId: "rawPalette" },
        { messageId: "rawPalette" },
      ],
    },

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

    {
      code: "const x = <div className={`text-blue-600 ${extra}`} />;",
      errors: [{ messageId: "rawPalette" }],
    },

    {
      code: `const x = <div style={{ color: "#111827", backgroundColor: "#fff" }} />;`,
      errors: [{ messageId: "inlineColor" }, { messageId: "inlineColor" }],
    },
    {
      code: `const x = <div style={{ color: "#ff0000" }} />;`,
      errors: [{ messageId: "inlineColor" }],
    },

    {
      code: `const x = <Badge fill="#7c3aed" />;`,
      errors: [{ messageId: "inlineColor" }],
    },

    {
      code: `const x = <div className="border-neutral-200 text-neutral-500 bg-slate-50 ring-red-950" />;`,
      errors: [
        { messageId: "rawPalette" },
        { messageId: "rawPalette" },
        { messageId: "rawPalette" },
        { messageId: "rawPalette" },
      ],
    },

    {
      code: `const x = <div style={{ color: "hsl(210, 40%, 98%)" }} />;`,
      errors: [{ messageId: "inlineColor" }],
    },

    {
      code: `const x = <circle className="fill-red-500" style={{ stroke: "#7c3aed" }} />;`,
      errors: [{ messageId: "rawPalette" }, { messageId: "inlineColor" }],
    },

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

const SOURCE = `const x = <div className="text-neutral-800" />;\n`;
const RAW_PALETTE_COMPONENT = `export const Badge = () => <span className="text-red-500" />;`;

interface Options {
  readonly requireSemanticTokens?: boolean;
  readonly opaqueForegroundPairs?: boolean;
}

interface LintCase {
  readonly name: string;
  readonly code: string;
  readonly filename: string;
  readonly cwd: string;
  readonly options: [Options];
  readonly errors?: { messageId: string }[];
  before(): void;
}

function lintCase(name: string, root: string, relative: string, code: string, options: Options, expected: readonly string[]): LintCase {
  const testCase: LintCase = { name, code, filename: join(root, relative), cwd: root, options: [options], before() {} };
  return expected.length === 0 ? testCase : { ...testCase, errors: expected.map((messageId) => ({ messageId })) };
}

function runCases(title: string, cases: readonly LintCase[]): void {
  const valid: LintCase[] = [];
  const invalid: (LintCase & { errors: { messageId: string }[] })[] = [];
  for (const entry of cases) {
    if (entry.errors === undefined) valid.push(entry);
    else invalid.push({ ...entry, errors: entry.errors });
  }
  RULE_TESTER.run(title, rule, { valid, invalid });
}

function runSequence(title: string, cases: readonly LintCase[]): void {
  cases.forEach((entry, index) => runCases(`${title} #${index + 1}`, [entry]));
}

function countCase(name: string, root: string, relative: string, count: 0 | 1): LintCase {
  return lintCase(name, root, relative, SOURCE, { requireSemanticTokens: true }, count === 0 ? [] : ["rawPalette"]);
}

function fileCase(name: string, root: string, relative: string, options: Options, expected: readonly string[]): LintCase {
  return lintCase(name, root, relative, RAW_PALETTE_COMPONENT, options, expected);
}

function project(marker: string | null, contents = ""): string {
  const root = mkdtempSync(join(tmpdir(), "sarj-psc-"));
  mkdirSync(join(root, "src", "components"), { recursive: true });
  if (marker !== null) writeFileSync(join(root, marker), contents);
  return root;
}

function tree(files: Readonly<Record<string, string>>): string {
  const root = mkdtempSync(join(tmpdir(), "sarj-psc-"));
  for (const [relative, contents] of Object.entries(files)) {
    const absolute = join(root, relative);
    mkdirSync(dirname(absolute), { recursive: true });
    writeFileSync(absolute, contents);
  }
  return root;
}

function makeRepo(files: Readonly<Record<string, string>>): string {
  const root = mkdtempSync(join(tmpdir(), "sarj-semantic-"));
  for (const [rel, contents] of Object.entries(files)) {
    const abs = join(root, rel);
    mkdirSync(dirname(abs), { recursive: true });
    writeFileSync(abs, contents, "utf8");
  }
  return root;
}

const TAILWIND_CONFIG =
  'export default { theme: { extend: { colors: { primary: "hsl(var(--primary))" } } } };\n';

describe("prefer-semantic-colors requireSemanticTokens gate", () => {
  runCases("requireSemanticTokens gate", [
    countCase(
      "accepts a tailwind config whose token vocabulary is not shadcn's",
      project("tailwind.config.cjs", "module.exports = { theme: { extend: { colors: { 'ui-fg-subtle': 'var(--fg-subtle)' } } } };\n"),
      "src/components/Thing.tsx",
      1,
    ),
    countCase(
      "accepts a Tailwind v4 @theme stylesheet, which has no config file at all",
      project("src/index.css", '@import "tailwindcss";\n@theme {\n  --color-brand: #123456;\n}\n'),
      "src/components/Thing.tsx",
      1,
    ),
    countCase("still stays silent in a project with no design-system marker anywhere", project(null), "src/components/Thing.tsx", 0),
    countCase(
      "finds a token config in a SIBLING workspace package",
      tree({
        "apps/web/app/(dashboard)/settings/badge.tsx": SOURCE,
        "apps/web/package.json": '{"name":"web"}\n',
        "package.json": '{"name":"root","workspaces":["apps/*","packages/*"]}\n',
        "packages/tailwind-config/package.json": '{"name":"tailwind-config"}\n',
        "packages/tailwind-config/tailwind.config.ts": TAILWIND_CONFIG,
      }),
      "apps/web/app/(dashboard)/settings/badge.tsx",
      1,
    ),
    countCase(
      "finds a sibling token config declared through pnpm-workspace.yaml",
      tree({
        "apps/site/src/badge.tsx": SOURCE,
        "packages/ui/components.json": '{"style":"default"}\n',
        "pnpm-workspace.yaml": "packages:\n  - 'apps/*'\n  - 'packages/*'\n",
      }),
      "apps/site/src/badge.tsx",
      1,
    ),
    countCase(
      "reaches a marker more than eight directories up",
      tree({ "a/b/c/d/e/f/g/h/i/badge.tsx": SOURCE, "components.json": '{"style":"default"}\n' }),
      "a/b/c/d/e/f/g/h/i/badge.tsx",
      1,
    ),
  ]);

  const deep = "a/b/c/d/e/f/g/h/i/deep.tsx";
  const shallow = "a/b/c/shallow.tsx";
  const files = { [deep]: SOURCE, [shallow]: SOURCE, "components.json": '{"style":"default"}\n' };
  const deepFirstRoot = tree(files);
  const shallowFirstRoot = tree(files);
  runSequence("gives the same answer whichever file is linted first", [
    countCase("deep first", deepFirstRoot, deep, 1),
    countCase("then shallow (not asserted in the original)", deepFirstRoot, shallow, 1),
    countCase("shallow first (not asserted in the original)", shallowFirstRoot, shallow, 1),
    countCase("deep after shallow", shallowFirstRoot, deep, 1),
  ]);
});

const SHADCN_CSS = `:root { --background: 0 0% 100%; --foreground: 222 47% 11%; }`;

describe("requireSemanticTokens gates on a real design system", () => {
  const bare = makeRepo({ "src/badge.tsx": "" });
  runSequence("requireSemanticTokens gates on a real design system", [
    fileCase("suppresses the rule when the option is on and no design system exists", makeRepo({ "src/badge.tsx": "" }), "src/badge.tsx", { requireSemanticTokens: true }, []),
    fileCase("still reports in that same tree when the option is off (default)", bare, "src/badge.tsx", {}, ["rawPalette"]),
    fileCase("still reports in that same tree when the option is off (false)", bare, "src/badge.tsx", { requireSemanticTokens: false }, ["rawPalette"]),
    fileCase("reports when the option is on and a design system does exist", makeRepo({ "components.json": "{}", "src/badge.tsx": "" }), "src/badge.tsx", { requireSemanticTokens: true }, ["rawPalette"]),
  ]);
});

describe("opaque foreground semantic-token enforcement", () => {
  const TOKENS = `:root {
    --background: 0 0% 100%;
    --primary: 222 47% 11%;
    --primary-foreground: 210 40% 98%;
  }`;
  const OPTIONS = { opaqueForegroundPairs: true } as const;

  function messages(name: string, source: string, expected: readonly string[], css: string = TOKENS): LintCase {
    const root = makeRepo({ "package.json": "{}", "app/globals.css": css, "src/app/card.tsx": source });
    return lintCase(name, root, "src/app/card.tsx", source, OPTIONS, expected);
  }

  runCases("opaque foreground semantic-token enforcement", [
    messages("reports a raw foreground only when its semantic pair is declared", `<button className="bg-primary text-white">Save</button>`, ["opaqueForegroundPair"]),
    messages("allows translucent overlays and unpaired foregrounds", `<><div className="bg-black/50" /><span className="text-white" /></>`, []),
    messages("allows exact paper colors in print-only variants", `<div className="print:bg-white print:text-black" />`, []),
    messages("allows a foreground when the matching semantic pair is not declared", `<button className="bg-primary text-white">Save</button>`, [], `:root { --primary: 222 47% 11%; }`),
    messages("keeps the existing raw-color diagnostics active without semantic tokens", `<div className="text-red-500" />`, ["rawPalette"], `body { margin: 0; }`),
    messages("excludes opaque utility classes inside SVG artwork", `<svg className="bg-white"><path className="text-white" /></svg>`, []),
    messages("excludes Remotion render trees", `import { AbsoluteFill } from "remotion"; <AbsoluteFill className="bg-white" />;`, []),
  ]);
});

describe("design-system detection covers systems that are not shadcn's", () => {
  const detected: Readonly<Record<string, Readonly<Record<string, string>>>> = {
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
    "a Tailwind v4 @theme block": {
      "src/index.css": `@import "tailwindcss";\n@theme {\n  --color-brand: oklch(0.7 0.1 200);\n}`,
    },
  };

  runCases("design-system detection", [
    ...Object.entries(detected).map(([name, files]) =>
      fileCase(`detects ${name}`, makeRepo({ ...files, "src/app/badge.tsx": "" }), "src/app/badge.tsx", { requireSemanticTokens: true }, ["rawPalette"])),
    fileCase(
      "does not treat a stylesheet without tokens as a design system",
      makeRepo({ "app/globals.css": `body { margin: 0; font-family: system-ui; }`, "src/app/badge.tsx": "" }),
      "src/app/badge.tsx",
      { requireSemanticTokens: true },
      [],
    ),
  ]);
});

describe("workspace detection", () => {
  runCases("workspace detection", [
    fileCase(
      "scans default package directories when a workspace declares no globs",
      makeRepo({ "apps/web/src/badge.tsx": "", "packages/ui/tailwind.config.ts": "export default {};", "turbo.json": "{}" }),
      "apps/web/src/badge.tsx",
      { requireSemanticTokens: true },
      ["rawPalette"],
    ),
  ]);
});

describe("the resolved-answer cache is order-independent", () => {
  const layout = {
    "components.json": "{}",
    "src/shallow.tsx": "",
    "src/features/nested/deep.tsx": "",
  };
  const relatives = ["src/shallow.tsx", "src/features/nested/deep.tsx"] as const;

  function lintInOrder(label: string, order: readonly string[]): LintCase[] {
    const root = makeRepo(layout);
    return order.map((rel) => fileCase(`${label}: ${rel}`, root, rel, { requireSemanticTokens: true }, ["rawPalette"]));
  }

  runSequence("gives every file the same answer whichever file warms the cache first", [
    ...lintInOrder("forward", relatives),
    ...lintInOrder("reversed", [...relatives].reverse()),
  ]);

  const root = makeRepo({ "src/a.tsx": "", "src/b.tsx": "" });
  runSequence("keeps a negative answer stable across repeated lints", [
    fileCase("a", root, "src/a.tsx", { requireSemanticTokens: true }, []),
    fileCase("b", root, "src/b.tsx", { requireSemanticTokens: true }, []),
    fileCase("a again", root, "src/a.tsx", { requireSemanticTokens: true }, []),
    fileCase("a with the option off", root, "src/a.tsx", {}, ["rawPalette"]),
  ]);
});
