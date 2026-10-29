/**
 * @fileoverview no-mutating-input-with-result — Return replacement object values instead of writing input fields in result-returning functions.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-mutating-input-with-result.test.ts
 */

import { AST_NODE_TYPES, ASTUtils, type TSESLint, type TSESTree } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { forEachOwnAstChild } from "./_for-each-own-ast-child.js";
import { isGeneratedFile } from "./_paths.js";
import { unwrapExpression } from "./_unwrap-expression.js";

type FunctionNode = TSESTree.FunctionDeclaration | TSESTree.FunctionExpression | TSESTree.ArrowFunctionExpression;

export const NO_MUTATING_INPUT_WITH_RESULT_DOCUMENTATION = {
  defaultLevel: "warning",
  summary: "Return replacement object values instead of writing input fields in result-returning functions.",
  rationale: "A result-returning function that also writes a caller-owned object changes aliases outside the returned value, hiding its mutation contract.",
  remediation: "Return a fresh replacement and update the caller to use it, or expose an explicit in-place command returning void. Do not add a dummy return or discard the operation.",
  category: "correctness",
  limitations: [
    "Checks direct property assignments, updates and deletions on stable object parameters in explicitly nonvoid functions that visibly return a value. Property contracts must come from an inline type or a same-file unextended, undecorated interface, object type alias or class. Only declared mutable data fields are checked; readonly-field errors remain compiler-owned.",
    "Void/undefined/never commands, Promise<void>, receiver state, arbitrary imported/generic contracts, array inputs, nested descendants, parameter rebindings and alias-indirected writes remain excluded. Nested functions and class bodies have separate ownership and are not traversed. Generated/vendor files are excluded; maintained tests are checked.",
    "No automatic rewrite chooses cloning semantics or changes function callers. Explicit command/result APIs with an intentional mutation require a local explanation.",
  ],
  examples: [
    { id: "mutates-input", title: "A result does not undo the caller-visible write", outcome: "match", files: [{ path: "src/config.ts", source: "interface Config { enabled: boolean; } function enable(config: Config): Config { config.enabled = true; return config; }" }], focusPath: "src/config.ts", expectedCount: 1, public: true },
    { id: "returns-replacement", title: "Return the replacement explicitly", outcome: "no-match", files: [{ path: "src/config.ts", source: "interface Config { enabled: boolean; } function enable(config: Config): Config { return { ...config, enabled: true }; }" }], focusPath: "src/config.ts", expectedCount: 0, public: true },
  ],
} as const satisfies RuleDocumentation;

function command(annotation: TSESTree.TypeNode): boolean {
  if (annotation.type === AST_NODE_TYPES.TSVoidKeyword || annotation.type === AST_NODE_TYPES.TSUndefinedKeyword || annotation.type === AST_NODE_TYPES.TSNeverKeyword) return true;
  if (annotation.type === AST_NODE_TYPES.TSTypeReference && annotation.typeName.type === AST_NODE_TYPES.Identifier && annotation.typeName.name === "Promise" && annotation.typeArguments?.params.length === 1) {
    const result = annotation.typeArguments.params[0];
    return result !== undefined && command(result);
  }
  return false;
}

function fields(annotation: TSESTree.TypeNode, sourceCode: Readonly<TSESLint.SourceCode>): ReadonlySet<string> {
  const names = new Set<string>();
  for (const member of membersOf(annotation, sourceCode)) {
    const name = mutableField(member);
    if (name !== null) names.add(name);
  }
  return names;
}

function membersOf(annotation: TSESTree.TypeNode, sourceCode: Readonly<TSESLint.SourceCode>): readonly TSESTree.Node[] {
  if (annotation.type === AST_NODE_TYPES.TSTypeLiteral) return annotation.members;
  if (annotation.type !== AST_NODE_TYPES.TSTypeReference || annotation.typeName.type !== AST_NODE_TYPES.Identifier || annotation.typeArguments !== undefined) return [];
  const variable = ASTUtils.findVariable(sourceCode.getScope(annotation.typeName), annotation.typeName.name);
  if (variable?.defs.length !== 1) return [];
  const definition = variable.defs[0]?.node;
  switch (definition?.type) {
    case AST_NODE_TYPES.TSInterfaceDeclaration:
      return definition.extends.length === 0 && definition.typeParameters === undefined ? definition.body.body : [];
    case AST_NODE_TYPES.TSTypeAliasDeclaration:
      return definition.typeParameters === undefined && definition.typeAnnotation.type === AST_NODE_TYPES.TSTypeLiteral ? definition.typeAnnotation.members : [];
    case AST_NODE_TYPES.ClassDeclaration:
      return definition.superClass === null && definition.typeParameters === undefined && definition.decorators.length === 0 ? definition.body.body : [];
    default: return [];
  }
}

