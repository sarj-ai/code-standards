// vitest: shared-module-graph
import { describe, expect, it } from "vitest";

import {
  createLogMatcher,
  type LogMatcher,
  LOGGER_FACTORIES,
  LOGGER_NAMES,
  LOG_METHODS,
} from "../../src/utils/logging.js";
import { probe } from "./_probe.js";

function isLoggingCall(matcher: LogMatcher, source: string): boolean {
  return probe(source, (context) => {
    const statement = context.sourceCode.ast.body[0];
    if (statement?.type !== "ExpressionStatement") {
      throw new Error(`Expected an expression: ${source}`);
    }
    return matcher.isLoggingCall(statement.expression);
  });
}

describe("createLogMatcher", () => {
  const matcher = createLogMatcher();

  it.each([
    "console.error(error)",
    "logger.warn(error)",
    "this.logger.info(error)",
    "logger.bind({ requestId }).error(error)",
    'logging.getLogger("api").debug(error)',
    'console["error"](error)',
    'this["logger"]["warn"](error)',
    'logging["getLogger"]("api")["debug"](error)',
  ])("recognizes receiver-shaped logging call %s", (source) => {
    expect(isLoggingCall(matcher, source)).toBe(true);
  });

  it.each([
    "metrics.error(error)",
    "logger.flush(error)",
    "console[method](error)",
    "logEvent(error)",
  ])("does not infer that %s is a logging call", (source) => {
    expect(isLoggingCall(matcher, source)).toBe(false);
  });

  it("recognizes only configured static logging function names", () => {
    const configured = createLogMatcher({ logFunctions: ["logEvent"] });

    expect(isLoggingCall(configured, "logEvent(error)")).toBe(true);
    expect(isLoggingCall(configured, "events.logEvent(error)")).toBe(true);
    expect(isLoggingCall(configured, "auditEvent(error)")).toBe(false);
    expect(isLoggingCall(configured, 'events["logEvent"](error)')).toBe(true);
    expect(isLoggingCall(matcher, "logEvent(error)")).toBe(false);
    expect(isLoggingCall(configured, "events[method](error)")).toBe(false);
  });

  it("extends receiver names without changing the defaults", () => {
    const configured = createLogMatcher({ loggerNames: ["observability"] });

    expect(isLoggingCall(configured, "observability.error(error)")).toBe(true);
    expect(isLoggingCall(matcher, "observability.error(error)")).toBe(false);
    expect(isLoggingCall(configured, "console.error(error)")).toBe(true);
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
