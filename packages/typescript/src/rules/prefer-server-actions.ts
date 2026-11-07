/**
 * @fileoverview prefer-server-actions — an internal `/api/*` mutation hand-rolls the transport, types and error path a Server Action gets from the framework.
 *
 * Port of the 18.x `prefer-server-actions` rule. The rule is untyped, so
 * the port covers all of it. The original's per-file directive and import
 * checks run in `before()`; a non-React framework import, which made every
 * `CallExpression` visit return early, skips the file there.
 */

import { defineRule, type Context, type ESTree, type Node, type Scope, type TsDefinition, type TsVariable } from "../types.js";
import { unwrapExpression } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { importSpecifierName } from "../utils/import-specifier-name.js";
import { findVariable, getPropertyName } from "../utils/static-string.js";
import { isValidBasePath, NON_REACT_FRAMEWORK_RE } from "./no-raw-fetch-outside-clients.js";

const NAME = "prefer-server-actions";

interface RuleOptions {
  readonly basePath?: string;
}

const MUTATION_METHODS: ReadonlySet<string> = new Set(["POST", "PUT", "DELETE", "PATCH"]);
const AXIOS_MUTATION_METHODS: ReadonlySet<string> = new Set(["post", "put", "delete", "patch"]);

const SKIP_FILE_REGEX =
  /(?:\.test\.[jt]sx?$|\.spec\.[jt]sx?$|-(?:test|spec)\.[jt]sx?$|\/tests?\/|\/__tests__\/|\/__testfixtures__\/|\/scripts?\/|(?:^|\/)app(?:\/.*)?\/route\.[jt]sx?$|(?:^|\/)middleware\.[jt]sx?$|\/pages\/api\/)/;

const LOCAL_AXIOS_FORBIDDEN_OPTIONS: ReadonlySet<string> = new Set(["baseURL", "adapter"]);

type Ctx = Readonly<Context>;

function getScope(context: Ctx, node: Node): Scope {
  return context.sourceCode.getScope(node);
}

function resolvesToGlobalFetch(
  context: Ctx,
  identifier: { readonly name: string } & Node,
): boolean {
  const variable = findVariable(getScope(context, identifier), identifier.name);
  return variable === null || variable.defs.length === 0;
}

function resolveNode(
  node: Node | null | undefined,
  context: Ctx,
): Node | null {
  if (node === null || node === undefined) return null;
  node = unwrapExpression(node);
  if (node.type !== "Identifier") return node;

  const variable = findVariable(getScope(context, node), node.name);
  const definition = variable?.defs.length === 1 ? variable.defs[0] : undefined;
  if (definition?.type !== "Variable" || (definition.parent as ESTree.VariableDeclaration).kind !== "const") return node;
  const init = (definition.node as ESTree.VariableDeclarator).init;
  if (init === null || variable?.references.some((reference) => reference.isWrite() && reference.init !== true)) return node;
  if (init.type === "ObjectExpression" && variable?.references.some((reference) => reference.identifier !== node && reference.init !== true)) return node;
  return init;
}

/** An unreassigned `axios` default import, or a `const` from `<axios client>.create(<local options>)`, used only for calls. */
function isAxiosClient(node: Node, context: Ctx, seen = new Set<Node>()): boolean {
  if (node.type !== "Identifier" || seen.has(node)) return false;
  seen.add(node);
  const variable = findVariable(getScope(context, node), node.name);
  const definition = variable?.defs.length === 1 ? variable.defs[0] : undefined;
  if (variable === null || definition === undefined || !isOnlyCalled(variable)) return false;
  if (definition.type === "ImportBinding") return isAxiosDefaultImport(definition);
  if (definition.type !== "Variable" || (definition.parent as ESTree.VariableDeclaration).kind !== "const") return false;
  const init = (definition.node as ESTree.VariableDeclarator).init;
  return init?.type === "CallExpression" && isLocalAxiosCreate(init, context, seen);
}

/** `<axios client>.create()` or `.create(options)` without a base URL or adapter. */
function isLocalAxiosCreate(call: ESTree.CallExpression, context: Ctx, seen: Set<Node>): boolean {
  const { callee } = call;
  return call.arguments.length <= 1 && hasLocalAxiosOptions(call.arguments[0], context) &&
    callee.type === "MemberExpression" && !callee.computed && callee.property.type === "Identifier" &&
    callee.property.name === "create" && isAxiosClient(callee.object, context, seen);
}

/** Never reassigned, and every other use calls it (`client()`) or one of its methods (`client.post()`). */
function isOnlyCalled(variable: TsVariable): boolean {
  return variable.references.every((reference) => {
    if (reference.init === true) return true;
    if (reference.isWrite()) return false;
    const identifier = reference.identifier;
    const parent = identifier.parent;
    if (parent.type === "CallExpression" && parent.callee === identifier) return true;
    return parent.type === "MemberExpression" && parent.object === identifier && !parent.computed &&
      parent.parent.type === "CallExpression" && parent.parent.callee === parent;
  });
}

