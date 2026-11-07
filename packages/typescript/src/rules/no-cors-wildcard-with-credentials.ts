/**
 * @fileoverview no-cors-wildcard-with-credentials — wildcard CORS origins cannot serve credentialed responses.
 *
 * Port of the 18.x `no-cors-wildcard-with-credentials` rule. The rule is
 * untyped, so the port covers all of it.
 */

import type { Definition, Reference, Variable } from "@oxlint/plugins";

import { defineRule, tsReference, type ESTree, type Node } from "../types.js";
import { outerExpression, parentOf, unwrapExpression } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { importSpecifierName } from "../utils/import-specifier-name.js";
import { findVariable, getPropertyName, staticString } from "../utils/static-string.js";

const NAME = "no-cors-wildcard-with-credentials";

type HeaderName = "access-control-allow-origin" | "access-control-allow-credentials";
type ReceiverKey = Variable | string;

const ACAO_HEADER = "access-control-allow-origin";
const ACAC_HEADER = "access-control-allow-credentials";
const HEADER_METHODS: ReadonlySet<string> = new Set(["set", "setHeader", "append", "delete", "removeHeader"]);
const CONTROL_STATEMENTS: ReadonlySet<string> = new Set([
  "BlockStatement", "IfStatement", "SwitchStatement", "TryStatement", "ForStatement",
  "ForInStatement", "ForOfStatement", "WhileStatement", "DoWhileStatement", "WithStatement", "LabeledStatement",
]);
const FUNCTION_TYPES: ReadonlySet<string> = new Set(["FunctionDeclaration", "FunctionExpression", "ArrowFunctionExpression"]);
const ALIAS_INITIALIZER_TYPES: ReadonlySet<string> = new Set([
  "Identifier", "MemberExpression", "AssignmentExpression", "ConditionalExpression", "LogicalExpression", "SequenceExpression",
]);
const SCALAR_HEADER_VALUE_TYPES: ReadonlySet<string> = new Set(["boolean", "number"]);
const HEADER_WHITESPACE_RE = /^[\t\n\r ]+|[\t\n\r ]+$/g;

interface HeaderState {
  readonly values: Record<HeaderName, string | null | undefined>;
  origin: ESTree.CallExpression | null;
}

interface HeaderWrite {
  readonly receiver: ESTree.IdentifierReference;
  readonly header: string;
  readonly value: string | null;
  readonly append: boolean;
}

