/**
 * @fileoverview no-redundant-optional-array-default — an outer array default already accepts undefined input.
 *
 * Port of the 18.x `no-redundant-optional-array-default` rule. Same
 * algorithm; the test-file and generated-file gates run in `before()`, which
 * also resets the per-file import bindings.
 */

import { defineRule, type ESTree, type Node, type SourceCode } from "../types.js";
import { unwrapExpression } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { importSpecifierName } from "../utils/import-specifier-name.js";
import { isGeneratedFile, isTestFile } from "../utils/paths.js";
import { findVariable, getPropertyName } from "../utils/static-string.js";
import { isZodModule } from "../utils/zod.js";
import { privateLegacyArrayDefaultFix } from "./_private-legacy-array-default-fix.js";

const NAME = "no-redundant-optional-array-default";

type Identifier = Extract<Node, { type: "Identifier" }>;

function hasArrayFallback(node: ESTree.CallExpression): boolean {
  const argument = node.arguments[0];
  if (node.arguments.length !== 1 || argument === undefined) return false;
  const value = unwrapExpression(argument);
  if (value.type === "ArrayExpression") return true;
  if (
    (value.type !== "ArrowFunctionExpression" &&
      value.type !== "FunctionExpression") ||
    value.async ||
    value.generator
  )
    return false;
  // A function expression always has a body; `null` is only typed for declarations.
  if (value.body === null) return false;
  if (value.body.type !== "BlockStatement") {
    return unwrapExpression(value.body).type === "ArrayExpression";
  }
  const statement = value.body.body[0];
  return (
    value.body.body.length === 1 &&
    statement?.type === "ReturnStatement" &&
    statement.argument !== null &&
    unwrapExpression(statement.argument).type === "ArrayExpression"
  );
}

export default defineRule({
  meta: {
    type: "problem",
    docs: {
      description:
        "Remove `.optional()` immediately inside a Zod array default.",
      url: docsUrl(NAME),
    },
    fixable: "code",
    schema: [],
    messages: {
      redundantOptionalArrayDefault:
        "This array's outer `.default()` already handles undefined input. Remove the redundant inner `.optional()`.",
    },
  },
  createOnce(context) {
    let sourceCode: SourceCode;
    let namespaces = new Set<string>();
    let arrayConstructors = new Set<string>();
    let importBindings = new Map<string, Identifier>();

    function resolvesToTrackedImport(node: Identifier): boolean {
      const binding = importBindings.get(node.name);
      return binding !== undefined &&
        findVariable(sourceCode.getScope(node), node.name)?.defs.some((definition) => definition.name === binding) === true;
    }

    function isTrackedNamespace(node: Node): boolean {
      return node.type === "Identifier" && namespaces.has(node.name) && resolvesToTrackedImport(node);
    }

    function isArraySchemaExpression(node: Node): boolean {
      if (node.type !== "CallExpression") return false;
      const callee = unwrapExpression(node.callee);
      if (callee.type === "Identifier") return arrayConstructors.has(callee.name) && resolvesToTrackedImport(callee);
      if (callee.type !== "MemberExpression") return false;
      const receiver = unwrapExpression(callee.object);
      const arrayFactory = getPropertyName(callee) === "array" &&
        (receiver.type === "Identifier" ? isTrackedNamespace(receiver) : isZodSchemaExpression(receiver));
      return arrayFactory || isArraySchemaExpression(receiver);
    }

    function isZodSchemaExpression(node: Node): boolean {
      if (node.type !== "CallExpression") return false;
      const callee = unwrapExpression(node.callee);
      if (callee.type === "Identifier") return resolvesToTrackedImport(callee);
      if (callee.type !== "MemberExpression") return false;
      const receiver = unwrapExpression(callee.object);
      return isTrackedNamespace(receiver) || isZodSchemaExpression(receiver);
    }

    return {
      before(): boolean | void {
        sourceCode = context.sourceCode;
        const file = { filename: context.filename, cwd: context.cwd };
        if (isTestFile(file) || isGeneratedFile(file, sourceCode.text)) {
          return false;
        }
        namespaces = new Set<string>();
        arrayConstructors = new Set<string>();
        importBindings = new Map<string, Identifier>();
      },
      ImportDeclaration(node: ESTree.ImportDeclaration): void {
        if (!isZodModule(node.source.value)) return;
        for (const specifier of node.specifiers) {
          if (
            specifier.type === "ImportNamespaceSpecifier" ||
            specifier.type === "ImportDefaultSpecifier"
          ) {
            namespaces.add(specifier.local.name);
            importBindings.set(specifier.local.name, specifier.local);
            continue;
          }
          const imported = importSpecifierName(specifier);
          if (imported === "z") namespaces.add(specifier.local.name);
          else if (imported === "array") arrayConstructors.add(specifier.local.name);
          importBindings.set(specifier.local.name, specifier.local);
        }
      },
      CallExpression(node: ESTree.CallExpression): void {
        const defaultCallee = unwrapExpression(node.callee);
        if (defaultCallee.type !== "MemberExpression" || getPropertyName(defaultCallee) !== "default" || !hasArrayFallback(node)) return;
        const optionalCall = unwrapExpression(defaultCallee.object);
        if (optionalCall.type !== "CallExpression") return;
        const optionalCallee = unwrapExpression(optionalCall.callee);
        if (
          optionalCallee.type !== "MemberExpression" ||
          getPropertyName(optionalCallee) !== "optional" ||
          optionalCall.arguments.length !== 0 ||
          !isArraySchemaExpression(unwrapExpression(optionalCallee.object)) ||
          sourceCode.getCommentsInside(optionalCall).length > 0
        ) {
          return;
        }
        const fix = privateLegacyArrayDefaultFix(sourceCode, node, context.filename);
        context.report({
          node: optionalCall,
          messageId: "redundantOptionalArrayDefault",
          ...(fix !== null && { fix }),
        });
      },
    };
  },
});
