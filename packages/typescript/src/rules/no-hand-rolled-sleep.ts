/**
 * @fileoverview no-hand-rolled-sleep — a hand-rolled promisified timer cannot be cancelled; the stdlib form takes an `AbortSignal`.
 *
 * Examples: https://github.com/sarj-ai/standards/blob/main/packages/typescript/tests/rules/no-hand-rolled-sleep.test.ts
 */

import { AST_NODE_TYPES, type TSESTree } from "@typescript-eslint/utils";

import { createRule } from "./_docs.js";
import { isGeneratedFile, isScriptFile, isTestFile } from "./_paths.js";

type MessageIds = "handRolledSleep" | "handRolledTimeoutRace";
type Options = readonly [
  {
    allowIn?: readonly string[];
    checkClientModules?: boolean;
  }?,
];

/** Receivers of an explicit `<obj>.setTimeout(...)` that still mean the global. */
const GLOBAL_OBJECTS: ReadonlySet<string> = new Set([
  "globalThis",
  "window",
  "self",
  "global",
]);

/** Modules whose presence proves the file is bundled for a non-Node runtime. */
const CLIENT_ONLY_MODULES =
  /^(react|react-dom|react-native|svelte|vue|preact|solid-js)(\/|$)|^next\/(navigation|router|link|image)$/;

/** `Promise` combinators whose losing arm is discarded, leaking an orphan timer. */
const RACE_METHODS: ReadonlySet<string> = new Set(["race", "any"]);

/**
 * Glob-ish matcher mirroring `require-fetch-timeout`'s: `**` spans separators,
 * `*` does not. Kept local for the same reason it is there — two call sites do
 * not yet justify a shared module, and the semantics must not drift silently.
 */
function matchesAnyPattern(filename: string, patterns: readonly string[]): boolean {
  for (const pattern of patterns) {
    const regexSource = pattern
      .replace(/[.+^${}()|[\]\\]/g, "\\$&")
      .replace(/\*\*/g, "::DOUBLESTAR::")
      .replace(/\*/g, "[^/\\\\]*")
      .replace(/::DOUBLESTAR::/g, ".*");
    if (new RegExp(`^${regexSource}$`).test(filename)) {
      return true;
    }
  }
  return false;
}

/** True when `callee` names `setTimeout`, bare or on an explicit global object. */
function isSetTimeoutCallee(callee: TSESTree.Node): boolean {
  if (callee.type === AST_NODE_TYPES.Identifier) {
    return callee.name === "setTimeout";
  }
  return (
    callee.type === AST_NODE_TYPES.MemberExpression &&
    !callee.computed &&
    callee.property.type === AST_NODE_TYPES.Identifier &&
    callee.property.name === "setTimeout" &&
    callee.object.type === AST_NODE_TYPES.Identifier &&
    GLOBAL_OBJECTS.has(callee.object.name)
  );
}

function soleCall(fn: TSESTree.ArrowFunctionExpression | TSESTree.FunctionExpression):
  | TSESTree.CallExpression
  | null {
  if (fn.body.type !== AST_NODE_TYPES.BlockStatement) {
    return fn.body.type === AST_NODE_TYPES.CallExpression ? fn.body : null;
  }
  if (fn.body.body.length !== 1) {
    return null;
  }
  const [only] = fn.body.body;
  if (only?.type !== AST_NODE_TYPES.ExpressionStatement) {
    return null;
  }
  return only.expression.type === AST_NODE_TYPES.CallExpression ? only.expression : null;
}

/** True for a delay that is a real wait: absent-of-literal, or a nonzero literal. */
function isTimedDelay(delay: TSESTree.Node | undefined): boolean {
  if (delay === undefined) {
    return false;
  }
  if (delay.type === AST_NODE_TYPES.Literal && typeof delay.value === "number") {
    return delay.value !== 0;
  }
  // A variable / member / expression delay is the motivating case: a `sleep(ms)`
  // helper forwarding its parameter. Only a literal `0` is provably a yield.
  return true;
}

/**
 * True when `callback` settles `name` and carries no value: the bare identifier
 * `name`, or a zero-argument `() => name()` / `() => { name(); }` forwarder.
 * A callback passing a value is a delayed RESULT, which this rule leaves alone.
 */
function settlesWithoutValue(callback: TSESTree.Node, name: string): boolean {
  if (callback.type === AST_NODE_TYPES.Identifier) {
    return callback.name === name;
  }
  if (
    callback.type !== AST_NODE_TYPES.ArrowFunctionExpression &&
    callback.type !== AST_NODE_TYPES.FunctionExpression
  ) {
    return false;
  }
  const call = soleCall(callback);
  return (
    call !== null &&
    call.arguments.length === 0 &&
    call.callee.type === AST_NODE_TYPES.Identifier &&
    call.callee.name === name
  );
}

/**
 * True when `callback` calls `name` — with or without an argument, since a
 * timeout arm conventionally rejects with an `Error`. Only consulted for the
 * REJECT parameter inside a `Promise.race`, where any rejection at all means
 * "time this out"; the value-carrying case that the resolve path excludes is
 * exactly what a rejection is supposed to look like.
 */