export default defineRule({
  meta: {
    type: "problem",
    docs: {
      description: "Review wildcard CORS origins combined with an explicit credentials opt-in.",
      url: docsUrl(NAME),
    },
    schema: [],
    messages: {
      corsWildcardWithCredentials: "A wildcard CORS origin blocks browser access to credentialed responses. Review the intended contract: use a trusted explicit origin for credentialed callers, or omit the credentials opt-in for a credentialless endpoint.",
    },
  },
  createOnce(context) {
    const importedCors = new Set<Variable>();
    const importedNamespaces = new Set<Variable>();
    const receiverProof = new Map<ReceiverKey, boolean>();

    function binding(node: ESTree.IdentifierReference | ESTree.BindingIdentifier): Variable | null {
      return findVariable(context.sourceCode.getScope(node), node.name);
    }

    function officialCors(node: Node): boolean {
      const value = unwrapExpression(node);
      if (value.type === "Identifier") {
        const variable = binding(value);
        return variable !== null && importedCors.has(variable);
      }
      if (value.type !== "MemberExpression" || value.optional || value.computed ||
        value.property.type !== "Identifier" || value.property.name !== "cors" || value.object.type !== "Identifier") return false;
      const variable = binding(value.object);
      return variable !== null && importedNamespaces.has(variable);
    }

    function recordImports(node: ESTree.Program): void {
      for (const statement of node.body) {
        if (statement.type === "ImportDeclaration" && statement.importKind !== "type") recordImport(statement);
      }
    }

    function recordImport(node: ESTree.ImportDeclaration): void {
      for (const specifier of node.specifiers) {
        const role = importRole(specifier, node.source.value);
        if (role === null) continue;
        const variable = binding(specifier.local);
        if (variable === null || variable.references.some(reference => reference.isWrite())) continue;
        (role === "namespace" ? importedNamespaces : importedCors).add(variable);
      }
    }

    function inspectSequence(node: ESTree.Program | ESTree.BlockStatement): void {
      const body = node.body as readonly Node[];
      if (body.some(statement => CONTROL_STATEMENTS.has(statement.type))) return;
      const states = new Map<ReceiverKey, HeaderState>();
      for (const statement of body) {
        if (statement.type === "ImportDeclaration" || statement.type === "FunctionDeclaration") continue;
        if (statement.type === "VariableDeclaration") {
          recordHeaderDeclaration(statement, states);
          continue;
        }
        const expression = statement.type === "ExpressionStatement" ? unwrapExpression(statement.expression) : null;
        if (expression?.type !== "CallExpression" || !applyHeaderWrite(expression, states)) states.clear();
      }
      for (const state of states.values()) {
        if (state.values[ACAO_HEADER] === "*" && state.values[ACAC_HEADER] === "true" && state.origin !== null) {
          context.report({ node: state.origin, messageId: "corsWildcardWithCredentials" });
        }
      }
    }

    function recordHeaderDeclaration(node: ESTree.VariableDeclaration, states: Map<ReceiverKey, HeaderState>): void {
      for (const declaration of node.declarations) {
        if (declaration.id.type === "Identifier" && declaration.init !== null && freshHeaders(declaration.init)) {
          const key = receiverKey(declaration.id);
          if (key !== null) states.set(key, { values: { [ACAO_HEADER]: null, [ACAC_HEADER]: null }, origin: null });
        } else if (declaration.id.type !== "Identifier" || (declaration.init !== null && unwrapExpression(declaration.init).type !== "Literal")) states.clear();
      }
    }

    function freshHeaders(node: Node): boolean {
      const value = unwrapExpression(node);
      if (value.type !== "NewExpression" || value.arguments.length !== 0) return false;
      const callee = unwrapExpression(value.callee);
      return callee.type === "Identifier" && callee.name === "Headers" && !binding(callee)?.defs.length;
    }

    function applyHeaderWrite(node: ESTree.CallExpression, states: Map<ReceiverKey, HeaderState>): boolean {
      const write = headerWrite(node);
      const key = write === null ? null : receiverKey(write.receiver);
      if (write === null || key === null) return false;
      let state = states.get(key);
      if (state === undefined) {
        state = { values: { [ACAO_HEADER]: undefined, [ACAC_HEADER]: undefined }, origin: null };
        states.set(key, state);
      }
      const { header, value } = write;
      if (header !== ACAO_HEADER && header !== ACAC_HEADER) return true;
      state.values[header] = write.append ? appendValue(state.values[header], value) : value;
      if (header === ACAO_HEADER) state.origin = node;
      return true;
    }

    function receiverKey(node: ESTree.IdentifierReference | ESTree.BindingIdentifier): ReceiverKey | null {
      const variable = binding(node);
      const key = variable ?? node.name;
      const cached = receiverProof.get(key);
      if (cached !== undefined) return cached ? key : null;
      const references = variable?.references ??
        context.sourceCode.scopeManager?.globalScope?.through.filter(reference => reference.identifier.name === node.name) ?? [];
      const unaliased = !variable?.defs.some(aliasDefinition) && references.every(headerReceiverReference);
      receiverProof.set(key, unaliased);
      return unaliased ? key : null;
    }

    return {
      before() {
        importedCors.clear();
        importedNamespaces.clear();
        receiverProof.clear();
        return undefined;
      },
      Program(node: ESTree.Program): void {
        recordImports(node);
        inspectSequence(node);
      },
      BlockStatement(node: ESTree.BlockStatement): void {
        const parent = parentOf(node);
        if (parent !== null && FUNCTION_TYPES.has(parent.type)) inspectSequence(node);
      },
      CallExpression(node: ESTree.CallExpression): void {
        // Only imported `cors` bindings count, and imports are recorded on `Program`.
        if (importedCors.size === 0 && importedNamespaces.size === 0) return;
        if (node.optional || node.arguments.length !== 1 || !officialCors(node.callee)) return;
        if (wildcardCredentialedOptions(node.arguments[0])) context.report({ node, messageId: "corsWildcardWithCredentials" });
      },
      ObjectExpression(node: ESTree.ObjectExpression): void {
        if (spreadOnly(node)) return;
        const properties = effectiveProperties(node);
        if (properties === null) return;
        const headers = new Map<string, string>();
        for (const [key, property] of properties) {
          const value = headerValue(property.value);
          if (value === null) return;
          const name = key.toLowerCase();
          if (name !== ACAO_HEADER && name !== ACAC_HEADER) continue;
          const previous = headers.get(name);
          headers.set(name, previous === undefined ? value : previous + ", " + value);
        }
        if (headers.get(ACAO_HEADER) === "*" && headers.get(ACAC_HEADER) === "true") {
          context.report({ node, messageId: "corsWildcardWithCredentials" });
        }
      },
    };
  },
});

function importRole(specifier: ESTree.ImportDeclarationSpecifier, module: string): "function" | "namespace" | null {
  if (module === "hono/cors" && specifier.type === "ImportNamespaceSpecifier") return "namespace";
  if (module === "cors" && specifier.type === "ImportDefaultSpecifier") return "function";
  if (specifier.type !== "ImportSpecifier" || specifier.importKind === "type") return null;
  const name = importSpecifierName(specifier);
  return (module === "cors" && name === "default") || (module === "hono/cors" && name === "cors") ? "function" : null;
}

