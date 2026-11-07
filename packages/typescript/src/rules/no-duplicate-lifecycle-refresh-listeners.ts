/**
 * @fileoverview no-duplicate-lifecycle-refresh-listeners — tab activation must not refresh the same route twice.
 *
 * Port of the 18.x `no-duplicate-lifecycle-refresh-listeners` rule. Same
 * algorithm; pure checks are reordered so scope lookups run last, and files
 * without a `useRouter` import from `next/navigation` are skipped in `before()`
 * because the original can never report on them (no router hook, so no router,
 * so no refreshing callback).
 */

import { defineRule, type ESTree, type Node, type TsVariable } from "../types.js";
import { outerExpression, parentOf, unwrapExpression } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { importSpecifierName } from "../utils/import-specifier-name.js";
import { isGeneratedFile, isTestFile } from "../utils/paths.js";
import { enclosingFunction } from "../utils/stable-value-binding.js";
import { findVariable, getPropertyName, staticString } from "../utils/static-string.js";

type Identifier = Extract<Node, { type: "Identifier" }>;
type LifecycleEvent = "focus" | "visibilitychange";
type Registrations = Partial<Record<LifecycleEvent, ESTree.CallExpression>>;

const NAME = "no-duplicate-lifecycle-refresh-listeners";
const ROUTER_MODULE = "next/navigation";
const RECEIVER_EVENTS: ReadonlyMap<string, LifecycleEvent> = new Map([["window", "focus"], ["document", "visibilitychange"]]);

/** Whether the original's ImportDeclaration visitor could record any router hook. */
function importsRouterHook(body: readonly Node[]): boolean {
  for (const statement of body) {
    if (statement.type !== "ImportDeclaration" || statement.source.value !== ROUTER_MODULE) continue;
    for (const specifier of statement.specifiers) {
      if (specifier.type === "ImportSpecifier" && importSpecifierName(specifier) === "useRouter") return true;
    }
  }
  return false;
}

interface LifecycleListener {
  readonly receiver: Identifier;
  readonly callback: Identifier;
  readonly event: LifecycleEvent;
}

/** `window`'s focus or `document`'s visibilitychange listener call with an identifier callback. */
function lifecycleListener(node: ESTree.CallExpression, member: ESTree.MemberExpression): LifecycleListener | null {
  const receiver = unwrapExpression(member.object);
  const [eventArgument, callbackArgument] = node.arguments;
  if (receiver.type !== "Identifier" || eventArgument === undefined || callbackArgument === undefined) return null;
  const event = RECEIVER_EVENTS.get(receiver.name);
  const callback = unwrapExpression(callbackArgument);
  if (event === undefined || callback.type !== "Identifier" || staticString(eventArgument) !== event) return null;
  return { receiver, callback, event };
}

function isReassigned(variable: TsVariable): boolean {
  return variable.references.some((reference) => reference.isWrite() && !reference.init);
}

function statementContainer(node: ESTree.CallExpression): Node | null {
  const statement = parentOf(outerExpression(node));
  if (statement?.type !== "ExpressionStatement") return null;
  const container = parentOf(statement);
  return container?.type === "Program" || container?.type === "BlockStatement" ? container : null;
}

