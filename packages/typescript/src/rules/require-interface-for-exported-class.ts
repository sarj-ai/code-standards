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
type ClassLike = TSESTree.ClassDeclaration | TSESTree.ClassExpression;

interface ClassBinding {
  readonly declaration: ClassLike;
  readonly name: string;
}

export const REQUIRE_INTERFACE_FOR_EXPORTED_CLASS_DOCUMENTATION = {
  summary: "Require exported concrete classes with public behavior to declare a contract.",
  rationale:
    "Consumers coupled only to a concrete class cannot substitute implementations or state the supported public capability independently of implementation details.",
  remediation:
    "Declare a focused interface and add an implements clause, or inherit from an intentional base contract.",
  category: "architecture",
  limitations: [
    "The warning-stage rule checks module-level class declarations and direct class-expression values exported directly, through local export specifiers, or through a default identifier; re-exports and expressions wrapped in other calls require review.",
    "An extends clause satisfies the contract only when its target is a locally declared abstract class; imported base-class contracts require an explicit implements clause.",
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

function hasPublicInstanceBehavior(node: ClassLike): boolean {
  return node.body.body.some((member) => {
    if (member.type === AST_NODE_TYPES.MethodDefinition) {
      return (
        member.kind !== "constructor" &&
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

function classBindings(
  statement: TSESTree.ProgramStatement,
): readonly ClassBinding[] {
  const declaration = statement.type === AST_NODE_TYPES.ExportNamedDeclaration
    ? statement.declaration
    : statement;
  if (declaration?.type === AST_NODE_TYPES.ClassDeclaration) {
    return declaration.id === null
      ? []
      : [{ declaration, name: declaration.id.name }];
  }
  if (declaration?.type !== AST_NODE_TYPES.VariableDeclaration) return [];
  return declaration.declarations.flatMap((item) =>
    item.id.type === AST_NODE_TYPES.Identifier &&
    item.init?.type === AST_NODE_TYPES.ClassExpression
      ? [{ declaration: item.init, name: item.id.name }]
      : [],
  );
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
      "Program:exit"(program): void {
        const classes = new Map<string, ClassLike>();
        const abstractBases = new Set<string>();
        for (const statement of program.body) {
          for (const binding of classBindings(statement)) {
            classes.set(binding.name, binding.declaration);
            if (binding.declaration.abstract) abstractBases.add(binding.name);
          }
        }

        const exported = new Map<ClassLike, string>();
        for (const statement of program.body) {
          if (statement.type === AST_NODE_TYPES.ExportNamedDeclaration) {
            for (const binding of classBindings(statement)) {
              exported.set(binding.declaration, binding.name);
            }
            if (statement.source !== null || statement.exportKind === "type") continue;
            for (const specifier of statement.specifiers) {
              if (specifier.exportKind === "type") continue;
              const candidate = classes.get(specifier.local.name);
              if (candidate === undefined) continue;
              const exportedName = specifier.exported.type === AST_NODE_TYPES.Identifier
                ? specifier.exported.name
                : specifier.exported.value;
              exported.set(candidate, exportedName);
            }
            continue;
          }
          if (statement.type !== AST_NODE_TYPES.ExportDefaultDeclaration) continue;
          if (
            statement.declaration.type === AST_NODE_TYPES.ClassDeclaration ||
            statement.declaration.type === AST_NODE_TYPES.ClassExpression
          ) {
            exported.set(
              statement.declaration,
              statement.declaration.id?.name ?? "default",
            );
          } else if (statement.declaration.type === AST_NODE_TYPES.Identifier) {
            const candidate = classes.get(statement.declaration.name);
            if (candidate !== undefined) {
              exported.set(candidate, statement.declaration.name);
            }
          }
        }

        for (const [declaration, exportedName] of exported) {
          const extendsLocalAbstractBase =
            declaration.superClass?.type === AST_NODE_TYPES.Identifier &&
            abstractBases.has(declaration.superClass.name);
          if (
            declaration.abstract ||
            declaration.implements.length > 0 ||
            extendsLocalAbstractBase ||
            !hasPublicInstanceBehavior(declaration)
          ) continue;
          context.report({
            node: declaration.id ?? declaration,
            messageId: "requireContract",
            data: { name: exportedName },
          });
        }
      },
    };
  },
});