function aliasDefinition(definition: Definition): boolean {
  if (definition.type !== "Variable") return false;
  const declarator = definition.node;
  if (declarator.type !== "VariableDeclarator") return false;
  if (declarator.id.type !== "Identifier") return true;
  const initializer = declarator.init;
  return initializer !== null && ALIAS_INITIALIZER_TYPES.has(unwrapExpression(initializer).type);
}

function headerReceiverReference(reference: Reference): boolean {
  if (typeReference(reference)) return true;
  if (reference.isWrite()) return reference.init === true;
  const member = parentOf(reference.identifier);
  if (member?.type !== "MemberExpression" || member.object !== reference.identifier || member.optional ||
    !HEADER_METHODS.has(getPropertyName(member) ?? "")) return false;
  const call = parentOf(member);
  return call?.type === "CallExpression" && call.callee === member && !call.optional;
}

function typeReference(reference: Reference): boolean {
  if (tsReference(reference).isValueReference === false) return true;
  let typeParent = parentOf(reference.identifier);
  while (typeParent?.type === "TSQualifiedName") typeParent = parentOf(typeParent);
  return typeParent?.type === "TSTypeQuery";
}

/** A header-bag method call on a plain identifier, with a static name and (unless removing) a static value. */
function headerWrite(node: ESTree.CallExpression): HeaderWrite | null {
  const callee = unwrapExpression(node.callee);
  if (node.optional || callee.type !== "MemberExpression" || callee.optional || callee.object.type !== "Identifier") return null;
  const method = getPropertyName(callee) ?? "";
  if (!HEADER_METHODS.has(method)) return null;
  const removal = method === "delete" || method === "removeHeader";
  if (node.arguments.length !== (removal ? 1 : 2)) return null;
  const name = staticString(node.arguments[0]);
  const value = removal ? null : headerValue(node.arguments[1]);
  if (name === null || (!removal && value === null)) return null;
  return { receiver: callee.object, header: name.toLowerCase(), value, append: method === "append" };
}

function wildcardCredentialedOptions(argument: Node | undefined): boolean {
  if (argument === undefined) return false;
  const options = unwrapExpression(argument);
  const properties = options.type === "ObjectExpression" ? effectiveProperties(options) : null;
  const origin = properties?.get("origin");
  const credentials = properties?.get("credentials");
  if (origin === undefined || credentials === undefined) return false;
  const value = unwrapExpression(credentials.value);
  return staticString(origin.value) === "*" && value.type === "Literal" && value.value === true;
}

function appendValue(previous: string | null | undefined, value: string | null): string | null | undefined {
  if (previous === undefined) return undefined;
  return previous === null ? value : previous + ", " + value;
}

function headerValue(node: Node | undefined): string | null {
  const text = staticString(node) ?? scalarLiteralText(node);
  return text === null ? null : text.replace(HEADER_WHITESPACE_RE, "");
}

function scalarLiteralText(node: Node | undefined): string | null {
  const value = node === undefined ? undefined : unwrapExpression(node);
  return value?.type === "Literal" && SCALAR_HEADER_VALUE_TYPES.has(typeof value.value) ? String(value.value) : null;
}

function effectiveProperties(node: ESTree.ObjectExpression): ReadonlyMap<string, ESTree.ObjectProperty> | null {
  const properties = new Map<string, ESTree.ObjectProperty>();
  for (const entry of node.properties) {
    const entries = propertyEntries(entry);
    if (entries === null) return null;
    for (const [key, property] of entries) properties.set(key, property);
  }
  return properties;
}

function propertyEntries(entry: ESTree.ObjectPropertyKind): Iterable<readonly [string, ESTree.ObjectProperty]> | null {
  if (entry.type === "SpreadElement") {
    const value = unwrapExpression(entry.argument);
    return value.type === "ObjectExpression" ? effectiveProperties(value) : null;
  }
  if (entry.kind !== "init" || entry.method) return null;
  const key = entry.computed ? staticString(entry.key) : getPropertyName(entry);
  if (key === null) return null;
  if (key === "__proto__" && !entry.computed) {
    const value = unwrapExpression(entry.value);
    return value.type === "Literal" && value.value === null ? [] : null;
  }
  return [[key, entry]];
}

const SPREAD_PATH_TYPES: ReadonlySet<string> = new Set(["Property", "ObjectExpression", "ConditionalExpression", "LogicalExpression",
  "SequenceExpression", "TSAsExpression", "TSSatisfiesExpression", "TSNonNullExpression", "TSTypeAssertion"]);

function spreadOnly(node: ESTree.ObjectExpression): boolean {
  let current: Node = outerExpression(node);
  let parent = parentOf(current);
  while (parent !== null) {
    if (parent.type === "SpreadElement") return parentOf(parent)?.type === "ObjectExpression";
    if (!SPREAD_PATH_TYPES.has(parent.type)) return false;
    current = parent;
    parent = parentOf(current);
  }
  return false;
}
