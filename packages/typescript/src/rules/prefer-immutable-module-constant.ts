/**
 * @fileoverview prefer-immutable-module-constant — module constants should expose readonly collection state.
 *
 * Examples: https://github.com/sarj-ai/standards/blob/main/packages/typescript/tests/rules/prefer-immutable-module-constant.test.ts
 */

import { AST_NODE_TYPES, type TSESTree } from "@typescript-eslint/utils";

import { createRule } from "./_docs.js";
import { isGeneratedFile, isTestFile } from "./_paths.js";

type MessageIds = "preferAsConst" | "preferReadonlyCollection";
type Options = readonly [];

const CONSTANT_NAME = /^_?[A-Z][A-Z0-9_]*$/;
const MUTATING_METHODS: ReadonlySet<string> = new Set([
  "add",
  "clear",
  "copyWithin",
  "delete",
  "fill",
  "pop",
  "push",
  "reverse",
  "set",
  "shift",
  "sort",
  "splice",
  "unshift",
]);

function isAsConst(node: TSESTree.Node, sourceText: (node: TSESTree.Node) => string): boolean {
  if (node.type === AST_NODE_TYPES.TSSatisfiesExpression) {
    return isAsConst(node.expression, sourceText);
  }
  return (
    node.type === AST_NODE_TYPES.TSAsExpression &&
    sourceText(node.typeAnnotation).trim() === "const"
  );
}

/** Strip type-only wrappers without treating a mutable assertion as readonly. */
function unwrapExpression(node: TSESTree.Node): TSESTree.Node {
  if (
    node.type === AST_NODE_TYPES.TSAsExpression ||
    node.type === AST_NODE_TYPES.TSSatisfiesExpression ||
    node.type === AST_NODE_TYPES.TSNonNullExpression
  ) {
    return unwrapExpression(node.expression);
  }
  return node;
}

function isObjectFreeze(node: TSESTree.Node): boolean {
  const inner = unwrapExpression(node);
  return (
    inner.type === AST_NODE_TYPES.CallExpression &&
    inner.callee.type === AST_NODE_TYPES.MemberExpression &&
    !inner.callee.computed &&
    inner.callee.object.type === AST_NODE_TYPES.Identifier &&
    inner.callee.object.name === "Object" &&
    inner.callee.property.type === AST_NODE_TYPES.Identifier &&
    inner.callee.property.name === "freeze"
  );
}

function collectionKind(node: TSESTree.Node): "literal" | "Set" | "Map" | null {
  const inner = unwrapExpression(node);
  if (inner.type === AST_NODE_TYPES.ArrayExpression || inner.type === AST_NODE_TYPES.ObjectExpression) {
    return "literal";
  }
  if (
    inner.type === AST_NODE_TYPES.NewExpression &&
    inner.callee.type === AST_NODE_TYPES.Identifier &&
    (inner.callee.name === "Set" || inner.callee.name === "Map")
  ) {
    return inner.callee.name;
  }
  return null;
}

function isReadonlyType(node: TSESTree.Node, kind: "literal" | "Set" | "Map"): boolean {
  if (node.type === AST_NODE_TYPES.TSTypeOperator && node.operator === "readonly") {
    return true;
  }
  if (
    node.type !== AST_NODE_TYPES.TSTypeReference ||
    node.typeName.type !== AST_NODE_TYPES.Identifier
  ) {
    return false;
  }
  if (node.typeName.name === "Readonly") {
    return true;
  }
  return kind === "literal"
    ? node.typeName.name === "ReadonlyArray"
    : node.typeName.name === `Readonly${kind}`;
}

function declaredReadonlyType(
  node: TSESTree.VariableDeclarator,
  kind: "literal" | "Set" | "Map",
): boolean {
  const annotation = node.id.type === AST_NODE_TYPES.Identifier ? node.id.typeAnnotation : undefined;
  if (annotation !== undefined && isReadonlyType(annotation.typeAnnotation, kind)) {
    return true;
  }
  return node.init?.type === AST_NODE_TYPES.TSAsExpression && isReadonlyType(node.init.typeAnnotation, kind);
}

