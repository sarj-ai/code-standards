/**
 * @fileoverview prefer-zod-enum-validator — keep closed string validation in one runtime schema.
 *
 * Port of the 18.x `prefer-zod-enum-validator` rule. The rule is
 * untyped, so the port covers all of it.
 *
 * Absent optional fields are `null` under Oxlint and `undefined` under
 * TS-ESTree; the port accepts both. The original compares
 * `node.typeParameters !== undefined`, which is always true for Oxlint's
 * `null`, so under Oxlint the original never reports. The port reports what
 * the original reports under ESLint.
 */

import { defineRule, type ESTree, type Node } from "../types.js";
import { unwrapExpression } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { isGeneratedFile, isTestFile } from "../utils/paths.js";
import { staticString } from "../utils/static-string.js";

const NAME = "prefer-zod-enum-validator";

type ValidatorFunction = ESTree.Function | ESTree.ArrowFunctionExpression;

function isInput(node: Node | null | undefined, name: string): boolean {
  if (node == null) return false;
  const value = unwrapExpression(node);
  return value.type === "Identifier" && value.name === name;
}

function singleStatement(node: ESTree.Statement | null): ESTree.Statement | null {
  return node?.type === "BlockStatement"
    ? node.body.length === 1 ? node.body[0] ?? null : null
    : node;
}

function returnsInput(node: ESTree.Statement | null, name: string): boolean {
  const statement = singleStatement(node);
  return statement?.type === "ReturnStatement" && isInput(statement.argument, name);
}

function throws(node: ESTree.Statement | null): boolean {
  return singleStatement(node)?.type === "ThrowStatement";
}

function validatorDomain(node: ValidatorFunction, name: string): readonly string[] | null {
  if (node.body === null) return null;
  if (node.body.type !== "BlockStatement") return comparisonDomain(node.body, name, false);
  const statements = node.body.body;
  const [first] = statements;
  if (statements.length === 1 && first?.type === "ReturnStatement" && first.argument !== null) {
    return comparisonDomain(first.argument, name, false);
  }
  if (statements.length === 1 && first?.type === "SwitchStatement") return switchDomain(first, name);
  if (first?.type !== "IfStatement") return null;
  const alternative = ifAlternative(first, statements);
  return alternative === null ? null : conditionalDomain(first, alternative, name);
}

/** What runs when the test fails: the `else` branch, or the statement after an `if` without one. */
function ifAlternative(node: ESTree.IfStatement, statements: readonly ESTree.Statement[]): ESTree.Statement | null {
  if (node.alternate === null) return statements.length === 2 ? statements[1] ?? null : null;
  return statements.length === 1 ? node.alternate : null;
}

function conditionalDomain(node: ESTree.IfStatement, alternative: ESTree.Statement, name: string): readonly string[] | null {
  if (returnsInput(node.consequent, name) && throws(alternative)) return comparisonDomain(node.test, name, false);
  if (throws(node.consequent) && returnsInput(alternative, name)) return comparisonDomain(node.test, name, true);
  if (booleanReturn(node.consequent, true) && booleanReturn(alternative, false)) return comparisonDomain(node.test, name, false);
  if (booleanReturn(node.consequent, false) && booleanReturn(alternative, true)) return comparisonDomain(node.test, name, true);
  return null;
}

function switchDomain(node: ESTree.SwitchStatement, name: string): string[] | null {
  if (!isInput(node.discriminant, name) || node.cases.length < 3) return null;
  const last = node.cases.at(-1);
  if (last?.test !== null || last.consequent.length !== 1 || !throws(last.consequent[0] ?? null)) return null;
  // An unfinished label falling into the throwing default is not an accepted value.
  if (node.cases.at(-2)?.consequent.length !== 1) return null;
  const domain: string[] = [];
  for (const branch of node.cases.slice(0, -1)) {
    const value = acceptedCaseValue(branch, name);
    if (value === null) return null;
    domain.push(value);
  }
  return domain;
}

/** A `case "x":` label that returns the input or falls through to the next label. */
function acceptedCaseValue(branch: ESTree.SwitchCase, name: string): string | null {
  const value = branch.test === null ? null : staticString(branch.test);
  if (value === null || branch.consequent.length > 1) return null;
  return branch.consequent.length === 0 || returnsInput(branch.consequent[0] ?? null, name) ? value : null;
}

function comparisonDomain(node: Node, name: string, reject: boolean): string[] | null {
  const expression = unwrapExpression(node);
  if (expression.type === "LogicalExpression" && expression.operator === (reject ? "&&" : "||")) {
    const left = comparisonDomain(expression.left, name, reject);
    const right = comparisonDomain(expression.right, name, reject);
    return left === null || right === null ? null : [...left, ...right];
  }
  if (expression.type !== "BinaryExpression" || expression.operator !== (reject ? "!==" : "===")) return null;
  const literal = isInput(expression.left, name) ? expression.right : isInput(expression.right, name) ? expression.left : null;
  const value = literal === null ? null : staticString(literal);
  return value === null ? null : [value];
}

function booleanReturn(node: ESTree.Statement | null, expected: boolean): boolean {
  const statement = singleStatement(node);
  if (statement?.type !== "ReturnStatement" || statement.argument === null) return false;
  const value = unwrapExpression(statement.argument);
  return value.type === "Literal" && value.value === expected;
}
function isMethod(node: ValidatorFunction): boolean {
  const { parent } = node;
  return parent.type === "MethodDefinition" || (parent.type === "Property" && parent.method);
}

/** The name of a function's sole required `string` or `unknown` parameter. */
function stringInputName(node: ValidatorFunction): string | null {
  const [parameter] = node.params;
  if (node.params.length !== 1 || parameter?.type !== "Identifier" || parameter.optional) return null;
  const annotation = parameter.typeAnnotation?.typeAnnotation;
  return annotation?.type === "TSUnknownKeyword" || annotation?.type === "TSStringKeyword" ? parameter.name : null;
}

export default defineRule({
  meta: {
    type: "suggestion",
    docs: {
      description: "Express closed string validators with a reusable Zod enum schema.",
      url: docsUrl(NAME),
    },
    schema: [],
    messages: { useEnumSchema: "Replace this closed string validator with a named z.enum([…]) schema and derive its type with z.infer. Use parse for parsing or safeParse for a boolean check; preserve intentional failure behavior." },
  },
  createOnce(context) {
    function inspect(node: ValidatorFunction): void {
      if (node.async || node.generator || node.typeParameters != null || isMethod(node)) return;
      const parameter = stringInputName(node);
      if (parameter === null) return;
      const domain = validatorDomain(node, parameter);
      if (domain === null || new Set(domain).size < 2) return;
      context.report({ node, messageId: "useEnumSchema" });
    }
    return {
      before() {
        const file = { filename: context.filename, cwd: context.cwd };
        if (isTestFile(file) || isGeneratedFile(file, context.sourceCode.text)) return false;
        return undefined;
      },
      FunctionDeclaration: inspect,
      FunctionExpression: inspect,
      ArrowFunctionExpression: inspect,
    };
  },
});
