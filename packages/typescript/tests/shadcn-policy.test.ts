import { mkdtemp, mkdir, realpath, rm, symlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { ESLint, type Linter } from "eslint";
import { afterAll, beforeAll, describe, expect, it } from "vitest";

import {
  createConfig,
} from "../../standards/src/sarj_standards/configs/eslint.strict.mjs";

const createStrictConfig = createConfig as (options: {
  projectService: boolean;
  tsconfigRootDir: string;
}) => Linter.Config[];
const SHADCN_RULES = [
  "shadcn/no-restyle",
  "shadcn/no-arbitrary-values",
  "shadcn/no-inline-styles",
  "shadcn/no-unknown-classes",
  "shadcn/require-static-classes",
] as const;

let root: string;

async function fixture(path: string, source: string): Promise<void> {
  const destination = join(root, path);
  await mkdir(dirname(destination), { recursive: true });
  await writeFile(destination, source);
}

function linter(extraConfig: Linter.Config[] = [], rules: readonly string[] = SHADCN_RULES): ESLint {
  return new ESLint({
    cwd: root,
    overrideConfigFile: true,
    overrideConfig: [
      ...createStrictConfig({ projectService: false, tsconfigRootDir: root }),
      ...extraConfig,
    ],
    ruleFilter: ({ ruleId }) => rules.includes(ruleId),
  });
}

async function messages(source: string, path = "app/src/page.tsx", extraConfig: Linter.Config[] = []) {
  const [result] = await linter(extraConfig).lintText(source, { filePath: path });
  expect(result).toMatchObject({ fatalErrorCount: 0, errorCount: 0 });
  return result.messages;
}

beforeAll(async () => {
  root = await realpath(await mkdtemp(join(tmpdir(), "sarj-shadcn-policy-")));
  await symlink(fileURLToPath(new URL("../node_modules/", import.meta.url)), join(root, "node_modules"), "dir");
  await fixture("package.json", '{"name":"policy-fixtures","private":true}');
  await fixture("plain/package.json", '{"name":"plain-css","private":true}');
  await fixture("plain/src/styles.css", ".legacy-card { width: 120px; }");
  await fixture("app/package.json", '{"name":"tailwind-app","private":true}');
  await fixture("app/components.json", JSON.stringify({
    aliases: { ui: "@/ds" },
    tailwind: { css: "src/theme.css" },
  }));
  await fixture("app/tsconfig.json", JSON.stringify({
    compilerOptions: { baseUrl: ".", paths: { "@/*": ["./src/*"] } },
  }));
  await fixture("app/src/theme.css", '@import "tailwindcss"; @theme { --color-primary: #123456; } @utility tap-target { min-height: 44px; } .legacy-card { display: block; }');
  await fixture("app/src/ds/button.tsx", 'export const Button = ({ className }) => <button type="button" className={className} />;');
  await fixture("app/src/ds/index.ts", 'export { Button as Action } from "./button";');
  await fixture("app/src/other-button.tsx", 'export const Button = ({ className }) => <button type="button" className={className} />;');
  await fixture("app/src/save-button.tsx", 'import { Button } from "./ds/button"; export const SaveButton = ({ className }) => <Button className={className} />;');
  await fixture("app/src/utils.ts", 'export const cn = (...values) => values.join(" ");');
  await fixture("auto/package.json", '{"name":"tailwind-without-shadcn","private":true}');
  await fixture("auto/src/theme.css", '@import "tailwindcss"; @theme { --color-primary: #123456; }');
});

afterAll(async () => {
  await rm(root, { recursive: true, force: true });
});

describe("shared shadcn policy", () => {
  it("does not apply Tailwind policy to ordinary CSS projects", async () => {
    expect(await messages('<div className="legacy-card" style={{ width: 120 }} />', "plain/src/page.tsx")).toEqual([]);
  });

  it("allows component layout while reporting appearance overrides", async () => {
    const findings = await messages('import { Button } from "@/ds/button"; <Button className="w-full mt-4 p-4" />');
    expect(findings.map(({ ruleId }) => ruleId)).toEqual(["shadcn/no-restyle"]);
    expect(findings[0].message).toContain("p-4");
    expect(findings[0].severity).toBe(1);
  });

  it("allows arbitrary layout values while reporting appearance values", async () => {
    const findings = await messages('<div className="w-[320px] mt-[13px] p-[13px]" />');
    expect(findings.map(({ ruleId }) => ruleId)).toEqual(["shadcn/no-arbitrary-values"]);
    expect(findings[0].message).toContain("p-[13px]");
    expect(findings[0].suggestions?.length).toBeGreaterThan(0);
  });

  it("recognizes renamed component re-exports", async () => {
    const findings = await messages('import { Action as Save } from "@/ds"; <Save className="p-4" />');
    expect(findings.map(({ ruleId }) => ruleId)).toEqual(["shadcn/no-restyle"]);
  });

  it("recognizes namespace component imports", async () => {
    const findings = await messages('import * as UI from "@/ds"; <UI.Action className="p-4" />');
    expect(findings.map(({ ruleId }) => ruleId)).toEqual(["shadcn/no-restyle"]);
  });

  it("follows wrappers that forward classes to a design-system component", async () => {
    const findings = await messages('import { SaveButton } from "./save-button"; <SaveButton className="p-4" />');
    expect(findings.map(({ ruleId }) => ruleId)).toEqual(["shadcn/no-restyle"]);
  });

  it("does not recognize unrelated components by their exported names", async () => {
    expect(await messages('import { Button } from "./other-button"; <Button className="p-4" />')).toEqual([]);
  });

  it("exempts component internals discovered through custom tsconfig aliases", async () => {
    const source = 'import { Button } from "./button"; <><Button className={dynamicClasses} /><div className="p-[13px]" /></>';
    expect(await messages(source, "app/src/ds/primitive.tsx")).toEqual([]);
  });

  it("continues checking inline styles inside component implementations", async () => {
    const findings = await messages('<div style={{ padding: 13 }} />', "app/src/ds/primitive.tsx");
    expect(findings.map(({ ruleId }) => ruleId)).toEqual(["shadcn/no-inline-styles"]);
  });

  it("continues checking unknown classes inside component implementations", async () => {
    const findings = await messages('<div className="flex-cols" />', "app/src/ds/primitive.tsx");
    expect(findings.map(({ ruleId }) => ruleId)).toEqual(["shadcn/no-unknown-classes"]);
  });

  it("reports dynamic component classes at application call sites", async () => {
    const findings = await messages('import { Button } from "@/ds/button"; <Button className={dynamicClasses} />');
    expect(findings.map(({ ruleId }) => ruleId)).toEqual(["shadcn/require-static-classes"]);
  });

  it("accepts CSS custom properties carrying dynamic measurements", async () => {
    expect(await messages('<div style={{ "--panel-width": `${width}px` }} className="w-(--panel-width)" />')).toEqual([]);
  });

  it("reads conditional class helpers without scanning unrelated string data", async () => {
    const findings = await messages('const label = "p-[13px]"; const classes = cn("p-[13px]", active && "w-full"); <div className={classes} />');
    expect(findings.map(({ ruleId }) => ruleId)).toEqual(["shadcn/no-arbitrary-values"]);
  });

  it("honors consumer class-helper settings", async () => {
    const findings = await messages('const classes = customMerge("p-[13px]"); <div className={classes} />', undefined, [{
      settings: { shadcn: { mergeFunctions: ["customMerge"] } },
    }]);
    expect(findings.map(({ ruleId }) => ruleId)).toEqual(["shadcn/no-arbitrary-values"]);
  });

  it("accepts classes declared in the discovered theme", async () => {
    expect(await messages('<div className="legacy-card tap-target" />')).toEqual([]);
  });

  it("asks the native Tailwind engine about misspelled variants", async () => {
    const findings = await messages('<div className="hovr:flex" />');
    expect(findings.map(({ ruleId }) => ruleId)).toEqual(["shadcn/no-unknown-classes"]);
    expect(findings[0].suggestions?.length).toBeGreaterThan(0);
  });

  it("discovers Tailwind themes without requiring shadcn components", async () => {
    const findings = await messages('<div className="p-[13px]" />', "auto/src/page.tsx");
    expect(findings.map(({ ruleId }) => ruleId)).toEqual(["shadcn/no-arbitrary-values"]);
  });

  it.each(["jsx", "tsx", "js", "ts", "mjs", "mts", "cjs", "cts"])("checks class helpers in %s source", async (extension) => {
    const findings = await messages('const classes = cn("p-[13px]");', `app/src/helpers.${extension}`);
    expect(findings.map(({ ruleId }) => ruleId)).toEqual(["shadcn/no-arbitrary-values"]);
  });

  it("respects local rule suppressions", async () => {
    const findings = await messages('// eslint-disable-next-line shadcn/no-arbitrary-values -- Reviewed one-off spacing.\n<div className="p-[13px]" />');
    expect(findings).toEqual([]);
  });

  it("preserves application contracts and custom messages", async () => {
    const findings = await messages('import { Button } from "@/ds/button"; <Button className="rounded-full p-4" />', undefined, [{
      rules: {
        "shadcn/no-restyle": ["warn", {
          allow: ["layout"],
          contracts: [{ pattern: "^Button$", allow: ["layout", "shape"] }],
          message: "Use an approved component variant.",
        }],
      },
    }]);
    expect(findings).toHaveLength(1);
    expect(findings[0].message).toBe("Use an approved component variant.");
  });

  it("honors explicit shared-package recognition in projects without discovery metadata", async () => {
    const findings = await messages('import { Button } from "@workspace/ui"; <Button className="p-4" />', "plain/src/page.tsx", [{
      settings: { shadcn: { componentImports: ["^@workspace/ui$"] } },
    }]);
    expect(findings.map(({ ruleId }) => ruleId)).toEqual(["shadcn/no-restyle"]);
  });

  it("honors rule-local component recognition without requiring shared settings", async () => {
    const findings = await messages('import { Button } from "@workspace/ui"; <Button className="p-4" />', "plain/src/page.tsx", [{
      rules: { "shadcn/no-restyle": ["warn", { allow: ["layout"], componentImports: ["^@workspace/ui$"] }] },
    }]);
    expect(findings.map(({ ruleId }) => ruleId)).toEqual(["shadcn/no-restyle"]);
  });

  it("honors an explicit UI prefix without requiring discovery metadata", async () => {
    const findings = await messages('import { Button } from "@workspace/ui/button"; <Button className="p-4" />', "plain/src/page.tsx", [{
      settings: { shadcn: { ui: "@workspace/ui" } },
    }]);
    expect(findings.map(({ ruleId }) => ruleId)).toEqual(["shadcn/no-restyle"]);
  });

  it("keeps sibling application discovery separate in one lint process", async () => {
    const engine = linter();
    const source = '<div style={{ width: 120 }} />';
    const [app] = await engine.lintText(source, { filePath: "app/src/page.tsx" });
    const [plain] = await engine.lintText(source, { filePath: "plain/src/page.tsx" });
    const [again] = await engine.lintText(source, { filePath: "app/src/page.tsx" });
    expect(app.messages.map(({ ruleId }) => ruleId)).toEqual(["shadcn/no-inline-styles"]);
    expect(plain.messages).toEqual([]);
    expect(again.messages).toEqual(app.messages);
  });

  it("does not exempt application directories sharing an implementation prefix", async () => {
    const findings = await messages('<div className="p-[13px]" />', "app/src/ds-extra/page.tsx");
    expect(findings.map(({ ruleId }) => ruleId)).toEqual(["shadcn/no-arbitrary-values"]);
  });

  it("reports malformed source as incomplete analysis", async () => {
    const [result] = await linter().lintText('<div className={ />', { filePath: "app/src/page.tsx" });
    expect(result).toMatchObject({ fatalErrorCount: 1, errorCount: 1 });
  });

  it("preserves a consumer's explicit error-level policy", async () => {
    const [result] = await linter([{ rules: { "shadcn/no-inline-styles": "error" } }]).lintText('<div style={{ width: 120 }} />', { filePath: "app/src/page.tsx" });
    expect(result).toMatchObject({ errorCount: 1, messages: [{ severity: 2 }] });
  });

  it("preserves generated-output exclusions", async () => {
    const [result] = await linter().lintText('<div style={{ width: 120 }} />', { filePath: "app/dist/page.tsx", warnIgnored: false });
    expect(result).toBeUndefined();
  });

  it("keeps raw color policy under the existing semantic color owner", async () => {
    const [result] = await linter([], [...SHADCN_RULES, "@sarj/prefer-semantic-colors"]).lintText('<div className="bg-red-500" />', { filePath: "app/src/page.tsx" });
    expect(result.messages.map(({ ruleId }) => ruleId)).toEqual(["@sarj/prefer-semantic-colors"]);
  });

  it("keeps repeated checks deterministic and applies no automatic design rewrite", async () => {
    const engine = linter();
    const source = '<div className="p-[13px]" />';
    const first = await engine.lintText(source, { filePath: "app/src/page.tsx" });
    const second = await engine.lintText(source, { filePath: "app/src/page.tsx" });
    expect(second).toEqual(first);
    expect(first[0].output).toBeUndefined();
  });
});
