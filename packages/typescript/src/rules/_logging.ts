/**
 * @fileoverview _logging — shared recognition of logging / error-reporting calls, so the catch rules and the secret rule cannot disagree.
 */

import { ASTUtils, AST_NODE_TYPES, type TSESTree } from "@typescript-eslint/utils";
import { unwrapExpression } from "./_unwrap-expression.js";

export const LOG_METHODS: ReadonlySet<string> = new Set([
  "debug",
  "info",
  "warn",
  "warning",
  "error",
  "exception",
  "critical",
  "trace",
  "log",
  "fatal",
  "success",
]);

export const LOGGER_NAMES: ReadonlySet<string> = new Set([
  "logger",
  "log",
  "logging",
  "loguru",
  "console",
  "_logger",
  "_log",
]);

/** Factory methods that RETURN a logger (`logging.getLogger(name).info(...)`). */
export const LOGGER_FACTORIES: ReadonlySet<string> = new Set([
  "getlogger",
  "get_logger",
]);

/** Reporting names stay broad because consumers also require the caught binding. */
export const REPORT_NAME_RE = /error|report|capture|log|trace|warn/i;

/** Shared `loggerNames` / `logFunctions` option shape. */
export interface LoggingOptions {
  readonly loggerNames?: readonly string[];
  readonly logFunctions?: readonly string[];
}

/** Shared schema properties keep logging options consistent across consumers. */
export const LOGGING_OPTION_PROPERTIES = {
  loggerNames: { type: "array", items: { type: "string" } },
  logFunctions: { type: "array", items: { type: "string" } },
} as const;

/** The static callee name of a call (free function or method), or null. */
export function calleeName(callee: TSESTree.Node): string | null {
  if (callee.type === "Identifier") {
    return callee.name;
  }
  return callee.type === "MemberExpression" ? ASTUtils.getPropertyName(callee) : null;
}

export interface LogMatcher {
  /** Is `expr` a logger receiver (bare name, member chain, or factory call)? */
  isLoggerReceiver(expr: TSESTree.Expression | TSESTree.PrivateIdentifier): boolean;
  /** Is `expr` a project-declared free logging function call (`logEvent(...)`)? */
  isLogFunctionCall(expr: TSESTree.Node): boolean;
  /** Is `expr` a logging call of either shape? */
  isLoggingCall(expr: TSESTree.Node): boolean;
}

/** Builds a matcher with the project's declared receivers and functions. */
export function createLogMatcher(options: LoggingOptions = {}): LogMatcher {
  const loggerNames: ReadonlySet<string> = new Set([
    ...LOGGER_NAMES,
    ...(options.loggerNames ?? []).map((name) => name.toLowerCase()),
  ]);
  const logFunctions: ReadonlySet<string> = new Set(options.logFunctions ?? []);

  function isLoggerReceiver(
    expr: TSESTree.Expression | TSESTree.PrivateIdentifier,
  ): boolean {
    expr = unwrapExpression(expr);
    switch (expr.type) {
      case "Identifier":
        return loggerNames.has(expr.name.toLowerCase());
      case "MemberExpression": {
        const { object } = expr;
        const property = ASTUtils.getPropertyName(expr);
        if (property !== null) {
          const lowered = property.toLowerCase();
          if (loggerNames.has(lowered) || LOGGER_FACTORIES.has(lowered)) {
            return true;
          }
        }
        return isLoggerReceiver(object);
      }
      case "CallExpression": {
        const callee = expr.callee;
        const name = callee.type === "MemberExpression" ? ASTUtils.getPropertyName(callee) : null;
        if (name !== null && LOGGER_FACTORIES.has(name.toLowerCase())) {
          return true;
        }
        if (callee.type !== "Super") {
          return isLoggerReceiver(callee);
        }
        return false;
      }
      default:
        return false;
    }
  }

  function isLogFunctionCall(expr: TSESTree.Node): boolean {
    if (expr.type !== "CallExpression" || logFunctions.size === 0) {
      return false;
    }
    const name = calleeName(expr.callee);
    return name !== null && logFunctions.has(name);
  }

  function isLoggingCall(expr: TSESTree.Node): boolean {
    if (expr.type !== "CallExpression") {
      return false;
    }
    if (isLogFunctionCall(expr)) {
      return true;
    }
    const callee = expr.callee;
    const calleeReceiver = callee.type === AST_NODE_TYPES.MemberExpression ? unwrapExpression(callee.object) : callee;
    if (callee.type !== "MemberExpression") return false;
    const name = ASTUtils.getPropertyName(callee);
    return name !== null && LOG_METHODS.has(name.toLowerCase()) && isLoggerReceiver(calleeReceiver);
  }

  return { isLoggerReceiver, isLogFunctionCall, isLoggingCall };
}