function referenceMutates(identifier: TSESTree.Identifier): boolean {
  let member = identifier.parent;
  if (
    member?.type !== AST_NODE_TYPES.MemberExpression ||
    member.object !== identifier
  ) {
    return (
      member?.type === AST_NODE_TYPES.CallExpression &&
      member.arguments[0] === identifier &&
      member.callee.type === AST_NODE_TYPES.MemberExpression &&
      !member.callee.computed &&
      member.callee.object.type === AST_NODE_TYPES.Identifier &&
      member.callee.object.name === "Object" &&
      member.callee.property.type === AST_NODE_TYPES.Identifier &&
      member.callee.property.name === "assign"
    );
  }
  while (
    member.parent.type === AST_NODE_TYPES.MemberExpression &&
    member.parent.object === member
  ) {
    member = member.parent;
  }
  const parent = member.parent;
  if (parent?.type === AST_NODE_TYPES.AssignmentExpression && parent.left === member) {
    return true;
  }
  if (parent?.type === AST_NODE_TYPES.UpdateExpression && parent.argument === member) {
    return true;
  }
  if (parent?.type === AST_NODE_TYPES.UnaryExpression && parent.operator === "delete" && parent.argument === member) {
    return true;
  }
  return (
    parent?.type === AST_NODE_TYPES.CallExpression &&
    parent.callee === member &&
    member.property.type === AST_NODE_TYPES.Identifier &&
    MUTATING_METHODS.has(member.property.name)
  );
}

export default createRule<Options, MessageIds>({
  name: "prefer-immutable-module-constant",
  meta: {
    type: "suggestion",
    docs: {
      description:
        "Require module-level constant collections to expose readonly state.",
    },
    schema: [],
    messages: {
      preferAsConst:
        "Module constant `{{name}}` is a mutable literal. Add `as const` or use `Object.freeze` so consumers cannot mutate shared state.",
      preferReadonlyCollection:
        "Module constant `{{name}}` is a mutable {{kind}}. Expose it as `Readonly{{kind}}` or an immutable collection.",
    },
  },
  defaultOptions: [],
  create(context) {
    const sourceCode = context.sourceCode;
    if (isTestFile(context.filename) || isGeneratedFile(context.filename, sourceCode.getText())) {
      return {};
    }
    return {
      VariableDeclarator(node): void {
        const declaration = node.parent;
        if (
          declaration.type !== AST_NODE_TYPES.VariableDeclaration ||
          declaration.kind !== "const" ||
          node.id.type !== AST_NODE_TYPES.Identifier ||
          node.init === null ||
          !CONSTANT_NAME.test(node.id.name)
        ) {
          return;
        }
        const container = declaration.parent;
        if (
          container.type !== AST_NODE_TYPES.Program &&
          !(
            container.type === AST_NODE_TYPES.ExportNamedDeclaration &&
            container.parent.type === AST_NODE_TYPES.Program
          )
        ) {
          return;
        }
        if (isAsConst(node.init, (target) => sourceCode.getText(target)) || isObjectFreeze(node.init)) {
          return;
        }
        const kind = collectionKind(node.init);
        if (kind === null || declaredReadonlyType(node, kind)) {
          return;
        }
        const variable = sourceCode.getDeclaredVariables(node)[0];
        if (
          variable?.references.some(
            (reference) =>
              reference.identifier.type === AST_NODE_TYPES.Identifier &&
              referenceMutates(reference.identifier),
          ) === true
        ) {
          return;
        }
        context.report({
          node: node.id,
          messageId: kind === "literal" ? "preferAsConst" : "preferReadonlyCollection",
          data: { name: node.id.name, kind },
        });
      },
    };
  },
});
