import { mkdtemp, mkdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join, resolve, sep } from "node:path";

import * as parser from "@typescript-eslint/parser";
import { Linter, type Rule } from "eslint";

import type { DocumentedRule, RuleExample } from "./rules/_docs.js";

/** Execute all authored examples, including private regressions, in isolated projects. */
export async function verifyRuleExamples<Options extends readonly unknown[], MessageIds extends string>(
  rule: DocumentedRule<Options, MessageIds>,
): Promise<number> {
  const spec = rule.documentation;
  if (spec === undefined || !spec.publicExamples.some((item) => item.outcome === "match") ||
      !spec.publicExamples.some((item) => item.outcome === "no-match")) {
    throw new Error("rule requires documented public matching and non-matching examples");
  }
  for (const example of spec.examples) {
    const root = await mkdtemp(join(tmpdir(), "sarj-rule-example-"));
    try {
      for (const file of example.files) {
        const path = fixturePath(root, file.path);
        await mkdir(dirname(path), { recursive: true });
        await writeFile(path, file.source);
      }
      const tsconfig = join(root, "tsconfig.json");
      if (!example.files.some((file) => file.path === "tsconfig.json")) {
        await writeFile(tsconfig, JSON.stringify({ compilerOptions: {
          target: "ESNext", module: "ESNext", moduleResolution: "Bundler", strict: true,
          allowJs: true, jsx: "preserve", noEmit: true,
        }, include: ["**/*"] }));
      }
      const ruleId = `@sarj/${spec.ruleId}`;
      const config: Linter.Config = {
        files: ["**/*.{ts,tsx,js,jsx,mts,cts,mjs,cjs}"],
        languageOptions: { parser, parserOptions: { project: tsconfig, tsconfigRootDir: root } },
        plugins: { "@sarj": { rules: { [spec.ruleId]: rule as unknown as Rule.RuleModule } } },
        rules: { [ruleId]: ["error", ...(rule.defaultOptions ?? [])] },
      };
      await verifyExample(new Linter({ cwd: root }), config, example, root, ruleId);
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  }
  return spec.examples.length;
}

function fixturePath(root: string, path: string): string {
  const resolved = resolve(root, path);
  if (!resolved.startsWith(root + sep)) throw new Error(`unsafe example path: ${path}`);
  return resolved;
}

async function verifyExample(linter: Linter, config: Linter.Config, example: RuleExample, root: string, ruleId: string): Promise<void> {
  const focus = example.files.find((file) => file.path === example.focusPath);
  if (focus === undefined) throw new Error(`${example.id}: focus file is missing`);
  const filename = fixturePath(root, focus.path);
  const messages = linter.verify(focus.source, config, { filename });
  if (messages.some((message) => message.fatal || message.ruleId !== ruleId)) {
    throw new Error(`${example.id}: invalid fixture: ${messages.map((message) => message.message).join("; ")}`);
  }
  if (messages.length !== example.expectedCount) {
    throw new Error(`${example.id}: expected ${example.expectedCount} findings, received ${messages.length}`);
  }
  for (const expected of example.fixedFiles ?? []) {
    const input = example.files.find((file) => file.path === expected.path);
    if (input === undefined) throw new Error(`${example.id}: fixed file has no original`);
    const options = { filename: fixturePath(root, input.path) };
    const fixed = linter.verifyAndFix(input.source, config, options);
    if (fixed.output !== expected.source) throw new Error(`${example.id}: unexpected fixed source`);
    await writeFile(options.filename, fixed.output);
    const repeated = linter.verifyAndFix(fixed.output, config, options);
    if (repeated.fixed || repeated.output !== fixed.output || repeated.messages.length > 0) {
      throw new Error(`${example.id}: fix is not clean and idempotent`);
    }
  }
}
