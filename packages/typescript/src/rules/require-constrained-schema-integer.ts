/**
 * @fileoverview require-constrained-schema-integer — limit and version schema fields need integer lower bounds.
 *
 * Port of the 18.x `require-constrained-schema-integer` rule. The rule
 * is untyped, so the port covers all of it.
 */

import { defineRule, type ESTree, type Node } from "../types.js";
import { parentOf, unwrapExpression } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { importSpecifierName } from "../utils/import-specifier-name.js";
import { isGeneratedFile } from "../utils/paths.js";
import { findVariable, getPropertyName } from "../utils/static-string.js";
import { isZodModule } from "../utils/zod.js";

type IdentifierNode = Extract<Node, { type: "Identifier" }>;

const NAME = "require-constrained-schema-integer";

const FIELD_MINIMUMS: ReadonlyMap<string, number> = new Map([["limit", 1], ["version", 0]]);
const NUMBER_FACTORIES: ReadonlySet<string> = new Set(["number", "int", "int32", "uint32"]);
const OBJECT_FACTORIES: ReadonlySet<string> = new Set(["object", "strictObject", "looseObject"]);
const LOWER_BOUNDS: ReadonlySet<string> = new Set(["min", "gte", "gt"]);
const PRESERVING: ReadonlySet<string> = new Set(["optional", "nullable", "nullish", "default", "catch", "readonly", "brand", "describe", "meta", "max", "lte", "lt", "finite", "safe", "multipleOf"]);

type ImportClause = ESTree.ImportSpecifier | ESTree.ImportNamespaceSpecifier;
interface ChainCall {
  readonly method: string;
  readonly call: ESTree.CallExpression;
}

function chainContract(name: string, calls: readonly ChainCall[], minimum: number): boolean | null {
  if (!NUMBER_FACTORIES.has(name)) return null;
  let integer = name !== "number";
  let bounded = name === "uint32" && minimum === 0;
  for (const { method, call } of calls) {
    if (method === "int") integer = true;
    else if (method === "positive") bounded = true;
    else if (method === "nonnegative") bounded ||= minimum === 0;
    else if (LOWER_BOUNDS.has(method)) {
      const bound = lowerBound(call, minimum, method === "gt");
      if (bound === null) return null;
      bounded ||= bound;
    } else if (!PRESERVING.has(method)) return null;
  }
  return integer && bounded;
}

function lowerBound(call: ESTree.CallExpression, minimum: number, exclusive: boolean): boolean | null {
  const argument = call.arguments[0];
  if (argument === undefined || argument.type === "SpreadElement") return null;
  const bound = numericLiteral(argument);
  return bound === null || bound >= minimum - (exclusive ? 1 : 0);
}

function numericLiteral(node: Node): number | null {
  node = unwrapExpression(node);
  if (node.type === "Literal" && typeof node.value === "number") return node.value;
  if (node.type === "UnaryExpression" && (node.operator === "-" || node.operator === "+")) {
    const value = numericLiteral(node.argument);
    return value === null ? null : node.operator === "-" ? -value : value;
  }
  return null;
}

export default defineRule({
  meta: {
    type: "suggestion",
    docs: {
      description: "Declare integer and lower-bound validation for numeric limit and version schema fields.",
      url: docsUrl(NAME),
    },
    schema: [],
    messages: { constrainInteger: "Declare `{{field}}` as an integer with a lower bound of {{minimum}} or greater, or reuse its named domain schema." },
  },
  createOnce(context) {

    function factory(node: Node): string | null {
      node = unwrapExpression(node);
      if (node.type === "Identifier") {
        const definition = imported(node);
        return definition?.type === "ImportSpecifier" ? importSpecifierName(definition) : null;
      }
      if (node.type !== "MemberExpression") return null;
      let receiver = unwrapExpression(node.object);
      if (receiver.type === "MemberExpression" && getPropertyName(receiver) === "coerce") receiver = unwrapExpression(receiver.object);
      if (receiver.type !== "Identifier") return null;
      const definition = imported(receiver);
      if (definition === null || (definition.type === "ImportSpecifier" && importSpecifierName(definition) !== "z")) return null;
      return getPropertyName(node);
    }

    function imported(identifier: IdentifierNode): ImportClause | null {
      const variable = findVariable(context.sourceCode.getScope(identifier), identifier.name);
      const definition = variable?.defs[0]?.node;
      if (variable?.defs.length !== 1 || (definition?.type !== "ImportSpecifier" && definition?.type !== "ImportNamespaceSpecifier")) return null;
      const declaration = parentOf(definition);
      if (declaration?.type !== "ImportDeclaration" || declaration.importKind === "type" || !isZodModule(declaration.source.value)) return null;
      return definition.type === "ImportSpecifier" && definition.importKind === "type" ? null : definition;
    }

    function constrained(value: Node, minimum: number): boolean | null {
      const calls: ChainCall[] = [];
      value = unwrapExpression(value);
      while (value.type === "CallExpression") {
        const name = factory(value.callee);
        if (name !== null) return chainContract(name, calls, minimum);
        const callee = unwrapExpression(value.callee);
        if (callee.type !== "MemberExpression") return null;
        const method = getPropertyName(callee);
        if (method === null) return null;
        calls.push({ method, call: value });
        value = unwrapExpression(callee.object);
      }
      return null;
    }

    return {
      before() {
        if (isGeneratedFile({ filename: context.filename, cwd: context.cwd }, context.sourceCode.text)) return false;
        return undefined;
      },
      CallExpression(node: ESTree.CallExpression): void {
        const [shape] = node.arguments;
        if (node.arguments.length !== 1 || shape?.type !== "ObjectExpression") return;
        const name = factory(node.callee);
        if (name === null || !OBJECT_FACTORIES.has(name)) return;
        for (const property of shape.properties) {
          if (property.type !== "Property" || property.computed || property.kind !== "init" || property.method) continue;
          const field = getPropertyName(property);
          const minimum = field === null ? undefined : FIELD_MINIMUMS.get(field);
          if (minimum === undefined || field === null || constrained(property.value, minimum) !== false) continue;
          context.report({ node: property, messageId: "constrainInteger", data: { field, minimum } });
        }
      },
    };
  },
});
