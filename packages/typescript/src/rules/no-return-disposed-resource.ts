/**
 * @fileoverview no-return-disposed-resource — Do not return a resource whose using declaration disposes it before the caller receives it.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-return-disposed-resource.test.ts
 */

import { AST_NODE_TYPES, ASTUtils, type TSESLint, type TSESTree } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile } from "./_paths.js";
import { unwrapExpression } from "./_unwrap-expression.js";

export const NO_RETURN_DISPOSED_RESOURCE_DOCUMENTATION = {
  defaultLevel: "warning",
  summary: "Do not return a resource whose using declaration disposes it before the caller receives it.",
  rationale: "Leaving the resource's using scope invokes its disposer before the returned value reaches its consumer, producing an already disposed dependency.",
  remediation: "Keep consumers inside the resource scope, yield it through an awaited fixture use callback, or transfer ownership without a using declaration. Return an independent snapshot when appropriate.",
  category: "correctness",
  autofix: "none",
  limitations: [
    "Reports directly returned bindings declared with using or await using in the same function, including unchanged const aliases. Explicit resource-management syntax proves disposal; method names such as close or destroy are not guessed.",
    "Nested closures retaining an outer resource, returned object aggregates, dynamic wrappers, mutable aliases and deliberate disposed-resource contracts are not inferred. Awaited fixture use callbacks and snapshots remain valid.",
    "Findings remain warnings because an intentional disposed-resource contract requires review. No automatic ownership or cleanup rewrite is offered.",
  ],
  examples: [
    { id: "return-disposed-client", title: "The resource is disposed before return", outcome: "match", files: [{ path: "src/client.ts", source: "function client() { using handle = acquire(); return handle; }" }], focusPath: "src/client.ts", expectedCount: 1, public: true },
    { id: "return-snapshot", title: "Return a value independent of resource lifetime", outcome: "no-match", files: [{ path: "src/client.ts", source: "function client() { using handle = acquire(); return handle.snapshot(); }" }], focusPath: "src/client.ts", expectedCount: 0, public: true },
  ],
} as const satisfies RuleDocumentation;

function owningFunction(node: TSESTree.Node): TSESTree.Node | null {
  for (let current = node.parent; current != null; current = current.parent) {
    if (current.type === AST_NODE_TYPES.FunctionDeclaration || current.type === AST_NODE_TYPES.FunctionExpression ||
        current.type === AST_NODE_TYPES.ArrowFunctionExpression) return current;
  }
  return null;
}

function resourceOwner(source: Readonly<TSESLint.SourceCode>, value: TSESTree.Node, seen: ReadonlySet<TSESLint.Scope.Variable> = new Set()): TSESTree.VariableDeclarator | null {
  const node = unwrapExpression(value);
  if (node.type !== AST_NODE_TYPES.Identifier) return null;
  const variable = ASTUtils.findVariable(source.getScope(node), node.name);
  const definition = variable?.defs[0];
  if (variable === null || variable?.defs.length !== 1 || definition === undefined || seen.has(variable) ||
      variable.references.some(reference => reference.isWrite() && !reference.init) ||
      definition.node.type !== AST_NODE_TYPES.VariableDeclarator) return null;
  const declaration = definition.node;
  if (declaration.parent.kind === "using" || declaration.parent.kind === "await using") return declaration;
  if (declaration.parent.kind !== "const" || declaration.init === null || declaration.range[1] >= node.range[0]) return null;
  return resourceOwner(source, declaration.init, new Set([...seen, variable]));
}

export default createRule<[], "disposedReturn">({
  name: "no-return-disposed-resource",
  documentation: NO_RETURN_DISPOSED_RESOURCE_DOCUMENTATION,
  meta: {
    type: "problem",
    docs: { description: NO_RETURN_DISPOSED_RESOURCE_DOCUMENTATION.summary },
    schema: [],
    messages: { disposedReturn: "This using resource is disposed when its function returns; keep the consumer inside its lifetime or transfer ownership explicitly." },
  },
  defaultOptions: [],
  create(context) {
    if (isGeneratedFile(context, context.sourceCode.text)) return {};
    return {
      ReturnStatement(node): void {
        if (node.argument === null) return;
        const declaration = resourceOwner(context.sourceCode, node.argument);
        if (declaration !== null && owningFunction(declaration) === owningFunction(node)) context.report({ node: node.argument, messageId: "disposedReturn" });
      },
    };
  },
});