function isAxiosDefaultImport(definition: TsDefinition): boolean {
  const declaration = definition.parent as Node;
  const specifier = definition.node;
  if (declaration.type !== "ImportDeclaration" || declaration.source.value !== "axios" || declaration.importKind === "type") return false;
  if (specifier.type === "ImportDefaultSpecifier") return true;
  return specifier.type === "ImportSpecifier" && specifier.importKind !== "type" && importSpecifierName(specifier) === "default";
}

function hasLocalAxiosOptions(node: Node | undefined, context: Ctx): boolean {
  if (node === undefined) return true;
  const options = resolveNode(node, context);
  return options?.type === "ObjectExpression" && options.properties.every((property) =>
    property.type === "Property" && !property.computed && property.kind === "init" &&
    !LOCAL_AXIOS_FORBIDDEN_OPTIONS.has(property.key.type === "Identifier" ? property.key.name : property.key.type === "Literal" ? String(property.key.value) : "baseURL"),
  );
}

function isApiUrl(
  node: Node | null | undefined,
  context: Ctx,
  apiPrefixes: readonly string[],
): boolean {
  const resolved = resolveNode(node, context);
  if (!resolved) return false;

  if (resolved.type === "Literal" && typeof resolved.value === "string") {
    return apiPrefixes.some(
      (prefix) => resolved.value === prefix.slice(0, -1) || resolved.value.startsWith(prefix),
    );
  }
  if (resolved.type === "TemplateLiteral") {
    const firstQuasi = resolved.quasis[0];
    const cooked = firstQuasi?.value.cooked;
    return typeof cooked === "string" && apiPrefixes.some(
      (prefix) => cooked === prefix.slice(0, -1) || cooked.startsWith(prefix),
    );
  }
  if (resolved.type === "BinaryExpression" && resolved.operator === "+") {
    return isApiUrl(resolved.left, context, apiPrefixes);
  }
  return false;
}

function isMutationMethod(
  node: Node | null | undefined,
  context: Ctx,
): boolean {
  const resolved = resolveNode(node, context);
  if (!resolved) return false;

  if (resolved.type === "Literal" && typeof resolved.value === "string") {
    return MUTATION_METHODS.has(resolved.value.toUpperCase());
  }

  if (
    resolved.type === "TemplateLiteral" &&
    resolved.expressions.length === 0
  ) {
    const val = resolved.quasis.map((q) => q.value.cooked).join("");
    return MUTATION_METHODS.has(val.toUpperCase());
  }

  if (resolved.type === "ConditionalExpression") {
    return (
      isMutationMethod(resolved.consequent, context) ||
      isMutationMethod(resolved.alternate, context)
    );
  }

  if (resolved.type === "LogicalExpression" && resolved.operator === "||") {
    return (
      isMutationMethod(resolved.left, context) ||
      isMutationMethod(resolved.right, context)
    );
  }

  return false;
}

function isFunctionArgument(
  node: ESTree.Argument,
  context: Ctx,
): boolean {
  const resolved = resolveNode(node, context);
  if (
    resolved?.type === "ArrowFunctionExpression" ||
    resolved?.type === "FunctionExpression"
  ) {
    return true;
  }
  if (node.type !== "Identifier") return false;

  let scope: Scope | null = getScope(context, node);
  while (scope) {
    const variable = scope.set.get(node.name);
    if (
      variable?.defs.some((definition) => definition.type === "FunctionName")
    ) {
      return true;
    }
    scope = scope.upper;
  }
  return false;
}

function getPropertyNode(
  objNode: Node | null | undefined,
  propName: string,
): Node | null {
  if (!objNode || objNode.type !== "ObjectExpression") return null;
  if (objNode.properties.some((property) => property.type === "SpreadElement" || getPropertyName(property) === null)) return null;
  for (const prop of [...objNode.properties].reverse()) {
    if (prop.type !== "Property") continue;
    const keyName = getPropertyName(prop);
    if (keyName === propName) {
      // Skip destructuring patterns — they're not valid as config values.
      const valueType: string = prop.value.type;
      if (
        valueType === "AssignmentPattern" ||
        valueType === "ArrayPattern" ||
        valueType === "ObjectPattern"
      ) {
        return null;
      }
      return prop.value;
    }
  }
  return null;
}

