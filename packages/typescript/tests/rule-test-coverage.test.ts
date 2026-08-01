/**
 * A rule that no test exercises is a rule nobody has read the output of.
 *
 * `ban-loose-type-guards-in-tests` shipped in `configs.strict` at `"error"` for its
 * entire life with no test file at all — `git log --all` on
 * `tests/rules/ban-loose-type-guards-in-tests.test.ts` returns nothing. It was
 * deleted in #183 after a corpus read found 39 findings and 0 true positives. The
 * plugin's other gates could not have caught it: `strict-config-sync` checks that
 * every rule is WIRED, `flat-presets` checks tiers, and neither has any opinion
 * about whether the rule was ever run against a line of code.
 *
 * The floor here is deliberately behavioural rather than "a file exists". A test
 * file with only `valid` cases proves the rule is quiet, never that it fires; one
 * with only `invalid` cases proves it fires, never that it is safe. Both directions
 * are what makes a rule shippable, so both are required.
 *
 * The check is a static parse of the test file rather than a coverage run: it names
 * the missing thing precisely ("no invalid cases"), costs milliseconds, and cannot
 * be satisfied by a rule module being imported for an unrelated reason — which is
 * exactly how line coverage would have scored `ban-loose-type-guards-in-tests` as
 * covered the moment `src/index.ts` imported it.
 *
 * `rule-docs.test.ts` asserts that each rule's examples module EXISTS and is
 * non-empty, which is the file-shaped half. This file owns the behavioural half,
 * and it also covers names that are wired into a preset without being in the
 * `rules` export. The Python twin is `packages/python/tests/conftest.py`, which
 * measures the same invariant by running the rules instead of parsing them —
 * pytest has no single call shape to parse.
 */

import { existsSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import ts from "typescript";
import { describe, expect, it } from "vitest";

import plugin, { rules } from "../src/index.js";

const HERE = dirname(fileURLToPath(import.meta.url));
const RULE_TESTS_DIR = resolve(HERE, "rules");

/** Every rule name the plugin exports or wires into a preset, de-duplicated. */
function ruleNamesUnderTest(): string[] {
  const names = new Set(Object.keys(rules));
  for (const preset of Object.values(plugin.configs)) {
    for (const key of Object.keys(preset.rules)) {
      names.add(key.replace(/^@sarj\//u, ""));
    }
  }
  return [...names].sort();
}

/** `const x = [...]` array literals declared at any depth in the file, by name. */
function arrayConstants(source: ts.SourceFile): Map<string, ts.ArrayLiteralExpression> {
  const found = new Map<string, ts.ArrayLiteralExpression>();
  const visit = (node: ts.Node): void => {
    if (
      ts.isVariableDeclaration(node) &&
      ts.isIdentifier(node.name) &&
      node.initializer !== undefined &&
      ts.isArrayLiteralExpression(node.initializer)
    ) {
      found.set(node.name.text, node.initializer);
    }
    ts.forEachChild(node, visit);
  };
  ts.forEachChild(source, visit);
  return found;
}

/**
 * How many cases an `valid:` / `invalid:` value contributes.
 *
 * `undefined` means "could not be determined statically" — an imported array, a
 * function call — which is reported as a failure rather than assumed non-empty. A
 * gate that guesses in the permissive direction is the failure mode being fixed.
 */
function countCases(
  value: ts.Expression,
  constants: Map<string, ts.ArrayLiteralExpression>,
): number | undefined {
  if (ts.isIdentifier(value)) {
    const target = constants.get(value.text);
    return target === undefined ? undefined : countCases(target, constants);
  }
  if (!ts.isArrayLiteralExpression(value)) return undefined;

  let total = 0;
  for (const element of value.elements) {
    if (ts.isSpreadElement(element)) {
      const spread = countCases(element.expression, constants);
      if (spread === undefined) return undefined;
      total += spread;
      continue;
    }
    total += 1;
  }
  return total;
}

interface CaseCounts {
  readonly valid: number | undefined;
  readonly invalid: number | undefined;
}

/** The `{ valid, invalid }` totals across every `<tester>.run(name, rule, {...})` call. */
function caseCounts(filePath: string): CaseCounts {
  const source = ts.createSourceFile(
    filePath,
    readFileSync(filePath, "utf8"),
    ts.ScriptTarget.ESNext,
    true,
  );
  const constants = arrayConstants(source);

  let valid: number | undefined = 0;
  let invalid: number | undefined = 0;
  const add = (
    running: number | undefined,
    addition: number | undefined,
  ): number | undefined =>
    running === undefined || addition === undefined ? undefined : running + addition;

  const visit = (node: ts.Node): void => {
    if (
      ts.isCallExpression(node) &&
      ts.isPropertyAccessExpression(node.expression) &&
      node.expression.name.text === "run"
    ) {
      const config = node.arguments[2];
      if (config !== undefined && ts.isObjectLiteralExpression(config)) {
        for (const property of config.properties) {
          if (!ts.isPropertyAssignment(property) || !ts.isIdentifier(property.name)) {
            continue;
          }
          const count = countCases(property.initializer, constants);
          if (property.name.text === "valid") valid = add(valid, count);
          if (property.name.text === "invalid") invalid = add(invalid, count);
        }
      }
    }
    ts.forEachChild(node, visit);
  };
  ts.forEachChild(source, visit);

  return { invalid, valid };
}

describe("every shipped rule is exercised by its own tests", () => {
  const names = ruleNamesUnderTest();

  it("has rules to check", () => {
    expect(names.length).toBeGreaterThan(0);
  });

  it.each(names)("%s has a test file", (name) => {
    const path = join(RULE_TESTS_DIR, `${name}.test.ts`);
    expect(
      existsSync(path),
      `${name} is wired into a preset but has no tests/rules/${name}.test.ts. ` +
        `A rule nobody has run is a rule nobody has read the findings of.`,
    ).toBe(true);
  });

  it.each(names)("%s has at least one valid and one invalid case", (name) => {
    const path = join(RULE_TESTS_DIR, `${name}.test.ts`);
    if (!existsSync(path)) return; // owned by the assertion above

    const { invalid, valid } = caseCounts(path);
    expect(
      valid,
      `${name}: could not statically count RuleTester \`valid\` cases in ` +
        `tests/rules/${name}.test.ts — declare them as an array literal, or as a ` +
        `\`const\` array in the same file.`,
    ).not.toBeUndefined();
    expect(
      invalid,
      `${name}: could not statically count RuleTester \`invalid\` cases in ` +
        `tests/rules/${name}.test.ts — declare them as an array literal, or as a ` +
        `\`const\` array in the same file.`,
    ).not.toBeUndefined();
    expect(
      valid,
      `${name}: no \`valid\` cases. Without one, nothing pins that the rule stays ` +
        `quiet on the code it is supposed to allow.`,
    ).toBeGreaterThan(0);
    expect(
      invalid,
      `${name}: no \`invalid\` cases. Without one, nothing pins that the rule fires ` +
        `at all — which is how ban-loose-type-guards-in-tests shipped at "error", ` +
        `untested, for its whole life.`,
    ).toBeGreaterThan(0);
  });
});
