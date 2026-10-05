import {
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
  mkdirSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it } from "vitest";
import { createSelectedOxlintConfig } from "../src/create-selected-oxlint-config";

const folders: string[] = [];
const binary = resolve(
  dirname(fileURLToPath(import.meta.resolve("oxlint/package.json"))),
  "bin/oxlint",
);
function project(): string {
  const root = mkdtempSync(join(tmpdir(), "native-rule-selection-"));
  folders.push(root);
  return root;
}
afterEach(() => {
  for (const folder of folders.splice(0))
    rmSync(folder, { recursive: true, force: true });
});
const plugin = `export default {rules:{selected:{
  meta:{schema:[{type:'string'}]},
  create(c){return {Identifier(n){if(n.name===c.options[0])c.report({node:n,message:'selected'});}}}
},unrelated:{create(){throw new Error('unrelated rule executed');}}}};`;
function lint(
  root: string,
  file: string,
): { diagnostics: { message: string; severity: string }[] } {
  const result = spawnSync(
    binary,
    ["--config", "focused.mjs", "--format", "json", file],
    {
      cwd: root,
      encoding: "utf8",
      timeout: 30_000,
    },
  );
  expect({
    error: result.error,
    stderr: result.stderr,
    status: result.status,
  }).toMatchObject({
    error: undefined,
    stderr: "",
    status: expect.any(Number),
  });
  if (result.status !== 0 && result.status !== 1)
    throw new Error(result.stdout);
  return JSON.parse(result.stdout);
}
describe("native focused configuration", () => {
  it.each(["json", "mjs"])(
    "preserves inherited native options from a %s policy",
    async (extension) => {
      const root = project();
      const parent = {
        plugins: ["typescript"],
        rules: {
          "typescript/consistent-type-assertions": [
            "warn",
            { assertionStyle: "never" },
          ],
        },
      };
      const policy = join(root, `policy.${extension}`);
      if (extension === "json") {
        writeFileSync(join(root, "parent.json"), JSON.stringify(parent));
        writeFileSync(policy, JSON.stringify({ extends: ["./parent.json"] }));
      } else {
        writeFileSync(
          policy,
          `export default {extends:[${JSON.stringify(parent)}]};`,
        );
      }
      const selected = await createSelectedOxlintConfig(policy, [
        "typescript/consistent-type-assertions",
      ]);
      writeFileSync(
        join(root, "focused.mjs"),
        `export default ${JSON.stringify(selected)};`,
      );
      writeFileSync(join(root, "sample.ts"), "const count = 1 as number;");
      expect(lint(root, "sample.ts").diagnostics).toMatchObject([
        { severity: "warning" },
      ]);
      writeFileSync(join(root, "sample.ts"), "const count: number = 1;");
      expect(lint(root, "sample.ts").diagnostics).toEqual([]);
    },
  );
  it("keeps overrides, relative parent plugins, options, and warnings while disabling unrelated rules", async () => {
    const root = project();
    mkdirSync(join(root, "parent"));
    writeFileSync(join(root, "parent/plugin.mjs"), plugin);
    writeFileSync(
      join(root, "parent/policy.jsonc"),
      `{
      // Relative plugin belongs to the parent configuration.
      "jsPlugins":[{"name":"@sarj","specifier":"./plugin.mjs"}],
      "rules":{"@sarj/selected":["warn","needle"],"@sarj/unrelated":"error"},
      "overrides":[{"files":["*.test.ts"],"rules":{"@sarj/selected":"off"}}],
    }`,
    );
    const source = join(root, "policy.json");
    writeFileSync(
      source,
      JSON.stringify({
        extends: ["./parent/policy.jsonc"],
        categories: { suspicious: "error" },
      }),
    );
    const before = readFileSync(source, "utf8");
    const selected = await createSelectedOxlintConfig(source, ["selected"]);
    writeFileSync(
      join(root, "focused.mjs"),
      `export default ${JSON.stringify(selected)};`,
    );
    writeFileSync(join(root, "sample.ts"), "const needle: number = 1;");
    writeFileSync(join(root, "sample.test.ts"), "const needle: number = 1;");
    expect(lint(root, "sample.ts").diagnostics).toMatchObject([
      { message: "selected", severity: "warning" },
    ]);
    expect(lint(root, "sample.test.ts").diagnostics).toEqual([]);
    expect(readFileSync(source, "utf8")).toBe(before);
  });
  it("filters a core rule without raising its configured severity", async () => {
    const root = project();
    const policy = join(root, "policy.mjs");
    writeFileSync(
      policy,
      "export default {rules:{'no-debugger':'warn','no-console':'error'}};",
    );
    const selected = await createSelectedOxlintConfig(policy, ["no-debugger"]);
    writeFileSync(
      join(root, "focused.mjs"),
      `export default ${JSON.stringify(selected)};`,
    );
    writeFileSync(join(root, "sample.js"), "debugger;console.log('ok');");
    const result = lint(root, "sample.js");
    expect(result.diagnostics).toMatchObject([{ severity: "warning" }]);
    expect(result.diagnostics).toHaveLength(1);
  });
  it.each(["no-const-assign", "eslint/no-const-assign"])(
    "preserves category-enabled %s and its warning severity",
    async (rule) => {
      const root = project();
      const policy = join(root, "policy.json");
      writeFileSync(
        policy,
        JSON.stringify({
          categories: { correctness: "warn" },
          rules: { "no-console": "error" },
        }),
      );
      const selected = await createSelectedOxlintConfig(policy, [rule]);
      writeFileSync(
        join(root, "focused.mjs"),
        `export default ${JSON.stringify(selected)};`,
      );
      writeFileSync(
        join(root, "sample.js"),
        "const count=1;count=2;console.log(count);",
      );
      const result = lint(root, "sample.js");
      expect(result.diagnostics).toMatchObject([{ severity: "warning" }]);
      expect(result.diagnostics).toHaveLength(1);
    },
  );
  it("rejects missing rules, malformed JSONC, and circular parents", async () => {
    const root = project();
    const policy = join(root, "policy.jsonc");
    writeFileSync(policy, '{"rules":{"no-debugger":"error"}}');
    await expect(
      createSelectedOxlintConfig(policy, ["missing"]),
    ).rejects.toThrow("Selected rule is absent");
    writeFileSync(policy, '{"rules":');
    await expect(createSelectedOxlintConfig(policy, [])).rejects.toThrow(
      "Invalid JSON configuration",
    );
    writeFileSync(policy, '{"extends":["./policy.jsonc"]}');
    await expect(createSelectedOxlintConfig(policy, [])).rejects.toThrow(
      "Circular Oxlint configuration",
    );
  });
});
