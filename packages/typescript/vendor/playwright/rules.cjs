"use strict";
// src/utils/parseFnCall.ts
var testHooks = /* @__PURE__ */ new Set(["afterAll", "afterEach", "beforeAll", "beforeEach"]);
var VALID_CHAINS = /* @__PURE__ */ new Set([
  // Hooks
  "afterAll",
  "afterEach",
  "beforeAll",
  "beforeEach",
  "test.afterAll",
  "test.afterEach",
  "test.beforeAll",
  "test.beforeEach",
  // Describe
  "describe",
  "describe.only",
  "describe.skip",
  "describe.fixme",
  "describe.fixme.only",
  "describe.configure",
  "describe.serial",
  "describe.serial.only",
  "describe.serial.skip",
  "describe.serial.fixme",
  "describe.serial.fixme.only",
  "describe.parallel",
  "describe.parallel.only",
  "describe.parallel.skip",
  "describe.parallel.fixme",
  "describe.parallel.fixme.only",
  "test.describe",
  "test.describe.only",
  "test.describe.skip",
  "test.describe.fixme",
  "test.describe.fixme.only",
  "test.describe.configure",
  "test.describe.serial",
  "test.describe.serial.only",
  "test.describe.serial.skip",
  "test.describe.serial.fixme",
  "test.describe.serial.fixme.only",
  "test.describe.parallel",
  "test.describe.parallel.only",
  "test.describe.parallel.skip",
  "test.describe.parallel.fixme",
  "test.describe.parallel.fixme.only",
  // Test
  "test",
  "test.fail",
  "test.fail.only",
  "test.fixme",
  "test.only",
  "test.skip",
  "test.step",
  "test.step.skip",
  "test.slow",
  "test.use"
]);
var joinChains = (a, b) => a && b ? [...a, ...b] : null;
var isSupportedAccessor = (node, value) => isIdentifier(node, value) || isStringNode(node, value);
var Chain = class {
  #nodes = null;
  #leaves = /* @__PURE__ */ new WeakSet();
  constructor(node) {
    this.#nodes = this.#buildChain(node);
  }
  isLeaf(node) {
    return this.#leaves.has(node);
  }
  get nodes() {
    return this.#nodes;
  }
  #buildChain(node, insideCall = false) {
    if (isSupportedAccessor(node)) {
      if (insideCall) {
        this.#leaves.add(node);
      }
      return [node];
    }
    switch (node.type) {
      case "TaggedTemplateExpression":
        return this.#buildChain(node.tag);
      case "MemberExpression":
        return joinChains(
          this.#buildChain(node.object),
          this.#buildChain(node.property, insideCall)
        );
      case "CallExpression":
        return this.#buildChain(node.callee, true);
      default:
        return null;
    }
  }
};
function resolvePossibleAliasedGlobal(context, name) {
  const settings = context.settings;
  const globalAliases = settings?.playwright?.globalAliases ?? {};
  const alias = Object.entries(globalAliases).find(([, aliases]) => aliases.includes(name));
  return alias?.[0] ?? null;
}
function resolveImportAlias(context, node) {
  if (node.type !== "Identifier") {
    return null;
  }
  const scope = context.sourceCode.getScope(node);
  const ref = scope.references.find((r) => r.identifier === node);
  for (const def of ref?.resolved?.defs ?? []) {
    if (def.type === "ImportBinding" && def.node.type === "ImportSpecifier") {
      const imported = getStringValue(def.node.imported);
      if (imported !== node.name) {
        return imported;
      }
    }
  }
  return null;
}
var resolveToPlaywrightFn = (context, accessor) => {
  const ident = getStringValue(accessor);
  const resolved = /(^expect|Expect)$/.test(ident) ? "expect" : ident;
  if (resolved === "test" || resolved === "expect") {
    return { original: null, local: resolved };
  }
  return {
    original: resolvePossibleAliasedGlobal(context, resolved) ?? resolveImportAlias(context, accessor),
    local: resolved
  };
};
function determinePlaywrightFnGroup(name) {
  if (name === "step") {
    return "step";
  }
  if (name === "expect") {
    return "expect";
  }
  if (name === "describe") {
    return "describe";
  }
  if (name === "test") {
    return "test";
  }
  if (testHooks.has(name)) {
    return "hook";
  }
  return "unknown";
}
var modifiers = /* @__PURE__ */ new Set(["not", "resolves", "rejects"]);
var findModifiersAndMatcher = (chain, members, stage) => {
  const modifiers2 = [];
  for (const member of members) {
    const name = getStringValue(member);
    if (name === "soft" || name === "poll") {
      if (modifiers2.length > 0) {
        return "modifier-unknown";
      }
    } else if (name === "resolves" || name === "rejects") {
      const lastModifier = getStringValue(modifiers2.at(-1));
      if (lastModifier && lastModifier !== "soft" && lastModifier !== "poll") {
        return "modifier-unknown";
      }
    } else if (name !== "not") {
      if (stage === "modifiers") {
        return null;
      }
      if (member.parent?.type === "MemberExpression" && member.parent.parent?.type === "CallExpression") {
        return {
          matcher: member,
          matcherArgs: member.parent.parent.arguments,
          matcherName: name,
          modifiers: modifiers2
        };
      }
      return "modifier-unknown";
    }
    if (chain.isLeaf(member)) {
      stage = "matchers";
    }
    modifiers2.push(member);
  }
  return "matcher-not-found";
};
function getExpectArguments(call) {
  return findParent(call.head.node, "CallExpression")?.arguments ?? [];
}
var parseExpectCall = (chain, call, stage) => {
  const modifiersAndMatcher = findModifiersAndMatcher(chain, call.members, stage);
  if (!modifiersAndMatcher) {
    return null;
  }
  if (typeof modifiersAndMatcher === "string") {
    return modifiersAndMatcher;
  }
  return {
    ...call,
    args: getExpectArguments(call),
    group: "expect",
    type: "expect",
    ...modifiersAndMatcher
  };
};
var findTopMostCallExpression = (node) => {
  let top = node;
  let parent = node.parent;
  let child = node;
  while (parent) {
    if (parent.type === "CallExpression" && parent.callee === child) {
      top = parent;
      parent = parent.parent;
      continue;
    }
    if (parent.type !== "MemberExpression") {
      break;
    }
    child = parent;
    parent = parent.parent;
  }
  return top;
};
function isTestExtendCall(context, node) {
  if (node.type !== "CallExpression" || node.callee.type !== "MemberExpression" || !isPropertyAccessor(node.callee, "extend")) {
    return false;
  }
  const object = node.callee.object;
  if (object.type === "Identifier") {
    const resolved = resolveToPlaywrightFn(context, object);
    if ((resolved?.original ?? resolved?.local) === "test") {
      return true;
    }
    const dereferenced = dereference(context, object);
    if (dereferenced) {
      return isTestExtendCall(context, dereferenced);
    }
  }
  return false;
}
function parse(context, node) {
  const chain = new Chain(node);
  if (!chain.nodes?.length) {
    return null;
  }
  const [first, ...rest] = chain.nodes;
  let resolved = resolveToPlaywrightFn(context, first);
  if (!resolved) {
    return null;
  }
  let name = resolved.original ?? resolved.local;
  const links = [name, ...rest.map((link) => getStringValue(link))];
  if (determinePlaywrightFnGroup(name) === "unknown") {
    const dereferenced = dereference(context, first);
    if (dereferenced && isTestExtendCall(context, dereferenced)) {
      name = "test";
      links[0] = "test";
      resolved = { local: resolved.local, original: "test" };
    }
  }
  if (name === "test" && links.length > 1) {
    const nextLinkName = links[1];
    const nextLinkGroup = determinePlaywrightFnGroup(nextLinkName);
    if (nextLinkGroup !== "unknown") {
      name = nextLinkName;
    }
  }
  if (name !== "expect" && !VALID_CHAINS.has(links.join("."))) {
    return null;
  }
  const parsedFnCall = {
    head: { ...resolved, node: first },
    // every member node must have a member expression as their parent
    // in order to be part of the call chain we're parsing
    members: rest,
    name
  };
  const group = determinePlaywrightFnGroup(name);
  if (group === "expect") {
    let stage = chain.isLeaf(parsedFnCall.head.node) ? "matchers" : "modifiers";
    if (isIdentifier(rest[0], "expect")) {
      stage = chain.isLeaf(rest[0]) ? "matchers" : "modifiers";
      parsedFnCall.members.shift();
    }
    const result = parseExpectCall(chain, parsedFnCall, stage);
    if (!result) {
      return null;
    }
    if (typeof result === "string" && findTopMostCallExpression(node) !== node) {
      return null;
    }
    if (result === "matcher-not-found") {
      if (node.parent?.type === "MemberExpression") {
        return "matcher-not-called";
      }
    }
    return result;
  }
  if (chain.nodes.slice(0, chain.nodes.length - 1).some((n) => n.parent?.type !== "MemberExpression")) {
    return null;
  }
  const parent = node.parent;
  if (parent?.type === "CallExpression" || parent?.type === "MemberExpression") {
    return null;
  }
  let type = group;
  if (name === "describe") {
    if (!isFunction(node.arguments.at(-1))) {
      type = "config";
    }
  } else if (name === "test") {
    if (node.arguments.length < 2 || !isFunction(node.arguments.at(-1))) {
      type = "config";
    }
  }
  return {
    ...parsedFnCall,
    group,
    type
  };
}
var cache = /* @__PURE__ */ new WeakMap();
function parseFnCallWithReason(context, node) {
  if (cache.has(node)) {
    return cache.get(node);
  }
  const call = parse(context, node);
  cache.set(node, call);
  return call;
}
function parseFnCall(context, node) {
  const call = parseFnCallWithReason(context, node);
  return typeof call === "string" ? null : call;
}
var isTypeOfFnCall = (context, node, types) => {
  const call = parseFnCall(context, node);
  return call !== null && types.includes(call.type);
};

