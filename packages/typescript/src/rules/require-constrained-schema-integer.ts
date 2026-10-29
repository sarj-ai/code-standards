/**
 * @fileoverview require-constrained-schema-integer — Declare integer and lower-bound validation for numeric limit and version schema fields.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/require-constrained-schema-integer.test.ts
 */

import { AST_NODE_TYPES, ASTUtils, type TSESTree } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile } from "./_paths.js";
import { unwrapExpression } from "./_unwrap-expression.js";
import { isZodModule } from "./_zod.js";

const FIELD_MINIMUMS: ReadonlyMap<string, number> = new Map([["limit", 1], ["version", 0]]);
const NUMBER_FACTORIES: ReadonlySet<string> = new Set(["number", "int", "int32", "uint32"]);
const PRESERVING: ReadonlySet<string> = new Set(["optional", "nullable", "nullish", "default", "catch", "readonly", "brand", "describe", "meta", "max", "lte", "lt", "finite", "safe", "multipleOf"]);

function numericLiteral(node: TSESTree.Node): number | null {
  node = unwrapExpression(node);
  if (node.type === AST_NODE_TYPES.Literal && typeof node.value === "number") return node.value;
  if (node.type === AST_NODE_TYPES.UnaryExpression && (node.operator === "-" || node.operator === "+")) {
    const value = numericLiteral(node.argument);
    return value === null ? null : node.operator === "-" ? -value : value;
  }
  return null;
}

export const REQUIRE_CONSTRAINED_SCHEMA_INTEGER_DOCUMENTATION = {
  defaultLevel: "warning",
  summary: "Declare integer and lower-bound validation for numeric limit and version schema fields.",
  rationale: "A bare number schema accepts fractions and negative limits or versions. Encoding the domain in validation makes downstream arithmetic and pagination contracts explicit.",
  remediation: "Use an integer schema with a positive lower bound for limit and a nonnegative lower bound for version, or reuse an existing named domain schema.",
  category: "correctness",
  limitations: [
    "This is the requested field policy for direct limit/version properties of runtime-imported Zod object/strictObject/looseObject schemas. Recognizes direct numeric and coerce constructors plus ordinary same-chain bounds and wrappers. Does not infer domains from arbitrary numeric variable names.",
    "Named schema aliases, imported domain schemas, unions, callbacks and transformations are excluded. Dynamic lower bounds count as an explicit reviewed constraint; generated/vendor files are excluded, and maintained tests are checked.",
    "Version zero remains valid; limits require at least one. Numeric custom sentinels require a precise named domain schema or an explained local suppression. No automatic runtime contract change is offered.",
  ],
  examples: [
    { id: "unconstrained-limit", title: "A number is broader than a limit", outcome: "match", files: [{ path: "src/options.ts", source: "import { z } from 'zod'; const OptionsSchema = z.object({ limit: z.number() });" }], focusPath: "src/options.ts", expectedCount: 1, public: true },
    { id: "constrained-fields", title: "Declare the numeric domain", outcome: "no-match", files: [{ path: "src/options.ts", source: "import { z } from 'zod'; const OptionsSchema = z.object({ limit: z.number().int().positive(), version: z.int().nonnegative() });" }], focusPath: "src/options.ts", expectedCount: 0, public: true },
  ],
} as const satisfies RuleDocumentation;

