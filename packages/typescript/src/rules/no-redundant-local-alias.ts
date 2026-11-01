/**
 * @fileoverview no-redundant-local-alias — Pass the original local into an object field instead of creating a single-use rename.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-redundant-local-alias.test.ts
 */

import { AST_NODE_TYPES, ASTUtils, type TSESLint, type TSESTree } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile } from "./_paths.js";
import { hasIdentifierNamed } from "./_unused-private-binding.js";

export const NO_REDUNDANT_LOCAL_ALIAS_DOCUMENTATION = {
  defaultLevel: "warning",
  summary: "Pass the original local into an object field instead of creating a single-use rename.",
  rationale: "An unannotated alias used only by its matching object field adds a second name without adding a contract.",
  remediation: "Write the object property with the original binding, then remove the redundant alias. Keep annotations, captured snapshots and independently useful names.",
  category: "maintainability",
  autofix: "safe",
  limitations: [
    "Checks an unannotated local const alias of a stable parameter or earlier const. Its single read must be a shorthand property in the same function scope. Module exports, imported bindings, captures, reassignment, positional uses and typed aliases are preserved.",
    "Safe fixes are limited to a plain module-scope function with one explicitly intrinsic-primitive parameter and exactly a const alias followed by a returned object containing that sole shorthand field. The source binding must remain the same at the returned field. Generics, return annotations, optional/default parameters, destructuring, overloads, comments, eval, async/generator functions and the special __proto__ key remain manual. Other diagnostics require review.",
  ],
  examples: [
    { id: "redundant-alias", title: "The property already supplies the name", outcome: "match", files: [{ path: "src/request.ts", source: "function request(value: string) { const accountId = value; return { accountId }; }" }], focusPath: "src/request.ts", expectedCount: 1, public: true },
    { id: "direct-property", title: "Use the original binding", outcome: "no-match", files: [{ path: "src/request.ts", source: "function request(value: string) { return { accountId: value }; }" }], focusPath: "src/request.ts", expectedCount: 0, public: true },
    { id: "closed-primitive-parameter-alias", scenarioId: "closed-primitive-parameter-alias", title: "The closed primitive return preserves the data-field contract", outcome: "match", files: [{ path: "src/request.ts", source: "export {};\nfunction request(value: string) {\n  const accountId = value;\n  return { accountId };\n}\n" }], fixedFiles: [{ path: "src/request.ts", source: "export {};\nfunction request(value: string) {\n\n  return { accountId: value };\n}\n" }], focusPath: "src/request.ts", expectedCount: 1, public: true },
    { id: "closed-primitive-parameter-alias-fixed", scenarioId: "closed-primitive-parameter-alias", title: "The direct data field needs no local alias", outcome: "no-match", files: [{ path: "src/request.ts", source: "export {};\nfunction request(value: string) {\n\n  return { accountId: value };\n}\n" }], focusPath: "src/request.ts", expectedCount: 0, public: true },
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

const PRIMITIVE_PARAMETERS: ReadonlySet<TSESTree.Node["type"]> = new Set([
  AST_NODE_TYPES.TSStringKeyword, AST_NODE_TYPES.TSNumberKeyword, AST_NODE_TYPES.TSBooleanKeyword,
  AST_NODE_TYPES.TSBigIntKeyword, AST_NODE_TYPES.TSSymbolKeyword,
]);

function closedPrimitiveReturnFix(
  sourceCode: TSESLint.SourceCode,
  node: TSESTree.VariableDeclarator,
  property: TSESTree.Property,
  source: TSESLint.Scope.Variable,
  target: TSESLint.Scope.Variable,
): TSESLint.ReportFixFunction | null {
  const statement = node.parent;
  const body = statement.parent;
  if (body.type !== AST_NODE_TYPES.BlockStatement) return null;
  const owner = body.parent;
  if (owner.type !== AST_NODE_TYPES.FunctionDeclaration || owner.parent.type !== AST_NODE_TYPES.Program ||
    owner.id === null || owner.async || owner.generator || owner.typeParameters !== undefined || owner.returnType !== undefined ||
    owner.params.length !== 1 || body.body.length !== 2 || body.body[0] !== statement ||
    node.id.type !== AST_NODE_TYPES.Identifier || node.id.name === "__proto__" || node.init?.type !== AST_NODE_TYPES.Identifier ||
    sourceCode.getCommentsInside(owner).length !== 0 || hasIdentifierNamed(sourceCode.ast, "eval")) return null;
  const parameter = owner.params[0];
  const returned = body.body[1];
  if (parameter?.type !== AST_NODE_TYPES.Identifier || parameter.optional === true || parameter.typeAnnotation === undefined ||
    !PRIMITIVE_PARAMETERS.has(parameter.typeAnnotation.typeAnnotation.type) ||
    returned?.type !== AST_NODE_TYPES.ReturnStatement || returned.argument !== property.parent ||
    property.parent.type !== AST_NODE_TYPES.ObjectExpression || property.parent.properties.length !== 1 ||
    ASTUtils.findVariable(sourceCode.getScope(parameter), parameter.name) !== source ||
    ASTUtils.findVariable(sourceCode.getScope(property), node.init.name) !== source ||
    source.references.some(reference => reference.isTypeReference) || target.references.some(reference => reference.isTypeReference)) return null;
  const name = owner.id.name;
  const bindings = sourceCode.getDeclaredVariables(owner).filter(binding => binding.name === name);
  if (bindings.length !== 1 || bindings[0]?.defs.length !== 1 || bindings[0].defs[0]?.node !== owner ||
    bindings[0].references.some(reference => reference.isTypeReference)) return null;
  const span: readonly [number, number] = [body.range[0] + 1, statement.range[1]];
  const boundaries = sourceCode.text.slice(...span).replace(/[^\r\n\u2028\u2029]/gu, "");
  const neighbor = Math.max(0, span[0] - 1);
  const before = sourceCode.text.slice(neighbor, span[1] + 1).match(/\r\n|[\r\n\u2028\u2029]/gu) ?? [];
  const after = (sourceCode.text.slice(neighbor, span[0]) + boundaries + sourceCode.text.slice(span[1], span[1] + 1))
    .match(/\r\n|[\r\n\u2028\u2029]/gu) ?? [];
  if (before.length !== after.length || before.some((ending, index) => ending !== after[index])) return null;
  const key = sourceCode.getText(property.key);
  const value = sourceCode.getText(node.init);
  return fixer => [fixer.replaceTextRange(span, boundaries), fixer.replaceText(property, `${key}: ${value}`)];
}

export default createRule<[], "redundantAlias">({
  name: "no-redundant-local-alias",
  documentation: NO_REDUNDANT_LOCAL_ALIAS_DOCUMENTATION,
  meta: {
    type: "suggestion",
    fixable: "code",
    docs: { description: NO_REDUNDANT_LOCAL_ALIAS_DOCUMENTATION.summary },
    schema: [],
    messages: { redundantAlias: "This alias is read only by its matching object field; pass `{{source}}` directly as `{{target}}: {{source}}`." },
  },
  defaultOptions: [],
  create(context) {
    if (isGeneratedFile(context, context.sourceCode.text)) return {};
    const hasModuleSyntax = context.sourceCode.ast.body.some(candidate => candidate.type === AST_NODE_TYPES.ImportDeclaration ||
      candidate.type === AST_NODE_TYPES.ExportNamedDeclaration || candidate.type === AST_NODE_TYPES.ExportDefaultDeclaration ||
      candidate.type === AST_NODE_TYPES.ExportAllDeclaration);
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
        context.report({ node, messageId: "redundantAlias", fix: hasModuleSyntax ? closedPrimitiveReturnFix(context.sourceCode, node, property, source, target) : null, data: { source: node.init.name, target: node.id.name } });
      },
    };
  },
});
