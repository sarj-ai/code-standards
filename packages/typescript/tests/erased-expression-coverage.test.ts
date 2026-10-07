/** Regressions labeled before widening static-member recognition. */
import { mkdtemp, mkdir, rm, symlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import * as parser from "@typescript-eslint/parser";
import { Linter, type Rule } from "eslint";
import { describe, expect, it } from "vitest";

import { RULES } from "../src/index.js";
import cases from "./fixtures/erased-expression-coverage.json";
import callCases from "./fixtures/call-expression-coverage.json";

describe("erased receivers, static template keys and discarded SQL", () => {
  it.each([...cases, ...callCases])("$rule: $name", async (example) => {
    const root = await mkdtemp(join(tmpdir(), "sarj-erased-expression-"));
    try {
      for (const file of example.files) {
        const path = join(root, file.path);
        await mkdir(dirname(path), { recursive: true });
        await writeFile(path, file.source);
      }
      const tsconfig = join(root, "tsconfig.json");
      if (!example.files.some(file => file.path === "tsconfig.json")) {
        await writeFile(tsconfig, JSON.stringify({ compilerOptions: {
          target: "ESNext", module: "ESNext", moduleResolution: "Bundler", strict: true,
          allowJs: true, jsx: "preserve", noEmit: true,
        }, include: ["**/*"] }));
      }
      await mkdir(join(root, "node_modules"));
      await symlink(fileURLToPath(new URL("../node_modules/zod", import.meta.url)), join(root, "node_modules/zod"));
      const rule = RULES[example.rule as keyof typeof RULES];
      const ruleId = `@sarj/${example.rule}`;
      const config: Linter.Config = {
        files: ["**/*.{ts,tsx,js,jsx,mts,cts,mjs,cjs}"],
        languageOptions: { parser, parserOptions: { project: tsconfig, tsconfigRootDir: root } },
        plugins: { "@sarj": { rules: { [example.rule]: rule as unknown as Rule.RuleModule } } },
        rules: { [ruleId]: ["error", ...(example.rule === "no-restricted-library-load" ? [{ libraries: [{ id: "LIB101", module: "axios", replacement: "Ky" }] }] : example.rule === "no-storage-in-stateless-modules"
          ? [{ modules: ["engineer-digest"] }] : rule.defaultOptions ?? [])] },
      };
      const focus = example.files.find(file => file.path === example.focusPath);
      expect(focus).toBeDefined();
      const linter = new Linter({ cwd: root });
      const filename = join(root, example.focusPath);
      const messages = linter.verify(focus?.source ?? "", config, { filename });
      expect(messages.filter(message => message.fatal || message.ruleId !== ruleId)).toEqual([]);
      expect(messages).toHaveLength(example.expected);
      expect(new Set(messages.map(message => `${message.line}:${message.column}`)).size).toBe(messages.length);
      if ("fixedSource" in example && typeof example.fixedSource === "string") {
        const fixed = linter.verifyAndFix(focus?.source ?? "", config, { filename });
        expect(fixed.output).toBe(example.fixedSource);
        await writeFile(filename, fixed.output);
        parser.clearCaches();
        const repeated = linter.verifyAndFix(fixed.output, config, { filename });
        expect(repeated.output).toBe(fixed.output);
        expect(repeated.fixed).toBe(false);
        expect(repeated.messages).toEqual([]);
      }
    } finally {
      await rm(root, { recursive: true, force: true });
      parser.clearCaches();
    }
  });
});