export default defineRule({
  meta: {
    type: "suggestion",
    docs: {
      description: "Do not register one Next.js route-refresh callback for both focus and visibilitychange.",
      url: docsUrl(NAME),
    },
    schema: [],
    messages: {
      duplicateLifecycleRefresh:
        "This Next.js route-refresh callback handles focus and visibilitychange; tab activation can invoke it twice.",
    },
  },
  createOnce(context) {
    const routerHooks = new Set<TsVariable>();
    const routerHookNames = new Set<string>();
    const routers = new Set<TsVariable>();
    const functionCallbacks = new Map<Node, TsVariable>();
    const refreshingCallbacks = new Set<TsVariable>();
    const registrations = new Map<Node, Map<TsVariable, Registrations>>();

    function lookup(node: Identifier): TsVariable | null {
      return findVariable(context.sourceCode.getScope(node), node.name);
    }

    function recordRegistration(node: ESTree.CallExpression, member: ESTree.MemberExpression, method: string): void {
      const listener = lifecycleListener(node, member);
      if (listener === null) return;
      // isUnshadowedGlobal
      const global = lookup(listener.receiver);
      if (global !== null && global.defs.length !== 0) return;

      const container = statementContainer(node);
      if (container === null) return;
      const variable = lookup(listener.callback);
      if (variable === null) return;
      const events = callbackRegistrations(container, variable);
      if (method === "addEventListener") events[listener.event] ??= node;
      else delete events[listener.event];
    }

    function callbackRegistrations(container: Node, variable: TsVariable): Registrations {
      let callbacks = registrations.get(container);
      if (callbacks === undefined) {
        callbacks = new Map<TsVariable, Registrations>();
        registrations.set(container, callbacks);
      }
      let events = callbacks.get(variable);
      if (events === undefined) {
        events = {};
        callbacks.set(variable, events);
      }
      return events;
    }

    function recordRefresh(node: ESTree.CallExpression, member: ESTree.MemberExpression): void {
      const receiver = unwrapExpression(member.object);
      if (receiver.type !== "Identifier") return;
      const router = lookup(receiver);
      if (router === null || !routers.has(router)) return;
      const fn = enclosingFunction(node);
      if (fn === null) return;
      const callback = functionCallbacks.get(fn);
      if (callback !== undefined) refreshingCallbacks.add(callback);
    }

    return {
      before() {
        routerHooks.clear();
        routerHookNames.clear();
        routers.clear();
        functionCallbacks.clear();
        refreshingCallbacks.clear();
        registrations.clear();
        const file = { filename: context.filename, cwd: context.cwd };
        if (isTestFile(file)) return false;
        const sourceCode = context.sourceCode;
        if (isGeneratedFile(file, sourceCode.text)) return false;
        return importsRouterHook(sourceCode.ast.body);
      },
      ImportDeclaration(node) {
        if (node.source.value !== ROUTER_MODULE) return;
        for (const specifier of node.specifiers) {
          if (specifier.type === "ImportSpecifier" && importSpecifierName(specifier) === "useRouter") {
            const variable = lookup(specifier.local);
            if (variable !== null) {
              routerHooks.add(variable);
              routerHookNames.add(variable.name);
            }
          }
        }
      },
      VariableDeclarator(node) {
        if (node.id.type !== "Identifier" || node.init === null) return;
        const initializer = unwrapExpression(node.init);
        if (initializer.type === "ArrowFunctionExpression" || initializer.type === "FunctionExpression") {
          const variable = lookup(node.id);
          if (variable !== null && !isReassigned(variable)) functionCallbacks.set(initializer, variable);
          return;
        }
        if (initializer.type !== "CallExpression") return;
        const hookCallee = unwrapExpression(initializer.callee);
        if (hookCallee.type !== "Identifier" || !routerHookNames.has(hookCallee.name)) return;
        const variable = lookup(node.id);
        if (variable === null || isReassigned(variable)) return;
        const hook = lookup(hookCallee);
        if (hook !== null && routerHooks.has(hook)) routers.add(variable);
      },
      FunctionDeclaration(node) {
        if (node.id === null) return;
        const variable = lookup(node.id);
        if (variable !== null && !isReassigned(variable)) functionCallbacks.set(node, variable);
      },
      CallExpression(node) {
        const callee = unwrapExpression(node.callee);
        if (callee.type !== "MemberExpression") return;
        const method = getPropertyName(callee);
        if (method === "addEventListener" || method === "removeEventListener") recordRegistration(node, callee, method);
        else if (method === "refresh" && routers.size !== 0) recordRefresh(node, callee);
      },
      "Program:exit"() {
        for (const callbacks of registrations.values()) {
          for (const [callback, events] of callbacks) {
            if (!refreshingCallbacks.has(callback) || events.focus === undefined || events.visibilitychange === undefined) continue;
            const focusStart = events.focus.range[0];
            const visibilityStart = events.visibilitychange.range[0];
            context.report({
              node: focusStart > visibilityStart ? events.focus : events.visibilitychange,
              messageId: "duplicateLifecycleRefresh",
            });
          }
        }
      },
    };
  },
});