// src/utils/ast.ts
function getStringValue(node) {
  if (!node) {
    return "";
  }
  return node.type === "Identifier" ? node.name : node.type === "TemplateLiteral" ? node.quasis[0].value.raw : node.type === "Literal" && typeof node.value === "string" ? node.value : "";
}
function getRawValue(node) {
  return node.type === "Literal" ? node.raw : void 0;
}
function isIdentifier(node, name) {
  return node?.type === "Identifier" && (!name || (typeof name === "string" ? node.name === name : name.test(node.name)));
}
function isLiteral(node, type, value) {
  return node.type === "Literal" && (value === void 0 ? typeof node.value === type : node.value === value);
}
var isTemplateLiteral = (node, value) => node.type === "TemplateLiteral" && node.quasis.length === 1 && // bail out if not simple
(value === void 0 || node.quasis[0].value.raw === value);
function isStringLiteral(node, value) {
  return isLiteral(node, "string", value);
}
function isBooleanLiteral(node, value) {
  return isLiteral(node, "boolean", value);
}
function isStringNode(node, value) {
  return node && (isStringLiteral(node, value) || isTemplateLiteral(node, value));
}
function isPropertyAccessor(node, name) {
  const value = getStringValue(node.property);
  return typeof name === "string" ? value === name : name.test(value);
}
function findParent(node, type) {
  const parent = node.parent;
  if (!parent) {
    return;
  }
  return parent.type === type ? parent : findParent(parent, type);
}
function dig(node, identifier) {
  return node.type === "MemberExpression" ? dig(node.property, identifier) : node.type === "CallExpression" ? dig(node.callee, identifier) : node.type === "Identifier" ? isIdentifier(node, identifier) : false;
}
var pageFrameFullPattern = /(^(page|frame)|(Page|Frame)$)/;
var pageFramePrefixPattern = /^(page|frame)/;
function isPageMethod(node, name) {
  if (node.callee.type !== "MemberExpression") {
    return false;
  }
  if (!isPropertyAccessor(node.callee, name)) {
    return false;
  }
  const obj = node.callee.object;
  if (obj.type === "MemberExpression") {
    const pattern = obj.object.type === "ThisExpression" ? pageFrameFullPattern : pageFramePrefixPattern;
    return isIdentifier(obj.property, pattern);
  }
  return dig(obj, pageFrameFullPattern);
}
function isFunction(node) {
  return node?.type === "ArrowFunctionExpression" || node?.type === "FunctionExpression";
}
var equalityMatchers = /* @__PURE__ */ new Set(["toBe", "toEqual", "toStrictEqual"]);
var joinNames = (a, b) => a && b ? `${a}.${b}` : null;
function getNodeName(node) {
  if (isSupportedAccessor(node)) {
    return getStringValue(node);
  }
  switch (node.type) {
    case "TaggedTemplateExpression":
      return getNodeName(node.tag);
    case "MemberExpression":
      return joinNames(getNodeName(node.object), getNodeName(node.property));
    case "NewExpression":
    case "CallExpression":
      return getNodeName(node.callee);
  }
  return null;
}
var isVariableDeclarator = (node) => node?.type === "VariableDeclarator";
var isAssignmentExpression = (node) => node?.type === "AssignmentExpression";
function isNodeLastAssignment(node, assignment) {
  if (node.range && assignment.range && node.range[0] < assignment.range[1]) {
    return false;
  }
  return assignment.left.type === "Identifier" && assignment.left.name === node.name;
}
function dereference(context, node) {
  if (node?.type !== "Identifier") {
    return node;
  }
  const scope = context.sourceCode.getScope(node);
  const parents = scope.references.map((ref) => ref.identifier).map((ident) => ident.parent);
  const decl = parents.filter(isVariableDeclarator).find((p) => p.id.type === "Identifier" && p.id.name === node.name);
  const expr = parents.filter(isAssignmentExpression).reverse().find((assignment) => isNodeLastAssignment(node, assignment));
  return expr?.right ?? decl?.init;
}
var getActualLastToken = (sourceCode, node) => {
  const semiToken = sourceCode.getLastToken(node);
  const prevToken = sourceCode.getTokenBefore(semiToken);
  const nextToken = sourceCode.getTokenAfter(semiToken);
  const isSemicolonLessStyle = !!prevToken && !!nextToken && prevToken.range[0] >= node.range[0] && semiToken.type === "Punctuator" && semiToken.value === ";" && semiToken.loc.start.line !== prevToken.loc.end.line && semiToken.loc.end.line === nextToken.loc.start.line;
  return isSemicolonLessStyle ? prevToken : semiToken;
};
var getPaddingLineSequences = (prevNode, nextNode, sourceCode) => {
  const pairs = [];
  let prevToken = getActualLastToken(sourceCode, prevNode);
  if (nextNode.loc.start.line - prevToken.loc.end.line >= 2) {
    do {
      const token = sourceCode.getTokenAfter(prevToken, {
        includeComments: true
      });
      if (token.loc.start.line - prevToken.loc.end.line >= 2) {
        pairs.push([prevToken, token]);
      }
      prevToken = token;
    } while (prevToken.range[0] < nextNode.range[0]);
  }
  return pairs;
};
var areTokensOnSameLine = (left, right) => left.loc.end.line === right.loc.start.line;
var isPromiseAccessor = (node) => {
  return node.type === "MemberExpression" && isIdentifier(node.property, /^(then|catch|finally)$/);
};

