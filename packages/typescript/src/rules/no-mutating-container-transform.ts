/**
 * @fileoverview no-mutating-container-transform — Return array replacements without mutating borrowed array inputs.
 *
 * Port of the 18.x `no-mutating-container-transform` rule. The file
 * gate moves to `before()`; the analysis is unchanged.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-mutating-container-transform.test.ts
 */

import { defineRule, type ESTree, type Node, type SourceCode, type TsVariable } from "../types.js";
import { forEachOwnAstChild, unwrapExpression } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { isPresent } from "../utils/is-present.js";
import { isGeneratedFile } from "../utils/paths.js";
import { findVariable, getPropertyName } from "../utils/static-string.js";

type FunctionNode = ESTree.Function | ESTree.ArrowFunctionExpression;
type Origins = Map<TsVariable, string>;

const MUTATORS: ReadonlySet<string> = new Set(["copyWithin", "fill", "pop", "push", "reverse", "shift", "sort", "splice", "unshift"]);
const PRIMITIVES: ReadonlySet<string> = new Set([
  "TSStringKeyword", "TSNumberKeyword", "TSBooleanKeyword",
  "TSBigIntKeyword", "TSSymbolKeyword",
]);

function arrayElement(node: Node, sourceCode: SourceCode): Node | null {
  if (node.type === "TSArrayType") return node.elementType;
  if (node.type === "TSTypeReference" && node.typeName.type === "Identifier" &&
    (node.typeName.name === "Array" || node.typeName.name === "ReadonlyArray") &&
    (findVariable(sourceCode.getScope(node.typeName), node.typeName.name)?.defs.length ?? 0) === 0 &&
    node.typeArguments?.params.length === 1) return node.typeArguments.params[0] ?? null;
  return null;
}

function returnsArray(node: FunctionNode, sourceCode: SourceCode): boolean {
  let annotation: Node | undefined = node.returnType?.typeAnnotation;
  if (annotation?.type === "TSTypeReference" && annotation.typeName.type === "Identifier" &&
    annotation.typeName.name === "Promise" && (findVariable(sourceCode.getScope(annotation.typeName), "Promise")?.defs.length ?? 0) === 0 &&
    annotation.typeArguments?.params.length === 1) annotation = annotation.typeArguments.params[0];
  return annotation !== undefined && arrayElement(annotation, sourceCode) !== null;
}

function supported(statements: readonly Node[]): boolean {
  return statements.every(statement => {
    switch (statement.type) {
      case "ExpressionStatement":
      case "VariableDeclaration":
      case "ReturnStatement":
      case "ThrowStatement":
      case "EmptyStatement": return true;
      case "BlockStatement": return supported(statement.body);
      case "IfStatement":
        return supported([statement.consequent]) && (statement.alternate === null || supported([statement.alternate]));
      default: return false;
    }
  });
}

