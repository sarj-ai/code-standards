/**
 * @fileoverview no-mutating-container-transform — Return array replacements without mutating borrowed array inputs.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-mutating-container-transform.test.ts
 */

import { AST_NODE_TYPES, ASTUtils, type TSESLint, type TSESTree } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { forEachOwnAstChild } from "./_for-each-own-ast-child.js";
import { isGeneratedFile } from "./_paths.js";
import { unwrapExpression } from "./_unwrap-expression.js";

type FunctionNode = TSESTree.FunctionDeclaration | TSESTree.FunctionExpression | TSESTree.ArrowFunctionExpression;
type Origins = Map<TSESLint.Scope.Variable, string>;
const MUTATORS: ReadonlySet<string> = new Set(["copyWithin", "fill", "pop", "push", "reverse", "shift", "sort", "splice", "unshift"]);
const PRIMITIVES: ReadonlySet<AST_NODE_TYPES> = new Set([
  AST_NODE_TYPES.TSStringKeyword, AST_NODE_TYPES.TSNumberKeyword, AST_NODE_TYPES.TSBooleanKeyword,
  AST_NODE_TYPES.TSBigIntKeyword, AST_NODE_TYPES.TSSymbolKeyword,
]);

export const NO_MUTATING_CONTAINER_TRANSFORM_DOCUMENTATION = {
  defaultLevel: "warning",
  summary: "Return array replacements without mutating borrowed array inputs.",
  rationale: "A returned array does not undo writes visible through the caller's original aliases. Copying only after mutation leaves the caller changed.",
  remediation: "Copy before changing the array and return the replacement, or use an explicit in-place command returning void. Preserve scalar command/result contracts.",
  category: "correctness",
  limitations: [
    "Checks explicit array-valued return annotations and primitive-element array parameters, including Array<T> and Promise<Array<T>> forms. Untyped JavaScript, named application types, arbitrary objects, nested descendants, generic elements and scalar-returning command APIs remain outside the rule.",
    "Tracks direct aliases and rebindings in linear statements and structured if branches. Unknown joins discard provenance; literal false branches are ignored. Loops, try blocks, nested functions and opaque statement forms cause the function to be excluded.",
    "Reports direct indexed/length writes, indexed deletion and standard array mutator calls. Unknown helper calls and reflective mutation are not inferred; fresh local copies are preserved. Generated/vendor files are excluded. No automatic ownership-changing rewrite is offered.",
  ],
  examples: [
    { id: "borrowed-sort", title: "Returning an array does not hide the mutation", outcome: "match", files: [{ path: "src/order.ts", source: "function ordered(values: number[]): number[] { values.sort(); return values; }" }], focusPath: "src/order.ts", expectedCount: 1, public: true },
    { id: "copied-sort", title: "Copy before mutating", outcome: "no-match", files: [{ path: "src/order.ts", source: "function ordered(values: number[]): number[] { const result = [...values]; result.sort(); return result; }" }], focusPath: "src/order.ts", expectedCount: 0, public: true },
  ],
} as const satisfies RuleDocumentation;

function arrayElement(node: TSESTree.TypeNode, sourceCode: Readonly<TSESLint.SourceCode>): TSESTree.TypeNode | null {
  if (node.type === AST_NODE_TYPES.TSArrayType) return node.elementType;
  if (node.type === AST_NODE_TYPES.TSTypeReference && node.typeName.type === AST_NODE_TYPES.Identifier &&
    (node.typeName.name === "Array" || node.typeName.name === "ReadonlyArray") &&
    (ASTUtils.findVariable(sourceCode.getScope(node.typeName), node.typeName.name)?.defs.length ?? 0) === 0 &&
    node.typeArguments?.params.length === 1) return node.typeArguments.params[0] ?? null;
  return null;
}