// src/utils/createRule.ts
function interpolate(str, data) {
  return str.replace(/{{\s*(\w+)\s*}}/g, (_, key) => data?.[key] ?? "");
}
function createRule(rule) {
  return {
    create(context) {
      const messages = context.settings?.playwright?.messages;
      if (!messages) {
        return rule.create(context);
      }
      const report = (options) => {
        if (messages && "messageId" in options) {
          const { data, messageId: messageId2, ...rest } = options;
          const message = messages?.[messageId2];
          return context.report(
            message ? {
              ...rest,
              message: interpolate(message, data)
            } : options
          );
        }
        return context.report(options);
      };
      const ruleContext = Object.freeze({
        ...context,
        cwd: context.cwd,
        filename: context.filename,
        id: context.id,
        languageOptions: context.languageOptions,
        options: context.options,
        // @ts-expect-error - Legacy context property
        parserOptions: context.parserOptions,
        // @ts-expect-error - Legacy context property
        parserPath: context.parserPath,
        physicalFilename: context.physicalFilename,
        report,
        settings: context.settings,
        sourceCode: context.sourceCode
      });
      return rule.create(ruleContext);
    },
    meta: rule.meta
  };
}

// src/utils/scope.ts
function createScopeInfo() {
  let scope = null;
  return {
    enter() {
      scope = { prevNode: null, upper: scope };
    },
    exit() {
      scope = scope.upper;
    },
    get prevNode() {
      return scope.prevNode;
    },
    set prevNode(node) {
      scope.prevNode = node;
    }
  };
}

