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
import { directEval } from "./_private-scalar-consumer.js";
import { stableValueBinding, writtenMember } from "./_stable-value-binding.js";
import { outerExpression, unwrapExpression } from "./_unwrap-expression.js";

type RenderFunction =
  | TSESTree.ArrowFunctionExpression
  | TSESTree.FunctionDeclaration
  | TSESTree.FunctionExpression;
type SourceCode = Readonly<TypeScriptSourceCode>;
type ParameterBindings = ReadonlySet<TSESLint.Scope.Variable>;
interface ReactImport {
  readonly specifier: TSESTree.Node;
  readonly replacedMembers: ReadonlySet<string | null> | undefined;
}
const VIEWS = new WeakMap<RenderFunction, boolean>();
const DIRECT_EVAL = new WeakMap<SourceCode, boolean>();
const REACT_IMPORTS = new WeakMap<
  TSESLint.Scope.Variable,
  ReactImport | null
>();
const PARAMETER_BINDINGS = new WeakMap<
  SourceCode,
  WeakMap<RenderFunction, ParameterBindings>
>();

export function renderFunction(node: TSESTree.Node): RenderFunction | null {
  let parent = node.parent;
  while (parent !== undefined && parent !== null) {
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
): ParameterBindings {
  let functions = PARAMETER_BINDINGS.get(source);
  if (functions === undefined) {
    functions = new WeakMap<RenderFunction, ParameterBindings>();
    PARAMETER_BINDINGS.set(source, functions);
  }
  let bindings = functions.get(node);
  if (bindings === undefined) {
    bindings = collectParameterBindings(source, node);
    functions.set(node, bindings);
  }
  return bindings;
}

function collectParameterBindings(
  source: SourceCode,
  node: RenderFunction,
): ParameterBindings {
  if (hasDirectEval(source)) return new Set();
  const parameter = node.params[0];
  const identifiers = new Set<TSESTree.Identifier>();
  if (parameter?.type === AST_NODE_TYPES.Identifier)
    identifiers.add(parameter);
  if (parameter?.type === AST_NODE_TYPES.ObjectPattern) {
    for (const property of parameter.properties) {
      if (
        property.type === AST_NODE_TYPES.Property &&
        !property.computed &&
        property.value.type === AST_NODE_TYPES.Identifier
      )
        identifiers.add(property.value);
    }
  }
  return new Set(
    source
      .getDeclaredVariables(node)
      .filter(
        (variable) =>
          variable.identifiers.some((identifier) =>
            identifiers.has(identifier),
          ) && stableValueBinding(variable),
      ),
  );
}

function hasDirectEval(source: SourceCode): boolean {
  let found = DIRECT_EVAL.get(source);
  if (found !== undefined) return found;
  found =
    source.scopeManager?.scopes.some((scope) =>
      scope.references.some(({ identifier }) => {
        if (
          identifier.type !== AST_NODE_TYPES.Identifier ||
          identifier.name !== "eval"
        )
          return false;
        let callee = outerExpression(identifier);
        while (
          callee.parent?.type === AST_NODE_TYPES.TSInstantiationExpression &&
          callee.parent.expression === callee
        )
          callee = outerExpression(callee.parent);
        const call = callee.parent;
        return (
          call?.type === AST_NODE_TYPES.CallExpression &&
          call.callee === callee &&
          !call.optional &&
          directEval(call)
        );
      }),
    ) ?? true;
  DIRECT_EVAL.set(source, found);
  return found;
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
    ASTUtils.getPropertyName(callee) === hook
  ) {
    const object = unwrapExpression(callee.object);
    if (object.type !== AST_NODE_TYPES.Identifier) return false;
    identifier = object;
    namespace = true;
  } else return false;
  const variable = ASTUtils.findVariable(
    source.getScope(identifier),
    identifier.name,
  );
  if (variable === null) return false;
  const imported = reactImport(variable);
  if (imported === null) return false;
  const { specifier, replacedMembers } = imported;
  return namespace
    ? (specifier.type === AST_NODE_TYPES.ImportDefaultSpecifier ||
        specifier.type === AST_NODE_TYPES.ImportNamespaceSpecifier) &&
        replacedMembers?.has(null) !== true &&
        replacedMembers?.has(hook) !== true
    : specifier.type === AST_NODE_TYPES.ImportSpecifier &&
        specifier.importKind !== "type" &&
        importSpecifierName(specifier) === hook;
}

function reactImport(
  variable: TSESLint.Scope.Variable,
): ReactImport | null {
  let imported = REACT_IMPORTS.get(variable);
  if (imported !== undefined) return imported;
  const definition = variable.defs[0];
  imported = null;
  if (
    variable.defs.length === 1 &&
    definition?.type === "ImportBinding" &&
    definition.parent.type === AST_NODE_TYPES.ImportDeclaration &&
    definition.parent.source.value === "react" &&
    definition.parent.importKind !== "type"
  ) {
    const specifier = definition.node;
    const replacedMembers = specifier.type === AST_NODE_TYPES.ImportSpecifier
      ? undefined : new Set<string | null>();
    if (stableValueBinding(variable, replacedMembers === undefined ? undefined : (reference) => {
      const object = outerExpression(reference.identifier);
      const member = object.parent;
      if (member?.type !== AST_NODE_TYPES.MemberExpression || member.object !== object)
        return true;
      const target = outerExpression(member);
      if (target.parent?.type === AST_NODE_TYPES.MemberExpression && target.parent.object === target)
        return true;
      if (writtenMember(member)) replacedMembers.add(ASTUtils.getPropertyName(member));
      return true;
    })) imported = { specifier, replacedMembers };
  }
  REACT_IMPORTS.set(variable, imported);
  return imported;
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

function isFunction(node: TSESTree.Node) {
  return (
    node.type === AST_NODE_TYPES.ArrowFunctionExpression ||
    node.type === AST_NODE_TYPES.FunctionDeclaration ||
    node.type === AST_NODE_TYPES.FunctionExpression
  );
}
