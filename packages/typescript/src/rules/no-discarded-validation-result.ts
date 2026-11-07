/**
 * @fileoverview no-discarded-validation-result — Zod validation outcomes and transformed outputs must be consumed.
 *
 * Port of the 18.x `no-discarded-validation-result` rule. The rule is
 * untyped, so the port covers all of it.
 */

import { defineRule, type ESTree, type Node } from "../types.js";
import { parentOf, unwrapExpression } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { importSpecifierName } from "../utils/import-specifier-name.js";
import { isGeneratedFile } from "../utils/paths.js";
import { findVariable, getPropertyName } from "../utils/static-string.js";
import { isZodModule } from "../utils/zod.js";

const NAME = "no-discarded-validation-result";

const CHANGING: ReadonlySet<string> = new Set(["transform", "default", "prefault", "catch", "coerce", "trim", "toLowerCase", "toUpperCase", "normalize", "preprocess"]);
const VALIDATION_METHODS: ReadonlySet<string> = new Set(["parse", "parseAsync", "safeParse", "safeParseAsync"]);

export default defineRule({
  meta: {
    type: "problem",
    docs: {
      description: "Consume Zod validation outcomes and transformed outputs instead of discarding them.",
      url: docsUrl(NAME),
    },
    schema: [],
    messages: { discarded: "Consume this validation result; its outcome or transformed value is currently discarded." },
  },
  createOnce(context) {
    /** The Zod schema an expression builds, and whether it changes the parsed value; null when it is not one. */
    function schema(node: Node, depth = 0): Schema | null {
      if (depth > 24) return null;
      node = unwrapExpression(node);
      if (node.type === "Identifier") return identifierSchema(node, depth);
      if (node.type === "MemberExpression") return schema(node.object, depth + 1);
      return node.type === "CallExpression" ? callSchema(node, depth) : null;
    }

    function identifierSchema(node: Extract<Node, { type: "Identifier" }>, depth: number): Schema | null {
      const variable = findVariable(context.sourceCode.getScope(node), node.name);
      const definition = variable?.defs[0]?.node;
      if (variable?.defs.length !== 1 || definition === undefined) return null;
      if (zodValueImport(definition) !== null) return { changed: false };
      const parent = parentOf(definition);
      if (definition.type === "VariableDeclarator" && parent?.type === "VariableDeclaration" && parent.kind === "const" && definition.init !== null && definition.range[1] < node.range[0] && !variable.references.some(reference => reference.isWrite() && !reference.init)) return schema(definition.init, depth + 1);
      return null;
    }

    function callSchema(node: ESTree.CallExpression, depth: number): Schema | null {
      const owner = schema(node.callee, depth + 1);
      if (owner === null) return null;
      const { callee } = node;
      const changingCall = callee.type === "MemberExpression" && (CHANGING.has(getPropertyName(callee) ?? "") || coercionNamespace(callee.object));
      return { changed: owner.changed || changingCall || node.arguments.some(argument => changingArgument(argument, depth)) };
    }

    function changingArgument(argument: Node, depth: number): boolean {
      if (argument.type === "ArrayExpression") return argument.elements.some(element => element !== null && changingSchema(element, depth));
      if (argument.type === "ObjectExpression") return argument.properties.some(property => property.type === "Property" && changingSchema(property.value, depth));
      return changingSchema(argument, depth);
    }

    function changingSchema(node: Node, depth: number): boolean {
      return schema(node, depth + 1)?.changed === true;
    }

    function coercionNamespace(node: Node): boolean {
      let namespace = false;
      if (node.type === "MemberExpression" && getPropertyName(node) === "coerce") {
        namespace = true;
        node = node.object;
      }
      if (node.type !== "Identifier") return false;
      const variable = findVariable(context.sourceCode.getScope(node), node.name);
      const definition = variable?.defs[0]?.node;
      const specifier = variable?.defs.length === 1 && definition !== undefined ? zodValueImport(definition) : null;
      if (specifier === null) return false;
      if (specifier.type === "ImportNamespaceSpecifier") return namespace;
      const name = importSpecifierName(specifier);
      return namespace ? name === "z" : name === "coerce";
    }

    return {
      before() {
        if (isGeneratedFile({ filename: context.filename, cwd: context.cwd }, context.sourceCode.text)) return false;
        return undefined;
      },
      ExpressionStatement(statement: ESTree.ExpressionStatement): void {
        let expression = unwrapExpression(statement.expression);
        if (expression.type === "AwaitExpression") expression = unwrapExpression(expression.argument);
        if (expression.type !== "CallExpression" || expression.callee.type !== "MemberExpression") return;
        const method = getPropertyName(expression.callee);
        if (!VALIDATION_METHODS.has(method ?? "")) return;
        const owner = schema(expression.callee.object);
        if (owner !== null && (owner.changed || method?.startsWith("safe") === true)) context.report({ node: expression, messageId: "discarded" });
      },
    };
  },
});

interface Schema {
  readonly changed: boolean;
}

/** A named or namespace value import from a Zod module. */
function zodValueImport(definition: Node): ESTree.ImportSpecifier | ESTree.ImportNamespaceSpecifier | null {
  const declaration = parentOf(definition);
  if (declaration?.type !== "ImportDeclaration" || declaration.importKind === "type" || !isZodModule(declaration.source.value)) return null;
  if (definition.type === "ImportNamespaceSpecifier") return definition;
  return definition.type === "ImportSpecifier" && definition.importKind !== "type" ? definition : null;
}