function mutableField(member: TSESTree.Node): string | null {
  if ((member.type !== AST_NODE_TYPES.TSPropertySignature && member.type !== AST_NODE_TYPES.PropertyDefinition) || member.readonly || member.computed) return null;
  if (member.type === AST_NODE_TYPES.PropertyDefinition && (member.static || member.accessibility === "private" || member.accessibility === "protected")) return null;
  if (member.key.type === AST_NODE_TYPES.Identifier) return member.key.name;
  return member.key.type === AST_NODE_TYPES.Literal && (typeof member.key.value === "string" || typeof member.key.value === "number") ? String(member.key.value) : null;
}

function walkBody(node: TSESTree.Node, visit: (node: TSESTree.Node) => void): void {
  if (node.type === AST_NODE_TYPES.FunctionDeclaration || node.type === AST_NODE_TYPES.FunctionExpression || node.type === AST_NODE_TYPES.ArrowFunctionExpression ||
    node.type === AST_NODE_TYPES.ClassDeclaration || node.type === AST_NODE_TYPES.ClassExpression) return;
  visit(node);
  if (node.type === AST_NODE_TYPES.BlockStatement) {
    for (const statement of node.body) {
      walkBody(statement, visit);
      if (statement.type === AST_NODE_TYPES.ReturnStatement || statement.type === AST_NODE_TYPES.ThrowStatement) break;
    }
    return;
  }
  const selected = selectedChildren(node);
  if (selected !== null) {
    for (const child of selected) walkBody(child, visit);
    return;
  }
  forEachOwnAstChild(node, child => walkBody(child, visit), key => key !== "typeAnnotation" && key !== "returnType");
}

function selectedChildren(node: TSESTree.Node): readonly TSESTree.Node[] | null {
  if (node.type === AST_NODE_TYPES.IfStatement && node.test.type === AST_NODE_TYPES.Literal) {
    const branch = node.test.value ? node.consequent : node.alternate;
    return branch === null ? [node.test] : [node.test, branch];
  }
  if (node.type === AST_NODE_TYPES.LogicalExpression && node.left.type === AST_NODE_TYPES.Literal) {
    const skips = node.operator === "&&" && !node.left.value || node.operator === "||" && !!node.left.value || node.operator === "??" && node.left.value !== null;
    return skips ? [node.left] : [node.left, node.right];
  }
  if (node.type === AST_NODE_TYPES.ConditionalExpression && node.test.type === AST_NODE_TYPES.Literal) return [node.test, node.test.value ? node.consequent : node.alternate];
  return null;
}

export default createRule<[], "inputWrite">({
  name: "no-mutating-input-with-result",
  documentation: NO_MUTATING_INPUT_WITH_RESULT_DOCUMENTATION,
  meta: {
    type: "suggestion",
    docs: { description: NO_MUTATING_INPUT_WITH_RESULT_DOCUMENTATION.summary },
    schema: [],
    messages: { inputWrite: "This result-returning function writes input `{{name}}`; return a replacement value or declare an in-place command returning void." },
  },
  defaultOptions: [],
  create(context) {
    if (isGeneratedFile(context, context.sourceCode.text)) return {};
    const sourceCode = context.sourceCode;
    function inspect(node: FunctionNode): void {
      const annotation = node.returnType?.typeAnnotation;
      if (annotation === undefined || command(annotation) || node.body === undefined) return;
      const inputs = new Map<TSESLint.Scope.Variable, ReadonlySet<string>>();
      for (const parameter of node.params) {
        if (parameter.type !== AST_NODE_TYPES.Identifier || parameter.typeAnnotation === undefined) continue;
        const variable = ASTUtils.findVariable(sourceCode.getScope(parameter), parameter.name);
        if (variable === null || variable.references.some(reference => reference.isWrite())) continue;
        const names = fields(parameter.typeAnnotation.typeAnnotation, sourceCode);
        if (names.size > 0) inputs.set(variable, names);
      }
      if (inputs.size === 0) return;
      let returned = node.body.type !== AST_NODE_TYPES.BlockStatement;
      const writes: { readonly node: TSESTree.MemberExpression; readonly name: string }[] = [];
      walkBody(node.body, current => {
        if (current.type === AST_NODE_TYPES.ReturnStatement && current.argument !== null) returned = true;
        const candidate = current.type === AST_NODE_TYPES.AssignmentExpression ? current.left :
          current.type === AST_NODE_TYPES.UpdateExpression || current.type === AST_NODE_TYPES.UnaryExpression && current.operator === "delete" ? current.argument : null;
        if (candidate === null) return;
        const target = unwrapExpression(candidate);
        if (target.type !== AST_NODE_TYPES.MemberExpression || target.object.type !== AST_NODE_TYPES.Identifier) return;
        const variable = ASTUtils.findVariable(sourceCode.getScope(target.object), target.object.name);
        const property = ASTUtils.getPropertyName(target);
        if (variable !== null && property !== null && inputs.get(variable)?.has(property)) writes.push({ node: target, name: target.object.name });
      });
      const first = writes[0];
      if (returned && first !== undefined) context.report({ node: first.node, messageId: "inputWrite", data: { name: first.name } });
    }
    return { FunctionDeclaration: inspect, FunctionExpression: inspect, ArrowFunctionExpression: inspect };
  },
});
