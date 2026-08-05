/**
 * @fileoverview no-positional-tuple-return — a positional tuple crossing a module boundary names its fields only at the call site, so call sites disagree.
 *
 * Examples: https://github.com/sarj-ai/standards/blob/main/packages/typescript/tests/rules/no-positional-tuple-return.test.ts
 */

import { AST_NODE_TYPES, type TSESTree } from "@typescript-eslint/utils";

import { createRule } from "./_docs.js";

type MessageIds = "noPositionalTupleReturn";
type Options = readonly [];

const MIN_ELEMENTS = 2;

/** Type wrappers whose single type argument is the value actually returned. */
const AWAITABLE_TYPES: ReadonlySet<string> = new Set(["Promise", "PromiseLike", "Awaited"]);

/** The first boundary tuple in a return annotation, unwrapping transparent wrappers and unions. */
function tupleReturnType(node: TSESTree.TypeNode): TSESTree.TSTupleType | null {
  if (node.type === AST_NODE_TYPES.TSTupleType) {
    return node;
  }
  if (
    node.type === AST_NODE_TYPES.TSTypeReference &&
    node.typeName.type === AST_NODE_TYPES.Identifier &&
    AWAITABLE_TYPES.has(node.typeName.name)
  ) {
    const argument = node.typeArguments?.params.at(0);
    return argument === undefined ? null : tupleReturnType(argument);
  }
  if (node.type === AST_NODE_TYPES.TSTypeOperator && node.operator === "readonly") {
    return node.typeAnnotation === undefined ? null : tupleReturnType(node.typeAnnotation);
  }
  if (node.type === AST_NODE_TYPES.TSUnionType || node.type === AST_NODE_TYPES.TSIntersectionType) {
    for (const member of node.types) {
      const tuple = tupleReturnType(member);
      if (tuple !== null) return tuple;
    }
  }
  return null;
}

/** The declared name of a function-ish node, or null for an anonymous one. */
function functionName(node: TSESTree.Node): string | null {
  if (node.type === AST_NODE_TYPES.FunctionDeclaration) {
    return node.id?.name ?? null;
  }
  const parent = node.parent;
  if (parent?.type === AST_NODE_TYPES.VariableDeclarator && parent.id.type === AST_NODE_TYPES.Identifier) {
    return parent.id.name;
  }
  if (
    (parent?.type === AST_NODE_TYPES.MethodDefinition ||
      parent?.type === AST_NODE_TYPES.PropertyDefinition ||
      parent?.type === AST_NODE_TYPES.Property) &&
    parent.key.type === AST_NODE_TYPES.Identifier
  ) {
    return parent.key.name;
  }
  return null;
}

/**
 * True when an ancestor statement carries the `export` keyword inline —
 * `export function f`, `export const f =`, `export default function f`.
 */
function isInlineExported(node: TSESTree.Node): boolean {
  for (let current: TSESTree.Node | undefined | null = node; current != null; current = current.parent) {
    const parent = current.parent;
    if (
      parent?.type === AST_NODE_TYPES.ExportNamedDeclaration ||
      parent?.type === AST_NODE_TYPES.ExportDefaultDeclaration
    ) {
      return true;
    }
  }
  return false;
}

/**
 * The module-scope binding the function lives under — `split` for a top-level
 * `function split`, `Repo` for a method of a top-level `class Repo`. That is the
 * name an `export { … }` specifier elsewhere in the file would refer to. Null
 * when the function is not anchored to a named top-level declaration.
 */
function moduleScopeBindingName(node: TSESTree.Node): string | null {
  let current: TSESTree.Node = node;
  let child: TSESTree.Node = node;
  while (current.parent != null && current.parent.type !== AST_NODE_TYPES.Program) {
    child = current;
    current = current.parent;
  }
  if (current.parent?.type !== AST_NODE_TYPES.Program) {
    return null;
  }
  if (
    current.type === AST_NODE_TYPES.FunctionDeclaration ||
    current.type === AST_NODE_TYPES.ClassDeclaration
  ) {
    return current.id?.name ?? null;
  }
  if (current.type === AST_NODE_TYPES.VariableDeclaration) {
    if (child.type !== AST_NODE_TYPES.VariableDeclarator || child.id.type !== AST_NODE_TYPES.Identifier) {
      return null;
    }
    return child.id.name;
  }
  return null;
}

/**
 * Local names this module puts on its public surface through a *detached* export
 * statement: `export { split }`, `export { split as s }`, `export default split`,
 * `export = split`. A re-export (`export { x } from "./other"`) names a binding
 * owned by another module, and a type-only export (`export type { x }`) does not
 * expose the value, so neither counts.
 */
function specifierExportedNames(program: TSESTree.Program): ReadonlySet<string> {
  const names = new Set<string>();
  for (const statement of program.body) {
    if (
      statement.type === AST_NODE_TYPES.ExportNamedDeclaration &&
      statement.declaration == null &&
      statement.source == null &&
      statement.exportKind !== "type"
    ) {
      for (const specifier of statement.specifiers) {
        if (specifier.exportKind !== "type" && specifier.local.type === AST_NODE_TYPES.Identifier) {
          names.add(specifier.local.name);
        }
      }
      continue;
    }
    if (
      statement.type === AST_NODE_TYPES.ExportDefaultDeclaration &&
      statement.declaration.type === AST_NODE_TYPES.Identifier
    ) {
      names.add(statement.declaration.name);
      continue;
    }
    if (
      statement.type === AST_NODE_TYPES.TSExportAssignment &&
      statement.expression.type === AST_NODE_TYPES.Identifier
    ) {
      names.add(statement.expression.name);
    }
  }
  return names;
}

/**
 * True when the function is reachable from outside the module — the boundary the
 * rule is about. Either the declaration is exported inline, or its module-scope
 * binding is exported later through an export specifier.
 */
function isExported(node: TSESTree.Node, specifierExports: ReadonlySet<string>): boolean {
  if (isInlineExported(node)) {
    return true;
  }
  if (specifierExports.size === 0) {
    return false;
  }
  const binding = moduleScopeBindingName(node);
  return binding !== null && specifierExports.has(binding);
}

export default createRule<Options, MessageIds>({
  name: "no-positional-tuple-return",
  meta: {
    type: "suggestion",
    docs: {
      description:
        "Disallow returning a multi-field tuple from an exported function; return a named object so call sites cannot mismatch slots.",
    },
    schema: [],
    messages: {
      noPositionalTupleReturn:
        "Exported `{{name}}` returns a {{count}}-field tuple, so consumers depend on positional slots that can be reordered silently. Return a named object instead.",
    },
  },
  defaultOptions: [],
  create(context) {
    const specifierExports = specifierExportedNames(context.sourceCode.ast);
    const check = (
      node:
        | TSESTree.FunctionDeclaration
        | TSESTree.FunctionExpression
        | TSESTree.ArrowFunctionExpression,
    ): void => {
      const annotation = node.returnType?.typeAnnotation;
      if (annotation === undefined) {
        return;
      }
      const tuple = tupleReturnType(annotation);
      if (tuple === null || tuple.elementTypes.length < MIN_ELEMENTS) {
        return;
      }
      const name = functionName(node);
      if (name === null) {
        return;
      }
      if (!isExported(node, specifierExports)) {
        return;
      }
      context.report({
        node: tuple,
        messageId: "noPositionalTupleReturn",
        data: { name, count: String(tuple.elementTypes.length) },
      });
    };
    return {
      FunctionDeclaration: check,
      FunctionExpression: check,
      ArrowFunctionExpression: check,
    };
  },
});
