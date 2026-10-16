/**
 * @fileoverview no-cors-wildcard-with-credentials — review wildcard origins that prevent browser access to credentialed responses.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-cors-wildcard-with-credentials.test.ts
 */

import { ASTUtils, type TSESLint, type TSESTree } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { outerExpression, unwrapExpression } from "./_unwrap-expression.js";
import { staticString } from "./_static-string.js";

type MessageIds = "corsWildcardWithCredentials";
type Options = readonly [];
type HeaderName = "access-control-allow-origin" | "access-control-allow-credentials";

const ACAO_HEADER = "access-control-allow-origin";
const ACAC_HEADER = "access-control-allow-credentials";
const HEADER_METHODS: ReadonlySet<string> = new Set(["set", "setHeader", "append", "delete", "removeHeader"]);
const CONTROL_STATEMENTS: ReadonlySet<string> = new Set([
  "BlockStatement", "IfStatement", "SwitchStatement", "TryStatement", "ForStatement",
  "ForInStatement", "ForOfStatement", "WhileStatement", "DoWhileStatement", "WithStatement", "LabeledStatement",
]);

export const NO_CORS_WILDCARD_WITH_CREDENTIALS_DOCUMENTATION = {
  summary: "Review wildcard CORS origins combined with an explicit credentials opt-in.",
  rationale: "Browsers do not expose credentialed cross-origin responses when Access-Control-Allow-Origin is '*'. Credentialless requests can still use a wildcard even when Access-Control-Allow-Credentials is emitted, so review the intended caller contract.",
  remediation: "Use a trusted explicit origin for credentialed callers, or omit the credentials opt-in for a credentialless wildcard endpoint.",
  category: "correctness",
  defaultLevel: "warning",
  autofix: "none",
  references: ["https://fetch.spec.whatwg.org/#cors-protocol-and-credentials"],
  limitations: [
    "Options require a stable official cors default import or hono/cors named or namespace import, one literal object argument, literal origin '*', and credentials true. No-substitution templates and erased TypeScript literal wrappers preserve these values. Custom bindings, callbacks, arrays, conditional origins and dynamic options are excluded.",
    "Literal header maps use effective case-sensitive JavaScript property writes followed by native Headers combination of differently-cased header names. Unknown values/spreads/computed keys, accessors and non-null prototypes lose proof; literals used only inside object spreads are not reported independently.",
    "Manual set/setHeader/delete/removeHeader calls (including static computed method names) use direct identifier receivers and literal arguments in straight-line program or function bodies. Control-flow bodies, member receivers, aliases and unknown operations are excluded. Append requires a proven empty native Headers constructor or a preceding known write/removal.",
    "The rule reviews a local configuration contract, not actual request credentials or a data disclosure. Runtime patches, custom header method implementations, interprocedural mutation and later consumers are not resolved. No autofix.",
  ],
  examples: [
    {
      id: "trusted-origin-with-credentials",
      title: "Use a trusted origin for credentialed callers",
      outcome: "no-match",
      files: [{ path: "src/server.ts", source: "import cors from 'cors'; cors({ origin: 'https://app.example.com', credentials: true });" }],
      focusPath: "src/server.ts", expectedCount: 0, public: true,
    },
    {
      id: "wildcard-origin-with-credentials",
      title: "Review a wildcard that blocks access to credentialed responses",
      outcome: "match",
      files: [{ path: "src/server.ts", source: "import cors from 'cors'; cors({ origin: '*', credentials: true });" }],
      focusPath: "src/server.ts", expectedCount: 1, public: true,
    },
  ],
} as const satisfies RuleDocumentation;

interface HeaderState {
  readonly values: Record<HeaderName, string | null | undefined>;
  origin: TSESTree.CallExpression | null;
}