export default defineRule({
  meta: {
    type: "problem",
    docs: {
      description: "Return array replacements without mutating borrowed array inputs.",
      url: docsUrl("no-mutating-container-transform"),
    },
    schema: [],
    messages: { borrowedMutation: "This array-valued transformation mutates borrowed input `{{parameter}}`; copy before writing or expose an in-place command returning void." },
  },
  createOnce(context) {
    let sourceCode: SourceCode;

    function binding(node: Node): TsVariable | null {
      return node.type === "Identifier" ? findVariable(sourceCode.getScope(node), node.name) : null;
    }

    function inspect(node: FunctionNode): void {
      if (node.body?.type !== "BlockStatement" || !returnsArray(node, sourceCode) || !supported(node.body.body)) return;
      const initial: Origins = new Map();
      for (const parameter of node.params) {
        if (parameter.type !== "Identifier" || !isPresent(parameter.typeAnnotation)) continue;
        const element = arrayElement(parameter.typeAnnotation.typeAnnotation, sourceCode);
        const variable = binding(parameter);
        if (element !== null && PRIMITIVES.has(element.type) && variable !== null) initial.set(variable, parameter.name);
      }
      if (initial.size === 0) return;
      let first: { node: Node; parameter: string } | null = null;

      function origin(expression: Node, state: Origins): string | undefined {
        const variable = binding(unwrapExpression(expression));
        return variable === null ? undefined : state.get(variable);
      }

      function expression(current: Node, state: Origins): void {
        switch (current.type) {
          case "FunctionExpression":
          case "ArrowFunctionExpression":
          case "ClassExpression": return;
          case "AssignmentExpression": assignment(current, state); return;
          case "LogicalExpression": logical(current, state); return;
          case "ConditionalExpression": conditional(current, state); return;
          case "UpdateExpression": write(current.argument, state); break;
          case "UnaryExpression": if (current.operator === "delete") write(current.argument, state); break;
          case "CallExpression": mutationCall(current, state); break;
          default: break;
        }
        forEachOwnAstChild(current, child => expression(child, state), key => key !== "typeAnnotation" && key !== "returnType");
      }

      function assignment(current: ESTree.AssignmentExpression, state: Origins): void {
        expression(current.right, state);
        write(current.left, state);
        const target = binding(current.left);
        if (target === null) return;
        const owner = current.operator === "=" ? origin(current.right, state) : undefined;
        if (owner === undefined) state.delete(target); else state.set(target, owner);
      }

      function logical(current: ESTree.LogicalExpression, state: Origins): void {
        expression(current.left, state);
        const left = unwrapExpression(current.left);
        if (left.type === "Literal" && (
          current.operator === "&&" && !left.value || current.operator === "||" && !!left.value ||
          current.operator === "??" && left.value !== null
        )) return;
        expression(current.right, state);
      }

      function conditional(current: ESTree.ConditionalExpression, state: Origins): void {
        expression(current.test, state);
        const test = unwrapExpression(current.test);
        if (test.type === "Literal") {
          expression(test.value ? current.consequent : current.alternate, state);
          return;
        }
        expression(current.consequent, state);
        expression(current.alternate, state);
      }

      function mutationCall(current: ESTree.CallExpression, state: Origins): void {
        if (current.callee.type !== "MemberExpression" || !MUTATORS.has(getPropertyName(current.callee) ?? "")) return;
        const parameter = origin(current.callee.object, state);
        if (parameter !== undefined && first === null) first = { node: current, parameter };
      }

      function write(written: Node, state: Origins): void {
        const target = unwrapExpression(written);
        if (target.type !== "MemberExpression" || (!target.computed && getPropertyName(target) !== "length")) return;
        const parameter = origin(target.object, state);
        if (parameter !== undefined && first === null) first = { node: target, parameter };
      }

      function statements(items: readonly Node[], state: Origins): boolean {
        for (const current of items) if (statement(current, state)) return true;
        return false;
      }

      function statement(current: Node, state: Origins): boolean {
        switch (current.type) {
          case "BlockStatement": return statements(current.body, state);
          case "IfStatement": return branch(current, state);
          case "VariableDeclaration": declarations(current, state); return false;
          case "ReturnStatement":
          case "ThrowStatement":
            if (current.argument !== null) expression(current.argument, state);
            return true;
          case "ExpressionStatement": expression(current.expression, state); return false;
          default: return false;
        }
      }

      function branch(current: ESTree.IfStatement, state: Origins): boolean {
        expression(current.test, state);
        if (current.test.type === "Literal") return current.test.value
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

      function declarations(current: ESTree.VariableDeclaration, state: Origins): void {
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
        const mutation: { node: Node; parameter: string } = first;
        context.report({ node: mutation.node, messageId: "borrowedMutation", data: { parameter: mutation.parameter } });
      }
    }

    return {
      before() {
        sourceCode = context.sourceCode;
        if (isGeneratedFile({ filename: context.filename, cwd: context.cwd }, sourceCode.text)) return false;
        return undefined;
      },
      FunctionDeclaration: inspect,
      FunctionExpression: inspect,
      ArrowFunctionExpression: inspect,
    };
  },
});
