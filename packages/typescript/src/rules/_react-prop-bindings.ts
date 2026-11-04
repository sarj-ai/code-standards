/**
 * @fileoverview _react-prop-bindings — resolve stable React hooks and direct props within the owning JSX function.
 */

import {
  AST_NODE_TYPES,
  ASTUtils,
  type TSESLint,
  type TSESTree,
} from "@typescript-eslint/utils";

import type { TypeScriptSourceCode } from "./_eslint-rule.js";
import { forEachOwnAstChild } from "./_for-each-own-ast-child.js";
import { importSpecifierName } from "./_import-specifier-name.js";
import { stableValueBinding } from "./_stable-value-binding.js";
import { unwrapExpression } from "./_unwrap-expression.js";

type RenderFunction =
  | TSESTree.ArrowFunctionExpression
  | TSESTree.FunctionDeclaration
  | TSESTree.FunctionExpression;
type SourceCode = Readonly<TypeScriptSourceCode>;
const VIEWS = new WeakMap<RenderFunction, boolean>();

export function renderFunction(node: TSESTree.Node): RenderFunction | null {
  let parent = node.parent;
  while (parent !== undefined) {
    if (isFunction(parent)) {
      let view = VIEWS.get(parent);
      if (view === undefined) {
        view = containsView(parent.body);
        VIEWS.set(parent, view);
      }
      return view ? parent : null;
    }
    parent = parent.parent;
  }
  return null;
}

export function firstParameterBindings(
  source: SourceCode,
  node: RenderFunction,
): ReadonlySet<TSESLint.Scope.Variable> {
  const parameter = node.params[0];
  const identifiers: TSESTree.Identifier[] = [];
  if (parameter?.type === AST_NODE_TYPES.Identifier)
    identifiers.push(parameter);
  if (parameter?.type === AST_NODE_TYPES.ObjectPattern) {
    for (const property of parameter.properties) {
      if (
        property.type === AST_NODE_TYPES.Property &&
        !property.computed &&
        property.value.type === AST_NODE_TYPES.Identifier
      )
        identifiers.push(property.value);
    }
  }
  return new Set(
    source
      .getDeclaredVariables(node)
      .filter(
        (variable) =>
          identifiers.some((identifier) =>
            variable.identifiers.includes(identifier),
          ) && stableValueBinding(variable),
      ),
  );
}

export function parameterPath(
  source: SourceCode,
  node: TSESTree.Node,
  bindings: ReadonlySet<TSESLint.Scope.Variable>,
): boolean {
  let current = unwrapExpression(node);
  for (let depth = 0; depth < 64; depth += 1) {
    if (current.type === AST_NODE_TYPES.Identifier) {
      const variable = ASTUtils.findVariable(
        source.getScope(current),
        current.name,
      );
      return variable !== null && bindings.has(variable);
    }
    if (
      current.type !== AST_NODE_TYPES.MemberExpression ||
      current.optional ||
      (current.computed &&
        (current.property.type !== AST_NODE_TYPES.Literal ||
          typeof current.property.value !== "string"))
    )
      return false;
    current = unwrapExpression(current.object);
  }
  return false;
}

export function reactHook(
  source: SourceCode,
  callee: TSESTree.Node,
  hook: string,
): boolean {
  callee = unwrapExpression(callee);
  let identifier: TSESTree.Identifier;
  let namespace = false;
  if (callee.type === AST_NODE_TYPES.Identifier) identifier = callee;
  else if (
    callee.type === AST_NODE_TYPES.MemberExpression &&
    !callee.optional &&
    ASTUtils.getPropertyName(callee) === hook &&
    callee.object.type === AST_NODE_TYPES.Identifier
  ) {
    identifier = callee.object;
    namespace = true;
  } else return false;
  const variable = ASTUtils.findVariable(
    source.getScope(identifier),
    identifier.name,
  );
  if (
    variable === null ||
    variable.defs.length !== 1 ||
    !stableValueBinding(variable)
  )
    return false;
  const definition = variable.defs[0];
  if (
    definition?.type !== "ImportBinding" ||
    definition.parent.type !== AST_NODE_TYPES.ImportDeclaration ||
    definition.parent.source.value !== "react" ||
    definition.parent.importKind === "type"
  )
    return false;
  const specifier = definition.node;
  return namespace
    ? specifier.type === AST_NODE_TYPES.ImportDefaultSpecifier ||
        specifier.type === AST_NODE_TYPES.ImportNamespaceSpecifier
    : specifier.type === AST_NODE_TYPES.ImportSpecifier &&
        specifier.importKind !== "type" &&
        importSpecifierName(specifier) === hook;
}

function containsView(node: TSESTree.Node): boolean {
  if (
    node.type === AST_NODE_TYPES.JSXElement ||
    node.type === AST_NODE_TYPES.JSXFragment
  )
    return true;
  if (isFunction(node)) return false;
  return forEachOwnAstChild(
    node,
    containsView,
    (key) => key !== "tokens" && key !== "comments",
  );
}

function isFunction(node: TSESTree.Node): node is RenderFunction {
  return (
    node.type === AST_NODE_TYPES.ArrowFunctionExpression ||
    node.type === AST_NODE_TYPES.FunctionDeclaration ||
    node.type === AST_NODE_TYPES.FunctionExpression
  );
}