function returnsArray(node: FunctionNode, sourceCode: Readonly<TSESLint.SourceCode>): boolean {
  let annotation = node.returnType?.typeAnnotation;
  if (annotation?.type === AST_NODE_TYPES.TSTypeReference && annotation.typeName.type === AST_NODE_TYPES.Identifier &&
    annotation.typeName.name === "Promise" && (ASTUtils.findVariable(sourceCode.getScope(annotation.typeName), "Promise")?.defs.length ?? 0) === 0 &&
    annotation.typeArguments?.params.length === 1) annotation = annotation.typeArguments.params[0];
  return annotation !== undefined && arrayElement(annotation, sourceCode) !== null;
}

function supported(statements: readonly TSESTree.Statement[]): boolean {
  return statements.every(statement => {
    switch (statement.type) {
      case AST_NODE_TYPES.ExpressionStatement:
      case AST_NODE_TYPES.VariableDeclaration:
      case AST_NODE_TYPES.ReturnStatement:
      case AST_NODE_TYPES.ThrowStatement:
      case AST_NODE_TYPES.EmptyStatement: return true;
      case AST_NODE_TYPES.BlockStatement: return supported(statement.body);
      case AST_NODE_TYPES.IfStatement:
        return supported([statement.consequent]) && (statement.alternate === null || supported([statement.alternate]));
      default: return false;
    }
  });
}