export default createRule<Options, MessageIds>({
  name: "no-cors-wildcard-with-credentials",
  documentation: NO_CORS_WILDCARD_WITH_CREDENTIALS_DOCUMENTATION,
  meta: {
    type: "problem",
    docs: { description: NO_CORS_WILDCARD_WITH_CREDENTIALS_DOCUMENTATION.summary },
    schema: [],
    messages: {
      corsWildcardWithCredentials: "A wildcard CORS origin blocks browser access to credentialed responses. Review the intended contract: use a trusted explicit origin for credentialed callers, or omit the credentials opt-in for a credentialless endpoint.",
    },
  },
  defaultOptions: [],
  create(context) {
    const sourceCode = context.sourceCode;
    const importedCors = new Set<TSESLint.Scope.Variable>();
    const importedNamespaces = new Set<TSESLint.Scope.Variable>();
    const receiverProof = new Map<TSESLint.Scope.Variable | string, boolean>();

    function binding(node: TSESTree.Identifier): TSESLint.Scope.Variable | null {
      return ASTUtils.findVariable(sourceCode.getScope(node), node.name);
    }

    function officialCors(node: TSESTree.Node): boolean {
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

    function recordImports(node: TSESTree.Program): void {
      for (const statement of node.body) {
        if (statement.type === "ImportDeclaration" && statement.importKind !== "type") recordImport(statement);
      }
    }

    function recordImport(node: TSESTree.ImportDeclaration): void {
      for (const specifier of node.specifiers) {
        const role = importRole(specifier, node.source.value);
        if (role === null) continue;
        const variable = binding(specifier.local);
        if (variable === null || variable.references.some(reference => reference.isWrite())) continue;
        (role === "namespace" ? importedNamespaces : importedCors).add(variable);
      }
    }

    function inspectSequence(node: TSESTree.Program | TSESTree.BlockStatement): void {
      if (node.body.some(statement => CONTROL_STATEMENTS.has(statement.type))) return;
      const states = new Map<TSESLint.Scope.Variable | string, HeaderState>();
      for (const statement of node.body) {
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

    function recordHeaderDeclaration(node: TSESTree.VariableDeclaration, states: Map<TSESLint.Scope.Variable | string, HeaderState>): void {
      for (const declaration of node.declarations) {
        if (declaration.id.type === "Identifier" && declaration.init !== null && freshHeaders(declaration.init)) {
          const key = receiverKey(declaration.id);
          if (key !== null) states.set(key, { values: { [ACAO_HEADER]: null, [ACAC_HEADER]: null }, origin: null });
        } else if (declaration.id.type !== "Identifier" || (declaration.init !== null && unwrapExpression(declaration.init).type !== "Literal")) states.clear();
      }
    }

    function freshHeaders(node: TSESTree.Node): boolean {
      const value = unwrapExpression(node);
      if (value.type !== "NewExpression" || value.arguments.length !== 0) return false;
      const callee = unwrapExpression(value.callee);
      return callee.type === "Identifier" && callee.name === "Headers" && !binding(callee)?.defs.length;
    }

    function applyHeaderWrite(node: TSESTree.CallExpression, states: Map<TSESLint.Scope.Variable | string, HeaderState>): boolean {
      const callee = unwrapExpression(node.callee);
      if (node.optional || callee.type !== "MemberExpression" || callee.optional ||
        !HEADER_METHODS.has(ASTUtils.getPropertyName(callee) ?? "") || callee.object.type !== "Identifier") return false;
      const method = ASTUtils.getPropertyName(callee);
      const removal = method === "delete" || method === "removeHeader";
      if (node.arguments.length !== (removal ? 1 : 2)) return false;
      const name = literalString(node.arguments[0]);
      const value = removal ? null : headerValue(node.arguments[1]);
      if (name === null || (!removal && value === null)) return false;
      const key = receiverKey(callee.object);
      if (key === null) return false;
      let state = states.get(key);
      if (state === undefined) {
        state = { values: { [ACAO_HEADER]: undefined, [ACAC_HEADER]: undefined }, origin: null };
        states.set(key, state);
      }
      const header = name.toLowerCase();
      if (header !== ACAO_HEADER && header !== ACAC_HEADER) return true;
      state.values[header] = method === "append" ? appendValue(state.values[header], value) : value;
      if (header === ACAO_HEADER) state.origin = node;
      return true;
    }

    function receiverKey(node: TSESTree.Identifier): TSESLint.Scope.Variable | string | null {
      const variable = binding(node);
      const key = variable ?? node.name;
      const cached = receiverProof.get(key);
      if (cached !== undefined) return cached ? key : null;
      const references = variable?.references ?? sourceCode.scopeManager?.globalScope?.through.filter(reference => reference.identifier.name === node.name) ?? [];
      const unaliased = !variable?.defs.some(aliasDefinition) && references.every(headerReceiverReference);
      receiverProof.set(key, unaliased);
      return unaliased ? key : null;
    }

    return {
      Program(node): void {
        recordImports(node);
        inspectSequence(node);
      },
      BlockStatement(node): void {
        if (["FunctionDeclaration", "FunctionExpression", "ArrowFunctionExpression"].includes(node.parent.type)) inspectSequence(node);
      },
      CallExpression(node): void {
        if (node.optional || node.arguments.length !== 1 || !officialCors(node.callee)) return;
        const argument = node.arguments[0];
        const options = argument === undefined ? undefined : unwrapExpression(argument);
        if (options?.type !== "ObjectExpression") return;
        const properties = effectiveProperties(options);
        const origin = properties?.get("origin");
        const credentials = properties?.get("credentials");
        const value = credentials === undefined ? undefined : unwrapExpression(credentials.value);
        if (origin !== undefined && literalString(origin.value) === "*" && value?.type === "Literal" && value.value === true) {
          context.report({ node, messageId: "corsWildcardWithCredentials" });
        }
      },
      ObjectExpression(node): void {
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

function importRole(specifier: TSESTree.ImportDeclaration["specifiers"][number], module: string): "function" | "namespace" | null {
  if (module === "hono/cors" && specifier.type === "ImportNamespaceSpecifier") return "namespace";
  if (module === "cors" && specifier.type === "ImportDefaultSpecifier") return "function";
  if (specifier.type !== "ImportSpecifier" || specifier.importKind === "type") return null;
  const name = specifier.imported.type === "Identifier" ? specifier.imported.name : specifier.imported.value;
  return (module === "cors" && name === "default") || (module === "hono/cors" && name === "cors") ? "function" : null;
}

function aliasDefinition(definition: TSESLint.Scope.Definition): boolean {
  if (definition.type !== "Variable") return false;
  if (definition.node.id.type !== "Identifier") return true;
  const initializer = definition.node.init;
  return initializer !== null && ["Identifier", "MemberExpression", "AssignmentExpression", "ConditionalExpression", "LogicalExpression", "SequenceExpression"].includes(unwrapExpression(initializer).type);
}

function headerReceiverReference(reference: TSESLint.Scope.Reference): boolean {
  let typeName: TSESTree.Node = reference.identifier;
  while (typeName.parent.type === "TSQualifiedName") typeName = typeName.parent;
  if (reference.isValueReference === false || typeName.parent.type === "TSTypeQuery") return true;
  if (reference.isWrite()) return reference.init === true;
  const member = reference.identifier.parent;
  if (member.type !== "MemberExpression" || member.object !== reference.identifier || member.optional ||
    !HEADER_METHODS.has(ASTUtils.getPropertyName(member) ?? "")) return false;
  return member.parent.type === "CallExpression" && member.parent.callee === member && !member.parent.optional;
}

function appendValue(previous: string | null | undefined, value: string | null): string | null | undefined {
  if (previous === undefined) return undefined;
  return previous === null ? value : previous + ", " + value;
}

function literalString(node: TSESTree.Node | undefined): string | null {
  return staticString(node);
}

function headerValue(node: TSESTree.Node | undefined): string | null {
  const value = node === undefined ? undefined : unwrapExpression(node);
  const text = staticString(node);
  if (text === null && (value?.type !== "Literal" || !["boolean", "number"].includes(typeof value.value))) return null;
  return (text ?? String(value?.type === "Literal" ? value.value : "")).replace(/^[\t\n\r ]+|[\t\n\r ]+$/g, "");
}

function effectiveProperties(node: TSESTree.ObjectExpression): ReadonlyMap<string, TSESTree.Property> | null {
  const properties = new Map<string, TSESTree.Property>();
  for (const entry of node.properties) {
    const entries = propertyEntries(entry);
    if (entries === null) return null;
    for (const [key, property] of entries) properties.set(key, property);
  }
  return properties;
}

function propertyEntries(entry: TSESTree.ObjectLiteralElement): Iterable<readonly [string, TSESTree.Property]> | null {
  if (entry.type === "SpreadElement") {
    const value = unwrapExpression(entry.argument);
    return value.type === "ObjectExpression" ? effectiveProperties(value) : null;
  }
  if (entry.kind !== "init" || entry.method) return null;
  const key = entry.computed ? literalPropertyKey(entry.key) : ASTUtils.getPropertyName(entry);
  if (key === null) return null;
  if (key === "__proto__" && !entry.computed) {
    const value = unwrapExpression(entry.value);
    return value.type === "Literal" && value.value === null ? [] : null;
  }
  return [[key, entry]];
}

function literalPropertyKey(node: TSESTree.Node): string | null {
  const value = unwrapExpression(node);
  const literal = literalString(value);
  if (literal !== null) return literal;
  if (value.type !== "TemplateLiteral" || value.expressions.length !== 0) return null;
  return value.quasis[0]?.value.cooked ?? null;
}

function spreadOnly(node: TSESTree.ObjectExpression): boolean {
  let current: TSESTree.Node = outerExpression(node);
  while (current.parent !== undefined) {
    const parent: TSESTree.Node = current.parent;
    if (parent.type === "SpreadElement") return parent.parent.type === "ObjectExpression";
    if (!["Property", "ObjectExpression", "ConditionalExpression", "LogicalExpression", "SequenceExpression",
      "TSAsExpression", "TSSatisfiesExpression", "TSNonNullExpression", "TSTypeAssertion"].includes(parent.type)) return false;
    current = parent;
  }
  return false;
}
