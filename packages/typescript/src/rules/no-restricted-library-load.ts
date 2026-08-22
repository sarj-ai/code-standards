/**
 * @fileoverview no-restricted-library-load — literal runtime module loads must obey the same library policy as static imports.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-restricted-library-load.test.ts
 */

import { AST_NODE_TYPES, ASTUtils, type TSESTree } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";

export interface RestrictedLibrary {
  readonly id: string;
  readonly module: string;
  readonly replacement: string;
  readonly note?: string;
}

type MessageIds = "restrictedLibraryLoad";
type Options = readonly [
  {
    libraries: readonly RestrictedLibrary[];
  },
];

export const NO_RESTRICTED_LIBRARY_LOAD_DOCUMENTATION = {
  summary: "Apply a configured library-replacement policy to literal dynamic imports, CommonJS loads, and TypeScript import-equals declarations.",
  rationale: "Runtime module loads can bypass the replacement policy enforced for static imports.",
  remediation: "Load the configured replacement library instead of the restricted module.",
  category: "architecture",
  limitations: ["Only literal dynamic imports, unshadowed CommonJS loads, and TypeScript import-equals declarations are checked."],
  examples: [
    { id: "static-import", title: "Static imports remain the static-import rule's responsibility", outcome: "no-match", files: [{ path: "src/client.ts", source: "import axios from 'axios';" }], focusPath: "src/client.ts", expectedCount: 0, public: true },
    { id: "runtime-load", title: "Do not load a restricted library at runtime", outcome: "match", files: [{ path: "src/client.ts", source: "const client = require('axios');" }], focusPath: "src/client.ts", expectedCount: 1, public: true },
  ],
} as const satisfies RuleDocumentation;

function literalModule(node: TSESTree.Node | undefined): string | null {
  return node?.type === AST_NODE_TYPES.Literal && typeof node.value === "string"
    ? node.value
    : null;
}

function matchesModule(source: string, module: string): boolean {
  return source === module || source.startsWith(`${module}/`);
}

export default createRule<Options, MessageIds>({
  name: "no-restricted-library-load",
  documentation: NO_RESTRICTED_LIBRARY_LOAD_DOCUMENTATION,
  meta: {
    type: "problem",
    docs: {
      description:
        "Apply a configured library-replacement policy to literal dynamic imports, CommonJS loads, and TypeScript import-equals declarations.",
    },
    schema: [
      {
        type: "object",
        additionalProperties: false,
        required: ["libraries"],
        properties: {
          libraries: {
            type: "array",
            items: {
              type: "object",
              additionalProperties: false,
              required: ["id", "module", "replacement"],
              properties: {
                id: { type: "string", minLength: 1 },
                module: { type: "string", minLength: 1 },
                replacement: { type: "string", minLength: 1 },
                note: { type: "string", minLength: 1 },
              },
            },
          },
        },
      },
    ],
    messages: {
      restrictedLibraryLoad:
        "{{id}}: Replace runtime loading of {{module}} with {{replacement}}.{{note}}",
    },
  },
  defaultOptions: [{ libraries: [] }],
  create(context, [options]) {
    const restrictions = options.libraries;

    function report(node: TSESTree.Node, source: string): void {
      const restriction = restrictions.find((entry) =>
        matchesModule(source, entry.module),
      );
      if (restriction === undefined) return;
      context.report({
        node,
        messageId: "restrictedLibraryLoad",
        data: {
          id: restriction.id,
          module: restriction.module,
          replacement: restriction.replacement,
          note: restriction.note === undefined ? "" : ` ${restriction.note}`,
        },
      });
    }

    function isUnshadowedRequire(node: TSESTree.Identifier): boolean {
      const variable = ASTUtils.findVariable(
        context.sourceCode.getScope(node),
        node.name,
      );
      return variable === null || variable.defs.length === 0;
    }

    return {
      ImportExpression(node: TSESTree.ImportExpression): void {
        const source = literalModule(node.source);
        if (source !== null) report(node.source, source);
      },
      CallExpression(node: TSESTree.CallExpression): void {
        let requireIdentifier: TSESTree.Identifier | null = null;
        if (
          node.callee.type === AST_NODE_TYPES.Identifier &&
          node.callee.name === "require"
        ) {
          requireIdentifier = node.callee;
        } else if (
          node.callee.type === AST_NODE_TYPES.MemberExpression &&
          !node.callee.computed &&
          node.callee.object.type === AST_NODE_TYPES.Identifier &&
          node.callee.object.name === "require" &&
          node.callee.property.type === AST_NODE_TYPES.Identifier &&
          node.callee.property.name === "resolve"
        ) {
          requireIdentifier = node.callee.object;
        }
        if (requireIdentifier === null || !isUnshadowedRequire(requireIdentifier)) return;
        const source = literalModule(node.arguments[0]);
        if (source !== null) report(node.arguments[0] as TSESTree.Node, source);
      },
      TSImportEqualsDeclaration(node: TSESTree.TSImportEqualsDeclaration): void {
        if (node.moduleReference.type !== AST_NODE_TYPES.TSExternalModuleReference) return;
        const source = literalModule(node.moduleReference.expression);
        if (source !== null) report(node.moduleReference.expression, source);
      },
    };
  },
});
