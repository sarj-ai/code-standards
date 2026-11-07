/**
 * @fileoverview prefer-native-random-uuid — Node 22's native UUID generator makes the dependency unnecessary for UUID v4 calls.
 *
 * Port of the 18.x `prefer-native-random-uuid` rule. Untyped.
 */

import { defineRule, type ESTree, type Node, type SourceCode, type TsVariable } from "../types.js";
import { unwrapExpression } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { existingUuidProviderFix } from "../utils/existing-uuid-provider-fix.js";
import { importSpecifierName } from "../utils/import-specifier-name.js";
import { findVariable } from "../utils/static-string.js";

const NAME = "prefer-native-random-uuid";

type Identifier = Extract<Node, { type: "Identifier" }>;

/** The `require` callee of a `require("uuid")` call, or null. */
function requireUuidCallee(node: Node | null): Identifier | null {
  return node?.type === "CallExpression" &&
    node.callee.type === "Identifier" &&
    node.callee.name === "require" &&
    node.arguments.length === 1 &&
    node.arguments[0]?.type === "Literal" &&
    node.arguments[0].value === "uuid"
    ? node.callee
    : null;
}

/** `v4` or `"v4"` as a non-computed destructuring key. */
function isV4Key(property: ESTree.BindingProperty): boolean {
  if (property.computed) return false;
  return (property.key.type === "Identifier" && property.key.name === "v4") || (property.key.type === "Literal" && property.key.value === "v4");
}

export default defineRule({
  meta: {
    type: "suggestion",
    docs: {
      description:
        "Prefer `globalThis.crypto.randomUUID()` over resolved zero-argument UUID v4 bindings from the `uuid` package.",
      url: docsUrl(NAME),
    },
    hasSuggestions: true,
    fixable: "code",
    schema: [],
    messages: {
      preferNative:
        "Where supported by the deployment runtime, prefer native `globalThis.crypto.randomUUID()` over the `uuid` package for UUID v4.",
      replaceWithNative: "Replace this UUID v4 call with the native implementation.",
    },
  },
  createOnce(context) {
    let sourceCode: SourceCode;
    let directBindings = new Set<TsVariable>();
    let namespaceBindings = new Set<TsVariable>();

    function resolve(identifier: Identifier): TsVariable | null {
      return findVariable(sourceCode.getScope(identifier), identifier.name);
    }

    function record(identifier: Identifier, destination: Set<TsVariable>): void {
      const variable = resolve(identifier);
      if (variable !== null) destination.add(variable);
    }

    function report(node: ESTree.CallExpression): void {
      const globalBinding = findVariable(sourceCode.getScope(node), "globalThis");
      const canSuggest = (globalBinding?.defs.length ?? 0) === 0 && sourceCode.getCommentsInside(node).length === 0;
      const fix = existingUuidProviderFix(sourceCode, node, "package");
      context.report({
        node,
        messageId: "preferNative",
        ...(fix !== null && { fix }),
        suggest: canSuggest
          ? [
              {
                messageId: "replaceWithNative",
                fix: (fixer) => fixer.replaceText(node, "globalThis.crypto.randomUUID()"),
              },
            ]
          : [],
      });
    }

    return {
      before() {
        sourceCode = context.sourceCode;
        directBindings = new Set();
        namespaceBindings = new Set();
      },
      ImportDeclaration(node) {
        if (node.source.value !== "uuid") return;
        for (const specifier of node.specifiers) {
          if (
            specifier.type === "ImportSpecifier" && importSpecifierName(specifier) === "v4"
          ) {
            record(specifier.local, directBindings);
          } else if (specifier.type === "ImportNamespaceSpecifier") {
            record(specifier.local, namespaceBindings);
          }
        }
      },
      VariableDeclarator(node) {
        const declaration = node.parent as ESTree.VariableDeclaration;
        if (declaration.kind !== "const") return;
        const require = requireUuidCallee(node.init);
        if (require === null || (resolve(require)?.defs.length ?? 0) > 0) return;
        if (node.id.type === "Identifier") {
          record(node.id, namespaceBindings);
          return;
        }
        if (node.id.type !== "ObjectPattern") return;
        for (const property of node.id.properties) {
          if (property.type === "Property" && isV4Key(property) && property.value.type === "Identifier") {
            record(property.value, directBindings);
          }
        }
      },
      "CallExpression:exit"(node: ESTree.CallExpression) {
        // With no binding recorded yet no call can match, so skip the scope lookups.
        if (node.arguments.length !== 0 || (directBindings.size === 0 && namespaceBindings.size === 0)) return;
        const callee = unwrapExpression(node.callee);
        if (callee.type === "Identifier") {
          const variable = resolve(callee);
          if (variable !== null && directBindings.has(variable)) report(node);
          return;
        }
        if (
          callee.type !== "MemberExpression" ||
          callee.computed ||
          callee.object.type !== "Identifier" ||
          callee.property.type !== "Identifier" ||
          callee.property.name !== "v4"
        ) {
          return;
        }
        const variable = resolve(callee.object);
        if (variable !== null && namespaceBindings.has(variable)) report(node);
      },
    };
  },
});
