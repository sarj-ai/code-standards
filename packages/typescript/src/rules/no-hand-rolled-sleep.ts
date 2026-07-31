/**
 * @fileoverview Ban the hand-rolled promisified timer —
 * `new Promise((resolve) => setTimeout(resolve, ms))` — in favour of
 * `node:timers/promises`'s `setTimeout`, and ban the hand-rolled
 * `Promise.race` timeout arm in favour of `AbortSignal.timeout(ms)`.
 *
 * This is not a style preference. The stdlib version takes an `AbortSignal`;
 * the hand-rolled one silently cannot be cancelled, so it is a capability loss:
 *
 *   - A hand-rolled sleep holds a live Node timer for its full duration. There
 *     is no handle to clear, so a request that is aborted, a shutdown, or a
 *     `Promise.race` the sleep loses all still wait out the whole delay. The
 *     `node:timers/promises` form takes `{ signal }` and rejects promptly.
 *   - The `Promise.race([work, rejectAfter(ms)])` idiom leaks the losing arm the
 *     other way round: when `work` wins, the timer is never cleared and keeps
 *     the event loop alive until it fires. `AbortSignal.timeout(ms)` is the
 *     stdlib expression of the same intent with no orphan timer.
 *
 * WHY A CUSTOM RULE — no enabled rule reports this position. Resolved with
 * `ESLint#calculateConfigForFile` against the shipped `eslint.strict.mjs`
 * (204 enabled rules before this one) and confirmed by linting a file
 * containing every shape below: the only report was an unrelated
 * `promise-function-async`. The nearby external rules were checked individually
 * and each covers a DIFFERENT shape:
 *
 *   - `unicorn` 72.0.0 has no promisified-timer rule at all (341 rules; the
 *     timer/promise family is `explicit-timer-delay`, `prefer-abort-signal-any`,
 *     `prefer-abort-signal-timeout`, `prefer-promise-with-resolvers`,
 *     `prefer-promise-try`, `no-multiple-promise-resolver-calls`).
 *   - `unicorn/prefer-abort-signal-timeout` (available, not enabled) fires on
 *     `new AbortController()` + `setTimeout(() => c.abort(), ms)`. Run against
 *     the shape file it reported ONLY that line and not the `Promise.race`
 *     timeout arm. Worth enabling on its own merits; it is not this rule.
 *   - core `no-promise-executor-return` (available, not enabled) fires on the
 *     concise-arrow spelling only — it did NOT report the block-bodied
 *     `(resolve) => { setTimeout(resolve, ms); }` motivating case, nor the
 *     `function (resolve) { ... }` spelling. Its remedy is "add braces", which
 *     entrenches the hand-rolled sleep rather than replacing it.
 *
 * The polling-loop shape (`while (!done) { await sleep(ms); }`) is deliberately
 * NOT implemented here: core `no-await-in-loop` is already enabled at `error`
 * and reports that exact position (2 reports on the shape file). 74 non-test
 * occurrences in the OSS corpus below would have been duplicate reports.
 *
 * MEASURED (2026-07). OSS corpus, 15 repos (hono, tRPC, drizzle-orm, undici,
 * vitest, got, cal.com, documenso, dub, formbricks, midday, openstatus,
 * papermark, unkey, zod): 124 non-test `new Promise` + `setTimeout` sleeps and
 * 22 non-test reject-flavoured race arms. Private corpus, 7 repos: 53 non-test
 * sleeps across 21 files (plus 18 in one-off scripts, 1 in a test) and 1 race
 * arm. 463 further OSS occurrences are in test files and belong to the already
 * enabled `@sarj/no-sleep-in-test-body`, which is why test files are skipped
 * here rather than double-reported.
 *
 * FIRES ONLY on the exact idiom, which is what keeps false positives near zero:
 * a `new Promise` whose executor body is a SINGLE `setTimeout` call and whose
 * callback is the executor's own `resolve` (or `reject`) parameter, passed
 * directly or as a zero-argument `() => resolve()` forwarder.
 *
 * DELIBERATELY NOT FLAGGED:
 *   - `setTimeout(() => resolve(value), ms)` — a delayed VALUE, not a sleep.
 *     Every such occurrence measured in the private corpus was the losing arm
 *     of a race that resolves to a fallback result; `AbortSignal.timeout` does
 *     not express that and `node:timers/promises` would change the semantics.
 *   - `setTimeout(resolve, 0)` — a macrotask yield, not a delay. The stdlib
 *     answer is `setImmediate`, a different fix; `@sarj/no-sleep-in-test-body`
 *     draws the same nonzero-literal line.
 *   - Any executor doing more than the one `setTimeout` call — capturing the
 *     handle for `clearTimeout`, wiring `signal.addEventListener("abort", ...)`,
 *     or attaching listeners. That code is already cancellable; it is the thing
 *     this rule asks for, so reporting it would be backwards.
 *   - A reject-flavoured arm NOT inside `Promise.race` / `Promise.any`. Alone
 *     it is a delayed rejection, and `AbortSignal.timeout` is not a substitute.
 *   - Test files (`@sarj/no-sleep-in-test-body` owns those, and is enabled),
 *     one-off scripts, and generated files. The generated exclusion is load
 *     bearing rather than hypothetical: the same vendored SSE client
 *     (`.../generated/core/serverSentEvents.gen.ts`) supplied the only hit in
 *     three separate private repos, and it is overwritten on every codegen run.
 *
 * CLIENT MODULES ARE SKIPPED BY DEFAULT, and this is the single most important
 * option. A browser or React Native bundle cannot import `node:timers/promises`
 * and the web platform ships no equivalent, so the fix advice is impossible to
 * follow there. This is the common case, not an edge case: 42 of the 53 private
 * corpus sleeps (79%) are in `.tsx` components. Set `checkClientModules: true`
 * only in a tree where every file can resolve `node:` builtins. The RACE
 * message is reported in client modules regardless — `AbortSignal.timeout` is
 * available on the web platform, so that fix always applies.
 */

import { AST_NODE_TYPES, ESLintUtils, type TSESTree } from "@typescript-eslint/utils";

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

/**
 * The single call an executor body consists of, or `null` when the body does
 * anything else. "Anything else" is the false-positive guard: a body with a
 * second statement is capturing the handle, wiring an abort listener, or
 * otherwise already doing the cancellable thing this rule asks for.
 */
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

export default ESLintUtils.RuleCreator(
  (name) =>
    `https://github.com/sarj-ai/standards/blob/main/packages/typescript/src/rules/${name}.ts`,
)<Options, MessageIds>({
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