export default createRule<[], "constrainInteger">({
  name: "require-constrained-schema-integer",
  documentation: REQUIRE_CONSTRAINED_SCHEMA_INTEGER_DOCUMENTATION,
  meta: {
    type: "suggestion",
    docs: { description: REQUIRE_CONSTRAINED_SCHEMA_INTEGER_DOCUMENTATION.summary },
    schema: [],
    messages: { constrainInteger: "Declare `{{field}}` as an integer with a lower bound of {{minimum}} or greater, or reuse its named domain schema." },
  },
  defaultOptions: [],
  create(context) {
    if (isGeneratedFile(context, context.sourceCode.text)) return {};
    const sourceCode = context.sourceCode;
    function factory(node: TSESTree.Node): string | null {
      node = unwrapExpression(node);
      if (node.type === AST_NODE_TYPES.Identifier) {
        const definition = imported(node);
        return definition?.type === AST_NODE_TYPES.ImportSpecifier ? (definition.imported.type === AST_NODE_TYPES.Identifier ? definition.imported.name : definition.imported.value) : null;
      }
      if (node.type !== AST_NODE_TYPES.MemberExpression) return null;
      let receiver = unwrapExpression(node.object);
      if (receiver.type === AST_NODE_TYPES.MemberExpression && ASTUtils.getPropertyName(receiver) === "coerce") receiver = unwrapExpression(receiver.object);
      if (receiver.type !== AST_NODE_TYPES.Identifier) return null;
      const definition = imported(receiver);
      if (definition === null || (definition.type === AST_NODE_TYPES.ImportSpecifier &&
        (definition.imported.type === AST_NODE_TYPES.Identifier ? definition.imported.name : definition.imported.value) !== "z")) return null;
      return ASTUtils.getPropertyName(node);
    }
function imported(identifier: TSESTree.Identifier): TSESTree.ImportClause | null {
      const variable = ASTUtils.findVariable(sourceCode.getScope(identifier), identifier.name);
      const definition = variable?.defs[0]?.node;
      if (variable?.defs.length !== 1 || (definition?.type !== AST_NODE_TYPES.ImportSpecifier && definition?.type !== AST_NODE_TYPES.ImportNamespaceSpecifier) ||
        definition.parent.type !== AST_NODE_TYPES.ImportDeclaration || definition.parent.importKind === "type" || !isZodModule(definition.parent.source.value)) return null;
      return definition.type === AST_NODE_TYPES.ImportSpecifier && definition.importKind === "type" ? null : definition;
    }
    function constrained(value: TSESTree.Node, minimum: number): boolean | null {
      const calls: { method: string; call: TSESTree.CallExpression }[] = [];
      value = unwrapExpression(value);
      while (value.type === AST_NODE_TYPES.CallExpression) {
        const name = factory(value.callee);
        if (name !== null) {
          return chainContract(name, calls, minimum);
        }
        const callee = unwrapExpression(value.callee);
        if (callee.type !== AST_NODE_TYPES.MemberExpression) return null;
        const method = ASTUtils.getPropertyName(callee);
        if (method === null) return null;
        calls.push({ method, call: value });
        value = unwrapExpression(callee.object);
      }
      return null;
    }
    function chainContract(name: string, calls: readonly { readonly method: string; readonly call: TSESTree.CallExpression }[], minimum: number): boolean | null {
      if (!NUMBER_FACTORIES.has(name)) return null;
      let integer = name !== "number";
      let bounded = name === "uint32" && minimum === 0;
      for (const { method, call } of calls) {
        if (method === "int") integer = true;
        else if (method === "positive") bounded = true;
        else if (method === "nonnegative") bounded ||= minimum === 0;
        else if (["min", "gte", "gt"].includes(method)) {
          const bound = lowerBound(call, minimum, method === "gt");
          if (bound === null) return null;
          bounded ||= bound;
        } else if (!PRESERVING.has(method)) return null;
      }
      return integer && bounded;
    }
    function lowerBound(call: TSESTree.CallExpression, minimum: number, exclusive: boolean): boolean | null {
      const argument = call.arguments[0];
      if (argument === undefined || argument.type === AST_NODE_TYPES.SpreadElement) return null;
      const bound = numericLiteral(argument);
      return bound === null || bound >= minimum - (exclusive ? 1 : 0);
    }
    return {
      CallExpression(node): void {
        const name = factory(node.callee);
        if (name === null || !["object", "strictObject", "looseObject"].includes(name) || node.arguments.length !== 1) return;
        const shape = node.arguments[0];
        if (shape?.type !== AST_NODE_TYPES.ObjectExpression) return;
        for (const property of shape.properties) {
          if (property.type !== AST_NODE_TYPES.Property || property.computed || property.kind !== "init" || property.method) continue;
          const field = ASTUtils.getPropertyName(property);
          const minimum = field === null ? undefined : FIELD_MINIMUMS.get(field);
          if (minimum === undefined || field === null || constrained(property.value, minimum) !== false) continue;
          context.report({ node: property, messageId: "constrainInteger", data: { field, minimum } });
        }
      },
    };
  },
});