export default createRule<[], "borrowedMutation">({
  name: "no-mutating-container-transform",
  documentation: NO_MUTATING_CONTAINER_TRANSFORM_DOCUMENTATION,
  meta: {
    type: "problem",
    docs: { description: NO_MUTATING_CONTAINER_TRANSFORM_DOCUMENTATION.summary },
    schema: [],
    messages: { borrowedMutation: "This array-valued transformation mutates borrowed input `{{parameter}}`; copy before writing or expose an in-place command returning void." },
  },
  defaultOptions: [],
  create(context) {
    if (isGeneratedFile(context, context.sourceCode.text)) return {};
    const sourceCode = context.sourceCode;
    function binding(node: TSESTree.Node): TSESLint.Scope.Variable | null {
      return node.type === AST_NODE_TYPES.Identifier ? ASTUtils.findVariable(sourceCode.getScope(node), node.name) : null;
    }
    function inspect(node: FunctionNode): void {
      if (node.body?.type !== AST_NODE_TYPES.BlockStatement || !returnsArray(node, sourceCode) || !supported(node.body.body)) return;
      const initial: Origins = new Map();
      for (const parameter of node.params) {
        if (parameter.type !== AST_NODE_TYPES.Identifier || parameter.typeAnnotation === undefined) continue;
        const element = arrayElement(parameter.typeAnnotation.typeAnnotation, sourceCode);
        const variable = binding(parameter);
        if (element !== null && PRIMITIVES.has(element.type) && variable !== null) initial.set(variable, parameter.name);
      }
      if (initial.size === 0) return;
      let first: { node: TSESTree.Node; parameter: string } | null = null;
      function origin(expression: TSESTree.Node, state: Origins): string | undefined {
        const variable = binding(unwrapExpression(expression));
        return variable === null ? undefined : state.get(variable);
      }
      function expression(current: TSESTree.Node, state: Origins): void {
        switch (current.type) {
          case AST_NODE_TYPES.FunctionExpression:
          case AST_NODE_TYPES.ArrowFunctionExpression:
          case AST_NODE_TYPES.ClassExpression: return;
          case AST_NODE_TYPES.AssignmentExpression: assignment(current, state); return;
          case AST_NODE_TYPES.LogicalExpression: logical(current, state); return;
          case AST_NODE_TYPES.ConditionalExpression: conditional(current, state); return;
          case AST_NODE_TYPES.UpdateExpression: write(current.argument, state); break;
          case AST_NODE_TYPES.UnaryExpression: if (current.operator === "delete") write(current.argument, state); break;
          case AST_NODE_TYPES.CallExpression: mutationCall(current, state); break;
          default: break;
        }
        forEachOwnAstChild(current, child => expression(child, state), key => key !== "typeAnnotation" && key !== "returnType");
      }
      function assignment(current: TSESTree.AssignmentExpression, state: Origins): void {
        expression(current.right, state);
        write(current.left, state);
        const target = binding(current.left);
        if (target === null) return;
        const owner = current.operator === "=" ? origin(current.right, state) : undefined;
        if (owner === undefined) state.delete(target); else state.set(target, owner);
      }
      function logical(current: TSESTree.LogicalExpression, state: Origins): void {
        expression(current.left, state);
        const left = unwrapExpression(current.left);
        if (left.type === AST_NODE_TYPES.Literal && (
          current.operator === "&&" && !left.value || current.operator === "||" && !!left.value ||
          current.operator === "??" && left.value !== null
        )) return;
        expression(current.right, state);
      }
      function conditional(current: TSESTree.ConditionalExpression, state: Origins): void {
        expression(current.test, state);
        const test = unwrapExpression(current.test);
        if (test.type === AST_NODE_TYPES.Literal) {
          expression(test.value ? current.consequent : current.alternate, state);
          return;
        }
        expression(current.consequent, state);
        expression(current.alternate, state);
      }
      function mutationCall(current: TSESTree.CallExpression, state: Origins): void {
        if (current.callee.type !== AST_NODE_TYPES.MemberExpression || !MUTATORS.has(ASTUtils.getPropertyName(current.callee) ?? "")) return;
        const parameter = origin(current.callee.object, state);
        if (parameter !== undefined && first === null) first = { node: current, parameter };
      }
      function write(target: TSESTree.Node, state: Origins): void {
        target = unwrapExpression(target);
        if (target.type !== AST_NODE_TYPES.MemberExpression || (!target.computed && ASTUtils.getPropertyName(target) !== "length")) return;
        const parameter = origin(target.object, state);
        if (parameter !== undefined && first === null) first = { node: target, parameter };
      }
      function statements(items: readonly TSESTree.Statement[], state: Origins): boolean {
        for (const current of items) if (statement(current, state)) return true;
        return false;
      }
      function statement(current: TSESTree.Statement, state: Origins): boolean {
        switch (current.type) {
          case AST_NODE_TYPES.BlockStatement: return statements(current.body, state);
          case AST_NODE_TYPES.IfStatement: return branch(current, state);
          case AST_NODE_TYPES.VariableDeclaration: declarations(current, state); return false;
          case AST_NODE_TYPES.ReturnStatement:
          case AST_NODE_TYPES.ThrowStatement:
            if (current.argument !== null) expression(current.argument, state);
            return true;
          case AST_NODE_TYPES.ExpressionStatement: expression(current.expression, state); return false;
          default: return false;
        }
      }
      function branch(current: TSESTree.IfStatement, state: Origins): boolean {
        expression(current.test, state);
        if (current.test.type === AST_NODE_TYPES.Literal) return current.test.value
          ? statements([current.consequent], state)
          : current.alternate !== null && statements([current.alternate], state);
        const left: Origins = new Map(state);
        const right: Origins = new Map(state);
        const leftEnds = statements([current.consequent], left);
        const rightEnds = current.alternate !== null && statements([current.alternate], right);
        state.clear();
        if (leftEnds && rightEnds) return true;
        const continuing = leftEnds ? right : left;
        const other = rightEnds ? left : right;
        for (const [variable, owner] of continuing) if (leftEnds || rightEnds || other.get(variable) === owner) state.set(variable, owner);
        return false;
      }
      function declarations(current: TSESTree.VariableDeclaration, state: Origins): void {
        for (const declaration of current.declarations) {
          if (declaration.init === null) continue;
          expression(declaration.init, state);
          const variable = binding(declaration.id);
          const owner = origin(declaration.init, state);
          if (variable !== null && owner !== undefined) state.set(variable, owner);
        }
      }
      statements(node.body.body, initial);
      if (first !== null) {
        const mutation: { node: TSESTree.Node; parameter: string } = first;
        context.report({ node: mutation.node, messageId: "borrowedMutation", data: { parameter: mutation.parameter } });
      }
    }
    return { FunctionDeclaration: inspect, FunctionExpression: inspect, ArrowFunctionExpression: inspect };
  },
});
