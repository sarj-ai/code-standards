/**
 * @fileoverview require-static-next-matcher — Next.js matcher configuration must be statically analyzable at build time.
 *
 * Port of the 18.x `require-static-next-matcher` rule. Same algorithm;
 * the filename gate runs in `before()`.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/require-static-next-matcher.test.ts
 */

import { defineRule, type ESTree, type Node } from "../types.js";
import { unwrapExpression } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { staticMatcherFix } from "./_static-matcher-fix.js";

const NAME = "require-static-next-matcher";
const NEXT_ENTRY_FILE = /(?:^|[/\\])(?:middleware|proxy)\.[cm]?[jt]sx?$/u;

function isStaticValue(node: Node): boolean {
  const value = unwrapExpression(node);
  if (value.type === "Literal") {
    return true;
  }
  if (value.type === "TemplateLiteral") {
    return value.expressions.length === 0;
  }
  if (value.type === "ArrayExpression") {
    return value.elements.every(
      (element) => element !== null && element.type !== "SpreadElement" && isStaticValue(element),
    );
  }
  if (value.type === "ObjectExpression") {
    return value.properties.every(
      (property) =>
        property.type === "Property" &&
        property.kind === "init" &&
        !property.computed &&
        (property.value as Node).type !== "AssignmentPattern" &&
        isStaticValue(property.value),
    );
  }
  return false;
}

function propertyName(property: ESTree.ObjectProperty): string | null {
  if (!property.computed && property.key.type === "Identifier") return property.key.name;
  return property.key.type === "Literal" && typeof property.key.value === "string" ? property.key.value : null;
}

export default defineRule({
  meta: {
    type: "problem",
    fixable: "code",
    docs: {
      description: "Require Next.js middleware and proxy matcher configuration to contain only build-time literals.",
      url: docsUrl(NAME),
    },
    schema: [],
    messages: {
      dynamicMatcher:
        "Keep Next.js matcher strings, arrays and object fields literal in the exported config. Dynamic values such as variables are not supported by its build-time static analysis and can be ignored.",
    },
  },
  createOnce(context) {
    return {
      before(): boolean | void {
        if (!NEXT_ENTRY_FILE.test(context.filename)) return false;
      },
      ExportNamedDeclaration(node): void {
        if (node.declaration?.type !== "VariableDeclaration") {
          return;
        }
        for (const declaration of node.declaration.declarations) {
          if (declaration.id.type !== "Identifier" || declaration.id.name !== "config" || declaration.init === null) {
            continue;
          }
          const config = unwrapExpression(declaration.init);
          if (config.type !== "ObjectExpression") {
            continue;
          }
          for (const property of config.properties) {
            if (
              property.type !== "Property" ||
              propertyName(property) !== "matcher" ||
              (property.value as Node).type === "AssignmentPattern"
            ) {
              continue;
            }
            if (!isStaticValue(property.value)) {
              const fix = staticMatcherFix(context.sourceCode, property);
              context.report({
                node: property.value,
                messageId: "dynamicMatcher",
                ...(fix !== null && { fix }),
              });
            }
          }
        }
      },
    };
  },
});