// src/rules/missing-playwright-await.ts
var validTypes = /* @__PURE__ */ new Set(["AwaitExpression", "ReturnStatement", "ArrowFunctionExpression"]);
function isArrayLike(node) {
  return node.type === "ArrayExpression" || node.type === "NewExpression" && isIdentifier(node.callee, "Array") || node.type === "CallExpression" && node.callee.type === "MemberExpression" && isIdentifier(node.callee.object, "Array");
}
var waitForMethods = [
  "waitForConsoleMessage",
  "waitForDownload",
  "waitForEvent",
  "waitForFileChooser",
  "waitForFunction",
  "waitForPopup",
  "waitForRequest",
  "waitForResponse",
  "waitForWebSocket"
];
var waitForMethodsRegex = new RegExp(`^(${waitForMethods.join("|")})$`);
var pageMethods = /* @__PURE__ */ new Set([
  "addInitScript",
  "addScriptTag",
  "addStyleTag",
  "bringToFront",
  "check",
  "click",
  "close",
  "dblclick",
  "dispatchEvent",
  "dragAndDrop",
  "emulateMedia",
  "evaluate",
  "evaluateHandle",
  "exposeBinding",
  "exposeFunction",
  "fill",
  "focus",
  "getAttribute",
  "goBack",
  "goForward",
  "goto",
  "hover",
  "innerHTML",
  "innerText",
  "inputValue",
  "isChecked",
  "isDisabled",
  "isEditable",
  "isEnabled",
  "isHidden",
  "isVisible",
  "pdf",
  "press",
  "reload",
  "route",
  "routeFromHAR",
  "screenshot",
  "selectOption",
  "setBypassCSP",
  "setContent",
  "setChecked",
  "setExtraHTTPHeaders",
  "setInputFiles",
  "setViewportSize",
  "tap",
  "textContent",
  "title",
  "type",
  "uncheck",
  "unroute",
  "unrouteAll",
  "waitForLoadState",
  "waitForTimeout",
  "waitForURL"
]);
var locatorMethods = /* @__PURE__ */ new Set([
  "all",
  "allInnerTexts",
  "allTextContents",
  "blur",
  "boundingBox",
  "check",
  "clear",
  "click",
  "count",
  "dblclick",
  "dispatchEvent",
  "dragTo",
  "evaluate",
  "evaluateAll",
  "evaluateHandle",
  "fill",
  "focus",
  "getAttribute",
  "hover",
  "innerHTML",
  "innerText",
  "inputValue",
  "isChecked",
  "isDisabled",
  "isEditable",
  "isEnabled",
  "isHidden",
  "isVisible",
  "press",
  "pressSequentially",
  "screenshot",
  "scrollIntoViewIfNeeded",
  "selectOption",
  "selectText",
  "setChecked",
  "setInputFiles",
  "tap",
  "textContent",
  "type",
  "uncheck",
  "waitFor"
]);
var expectPlaywrightMatchers = [
  "toBeChecked",
  "toBeDisabled",
  "toBeEnabled",
  "toEqualText",
  // deprecated
  "toEqualUrl",
  "toEqualValue",
  "toHaveFocus",
  "toHaveSelector",
  "toHaveSelectorCount",
  "toHaveText",
  // deprecated
  "toMatchAttribute",
  "toMatchComputedStyle",
  "toMatchText",
  "toMatchTitle",
  "toMatchURL",
  "toMatchValue",
  "toPass"
];
var playwrightTestMatchers = [
  "toBeAttached",
  "toBeChecked",
  "toBeDisabled",
  "toBeEditable",
  "toBeEmpty",
  "toBeEnabled",
  "toBeFocused",
  "toBeHidden",
  "toBeInViewport",
  "toBeOK",
  "toBeVisible",
  "toContainText",
  "toHaveAccessibleErrorMessage",
  "toHaveAttribute",
  "toHaveCSS",
  "toHaveClass",
  "toHaveCount",
  "toHaveId",
  "toHaveJSProperty",
  "toHaveScreenshot",
  "toHaveText",
  "toHaveTitle",
  "toHaveURL",
  "toHaveValue",
  "toHaveValues",
  "toContainClass"
];
function getReportNode(node) {
  const parent = node.parent;
  return parent?.type === "MemberExpression" ? parent : node;
}
function getCallType(call, awaitableMatchers) {
  if (call.type === "step") {
    return {
      data: { name: "test.step" },
      messageId: "missingAwait",
      node: call.head.node
    };
  }
  if (call.type === "expect") {
    const isPoll = call.modifiers.some((m) => getStringValue(m) === "poll");
    if (isPoll || awaitableMatchers.has(call.matcherName)) {
      return {
        data: { name: isPoll ? "expect.poll" : call.matcherName },
        messageId: "missingAwait",
        node: call.head.node
      };
    }
  }
}
var missing_playwright_await_default = createRule({
  create(context) {
    const options = context.options[0] || {};
    const includePageLocatorMethods = !!options.includePageLocatorMethods;
    const awaitableMatchers = /* @__PURE__ */ new Set([
      ...expectPlaywrightMatchers,
      ...playwrightTestMatchers,
      // Add any custom matchers to the set
      ...options.customMatchers || []
    ]);
    function isVariableConsumed(variable, visited) {
      for (const ref of variable.references) {
        if (!ref.isRead()) {
          continue;
        }
        const refParent = ref.identifier.parent;
        if (!refParent || visited.has(refParent)) {
          continue;
        }
        if (validTypes.has(refParent.type)) {
          return true;
        }
        if (refParent.type === "VariableDeclarator") {
          if (checkValidity(ref.identifier, visited)) {
            return true;
          }
          continue;
        }
        if (checkValidity(refParent, visited)) {
          return true;
        }
      }
      return false;
    }
    function checkValidity(node, visited) {
      const parent = node.parent;
      if (!parent) {
        return false;
      }
      if (visited.has(parent)) {
        return false;
      }
      visited.add(parent);
      if (validTypes.has(parent.type)) {
        return true;
      }
      if (isPromiseAccessor(parent) && parent.parent?.type === "CallExpression") {
        return checkValidity(parent.parent, visited);
      }
      if (parent.type === "CallExpression" && parent.callee === node && isPromiseAccessor(node)) {
        return checkValidity(parent, visited);
      }
      if (parent.type === "ArrayExpression") {
        return checkValidity(parent, visited);
      }
      if (parent.type === "ConditionalExpression") {
        return checkValidity(parent, visited);
      }
      if (parent.type === "ChainExpression") {
        return checkValidity(parent, visited);
      }
      if (parent.type === "SpreadElement") {
        return checkValidity(parent, visited);
      }
      if (parent.type === "CallExpression" && parent.callee.type === "MemberExpression" && isIdentifier(parent.callee.object, "Promise") && isIdentifier(parent.callee.property, /^(all|allSettled|race|any)$/)) {
        return true;
      }
      if (parent.type === "MemberExpression" && parent.object === node && getStringValue(parent.property) === "resolves" && node.type === "CallExpression" && isIdentifier(node.callee, "expect")) {
        return checkValidity(parent, visited);
      }
      if (parent.type === "MemberExpression" && parent.object === node) {
        return checkValidity(parent, visited);
      }
      if (parent.type === "CallExpression" && (parent.callee === node || isIdentifier(parent.callee, "expect"))) {
        return checkValidity(parent, visited);
      }
      if (parent.type === "VariableDeclarator") {
        return context.sourceCode.getDeclaredVariables(parent).some((v) => isVariableConsumed(v, visited));
      }
      if (parent.type === "AssignmentExpression" && parent.right === node && parent.left.type === "Identifier") {
        const parentName = parent.left.name;
        let scope = context.sourceCode.getScope(node);
        while (scope) {
          const variable = scope.variables.find((v) => v.name === parentName);
          if (variable) {
            return isVariableConsumed(variable, visited);
          }
          scope = scope.upper;
        }
        return false;
      }
      return false;
    }
    return {
      CallExpression(node) {
        if (isPageMethod(node, waitForMethodsRegex)) {
          if (!checkValidity(node, /* @__PURE__ */ new Set())) {
            const methodName = getStringValue(node.callee.property);
            context.report({
              data: { name: methodName },
              messageId: "missingAwait",
              node
            });
          }
          return;
        }
        if (includePageLocatorMethods && node.callee.type === "MemberExpression") {
          const methodName = getStringValue(node.callee.property);
          const isPlaywrightMethod = !isArrayLike(node.callee.object) && (locatorMethods.has(methodName) || pageMethods.has(methodName) && isPageMethod(node, methodName));
          if (isPlaywrightMethod) {
            if (!checkValidity(node, /* @__PURE__ */ new Set())) {
              context.report({
                data: { name: methodName },
                messageId: "missingAwait",
                node
              });
            }
            return;
          }
        }
        const call = parseFnCall(context, node);
        if (call?.type !== "step" && call?.type !== "expect") {
          return;
        }
        const result = getCallType(call, awaitableMatchers);
        const isValid = result ? checkValidity(node, /* @__PURE__ */ new Set()) : false;
        if (result && !isValid) {
          context.report({
            data: result.data,
            fix: (fixer) => fixer.insertTextBefore(node, "await "),
            messageId: result.messageId,
            node: getReportNode(result.node)
          });
        }
      }
    };
  },
  meta: {
    docs: {
      description: `Identify false positives when async Playwright APIs are not properly awaited.`,
      recommended: true,
      url: "https://github.com/mskelton/eslint-plugin-playwright/tree/main/docs/rules/missing-playwright-await.md"
    },
    fixable: "code",
    messages: {
      missingAwait: "'{{name}}' must be awaited or returned."
    },
    schema: [
      {
        additionalProperties: false,
        properties: {
          customMatchers: {
            items: { type: "string" },
            type: "array"
          },
          includePageLocatorMethods: {
            type: "boolean"
          }
        },
        type: "object"
      }
    ],
    type: "problem"
  }
});

