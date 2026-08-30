/**
 * @fileoverview require-interface-for-exported-class — exported behavior needs an explicit substitutable contract.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/require-interface-for-exported-class.test.ts
 */

import { AST_NODE_TYPES, type TSESTree } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile, isStoryFile, isTestFile } from "./_paths.js";

type MessageIds = "requireContract";
type Options = [];

export const REQUIRE_INTERFACE_FOR_EXPORTED_CLASS_DOCUMENTATION = {
  summary: "Require exported concrete classes with public behavior to declare a contract.",
  rationale:
    "Consumers coupled only to a concrete class cannot substitute implementations or state the supported public capability independently of implementation details.",
  remediation:
    "Declare a focused interface and add an implements clause, or inherit from an intentional base contract.",
  category: "architecture",
  limitations: [
    "The warning-stage rule checks directly exported class declarations; classes exported later through a separate export list require review.",
    "Static factories and data-only classes without public instance methods are outside the contract requirement.",
  ],
  examples: [
    {
      id: "implemented-store-contract",
      title: "Export behavior through a focused contract",
      outcome: "no-match",
      files: [
        {
          path: "src/artifact-store.ts",
          source:
            "export interface ArtifactStorage { read(id: string): Promise<Uint8Array>; } export class ArtifactStore implements ArtifactStorage { async read(id: string) { return new Uint8Array(); } }",
        },
      ],
      focusPath: "src/artifact-store.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "concrete-only-store",
      title: "Do not export behavior only through a concrete class",
      outcome: "match",
      files: [
        {
          path: "src/artifact-store.ts",
          source:
            "export class ArtifactStore { async read(id: string) { return new Uint8Array(); } }",
        },
      ],
      focusPath: "src/artifact-store.ts",
      expectedCount: 1,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;

function hasPublicInstanceBehavior(node: TSESTree.ClassDeclaration): boolean {
  return node.body.body.some((member) => {
    if (member.type === AST_NODE_TYPES.MethodDefinition) {
      return (
        member.kind === "method" &&
        !member.static &&
        member.accessibility !== "private" &&
        member.accessibility !== "protected" &&
        member.key.type !== AST_NODE_TYPES.PrivateIdentifier
      );
    }
    if (member.type !== AST_NODE_TYPES.PropertyDefinition || member.static)
      return false;
    if (
      member.accessibility === "private" ||
      member.accessibility === "protected" ||
      member.key.type === AST_NODE_TYPES.PrivateIdentifier
    ) return false;
    return (
      member.value?.type === AST_NODE_TYPES.ArrowFunctionExpression ||
      member.value?.type === AST_NODE_TYPES.FunctionExpression ||
      member.typeAnnotation?.typeAnnotation.type === AST_NODE_TYPES.TSFunctionType
    );
  });
}

export default createRule<Options, MessageIds>({
  name: "require-interface-for-exported-class",
  documentation: REQUIRE_INTERFACE_FOR_EXPORTED_CLASS_DOCUMENTATION,
  meta: {
    type: "suggestion",
    docs: {
      description:
        "Require exported concrete classes with public behavior to declare a contract.",
    },
    schema: [],
    messages: {
      requireContract:
        "Exported class `{{name}}` has public behavior but no declared interface or base contract; add a focused contract and implement it.",
    },
  },
  defaultOptions: [],
  create(context) {
    if (
      isTestFile(context.filename) ||
      isStoryFile(context.filename) ||
      isGeneratedFile(context.filename, context.sourceCode.text)
    ) return {};
    return {
      ExportNamedDeclaration(node): void {
        const declaration = node.declaration;
        if (
          declaration?.type !== AST_NODE_TYPES.ClassDeclaration ||
          declaration.abstract ||
          declaration.implements.length > 0 ||
          declaration.superClass !== null ||
          !hasPublicInstanceBehavior(declaration)
        ) return;
        context.report({
          node: declaration.id ?? declaration,
          messageId: "requireContract",
          data: { name: declaration.id?.name ?? "default" },
        });
      },
      ExportDefaultDeclaration(node): void {
        const declaration = node.declaration;
        if (
          declaration.type !== AST_NODE_TYPES.ClassDeclaration ||
          declaration.abstract ||
          declaration.implements.length > 0 ||
          declaration.superClass !== null ||
          !hasPublicInstanceBehavior(declaration)
        ) return;
        context.report({
          node: declaration.id ?? declaration,
          messageId: "requireContract",
          data: { name: declaration.id?.name ?? "default" },
        });
      },
    };
  },
});
