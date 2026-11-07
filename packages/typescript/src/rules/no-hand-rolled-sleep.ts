/**
 * @fileoverview no-hand-rolled-sleep — a hand-rolled promisified timer cannot be cancelled; the stdlib form takes an `AbortSignal`.
 *
 * Port of the 18.x `no-hand-rolled-sleep` rule. The rule is untyped, so the port
 * covers all of it.
 */

import { defineRule, type ESTree, type Node } from "../types.js";
import { parentOf, unwrapExpression } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { isGeneratedFile, isScriptFile, isTestFile, matchesAnyPattern } from "../utils/paths.js";
import { findVariable } from "../utils/static-string.js";

const NAME = "no-hand-rolled-sleep";

interface Options {
  readonly allowIn?: readonly string[];
  readonly checkClientModules?: boolean;
}

type Executor = ESTree.ArrowFunctionExpression | ESTree.Function;

const GLOBAL_OBJECTS: ReadonlySet<string> = new Set([
  "globalThis",
  "window",
  "self",
  "global",
]);

const CLIENT_ONLY_MODULES =
  /^(react|react-dom|react-native|svelte|vue|preact|solid-js)(\/|$)|^next\/(navigation|router|link|image)$/;

const RACE_METHODS: ReadonlySet<string> = new Set(["race", "any"]);
const TIMER_MODULES: ReadonlySet<string> = new Set(["node:timers", "timers"]);

function isSetTimeoutCallee(callee: Node): boolean {
  callee = unwrapExpression(callee);
  if (callee.type === "Identifier") {
    return callee.name === "setTimeout";
  }
  return (
    callee.type === "MemberExpression" &&
    !callee.computed &&
    callee.property.type === "Identifier" &&
    callee.property.name === "setTimeout" &&
    callee.object.type === "Identifier" &&
    GLOBAL_OBJECTS.has(callee.object.name)
  );
}

function soleCall(fn: ESTree.ArrowFunctionExpression | ESTree.Function):
  | ESTree.CallExpression
  | null {
  // Callers pass only arrow and function expressions, which always have a body.
  const fnBody = fn.body as Node;
  if (fnBody.type !== "BlockStatement") {
    const body = unwrapExpression(fnBody);
    return body.type === "CallExpression" ? body : null;
  }
  if (fnBody.body.length !== 1) {
    return null;
  }
  const [only] = fnBody.body;
  if (only?.type !== "ExpressionStatement") {
    return null;
  }
  const expression = unwrapExpression(only.expression);
  return expression.type === "CallExpression" ? expression : null;
}

function isTimedDelay(delay: Node | undefined): boolean {
  if (delay === undefined) {
    return false;
  }
  delay = unwrapExpression(delay);
  if (delay.type === "Literal" && typeof delay.value === "number") {
    return delay.value !== 0;
  }
  return true;
}

/** A settling callback passes no value: `resolve` itself or `() => resolve()`. */
function passesNoValue(callback: Node): boolean {
  const value = unwrapExpression(callback);
  if (value.type === "Identifier") return true;
  return (value.type === "ArrowFunctionExpression" || value.type === "FunctionExpression") && soleCall(value)?.arguments.length === 0;
}

function isRaceArm(node: ESTree.NewExpression): boolean {
  const array = node.parent;
  if (array?.type !== "ArrayExpression") {
    return false;
  }
  const call = array.parent;
  return (
    call?.type === "CallExpression" &&
    call.arguments[0] === array &&
    call.callee.type === "MemberExpression" &&
    !call.callee.computed &&
    call.callee.object.type === "Identifier" &&
    call.callee.object.name === "Promise" &&
    call.callee.property.type === "Identifier" &&
    RACE_METHODS.has(call.callee.property.name)
  );
}

