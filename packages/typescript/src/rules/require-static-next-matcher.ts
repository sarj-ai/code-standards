/**
 * @fileoverview require-static-next-matcher — Next.js matcher configuration must be statically analyzable at build time.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/require-static-next-matcher.test.ts
 */

import { AST_NODE_TYPES, type TSESTree } from "@typescript-eslint/utils";

import { unwrapExpression } from "./_unwrap-expression.js";
import { staticMatcherFix } from "./_static-matcher-fix.js";

import { createRule, type RuleDocumentation } from "./_docs.js";

type MessageIds = "dynamicMatcher";
type Options = readonly [];

export const REQUIRE_STATIC_NEXT_MATCHER_DOCUMENTATION = {
  summary:
    "Require Next.js middleware and proxy matcher configuration to contain only build-time literals.",
  rationale:
    "Next.js must statically analyze matcher values at build time; computed values are ignored.",
  remediation:
    "Write matcher strings, arrays, and object fields as literals in the exported config.",
  category: "correctness",
  autofix: "safe",
  limitations: [
    "Only directly exported matcher configuration in middleware/proxy entry files is inspected. Literal matcher validity is left to Next.js; this rule checks static syntax, not the complete framework schema.",
    "Automatic edits only inline an existing private unannotated const string literal in a complete two-statement module whose only export is a const config containing that sole matcher reference. The exclusively inlined binding is removed. Imports, comments, arrays, other references or properties, wrappers, annotations, mutable bindings and computed keys remain manual.",
  ],
  references: [
    "https://nextjs.org/docs/app/api-reference/file-conventions/proxy",
  ],
  examples: [
    {
      id: "literal-matcher",
      title: "Use a literal matcher",
      outcome: "no-match",
      files: [
        {
          path: "src/middleware.ts",
          source: 'export const config = { matcher: "/api/:path*" };',
        },
      ],
      focusPath: "src/middleware.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "computed-matcher",
      title: "Do not compute the matcher",
      outcome: "match",
      files: [
        {
          path: "src/middleware.ts",
          source:
            'const matcher = "/api/:path*"; export const config = { matcher };',
        },
      ],
      focusPath: "src/middleware.ts",
      expectedCount: 1,
      public: true,
    },
    {
      id: "safe-autofix",
      title: "Inline the existing private literal route",
      outcome: "match",
      files: [
        {
          path: "src/middleware.ts",
          source:
            'const matcher = "/api/:path*"; export const config = { matcher };',
        },
      ],
      fixedFiles: [
        {
          path: "src/middleware.ts",
          source: 'export const config = { matcher: "/api/:path*" };',
        },
      ],
      focusPath: "src/middleware.ts",
      expectedCount: 1,
    },
  ],
} as const satisfies RuleDocumentation;

const NEXT_ENTRY_FILE = /(?:^|[/\\])(?:middleware|proxy)\.[cm]?[jt]sx?$/u;

function isStaticValue(node: TSESTree.Node): boolean {
  const value = unwrapExpression(node);
  if (value.type === AST_NODE_TYPES.Literal) {
    return true;
  }
  if (value.type === AST_NODE_TYPES.TemplateLiteral) {
    return value.expressions.length === 0;
  }
  if (value.type === AST_NODE_TYPES.ArrayExpression) {
    return value.elements.every(
      (element) =>
        element !== null &&
        element.type !== AST_NODE_TYPES.SpreadElement &&
        isStaticValue(element),
    );
  }
  if (value.type === AST_NODE_TYPES.ObjectExpression) {
    return value.properties.every(
      (property) =>
        property.type === AST_NODE_TYPES.Property &&
        property.kind === "init" &&
        !property.computed &&
        property.value.type !== AST_NODE_TYPES.AssignmentPattern &&
        isStaticValue(property.value),
    );
  }
  return false;
}

function propertyName(property: TSESTree.Property): string | null {
  if (!property.computed && property.key.type === AST_NODE_TYPES.Identifier)
    return property.key.name;
  return property.key.type === AST_NODE_TYPES.Literal &&
    typeof property.key.value === "string"
    ? property.key.value
    : null;
}

export default createRule<Options, MessageIds>({
  name: "require-static-next-matcher",
  documentation: REQUIRE_STATIC_NEXT_MATCHER_DOCUMENTATION,
  meta: {
    type: "problem",
    fixable: "code",
    docs: {
      description:
        "Require Next.js middleware and proxy matcher configuration to contain only build-time literals.",
    },
    schema: [],
    messages: {
      dynamicMatcher:
        "Keep Next.js matcher strings, arrays and object fields literal in the exported config. Dynamic values such as variables are not supported by its build-time static analysis and can be ignored.",
    },
  },
  defaultOptions: [],
  create(context) {
    if (!NEXT_ENTRY_FILE.test(context.filename)) {
      return {};
    }

    return {
      ExportNamedDeclaration(node): void {
        if (node.declaration?.type !== AST_NODE_TYPES.VariableDeclaration) {
          return;
        }
        for (const declaration of node.declaration.declarations) {
          if (
            declaration.id.type !== AST_NODE_TYPES.Identifier ||
            declaration.id.name !== "config" ||
            declaration.init === null
          ) {
            continue;
          }
          const config = unwrapExpression(declaration.init);
          if (config.type !== AST_NODE_TYPES.ObjectExpression) {
            continue;
          }
          for (const property of config.properties) {
            if (
              property.type !== AST_NODE_TYPES.Property ||
              propertyName(property) !== "matcher" ||
              property.value.type === AST_NODE_TYPES.AssignmentPattern
            ) {
              continue;
            }
            if (!isStaticValue(property.value)) {
              const fix = staticMatcherFix(context.sourceCode, property);
              context.report({
                node: property.value,
                messageId: "dynamicMatcher",
                fix,
              });
            }
          }
        }
      },
    };
  },
});
