import { ESLint } from "eslint";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const eslint = new ESLint({ cwd: fileURLToPath(new URL("..", import.meta.url)) });

describe("self-lint extension coverage", () => {
  it.each(["ts", "tsx", "mts", "cts", "mjs"])(
    "keeps .%s files on the type-aware ruleset",
    async (extension) => {
      const [result] = await eslint.lintText('async function example() { await "value"; }\nmissing;\n', {
        filePath: `example.${extension}`,
      });
      const ruleIds = result?.messages.map((message) => message.ruleId);

      expect(ruleIds).toContain("@typescript-eslint/await-thenable");
    },
  );

  it.each(["js", "cjs"])("keeps .%s files on the JavaScript ruleset", async (extension) => {
    const [result] = await eslint.lintText("missing;\n", { filePath: `example.${extension}` });
    const ruleIds = result?.messages.map((message) => message.ruleId);

    expect(ruleIds).toContain("no-undef");
    expect(ruleIds).not.toContain("@typescript-eslint/await-thenable");
  });
});
