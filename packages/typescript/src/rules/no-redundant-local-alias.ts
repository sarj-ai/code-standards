/**
 * @fileoverview no-redundant-local-alias — Pass the original local into an object field instead of creating a single-use rename.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-redundant-local-alias.test.ts
 */

import { AST_NODE_TYPES, ASTUtils, type TSESLint, type TSESTree } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile } from "./_paths.js";

export const NO_REDUNDANT_LOCAL_ALIAS_DOCUMENTATION = {
  defaultLevel: "warning",
  summary: "Pass the original local into an object field instead of creating a single-use rename.",
  rationale: "An unannotated alias used only by its matching object field adds a second name without adding a contract.",
  remediation: "Write the object property with the original binding, then remove the redundant alias. Keep annotations, captured snapshots and independently useful names.",
  category: "maintainability",
  limitations: [
    "Checks an unannotated local const alias of a stable parameter or earlier const. Its single read must be a shorthand property in the same function scope. Module exports, imported bindings, captures, reassignment, positional uses and typed aliases are preserved.",
    "A diagnostic requires review; no automatic rewrite changes inferred narrowing, shorthand source text or observable binding names.",
  ],
  examples: [
    { id: "redundant-alias", title: "The property already supplies the name", outcome: "match", files: [{ path: "src/request.ts", source: "function request(value: string) { const accountId = value; return { accountId }; }" }], focusPath: "src/request.ts", expectedCount: 1, public: true },
    { id: "direct-property", title: "Use the original binding", outcome: "no-match", files: [{ path: "src/request.ts", source: "function request(value: string) { return { accountId: value }; }" }], focusPath: "src/request.ts", expectedCount: 0, public: true },
  ],
} as const satisfies RuleDocumentation;

function stableSource(variable: TSESLint.Scope.Variable, alias: TSESTree.VariableDeclarator): boolean {
  const definition = variable.defs[0];
  if (variable.defs.length !== 1 || definition === undefined || variable.references.some(reference => reference.isWrite() && !reference.init)) return false;
  return definition.type === "Parameter" || (
    definition.node.type === AST_NODE_TYPES.VariableDeclarator &&
    definition.node.parent.kind === "const" && definition.node.init !== null &&
    definition.node.range[1] < alias.range[0]
  );
}

export default createRule<[], "redundantAlias">({
  name: "no-redundant-local-alias",
  documentation: NO_REDUNDANT_LOCAL_ALIAS_DOCUMENTATION,
  meta: {
    type: "suggestion",
    docs: { description: NO_REDUNDANT_LOCAL_ALIAS_DOCUMENTATION.summary },
    schema: [],
    messages: { redundantAlias: "This alias is read only by its matching object field; pass `{{source}}` directly as `{{target}}: {{source}}`." },
  },
  defaultOptions: [],
  create(context) {
    if (isGeneratedFile(context, context.sourceCode.text)) return {};
    return {
      VariableDeclarator(node): void {
        if (node.parent.kind !== "const" || node.parent.declarations.length !== 1 ||
          node.id.type !== AST_NODE_TYPES.Identifier || node.id.typeAnnotation !== undefined ||
          node.init?.type !== AST_NODE_TYPES.Identifier) return;
        const scope = context.sourceCode.getScope(node);
        if (scope.variableScope.type !== "function") return;
        const target = ASTUtils.findVariable(scope, node.id.name);
        const source = ASTUtils.findVariable(scope, node.init.name);
        if (target === null || source === null || !stableSource(source, node)) return;
        const reads = target.references.filter(reference => reference.isRead());
        if (reads.length !== 1 || target.references.some(reference => reference.isWrite() && !reference.init)) return;
        const read = reads[0];
        if (read === undefined || read.from.variableScope !== scope.variableScope) return;
        const property = read.identifier.parent;
        if (property.type !== AST_NODE_TYPES.Property || !property.shorthand || property.value !== read.identifier ||
          property.parent.type !== AST_NODE_TYPES.ObjectExpression || property.computed || property.method || property.kind !== "init") return;
        context.report({ node, messageId: "redundantAlias", data: { source: node.init.name, target: node.id.name } });
      },
    };
  },
});
