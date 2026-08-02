import * as tsParser from "@typescript-eslint/parser";
import { type TSESTree } from "@typescript-eslint/utils";
import { describe, expect, it } from "vitest";

import {
  createLogMatcher,
  LOGGER_FACTORIES,
  LOGGER_NAMES,
  LOG_METHODS,
} from "../../src/rules/_logging.js";

function expression(source: string): TSESTree.Expression {
  const program = tsParser.parse(source);
  const statement = program.body[0];
  if (statement?.type !== "ExpressionStatement") {
    throw new Error(`Expected an expression: ${source}`);
  }
  return statement.expression;
}

describe("createLogMatcher", () => {
  const matcher = createLogMatcher();

  it.each([
    "console.error(error)",
    "logger.warn(error)",
    "this.logger.info(error)",
    "logger.bind({ requestId }).error(error)",
    'logging.getLogger("api").debug(error)',
  ])("recognizes receiver-shaped logging call %s", (source) => {
    expect(matcher.isLoggingCall(expression(source))).toBe(true);
  });

  it.each([
    "metrics.error(error)",
    "logger.flush(error)",
    'console["error"](error)',
    "logEvent(error)",
  ])("does not infer that %s is a logging call", (source) => {
    expect(matcher.isLoggingCall(expression(source))).toBe(false);
  });

  it("recognizes only configured static logging function names", () => {
    const configured = createLogMatcher({ logFunctions: ["logEvent"] });

    expect(configured.isLoggingCall(expression("logEvent(error)"))).toBe(true);
    expect(configured.isLoggingCall(expression("events.logEvent(error)"))).toBe(true);
    expect(configured.isLoggingCall(expression("auditEvent(error)"))).toBe(false);
    expect(configured.isLoggingCall(expression('events["logEvent"](error)'))).toBe(false);
    expect(matcher.isLoggingCall(expression("logEvent(error)"))).toBe(false);
  });

  it("extends receiver names without changing the defaults", () => {
    const configured = createLogMatcher({ loggerNames: ["observability"] });

    expect(configured.isLoggingCall(expression("observability.error(error)"))).toBe(true);
    expect(matcher.isLoggingCall(expression("observability.error(error)"))).toBe(false);
    expect(configured.isLoggingCall(expression("console.error(error)"))).toBe(true);
  });

  it("pins the built-in receiver, factory, and method vocabulary", () => {
    expect([...LOGGER_NAMES]).toEqual([
      "logger",
      "log",
      "logging",
      "loguru",
      "console",
      "_logger",
      "_log",
    ]);
    expect([...LOGGER_FACTORIES]).toEqual(["getlogger", "get_logger"]);
    expect([...LOG_METHODS]).toEqual([
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
  });
});
