/**
 * @fileoverview no-hand-rolled-sleep — a hand-rolled promisified timer cannot be cancelled; the stdlib form takes an `AbortSignal`.
 *
 * Examples: https://github.com/sarj-ai/standards/blob/main/packages/typescript/tests/rules/no-hand-rolled-sleep.test.ts
 */

import { AST_NODE_TYPES, type TSESTree } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile, isScriptFile, isTestFile } from "./_paths.js";

type MessageIds = "handRolledSleep" | "handRolledTimeoutRace";
type Options = readonly [
  {
    allowIn?: readonly string[];
    checkClientModules?: boolean;
  }?,
];

export const noHandRolledSleepDocumentation = {
  summary: "Disallow uncancellable promisified timers and timeout arms.",
  rationale:
    "A timer that outlives an aborted operation or a lost promise race retains work and can keep the process alive until it fires.",
  remediation:
    "Use `node:timers/promises` with an abort signal for delays, or pass `AbortSignal.timeout(...)` to the timed operation.",
  category: "correctness",
  limitations: [
    "The rule skips tests, scripts, generated files, and client modules by default, and supports explicit path exemptions.",
  ],
  examples: [
    {
      id: "cancellable-node-timer",
      title: "A standard-library timer accepts an abort signal",
      outcome: "no-match",
      files: [{
        path: "src/lib/queue.ts",
        source: "import { setTimeout as sleep } from \"node:timers/promises\";\nawait sleep(500, undefined, { signal });",
      }],
      focusPath: "src/lib/queue.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "uncancellable-sleep",
      title: "A Promise wraps a timer without cancellation",
      outcome: "match",
      files: [{ path: "src/lib/queue.ts", source: "await new Promise((resolve) => setTimeout(resolve, 500));" }],
      focusPath: "src/lib/queue.ts",
      expectedCount: 1,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;

const GLOBAL_OBJECTS: ReadonlySet<string> = new Set([
  "globalThis",
  "window",
  "self",
  "global",
]);

const CLIENT_ONLY_MODULES =
  /^(react|react-dom|react-native|svelte|vue|preact|solid-js)(\/|$)|^next\/(navigation|router|link|image)$/;

const RACE_METHODS: ReadonlySet<string> = new Set(["race", "any"]);

/** Match configured paths where `**` spans separators and `*` does not. */
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

function isTimedDelay(delay: TSESTree.Node | undefined): boolean {
  if (delay === undefined) {
    return false;
  }
  if (delay.type === AST_NODE_TYPES.Literal && typeof delay.value === "number") {
    return delay.value !== 0;
  }
  return true;
}

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

function parameterName(
  fn: TSESTree.ArrowFunctionExpression | TSESTree.FunctionExpression,
  index: number,
): string | null {
  const parameter = fn.params[index];
  return parameter?.type === AST_NODE_TYPES.Identifier ? parameter.name : null;
}

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
  documentation: noHandRolledSleepDocumentation,
  meta: {
    type: "problem",
    docs: {
      description: "Disallow uncancellable promisified timers and timeout arms.",
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
