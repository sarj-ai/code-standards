/**
 * @fileoverview prefer-zod-enum-validator — keep closed string validation in one runtime schema.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/prefer-zod-enum-validator.test.ts
 */

import { AST_NODE_TYPES, type TSESTree } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile, isTestFile } from "./_paths.js";
import { staticString } from "./_static-string.js";
import { unwrapExpression } from "./_unwrap-expression.js";

type MessageIds = "useEnumSchema";
type Options = [];
type ValidatorFunction = TSESTree.FunctionDeclaration | TSESTree.FunctionExpression | TSESTree.ArrowFunctionExpression;

export const PREFER_ZOD_ENUM_VALIDATOR_DOCUMENTATION = {
  defaultLevel: "warning",
  summary: "Express closed string validators with a reusable Zod enum schema.",
  rationale: "Handwritten membership branches and parallel literal types repeat the accepted values and can drift. A named enum schema supplies validation and its inferred TypeScript union.",
  remediation: "Declare a module-level Schema = z.enum([…]), derive its type with z.infer<typeof Schema>, and use Schema.parse(value) or Schema.safeParse(value).success. Preserve any intentional error, fallback, or protocol behavior when migrating.",
  category: "maintainability",
  autofix: "none",
  requiresTypeInformation: false,
  references: ["https://zod.dev/api#enums", "https://zod.dev/basics#inferring-types"],
  limitations: [
    "Inspects synchronous single-parameter functions explicitly accepting unknown or string, whose complete body is a strict string-equality disjunction, an equivalent reject conjunction, or a closed switch that returns the input and throws otherwise. Boolean membership functions are also inspected.",
    "At least two distinct static string values are required. Membership collections, additional guards, coercion, normalization, transformed returns, methods, contextual parameter types, and multi-parameter functions are outside this bounded detector.",
    "Migration is manual because Zod errors, initialization and constructor hooks are observable; retain intentional failure behavior. A predicate must not be replaced with a throwing parse call. Test and generated files are excluded.",
  ],
  examples: [
    { id: "schema-validator", title: "Define validation and the type from one enum", outcome: "no-match", files: [{ path: "src/status.ts", source: "import { z } from 'zod'; const StatusSchema = z.enum(['ran', 'failed']); type Status = z.infer<typeof StatusSchema>; function status(value: unknown): Status { return StatusSchema.parse(value); }" }], focusPath: "src/status.ts", expectedCount: 0, public: true },
    { id: "manual-validator", title: "Replace a closed handwritten string parser", outcome: "match", files: [{ path: "src/status.ts", source: "type Status = 'ran' | 'failed'; function status(value: unknown): Status { if (value === 'ran' || value === 'failed') return value; throw new Error('Invalid status'); }" }], focusPath: "src/status.ts", expectedCount: 1, public: true },
  ],
} as const satisfies RuleDocumentation;

function isInput(node: TSESTree.Node | null | undefined, name: string): boolean {
  if (node == null) return false;
  const value = unwrapExpression(node);
  return value.type === AST_NODE_TYPES.Identifier && value.name === name;
}

function singleStatement(node: TSESTree.Statement | null): TSESTree.Statement | null {
  return node?.type === AST_NODE_TYPES.BlockStatement
    ? node.body.length === 1 ? node.body[0] ?? null : null
    : node;
}

function returnsInput(node: TSESTree.Statement | null, name: string): boolean {
  const statement = singleStatement(node);
  return statement?.type === AST_NODE_TYPES.ReturnStatement && isInput(statement.argument, name);
}

function throws(node: TSESTree.Statement | null): boolean {
  return singleStatement(node)?.type === AST_NODE_TYPES.ThrowStatement;
}

function validatorDomain(node: ValidatorFunction, name: string): readonly string[] | null {
  if (node.body?.type !== AST_NODE_TYPES.BlockStatement) return node.body === undefined ? null : comparisonDomain(node.body, name, false);
  const [first, second] = node.body.body;
  if (node.body.body.length === 1) {
    if (first?.type === AST_NODE_TYPES.ReturnStatement && first.argument !== null) return comparisonDomain(first.argument, name, false);
    if (first?.type === AST_NODE_TYPES.SwitchStatement) return switchDomain(first, name);
  }
  if (first?.type !== AST_NODE_TYPES.IfStatement) return null;
  const alternative = first.alternate === null && node.body.body.length === 2
    ? second ?? null
    : first.alternate !== null && node.body.body.length === 1 ? first.alternate : null;
  if (alternative === null) return null;
  return conditionalDomain(first, alternative, name);
}

