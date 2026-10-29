/**
 * @fileoverview prefer-dependency-interface — Annotate retained collaborators with their existing interface when the consumer uses only that contract.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/prefer-dependency-interface.test.ts
 */

import { AST_NODE_TYPES, ASTUtils, type TSESTree } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { forEachOwnAstChild } from "./_for-each-own-ast-child.js";
import { isGeneratedFile } from "./_paths.js";

export const PREFER_DEPENDENCY_INTERFACE_DOCUMENTATION = {
  defaultLevel: "warning",
  summary: "Annotate retained collaborators with their existing interface when the consumer uses only that contract.",
  rationale: "A concrete annotation can require private implementation identity even when a declared interface covers every consumed operation.",
  remediation: "Use the existing interface on the injected parameter. Keep concrete annotations for implementation-specific capabilities.",
  category: "architecture",
  limitations: [
    "Checks private readonly constructor parameter properties, an empty constructor body, and a local concrete class declaring exactly one local interface. Every direct this-property consumer must access an interface member.",
    "Interface/class inheritance, imports, dynamic members, escapes, implementation-specific reads, decorators, generics, mutable dependencies and protected properties remain unresolved. The compiler owns signature compatibility. No contract or automatic rewrite is invented.",
  ],
  examples: [
    { id: "concrete-store", title: "The consumer uses only the interface", outcome: "match", files: [{ path: "service.ts", source: "interface Store { read(): string } class SqlStore implements Store { private value = 'ok'; read() { return this.value; } } class Service { constructor(private readonly store: SqlStore) {} run() { return this.store.read(); } }" }], focusPath: "service.ts", expectedCount: 1, public: true },
    { id: "interface-store", title: "Accept another implementation", outcome: "no-match", files: [{ path: "service.ts", source: "interface Store { read(): string } class Service { constructor(private readonly store: Store) {} run() { return this.store.read(); } }" }], focusPath: "service.ts", expectedCount: 0, public: true },
  ],
} as const satisfies RuleDocumentation;

export default createRule<[], "interface">({
  name: "prefer-dependency-interface",
  documentation: PREFER_DEPENDENCY_INTERFACE_DOCUMENTATION,
  meta: { type: "suggestion", docs: { description: PREFER_DEPENDENCY_INTERFACE_DOCUMENTATION.summary }, schema: [], messages: { interface: "Use the existing `{{contract}}` interface for this dependency; its consumer uses only that contract." } },
  defaultOptions: [],
  create(context) {
    if (isGeneratedFile(context, context.sourceCode.text)) return {};
    function contract(node: TSESTree.Identifier): TSESTree.TSInterfaceDeclaration | null {
      const concrete = definition(node);
      if (concrete?.type !== AST_NODE_TYPES.ClassDeclaration || concrete.abstract || concrete.superClass !== null || concrete.decorators.length !== 0 || concrete.typeParameters !== undefined || concrete.implements.length !== 1) return null;
      const heritage = concrete.implements[0];
      if (heritage?.expression.type !== AST_NODE_TYPES.Identifier) return null;
      const port = definition(heritage.expression);
      return port?.type === AST_NODE_TYPES.TSInterfaceDeclaration && port.extends.length === 0 && port.typeParameters === undefined ? port : null;
    }
    function definition(node: TSESTree.Identifier): TSESTree.Node | null {
      const variable = ASTUtils.findVariable(context.sourceCode.getScope(node), node.name);
      return variable?.defs.length === 1 ? variable.defs[0]?.node ?? null : null;
    }
    function usesOnlyInterface(owner: TSESTree.ClassDeclaration | TSESTree.ClassExpression, name: string, port: TSESTree.TSInterfaceDeclaration): boolean {
      const members = new Set<string>();
      for (const member of port.body.body) {
        if ((member.type !== AST_NODE_TYPES.TSMethodSignature && member.type !== AST_NODE_TYPES.TSPropertySignature) || member.computed || member.key.type !== AST_NODE_TYPES.Identifier) return false;
        members.add(member.key.name);
      }
      let uses = 0;
      let compatible = true;
      function visit(node: TSESTree.Node): void {
        if (node.type === AST_NODE_TYPES.MemberExpression && node.object.type === AST_NODE_TYPES.ThisExpression && ASTUtils.getPropertyName(node) === name) {
          uses += 1;
          const parent = node.parent;
          if (parent.type !== AST_NODE_TYPES.MemberExpression || parent.object !== node || !members.has(ASTUtils.getPropertyName(parent) ?? "") || parent.parent.type === AST_NODE_TYPES.AssignmentExpression && parent.parent.left === parent || parent.parent.type === AST_NODE_TYPES.UpdateExpression) compatible = false;
        }
        if (node !== owner && (node.type === AST_NODE_TYPES.ClassDeclaration || node.type === AST_NODE_TYPES.ClassExpression)) return;
        forEachOwnAstChild(node, visit);
      }
      visit(owner);
      return compatible && uses > 0;
    }
    return {
      TSParameterProperty(node) {
        const parameter = node.parameter;
        const constructor = node.parent.parent;
        if (!node.readonly || node.accessibility !== "private" || node.decorators.length !== 0 || parameter.type !== AST_NODE_TYPES.Identifier || parameter.typeAnnotation?.typeAnnotation.type !== AST_NODE_TYPES.TSTypeReference || parameter.typeAnnotation.typeAnnotation.typeName.type !== AST_NODE_TYPES.Identifier || constructor.type !== AST_NODE_TYPES.MethodDefinition || constructor.kind !== "constructor" || constructor.value.body?.body.length !== 0 || constructor.parent.type !== AST_NODE_TYPES.ClassBody) return;
        const owner = constructor.parent.parent;
        if (owner.type !== AST_NODE_TYPES.ClassDeclaration && owner.type !== AST_NODE_TYPES.ClassExpression) return;
        if (owner.decorators.length !== 0 || owner.typeParameters !== undefined) return;
        const port = contract(parameter.typeAnnotation.typeAnnotation.typeName);
        if (port !== null && usesOnlyInterface(owner, parameter.name, port)) context.report({ node: parameter.typeAnnotation, messageId: "interface", data: { contract: port.id.name } });
      },
    };
  },
});
