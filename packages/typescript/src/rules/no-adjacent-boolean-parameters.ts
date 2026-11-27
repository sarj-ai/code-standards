/**
 * @fileoverview no-adjacent-boolean-parameters — Avoid swap-prone positional boolean parameters.
 */

import { defineRule, type ESTree, type Identifier, type Node, type SourceCode } from "../types.js";
import { outerExpression, parentOf } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { isGeneratedFile } from "../utils/paths.js";
import { getPropertyName } from "../utils/static-string.js";

const NAME = "no-adjacent-boolean-parameters";

type Signature = Node & {
  readonly params: readonly Node[];
  readonly returnType?: ESTree.TSTypeAnnotation | null;
};

function secondBoolean(signature: Signature): Identifier | undefined {
  if (signature.returnType?.typeAnnotation.type === "TSTypePredicate") return undefined;
  let seenBoolean = false;
  for (const parameter of signature.params) {
    const identifier = booleanParameter(parameter);
    if (identifier === undefined) continue;
    if (seenBoolean) return identifier;
    seenBoolean = true;
  }
  return undefined;
}

function booleanParameter(parameter: Node): Identifier | undefined {
  if (parameter.type === "TSParameterProperty") return booleanParameter(parameter.parameter);
  if (parameter.type === "Identifier" && parameter.name !== "this" &&
    parameter.typeAnnotation?.typeAnnotation.type === "TSBooleanKeyword") return parameter;
  if (parameter.type === "AssignmentPattern" && parameter.left.type === "Identifier" &&
    parameter.right.type === "Literal" && (parameter.right.value === true || parameter.right.value === false)) return parameter.left;
  return undefined;
}

function isInlineCallback(node: Node): boolean {
  if (node.type !== "FunctionExpression" && node.type !== "ArrowFunctionExpression") return false;
  const expression = outerExpression(node);
  const parent = parentOf(expression);
  return (parent?.type === "CallExpression" || parent?.type === "NewExpression") &&
    parent.arguments.some((argument) => argument === expression);
}

function hasOnlyNarrowOverloads(node: Signature, source: SourceCode): boolean {
  const parent = parentOf(node);
  let entry: Node;
  if (node.type === "FunctionDeclaration") {
    entry = parent?.type === "ExportNamedDeclaration" || parent?.type === "ExportDefaultDeclaration" ? parent : node;
  } else if (node.type === "FunctionExpression" && parent?.type === "MethodDefinition") {
    entry = parent;
  } else {
    return false;
  }

  const siblings = siblingsOf(entry);
  const index = siblings.indexOf(entry);
  // TypeScript overloads immediately precede their implementation in the same list.
  let foundOverload = false;
  for (let previous = index - 1; previous >= 0; previous -= 1) {
    const sibling = siblings[previous];
    if (sibling === undefined) break;
    const overload = overloadBefore(sibling, node.type === "FunctionDeclaration" ? node : entry, source);
    if (overload === undefined) break;
    foundOverload = true;
    if (secondBoolean(overload) !== undefined) return false;
  }
  return foundOverload;
}

function siblingsOf(node: Node): readonly Node[] {
  const parent = parentOf(node);
  switch (parent?.type) {
    case "Program":
    case "BlockStatement":
    case "TSModuleBlock":
    case "ClassBody":
      return parent.body;
    case "SwitchCase":
      return parent.consequent;
    default:
      return [];
  }
}

function overloadBefore(previous: Node, implementation: Node, source: SourceCode): Signature | undefined {
  const sibling = previous.type === "ExportNamedDeclaration" || previous.type === "ExportDefaultDeclaration"
    ? previous.declaration : previous;
  if (implementation.type === "FunctionDeclaration" && sibling?.type === "TSDeclareFunction" &&
    implementation.id !== null && sibling.id?.name === implementation.id.name) return sibling;
  if (implementation.type !== "MethodDefinition" || sibling?.type !== "MethodDefinition" ||
    sibling.value.type !== "TSEmptyBodyFunctionExpression" || sibling.static !== implementation.static ||
    sibling.kind !== implementation.kind) return undefined;
  const name = getPropertyName(implementation);
  const sameName = name === null
    ? sibling.computed === implementation.computed && source.getText(sibling.key) === source.getText(implementation.key)
    : getPropertyName(sibling) === name;
  return sameName ? sibling.value : undefined;
}

export default defineRule({
  meta: {
    type: "suggestion",
    docs: { description: "Avoid swap-prone positional boolean parameters.", url: docsUrl(NAME) },
    schema: [],
    messages: {
      noAdjacentBooleanParameters:
        "Two positional boolean parameters can be swapped silently. Use an options object or a literal-union parameter.",
    },
  },
  createOnce(context) {
    function check(node: Signature): void {
      const identifier = secondBoolean(node);
      if (identifier === undefined || isInlineCallback(node)) return;
      const parent = parentOf(node);
      if ((node.type === "TSMethodSignature" && node.kind === "set") ||
        ((parent?.type === "MethodDefinition" || parent?.type === "TSAbstractMethodDefinition" || parent?.type === "Property") &&
          parent.kind === "set")) return;
      if (hasOnlyNarrowOverloads(node, context.sourceCode)) return;
      context.report({ node: identifier, messageId: "noAdjacentBooleanParameters" });
    }

    return {
      before() {
        return !isGeneratedFile({ filename: context.filename, cwd: context.cwd }, context.sourceCode.text);
      },
      FunctionDeclaration: check,
      FunctionExpression: check,
      ArrowFunctionExpression: check,
      TSDeclareFunction: check,
      TSEmptyBodyFunctionExpression: check,
      TSMethodSignature: check,
      TSFunctionType: check,
    };
  },
});
