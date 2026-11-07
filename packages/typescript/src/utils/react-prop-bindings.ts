/**
 * @fileoverview react-prop-bindings — resolve stable React hooks and direct props within the owning JSX function.
 *
 * The original caches direct-eval and parameter bindings per `SourceCode`; Oxlint reuses one
 * `SourceCode` for every file, so those caches are keyed by `sourceCode.ast` here.
 */

import type { ESTree, Node, SourceCode, TsReference, TsVariable } from "../types.js";
import { forEachOwnAstChild, outerExpression, parentOf, unwrapExpression } from "./ast.js";
import { importSpecifierName } from "./import-specifier-name.js";
import { directEval } from "./private-scalar-consumer.js";
import { stableValueBinding, writtenMember } from "./stable-value-binding.js";
import { findVariable, getPropertyName } from "./static-string.js";

export type RenderFunction = ESTree.ArrowFunctionExpression | ESTree.Function;
type ParameterBindings = ReadonlySet<TsVariable>;
interface ReactImport {
  readonly specifier: Node;
  readonly replacedMembers: ReadonlySet<string | null> | undefined;
}
const VIEWS = new WeakMap<Node, boolean>();
const DIRECT_EVAL = new WeakMap<object, boolean>();
const REACT_IMPORTS = new WeakMap<TsVariable, ReactImport | null>();
const PARAMETER_BINDINGS = new WeakMap<object, WeakMap<Node, ParameterBindings>>();

export function renderFunction(node: Node): RenderFunction | null {
  let parent = parentOf(node);
  while (parent !== null) {
    const owner = functionNode(parent);
    if (owner !== null) {
      let view = VIEWS.get(owner);
      if (view === undefined) {
        view = owner.body !== null && containsView(owner.body);
        VIEWS.set(owner, view);
      }
      return view ? owner : null;
    }
    parent = parentOf(parent);
  }
  return null;
}

export function firstParameterBindings(source: SourceCode, node: RenderFunction): ParameterBindings {
  let functions = PARAMETER_BINDINGS.get(source.ast);
  if (functions === undefined) {
    functions = new WeakMap<Node, ParameterBindings>();
    PARAMETER_BINDINGS.set(source.ast, functions);
  }
  let bindings = functions.get(node);
  if (bindings === undefined) {
    bindings = collectParameterBindings(source, node);
    functions.set(node, bindings);
  }
  return bindings;
}

function collectParameterBindings(source: SourceCode, node: RenderFunction): ParameterBindings {
  if (hasDirectEval(source)) return new Set();
  const parameter = node.params[0];
  const identifiers = new Set<Node>();
  if (parameter?.type === "Identifier") identifiers.add(parameter);
  if (parameter?.type === "ObjectPattern") {
    for (const property of parameter.properties) {
      if (property.type === "Property" && !property.computed && property.value.type === "Identifier") identifiers.add(property.value);
    }
  }
  return new Set(source.getDeclaredVariables(node).filter((entry) => {
    const variable = entry as TsVariable;
    return variable.identifiers.some((identifier) => identifiers.has(identifier)) && stableValueBinding(variable);
  }) as TsVariable[]);
}

function hasDirectEval(source: SourceCode): boolean {
  let found = DIRECT_EVAL.get(source.ast);
  if (found !== undefined) return found;
  found = source.scopeManager.scopes.some((scope) =>
    scope.references.some(({ identifier }) => {
      if (identifier.type !== "Identifier" || identifier.name !== "eval") return false;
      let callee = outerExpression(identifier);
      let parent = parentOf(callee);
      while (parent?.type === "TSInstantiationExpression" && parent.expression === callee) {
        callee = outerExpression(parent);
        parent = parentOf(callee);
      }
      return parent?.type === "CallExpression" && parent.callee === callee && !parent.optional && directEval(parent);
    }));
  DIRECT_EVAL.set(source.ast, found);
  return found;
}

export function parameterPath(source: SourceCode, node: Node, bindings: ReadonlySet<TsVariable>): boolean {
  let current = unwrapExpression(node);
  for (let depth = 0; depth < 64; depth += 1) {
    if (current.type === "Identifier") {
      const variable = findVariable(source.getScope(current), current.name);
      return variable !== null && bindings.has(variable);
    }
    if (current.type !== "MemberExpression" || current.optional ||
      (current.computed && (current.property.type !== "Literal" || typeof current.property.value !== "string"))) return false;
    current = unwrapExpression(current.object);
  }
  return false;
}

export function reactHook(source: SourceCode, input: Node, hook: string): boolean {
  const callee = unwrapExpression(input);
  let identifier: ESTree.IdentifierReference;
  let namespace = false;
  if (callee.type === "Identifier") identifier = callee as ESTree.IdentifierReference;
  else if (callee.type === "MemberExpression" && !callee.optional && getPropertyName(callee) === hook) {
    const object = unwrapExpression(callee.object);
    if (object.type !== "Identifier") return false;
    identifier = object as ESTree.IdentifierReference;
    namespace = true;
  } else return false;
  const variable = findVariable(source.getScope(identifier), identifier.name);
  if (variable === null) return false;
  const imported = reactImport(variable);
  if (imported === null) return false;
  const { specifier, replacedMembers } = imported;
  return namespace
    ? (specifier.type === "ImportDefaultSpecifier" || specifier.type === "ImportNamespaceSpecifier") &&
      replacedMembers?.has(null) !== true && replacedMembers?.has(hook) !== true
    : specifier.type === "ImportSpecifier" && specifier.importKind !== "type" && importSpecifierName(specifier) === hook;
}

function reactImport(variable: TsVariable): ReactImport | null {
  let imported = REACT_IMPORTS.get(variable);
  if (imported !== undefined) return imported;
  const definition = variable.defs[0] as { readonly type: string; readonly node: Node; readonly parent: Node | null } | undefined;
  imported = null;
  const declaration = definition?.parent;
  if (variable.defs.length === 1 && definition?.type === "ImportBinding" && declaration?.type === "ImportDeclaration" &&
    declaration.source.value === "react" && declaration.importKind !== "type") {
    const specifier = definition.node;
    const replacedMembers = specifier.type === "ImportSpecifier" ? undefined : new Set<string | null>();
    if (stableValueBinding(variable, replacedMembers === undefined ? undefined : (reference: TsReference) => {
      const object = outerExpression(reference.identifier);
      const member = parentOf(object);
      if (member?.type !== "MemberExpression" || member.object !== object) return true;
      const target = outerExpression(member);
      const outer = parentOf(target);
      if (outer?.type === "MemberExpression" && outer.object === target) return true;
      if (writtenMember(member)) replacedMembers.add(getPropertyName(member));
      return true;
    })) imported = { specifier, replacedMembers };
  }
  REACT_IMPORTS.set(variable, imported);
  return imported;
}

function containsView(node: Node): boolean {
  if (node.type === "JSXElement" || node.type === "JSXFragment") return true;
  if (functionNode(node) !== null) return false;
  return forEachOwnAstChild(node, containsView, (key) => key !== "tokens" && key !== "comments");
}

function functionNode(node: Node): RenderFunction | null {
  return node.type === "ArrowFunctionExpression" || node.type === "FunctionDeclaration" || node.type === "FunctionExpression" ? node : null;
}