function conditionalDomain(node: TSESTree.IfStatement, alternative: TSESTree.Statement, name: string): readonly string[] | null {
  if (returnsInput(node.consequent, name) && throws(alternative)) return comparisonDomain(node.test, name, false);
  if (throws(node.consequent) && returnsInput(alternative, name)) return comparisonDomain(node.test, name, true);
  if (booleanReturn(node.consequent, true) && booleanReturn(alternative, false)) return comparisonDomain(node.test, name, false);
  if (booleanReturn(node.consequent, false) && booleanReturn(alternative, true)) return comparisonDomain(node.test, name, true);
  return null;
}

function switchDomain(node: TSESTree.SwitchStatement, name: string): string[] | null {
  if (!isInput(node.discriminant, name) || node.cases.length < 3) return null;
  const last = node.cases.at(-1);
  if (last?.test !== null || last.consequent.length !== 1 || !throws(last.consequent[0] ?? null)) return null;
  const domain: string[] = [];
  for (const branch of node.cases.slice(0, -1)) {
    const value = branch.test === null ? null : staticString(branch.test);
    if (value === null || branch.consequent.length > 1) return null;
    if (branch.consequent.length === 1 && !returnsInput(branch.consequent[0] ?? null, name)) return null;
    domain.push(value);
  }
  // An unfinished label falling into the throwing default is not an accepted value.
  if (node.cases.at(-2)?.consequent.length !== 1) return null;
  return domain;
}

function comparisonDomain(node: TSESTree.Node, name: string, reject: boolean): string[] | null {
  const expression = unwrapExpression(node);
  if (expression.type === AST_NODE_TYPES.LogicalExpression && expression.operator === (reject ? "&&" : "||")) {
    const left = comparisonDomain(expression.left, name, reject);
    const right = comparisonDomain(expression.right, name, reject);
    return left === null || right === null ? null : [...left, ...right];
  }
  if (expression.type !== AST_NODE_TYPES.BinaryExpression || expression.operator !== (reject ? "!==" : "===")) return null;
  const literal = isInput(expression.left, name) ? expression.right : isInput(expression.right, name) ? expression.left : null;
  const value = literal === null ? null : staticString(literal);
  return value === null ? null : [value];
}

function booleanReturn(node: TSESTree.Statement | null, expected: boolean): boolean {
  const statement = singleStatement(node);
  if (statement?.type !== AST_NODE_TYPES.ReturnStatement || statement.argument === null) return false;
  const value = unwrapExpression(statement.argument);
  return value.type === AST_NODE_TYPES.Literal && value.value === expected;
}


export default createRule<Options, MessageIds>({
  name: "prefer-zod-enum-validator",
  documentation: PREFER_ZOD_ENUM_VALIDATOR_DOCUMENTATION,
  meta: {
    type: "suggestion",
    docs: { description: PREFER_ZOD_ENUM_VALIDATOR_DOCUMENTATION.summary },
    schema: [],
    messages: { useEnumSchema: "Replace this closed string validator with a named z.enum([…]) schema and derive its type with z.infer. Use parse for parsing or safeParse for a boolean check; preserve intentional failure behavior." },
  },
  defaultOptions: [],
  create(context) {
    if (isTestFile(context) || isGeneratedFile(context, context.sourceCode.text)) return {};
    function inspect(node: ValidatorFunction): void {
      if (node.async || node.generator || node.params.length !== 1 || node.typeParameters !== undefined) return;
      const [parameter] = node.params;
      if (parameter?.type !== AST_NODE_TYPES.Identifier || parameter.optional) return;
      const annotation = parameter.typeAnnotation?.typeAnnotation;
      if (annotation?.type !== AST_NODE_TYPES.TSUnknownKeyword && annotation?.type !== AST_NODE_TYPES.TSStringKeyword) return;
      if (node.parent.type === AST_NODE_TYPES.MethodDefinition || (node.parent.type === AST_NODE_TYPES.Property && node.parent.method)) return;
      const domain = validatorDomain(node, parameter.name);
      if (domain === null || new Set(domain).size < 2) return;
      context.report({ node, messageId: "useEnumSchema" });
    }
    return { FunctionDeclaration: inspect, FunctionExpression: inspect, ArrowFunctionExpression: inspect };
  },
});
