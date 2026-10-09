import { ESLint } from "eslint";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const ESLINT = new ESLint({ cwd: fileURLToPath(new URL("..", import.meta.url)) });

describe("self-lint extension coverage", () => {
  it.each(["ts", "tsx", "mts", "cts", "mjs"])(
    "keeps .%s files on the type-aware ruleset",
    async (extension) => {
      const [result] = await ESLINT.lintText('async function example() { await "value"; }\nmissing;\n', {
        filePath: `example.${extension}`,
      });
      const ruleIds = result?.messages.map((message) => message.ruleId);

      expect(ruleIds).toContain("@typescript-eslint/await-thenable");
    },
  );

  it.each(["js", "cjs"])("keeps .%s files on the JavaScript ruleset", async (extension) => {
    const [result] = await ESLINT.lintText("missing;\n", { filePath: `example.${extension}` });
    const ruleIds = result?.messages.map((message) => message.ruleId);

    expect(ruleIds).toContain("no-undef");
    expect(ruleIds).not.toContain("@typescript-eslint/await-thenable");
  });
});

const HELPER_ESLINT = new ESLint({
  cwd: fileURLToPath(new URL("../../../.github/scripts", import.meta.url)),
});

describe("maintained CI JavaScript helpers", () => {
  it.each(["js", "cjs", "mjs"])("checks .%s helper source", async (extension) => {
    const [result] = await HELPER_ESLINT.lintText("missing;\n", {
      filePath: `nested/example.${extension}`,
    });

    expect(result?.messages.map((message) => message.ruleId)).toEqual(["no-undef"]);
  });

  it.each([
    ["unused import", 'import { join } from "node:path";\nJSON.parse("{}");\n', "no-unused-vars"],
    ["duplicate key", "JSON.stringify({ strict: true, strict: false });\n", "no-dupe-keys"],
    ["global write", "process = {};\n", "no-global-assign"],
  ])("rejects %s", async (_label, source, expectedRule) => {
    const [result] = await HELPER_ESLINT.lintText(source, { filePath: "example.mjs" });

    expect(result?.messages.map((message) => message.ruleId)).toEqual([expectedRule]);
  });

  it.each([
    'import { readFileSync } from "node:fs";\nJSON.parse(readFileSync(process.argv[2], "utf8"));\n',
    'function readFileSync(value) { return value; }\nJSON.parse(readFileSync("{}"));\n',
    '// missing;\nJSON.stringify("missing;");\n',
    'console.log(Buffer.from("fixture").toString("utf8"));\n',
  ])("accepts valid helper source", async (source) => {
    const [result] = await HELPER_ESLINT.lintText(source, { filePath: "example.mjs" });

    expect(result?.messages).toEqual([]);
  });

  it("rejects malformed source", async () => {
    const [result] = await HELPER_ESLINT.lintText("for (const file of []) {\n", {
      filePath: "example.mjs",
    });

    expect(result?.fatalErrorCount).toBe(1);
  });
});
