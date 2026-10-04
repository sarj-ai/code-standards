// Adapted from Biome 2.5.12; original algorithms and MIT attribution are retained nearby.
// Native lexical bindings and test/catch contexts preserve the replaced stock policy.
import { findVariable } from "../eslint-utils/index.mjs";

const assertionQualifiers = new Set([
  "soft", "poll", "element", "assertions", "hasAssertions",
]);
const conditionalReasons = new Map([
  ["IfStatement", "if statement"],
  ["ConditionalExpression", "ternary expression"],
  ["SwitchCase", "switch case"],
  ["LogicalExpression", "logical expression"],
  ["CatchClause", "catch clause"],
]);
const frameworkModules = new Set(["vitest", "@jest/globals", "vite-plus/test", "@effect/vitest"]);
const frameworkNames = new Set(["expect", "it", "test"]);
const nonTestMembers = new Set(["describe", "step", "beforeEach", "afterEach", "beforeAll", "afterAll"]);
const functionTypes = new Set([
  "FunctionDeclaration", "FunctionExpression", "ArrowFunctionExpression",
]);

export default {
  meta: {
    type: "problem",
    schema: [],
    docs: {
      description: "Disallow conditional assertions without treating matcher factories as assertions.",
      url: "https://biomejs.dev/linter/rules/no-conditional-expect/javascript/",
    },
    messages: {
      conditionalExpect: "Unexpected conditional expect() call inside a {{reason}}.",
    },
  },
  create(context) {
    const source = context.sourceCode;
    const globals = /(?:^|[\\/])__tests__(?:[\\/]|$)|(?:test|spec)\.(?:js|jsx|ts|tsx|mjs|cjs|mts|cts)$/.test(context.physicalFilename);
    return {
      CallExpression(node) {
        if (!isExpectExpression(node.callee, source, globals)) return;
        if (node.parent?.type === "MemberExpression" && node.parent.object === node) return;
        const reason = conditionalContext(node, source, globals);
        if (reason !== null && inTestContext(node, source, globals, new Set())) {
          context.report({ node, messageId: "conditionalExpect", data: { reason } });
        }
      },
    };
  },
};

function isExpectExpression(node, source, globals) {
  if (frameworkBinding(node, source, globals) === "expect") return true;
  if (node.type === "CallExpression") return isExpectExpression(node.callee, source, globals);
  if (node.type !== "MemberExpression") return false;
  if (frameworkBinding(node.object, source, globals) === "expect") {
    return assertionQualifiers.has(propertyName(node));
  }
  return isExpectExpression(node.object, source, globals);
}

function conditionalContext(node, source, globals) {
  for (let ancestor = node.parent; ancestor; ancestor = ancestor.parent) {
    if (ancestor.type === "CallExpression" && isTestCall(ancestor, source, globals)) return null;
    const reason = conditionalReasons.get(ancestor.type);
    if (reason !== undefined) return reason;
    if (functionTypes.has(ancestor.type)) {
      const parent = ancestor.parent;
      if (parent?.type === "CallExpression" &&
        parent.arguments.includes(ancestor) &&
        parent.callee.type === "MemberExpression" &&
        propertyName(parent.callee) === "catch") return "promise catch callback";
      if (ancestor.type !== "ArrowFunctionExpression") return null;
      if (isRegisteredTestCallback(ancestor, source, globals)) return null;
    }
  }
  return null;
}

function isRegisteredTestCallback(node, source, globals) {
  const binding = functionBinding(node, source);
  if (binding === null || binding.references.some((reference) => !reference.init && reference.isWrite())) return false;
  return binding.references.some(({ identifier }) => {
    const call = identifier.parent;
    return call?.type === "CallExpression" &&
      (call.arguments[1] === identifier || call.arguments[2] === identifier) &&
      isTestCall(call, source, globals);
  });
}

function inTestContext(node, source, globals, visited) {
  if (visited.has(node)) return false;
  visited.add(node);
  for (let ancestor = node.parent; ancestor; ancestor = ancestor.parent) {
    if (ancestor.type === "CallExpression" && isTestCall(ancestor, source, globals)) return true;
    if (functionTypes.has(ancestor.type)) {
      const binding = functionBinding(ancestor, source);
      if (binding !== null) {
        return binding.references.some(({ identifier }) => {
          const call = identifier.parent;
          return call?.type === "CallExpression" &&
            (call.callee === identifier || call.arguments.includes(identifier)) &&
            (isTestCall(call, source, globals) || inTestContext(call, source, globals, visited));
        });
      }
    }
  }
  return false;
}

function isTestCall(node, source, globals) {
  let callee = node.callee;
  while (callee.type === "MemberExpression" || callee.type === "CallExpression" || callee.type === "TaggedTemplateExpression") {
    if (callee.type === "MemberExpression") {
      if (nonTestMembers.has(propertyName(callee))) return false;
      const binding = frameworkBinding(callee, source, globals);
      if (binding === "it" || binding === "test") return true;
      callee = callee.object;
    } else {
      callee = callee.type === "CallExpression" ? callee.callee : callee.tag;
    }
  }
  const binding = frameworkBinding(callee, source, globals);
  return binding === "it" || binding === "test";
}

function functionBinding(node, source) {
  if (node.type === "FunctionDeclaration" && node.id) {
    return source.getDeclaredVariables(node).find(({ name }) => name === node.id.name) ?? null;
  }
  const parent = node.parent;
  return parent?.type === "VariableDeclarator" && parent.id.type === "Identifier"
    ? source.getDeclaredVariables(parent).find(({ name }) => name === parent.id.name) ?? null
    : null;
}

function frameworkBinding(node, source, globals) {
  if (node.type === "MemberExpression" && node.object.type === "Identifier") {
    const binding = findVariable(source.getScope(node.object), node.object.name);
    const definition = importDefinition(binding);
    const member = propertyName(node);
    return definition?.node.type === "ImportNamespaceSpecifier" && frameworkNames.has(member)
      ? member
      : null;
  }
  if (node.type !== "Identifier") return null;
  const binding = findVariable(source.getScope(node), node.name);
  if (binding === null || binding.defs.length === 0) {
    return globals && frameworkNames.has(node.name) && !binding?.references.some((reference) => reference.isWrite())
      ? node.name
      : null;
  }
  const definition = importDefinition(binding);
  if (definition?.node.type !== "ImportSpecifier" || definition.node.importKind === "type") return null;
  const imported = definition.node.imported;
  const name = imported.type === "Identifier" ? imported.name : imported.value;
  return frameworkNames.has(name) ? name : null;
}

function importDefinition(binding) {
  if (binding?.defs.length !== 1) return null;
  const definition = binding.defs[0];
  return definition.type === "ImportBinding" &&
    definition.parent.type === "ImportDeclaration" &&
    definition.parent.importKind !== "type" &&
    frameworkModules.has(definition.parent.source.value)
    ? definition
    : null;
}

function propertyName(node) {
  return node.computed
    ? node.property.type === "Literal" ? node.property.value : null
    : node.property.type === "Identifier" ? node.property.name : null;
}
