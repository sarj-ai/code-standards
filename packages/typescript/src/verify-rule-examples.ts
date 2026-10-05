import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join, resolve, sep } from "node:path";
import { RuleTester } from "oxlint/plugins-dev";
import type { DocumentedRule, RuleExample } from "./rules/_docs.js";

/** Execute authored syntax examples through the official Oxlint rule tester. */
export async function verifyRuleExamples<MessageIds extends string>(
  rule: DocumentedRule<MessageIds>,
): Promise<number> {
  const spec = rule.documentation;
  if (
    spec === undefined ||
    !spec.publicExamples.some((item) => item.outcome === "match") ||
    !spec.publicExamples.some((item) => item.outcome === "no-match")
  ) {
    throw new Error(
      "rule requires documented public matching and non-matching examples",
    );
  }
  for (const example of spec.examples) {
    const root = await mkdtemp(join(tmpdir(), "sarj-rule-example-"));
    try {
      await writeFixture(root, example.files);
      executeExample(spec.ruleId, rule, example, root);
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  }
  return spec.examples.length;
}

async function writeFixture(
  root: string,
  files: RuleExample["files"],
): Promise<void> {
  for (const file of files) {
    const path = fixturePath(root, file.path);
    await mkdir(dirname(path), { recursive: true });
    await writeFile(path, file.source);
  }
}

function executeExample<MessageIds extends string>(
  ruleId: string,
  rule: DocumentedRule<MessageIds>,
  example: RuleExample,
  root: string,
): void {
  const focus = example.files.find((file) => file.path === example.focusPath);
  if (focus === undefined)
    throw new Error(`${example.id}: focus file is missing`);
  if (example.fixedFiles?.some((file) => file.path !== example.focusPath)) {
    throw new Error(
      `${example.id}: a rule can fix only its current source file`,
    );
  }
  const fixed = example.fixedFiles?.find(
    (file) => file.path === example.focusPath,
  );
  const test = {
    name: example.id,
    filename: fixturePath(root, focus.path),
    code: focus.source,
  };
  // Official hooks permit immediate execution outside a test framework. The
  // synchronous run always restores them before another example can execute.
  const previousDescribe = RuleTester.describe;
  const previousIt = RuleTester.it;
  try {
    RuleTester.describe = (_name, callback) => callback();
    RuleTester.it = (_name, callback) => callback();
    const tester = new RuleTester();
    if (example.expectedCount === 0) {
      tester.run(ruleId, rule, { valid: [test], invalid: [] });
    } else {
      const invalid: RuleTester.InvalidTestCase = {
        ...test,
        errors: example.expectedCount,
      };
      if (fixed !== undefined) invalid.output = fixed.source;
      tester.run(ruleId, rule, { valid: [], invalid: [invalid] });
    }
    if (fixed !== undefined)
      tester.run(ruleId, rule, {
        valid: [{ ...test, name: `${example.id}: fixed`, code: fixed.source }],
        invalid: [],
      });
  } catch (error) {
    throw new Error(
      `${example.id}: ${error instanceof Error ? error.message : String(error)}`,
      { cause: error },
    );
  } finally {
    RuleTester.describe = previousDescribe;
    RuleTester.it = previousIt;
  }
}

function fixturePath(root: string, path: string): string {
  const resolved = resolve(root, path);
  if (!resolved.startsWith(root + sep))
    throw new Error(`unsafe example path: ${path}`);
  return resolved;
}