function rejectsInCallback(callback: TSESTree.Node, name: string): boolean {
  if (callback.type === AST_NODE_TYPES.Identifier) {
    return callback.name === name;
  }
  if (
    callback.type !== AST_NODE_TYPES.ArrowFunctionExpression &&
    callback.type !== AST_NODE_TYPES.FunctionExpression
  ) {
    return false;
  }
  const call = soleCall(callback);
  return (
    call !== null &&
    call.callee.type === AST_NODE_TYPES.Identifier &&
    call.callee.name === name
  );
}

/** The name of an executor parameter at `index`, when it is a plain identifier. */
function parameterName(
  fn: TSESTree.ArrowFunctionExpression | TSESTree.FunctionExpression,
  index: number,
): string | null {
  const parameter = fn.params[index];
  return parameter?.type === AST_NODE_TYPES.Identifier ? parameter.name : null;
}

/**
 * True when `node` sits directly in the array literal handed to
 * `Promise.race([...])` / `Promise.any([...])` — the only position where a
 * delayed rejection means "time this out" and `AbortSignal.timeout` applies.
 */
function isRaceArm(node: TSESTree.NewExpression): boolean {
  const array = node.parent;
  if (array?.type !== AST_NODE_TYPES.ArrayExpression) {
    return false;
  }
  const call = array.parent;
  return (
    call?.type === AST_NODE_TYPES.CallExpression &&
    call.arguments[0] === array &&
    call.callee.type === AST_NODE_TYPES.MemberExpression &&
    !call.callee.computed &&
    call.callee.object.type === AST_NODE_TYPES.Identifier &&
    call.callee.object.name === "Promise" &&
    call.callee.property.type === AST_NODE_TYPES.Identifier &&
    RACE_METHODS.has(call.callee.property.name)
  );
}

export default createRule<Options, MessageIds>({
  name: "no-hand-rolled-sleep",
  meta: {
    type: "problem",
    docs: {
      description:
        "Disallow hand-rolled promisified timers (`new Promise((r) => setTimeout(r, ms))`) and hand-rolled `Promise.race` timeout arms; the stdlib forms are cancellable, these are not.",
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
  defaultOptions: [{}],
  create(context, [optionsArg]) {
    const { filename, sourceCode } = context;
    if (
      isTestFile(filename) ||
      isScriptFile(filename) ||
      isGeneratedFile(filename, sourceCode.getText())
    ) {
      return {};
    }

    const allowIn = optionsArg?.allowIn ?? [];
    if (allowIn.length > 0 && matchesAnyPattern(filename, allowIn)) {
      return {};
    }

    const checkClientModules = optionsArg?.checkClientModules ?? false;

    /**
     * True when this module provably ships to a non-Node runtime: a JSX file, a
     * `"use client"` directive, or an import of a client-only framework. Blunt
     * on purpose — over-skipping costs a report, under-skipping prints advice
     * the consumer physically cannot follow.
     */
    function isClientModule(): boolean {
      if (/\.[cm]?[jt]sx$/.test(filename)) {
        return true;
      }
      const program = sourceCode.ast;
      for (const statement of program.body) {
        if (
          statement.type === AST_NODE_TYPES.ExpressionStatement &&
          statement.expression.type === AST_NODE_TYPES.Literal &&
          statement.expression.value === "use client"
        ) {
          return true;
        }
        if (
          statement.type === AST_NODE_TYPES.ImportDeclaration &&
          typeof statement.source.value === "string" &&
          CLIENT_ONLY_MODULES.test(statement.source.value)
        ) {
          return true;
        }
      }
      return false;
    }

    let clientModule: boolean | null = null;
    const reportsSleepHere = (): boolean => {
      if (checkClientModules) {
        return true;
      }
      clientModule ??= isClientModule();
      return !clientModule;
    };

    return {
      NewExpression(node: TSESTree.NewExpression): void {
        if (node.callee.type !== AST_NODE_TYPES.Identifier || node.callee.name !== "Promise") {
          return;
        }
        const executor = node.arguments[0];
        if (
          executor?.type !== AST_NODE_TYPES.ArrowFunctionExpression &&
          executor?.type !== AST_NODE_TYPES.FunctionExpression
        ) {
          return;
        }
        const call = soleCall(executor);
        if (call === null || !isSetTimeoutCallee(call.callee)) {
          return;
        }
        const [callback, delay] = call.arguments;
        if (callback === undefined || !isTimedDelay(delay)) {
          return;
        }

        const resolveName = parameterName(executor, 0);
        if (resolveName !== null && settlesWithoutValue(callback, resolveName)) {
          if (reportsSleepHere()) {
            context.report({ node, messageId: "handRolledSleep" });
          }
          return;
        }

        const rejectName = parameterName(executor, 1);
        if (
          rejectName !== null &&
          isRaceArm(node) &&
          rejectsInCallback(callback, rejectName)
        ) {
          context.report({ node, messageId: "handRolledTimeoutRace" });
        }
      },
    };
  },
});