export default defineRule({
  meta: {
    defaultOptions: [{}],
    type: "problem",
    docs: {
      description: "Disallow uncancellable promisified timers and timeout arms.",
      url: docsUrl(NAME),
    },
    schema: [
      {
        type: "object",
        additionalProperties: false,
        properties: {
          allowIn: {
            description:
              "Glob patterns for modules exempt from the rule (e.g. a single sanctioned `sleep` utility). Matched against the ABSOLUTE file path, so anchor with a `**/` prefix (e.g. `**/lib/sleep.ts`).",
            type: "array",
            items: { type: "string" },
          },
          checkClientModules: {
            description:
              "Also report the sleep form in browser/React Native modules. Off by default: those bundles cannot import `node:timers/promises` and the web platform has no equivalent, so the fix is impossible to follow. Turn on only where every file can resolve `node:` builtins.",
            type: "boolean",
          },
        },
      },
    ],
    messages: {
      handRolledSleep:
        "Hand-rolled sleep: `new Promise((resolve) => setTimeout(resolve, ms))` cannot be cancelled, so an aborted request or a lost race still waits out the full delay. Use `import { setTimeout as sleep } from \"node:timers/promises\"` and pass `{ signal }`.",
      handRolledTimeoutRace:
        "Hand-rolled timeout arm: when the other promise wins, this timer is never cleared and keeps the event loop alive until it fires. Use `AbortSignal.timeout(ms)` and pass the signal to the operation.",
    },
  },
  createOnce(context) {
    let filename = "";
    let checkClientModules = false;
    let clientModule: boolean | null = null;

    const bindingOf = (identifier: Node & { name: string }) => findVariable(context.sourceCode.getScope(identifier), identifier.name);
    const isGlobal = (identifier: Node & { name: string }): boolean => (bindingOf(identifier)?.defs.length ?? 0) === 0;
    /** `new Promise((settle) => setTimeout(callback, delay))` with a builtin timer and a nonzero delay. */
    function promisifiedTimer(node: ESTree.NewExpression): { executor: Executor; call: ESTree.CallExpression; callback: Node } | null {
      const callee = unwrapExpression(node.callee);
      if (callee.type !== "Identifier" || callee.name !== "Promise" || !isGlobal(callee)) return null;
      const executor = node.arguments[0];
      if (executor?.type !== "ArrowFunctionExpression" && executor?.type !== "FunctionExpression") return null;
      const call = soleCall(executor);
      if (call === null || !isBuiltinTimer(call.callee)) return null;
      const [callback, delay] = call.arguments;
      return callback !== undefined && isTimedDelay(delay) ? { executor, call, callback } : null;
    }

    const isBuiltinTimer = (callee: Node): boolean => {
      callee = unwrapExpression(callee);
      if (!isSetTimeoutCallee(callee)) return false;
      if (callee.type === "MemberExpression" && callee.object.type === "Identifier") return isGlobal(callee.object);
      if (callee.type !== "Identifier") return false;
      const binding = bindingOf(callee);
      return binding === null || binding.defs.length === 0 || binding.defs.every((definition) => {
        const declaration = definition.node;
        if (declaration.type !== "ImportSpecifier" || declaration.imported.type !== "Identifier" ||
          declaration.imported.name !== "setTimeout") return false;
        const statement = parentOf(declaration);
        return statement?.type === "ImportDeclaration" && TIMER_MODULES.has(String(statement.source.value));
      });
    };
    /** The callback is, or solely calls, the executor's parameter `index`. */
    const settlesParameter = (callback: Node, executor: Executor, index: number): boolean => {
      callback = unwrapExpression(callback);
      const parameter = executor.params[index];
      if (parameter?.type !== "Identifier") return false;
      const callee = callback.type === "Identifier" ? callback :
        callback.type === "ArrowFunctionExpression" || callback.type === "FunctionExpression" ? soleCall(callback)?.callee : null;
      return callee?.type === "Identifier" && bindingOf(callee) === bindingOf(parameter);
    };

    const reportsSleepHere = (): boolean => {
      if (checkClientModules) {
        return true;
      }
      clientModule ??= isClientModule();
      return !clientModule;
    };

    function isClientModule(): boolean {
      if (/\.[cm]?[jt]sx$/.test(filename)) {
        return true;
      }
      const program = context.sourceCode.ast;
      for (const statement of program.body) {
        if (
          statement.type === "ExpressionStatement" &&
          statement.expression.type === "Literal" &&
          statement.expression.value === "use client"
        ) {
          return true;
        }
        if (
          statement.type === "ImportDeclaration" &&
          typeof statement.source.value === "string" &&
          CLIENT_ONLY_MODULES.test(statement.source.value)
        ) {
          return true;
        }
      }
      return false;
    }

    return {
      before() {
        filename = context.filename;
        const file = { filename, cwd: context.cwd };
        if (isTestFile(file) || isScriptFile(file) || isGeneratedFile(file, context.sourceCode.getText())) return false;
        const options = context.options[0] as Options | undefined;
        const allowIn = options?.allowIn ?? [];
        if (allowIn.length > 0 && matchesAnyPattern(filename, allowIn)) return false;
        checkClientModules = options?.checkClientModules ?? false;
        clientModule = null;
        return undefined;
      },
      NewExpression(node: ESTree.NewExpression): void {
        const timer = promisifiedTimer(node);
        if (timer === null) return;
        const { executor, call, callback } = timer;
        if (call.arguments.length === 2 && settlesParameter(callback, executor, 0) && passesNoValue(callback)) {
          if (reportsSleepHere()) context.report({ node, messageId: "handRolledSleep" });
          return;
        }
        if (isRaceArm(node) && settlesParameter(callback, executor, 1)) {
          context.report({ node, messageId: "handRolledTimeoutRace" });
        }
      },
    };
  },
});