// src/rules/no-unnecessary-assertions.ts
var locatorMethods2 = /* @__PURE__ */ new Set([
  "getByAltText",
  "getByLabel",
  "getByPlaceholder",
  "getByRole",
  "getByTestId",
  "getByText",
  "getByTitle",
  "locator"
]);
var locatorReturning = /* @__PURE__ */ new Set([...locatorMethods2, "and", "filter", "first", "last", "nth", "or"]);
var positiveAlwaysTrue = {
  toBeDefined: "undefined",
  toBeTruthy: "falsy"
};
var negatedAlwaysTrue = {
  toBeFalsy: "falsy",
  toBeNull: "null",
  toBeUndefined: "undefined"
};
function isLocatorChain(node) {
  if (node?.type !== "CallExpression" || node.callee.type !== "MemberExpression" || !locatorReturning.has(getStringValue(node.callee.property))) {
    return false;
  }
  let current = node;
  while (current) {
    if (current.type === "CallExpression") {
      current = current.callee;
    } else if (current.type === "MemberExpression") {
      if (locatorMethods2.has(getStringValue(current.property))) {
        return true;
      }
      current = current.object;
    } else {
      return false;
    }
  }
  return false;
}
function awaitIsAllowed(node) {
  let current = node.parent;
  while (current) {
    switch (current.type) {
      case "ArrowFunctionExpression":
      case "FunctionDeclaration":
      case "FunctionExpression":
        return current.async === true;
      case "PropertyDefinition":
      case "StaticBlock":
        return false;
    }
    current = current.parent;
  }
  return false;
}
var no_unnecessary_assertions_default = createRule({
  create(context) {
    return {
      CallExpression(node) {
        const call = parseFnCall(context, node);
        if (call?.type !== "expect") {
          return;
        }
        const modifierNames = call.modifiers.map((mod) => getStringValue(mod));
        if (modifierNames.some((name) => name === "resolves" || name === "rejects")) {
          return;
        }
        const negated = modifierNames.includes("not");
        const value = negated ? negatedAlwaysTrue[call.matcherName] : positiveAlwaysTrue[call.matcherName];
        if (value === void 0) {
          return;
        }
        if (call.args.length === 0) {
          return;
        }
        const subject = dereference(context, call.args[0]);
        if (!isLocatorChain(subject)) {
          return;
        }
        const expectCall = findParent(call.head.node, "CallExpression");
        const matcherCall = findParent(call.matcher, "CallExpression");
        if (!expectCall || !matcherCall) {
          return;
        }
        const canReplace = awaitIsAllowed(matcherCall) && !context.sourceCode.commentsExistBetween(expectCall, call.matcher);
        context.report({
          data: {
            matcher: negated ? `not.${call.matcherName}` : call.matcherName,
            value
          },
          messageId: "noUnnecessaryAssertions",
          node: matcherCall,
          suggest: canReplace ? [
            {
              fix(fixer) {
                const fixes = [
                  fixer.replaceTextRange(
                    [expectCall.range[1], matcherCall.range[1]],
                    ".toBeVisible()"
                  )
                ];
                const alreadyAwaited = matcherCall.parent?.type === "AwaitExpression";
                if (!alreadyAwaited) {
                  fixes.unshift(fixer.insertTextBefore(expectCall, "await "));
                }
                return fixes;
              },
              messageId: "replaceWithToBeVisible"
            }
          ] : []
        });
      }
    };
  },
  meta: {
    docs: {
      description: "Disallow assertions on a Locator that can never fail",
      recommended: true,
      url: "https://github.com/mskelton/eslint-plugin-playwright/tree/main/docs/rules/no-unnecessary-assertions.md"
    },
    hasSuggestions: true,
    messages: {
      noUnnecessaryAssertions: "This assertion can never fail: a Playwright Locator is never {{value}}, so `expect(locator).{{matcher}}()` always passes. Assert rendered state with a web-first matcher such as `toBeVisible()`.",
      replaceWithToBeVisible: "Replace with `await expect(locator).toBeVisible()`."
    },
    type: "problem"
  }
});

// src/utils/misc.ts
var getAmountData = (amount) => ({
  amount: amount.toString(),
  s: amount === 1 ? "" : "s"
});
var truthy = Boolean;

// src/utils/fixer.ts
var getRangeOffset = (node) => node.type === "Identifier" ? 0 : 1;
function replaceAccessorFixer(fixer, node, text) {
  const [start, end] = node.range;
  return fixer.replaceTextRange([start + getRangeOffset(node), end - getRangeOffset(node)], text);
}
function removePropertyFixer(fixer, property) {
  const parent = property.parent;
  if (parent?.type !== "ObjectExpression") {
    return;
  }
  if (parent.properties.length === 1) {
    return fixer.remove(parent);
  }
  const index = parent.properties.indexOf(property);
  const range = index ? [parent.properties[index - 1].range[1], property.range[1]] : [property.range[0], parent.properties[1].range[0]];
  return fixer.removeRange(range);
}

// Native source export: retained syntax rules only.
module.exports = {
  "missing-playwright-await": missing_playwright_await_default,
  "no-unnecessary-assertions": no_unnecessary_assertions_default,
};