export default defineRule({
  meta: {
    defaultOptions: [{}],
    type: "suggestion",
    docs: {
      description: "Prefer Next.js Server Actions over same-origin API mutations.",
      url: docsUrl(NAME),
    },
    schema: [
      {
        type: "object",
        additionalProperties: false,
        properties: {
          basePath: { description: "Static application URL base path without query strings, fragments or parent segments.",
            type: "string",
            pattern: "^/(?!$)(?!.*[?#])(?!(?:.*/)?\\.\\.?(?:/|$))(?:[^/]+/)*[^/]+$",
          },
        },
      },
    ],
    messages: {
      preferServerAction:
        "This client mutation targets a same-origin API route. Consider a Server Action to remove the hand-written API wrapper; retain authorization and validation, since the call still crosses a network boundary.",
    },
  },
  createOnce(context) {
    let apiPrefixes: string[] = [];

    function isMutation(node: ESTree.CallExpression): boolean {
      const callee = unwrapExpression(node.callee);
      if (callee.type === "Identifier") {
        if (callee.name === "fetch" && resolvesToGlobalFetch(context, callee)) return isFetchMutation(node);
        // Check the arguments before resolving the callee's provenance.
        return isAxiosConfigMutation(node) && isAxiosClient(callee, context);
      }
      if (callee.type !== "MemberExpression" || callee.computed || callee.property.type !== "Identifier") return false;
      // Axios method calls require import or instance provenance.
      const methodName = callee.property.name.toLowerCase();
      return AXIOS_MUTATION_METHODS.has(methodName) && isAxiosClient(callee.object, context) && isAxiosMethodMutation(node, methodName);
    }

    /** `fetch('/api/orders', { method: 'POST' })`. */
    function isFetchMutation(node: ESTree.CallExpression): boolean {
      const [urlArg, initArg] = node.arguments;
      if (urlArg === undefined || urlArg.type === "SpreadElement" || !isApiUrl(urlArg, context, apiPrefixes)) return false;
      if (initArg === undefined || initArg.type === "SpreadElement") return false;
      const methodNode = getPropertyNode(resolveNode(initArg, context), "method");
      return methodNode !== null && isMutationMethod(methodNode, context);
    }

    /** `client.post('/api/orders', body)`, without a callback argument; `methodName` is a lowercase axios mutation method. */
    function isAxiosMethodMutation(node: ESTree.CallExpression, methodName: string): boolean {
      const config = node.arguments[methodName === "delete" ? 1 : 2];
      if (!hasLocalAxiosOptions(config, context)) return false;
      const urlArg = node.arguments[0];
      return urlArg !== undefined && urlArg.type !== "SpreadElement" &&
        !node.arguments.some((arg) => arg.type !== "SpreadElement" && isFunctionArgument(arg, context)) &&
        isApiUrl(urlArg, context, apiPrefixes);
    }

    /** `client({ method: 'post', url: '/api/orders' })`. */
    function isAxiosConfigMutation(node: ESTree.CallExpression): boolean {
      const firstArg = node.arguments[0];
      if (firstArg === undefined || firstArg.type === "SpreadElement") return false;
      const configArg = resolveNode(firstArg, context);
      if (configArg?.type !== "ObjectExpression" || !hasLocalAxiosOptions(firstArg, context)) return false;
      const urlNode = getPropertyNode(configArg, "url");
      const methodNode = getPropertyNode(configArg, "method");
      return urlNode !== null && isApiUrl(urlNode, context, apiPrefixes) && methodNode !== null && isMutationMethod(methodNode, context);
    }

    return {
      before() {
        const filename = context.filename.replaceAll("\\", "/");
        if (SKIP_FILE_REGEX.test(filename)) return false;
        const body = context.sourceCode.ast.body;
        const isNonReactFramework = body.some(
          (node) =>
            node.type === "ImportDeclaration" &&
            typeof node.source.value === "string" &&
            NON_REACT_FRAMEWORK_RE.test(node.source.value),
        );
        const hasUseClientDirective = body.some(
          (node) =>
            node.type === "ExpressionStatement" &&
            node.directive === "use client",
        );
        const hasUseServerDirective = body.some(
          (node) =>
            node.type === "ExpressionStatement" &&
            node.directive === "use server",
        );
        const importsServerOnly = body.some(
          (node) =>
            node.type === "ImportDeclaration" &&
            typeof node.source.value === "string" &&
            (node.source.value === "server-only" || node.source.value === "next/server"),
        );
        if (!hasUseClientDirective || hasUseServerDirective || importsServerOnly || isNonReactFramework) return false;
        const options = context.options[0] as RuleOptions | undefined;
        apiPrefixes = ["/api/"];
        if (options?.basePath !== undefined && isValidBasePath(options.basePath)) {
          apiPrefixes.push(`${options.basePath}/api/`);
        }
        return undefined;
      },
      CallExpression(node: ESTree.CallExpression) {
        if (isMutation(node)) context.report({ node, messageId: "preferServerAction" });
      },
    };
  },
});
