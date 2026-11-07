// vitest: shared-module-graph


import { existsSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import ts from "typescript";
import { describe, expect, it } from "vitest";

import plugin from "../src/index.js";

const HERE = dirname(fileURLToPath(import.meta.url));
const RULE_TESTS_DIR = resolve(HERE, "rules");


function ruleNamesUnderTest(): string[] {
  return Object.keys(plugin.rules).sort();
}


function arrayConstants(source: ts.SourceFile): Map<string, ts.ArrayLiteralExpression> {
  const found = new Map<string, ts.ArrayLiteralExpression>();
  const visit = (node: ts.Node): void => {
    if (
      ts.isVariableDeclaration(node) &&
      ts.isIdentifier(node.name) &&
      node.initializer !== undefined
    ) {
      const initializer = unwrap(node.initializer);
      if (ts.isArrayLiteralExpression(initializer)) found.set(node.name.text, initializer);
    }
    ts.forEachChild(node, visit);
  };
  ts.forEachChild(source, visit);
  return found;
}

function unwrap(value: ts.Expression): ts.Expression {
  while (ts.isParenthesizedExpression(value) || ts.isAsExpression(value) || ts.isSatisfiesExpression(value)) value = value.expression;
  return value;
}








function countCases(
  value: ts.Expression,
  constants: Map<string, ts.ArrayLiteralExpression>,
): number | undefined {
  value = unwrap(value);
  if (ts.isIdentifier(value)) {
    const target = constants.get(value.text);
    return target === undefined ? undefined : countCases(target, constants);
  }
  if (ts.isCallExpression(value) && ts.isPropertyAccessExpression(value.expression) && value.expression.name.text === "map" && value.arguments.length > 0) {
    return countCases(value.expression.expression, constants);
  }
  if (ts.isCallExpression(value) && ts.isIdentifier(value.expression) && value.arguments.length === 1) {
    const [cases] = value.arguments;
    return cases === undefined ? undefined : countCases(cases, constants);
  }
  if (!ts.isArrayLiteralExpression(value)) return undefined;

  let total = 0;
  for (const element of value.elements) {
    if (ts.isOmittedExpression(element)) return undefined;
    if (ts.isSpreadElement(element)) {
      total += countCases(element.expression, constants) ?? 0;
      continue;
    }
    total += 1;
  }
  return total;
}

it.each([
  ["literal", "[1, 2]", 2],
  ["empty", "[]", 0],
  ["local const", "CASES", 2],
  ["spread", "[...CASES, 3]", 3],
  ["unknown spread", "[...IMPORTED, 3]", 1],
  ["const assertion", "([1, 2] as const)", 2],
  ["satisfies", "([1, 2] satisfies readonly number[])", 2],
  ["map literal", "([1, 2] as const).map(value => ({code: String(value)}))", 2],
  ["map local const", "CASES.map(value => ({code: String(value)}))", 2],
  ["filter changes cardinality", "CASES.filter(Boolean)", undefined],
  ["flatMap changes cardinality", "CASES.flatMap(value => [value, value])", undefined],
  ["unknown input", "IMPORTED.map(value => value)", undefined],
  ["unknown factory", "makeCases().map(value => value)", undefined],
  ["custom map", "({map: custom}).map(value => value)", undefined],
  ["sparse array", "[, 1]", undefined],
])("counts %s without executing fixture code", (_name, expression, expected) => {
  const source = ts.createSourceFile("cases.ts", `const CASES = [1, 2] as const; const RESULT = ${expression};`, ts.ScriptTarget.ESNext, true);
  const statement = source.statements[1];
  if (statement === undefined || !ts.isVariableStatement(statement)) throw new Error("missing expression fixture");
  const value = statement.declarationList.declarations[0]?.initializer;
  if (value === undefined) throw new Error("missing expression initializer");
  expect(countCases(value, arrayConstants(source))).toBe(expected);
});

interface CaseCounts {
  readonly valid: number;
  readonly invalid: number;
}


function caseCounts(filePath: string): CaseCounts {
  const source = ts.createSourceFile(
    filePath,
    readFileSync(filePath, "utf8"),
    ts.ScriptTarget.ESNext,
    true,
  );
  const constants = arrayConstants(source);

  let valid = 0;
  let invalid = 0;
  const add = (running: number, addition: number | undefined): number => running + (addition ?? 0);

  function collectConfiguredCases(config: ts.ObjectLiteralExpression): void {
    for (const property of config.properties) {
      if (!ts.isPropertyAssignment(property) || !ts.isIdentifier(property.name)) {
        continue;
      }
      const count = countCases(property.initializer, constants);
      if (property.name.text === "valid") valid = add(valid, count);
      if (property.name.text === "invalid") invalid = add(invalid, count);
    }
  }

  const visit = (node: ts.Node): void => {
    if (
      ts.isCallExpression(node) &&
      ts.isPropertyAccessExpression(node.expression) &&
      node.expression.name.text === "run"
    ) {
      const config = casesObject(node.arguments[2], source);
      if (config !== undefined) collectConfiguredCases(config);
    }
    ts.forEachChild(node, visit);
  };
  ts.forEachChild(source, visit);

  return { invalid, valid };
}

function casesObject(value: ts.Expression | undefined, source: ts.SourceFile): ts.ObjectLiteralExpression | undefined {
  if (value === undefined) return undefined;
  value = unwrap(value);
  if (ts.isObjectLiteralExpression(value)) return value;
  if (ts.isIdentifier(value)) return casesObject(constantInitializer(source, value.text), source);
  return ts.isCallExpression(value) ? casesObject(value.arguments.at(-1), source) : undefined;
}

function constantInitializer(source: ts.SourceFile, name: string): ts.Expression | undefined {
  for (const statement of source.statements) {
    if (!ts.isVariableStatement(statement)) continue;
    const declaration = statement.declarationList.declarations.find((item) => ts.isIdentifier(item.name) && item.name.text === name);
    if (declaration !== undefined) return declaration.initializer;
  }
  return undefined;
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
      `${name} ships in the plugin but has no tests/rules/${name}.test.ts. ` +
      `A rule nobody has run is a rule nobody has read the findings of.`,
    ).toBe(true);
  });

  it.each(names.filter((name) => existsSync(join(RULE_TESTS_DIR, `${name}.test.ts`))))("%s has at least one valid and one invalid case", (name) => {
    const path = join(RULE_TESTS_DIR, `${name}.test.ts`);
    const { invalid, valid } = caseCounts(path);
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
