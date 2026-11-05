import type { ESLint } from "eslint";
import type { z } from "zod";

import { resolve } from "node:path";

import { record } from "./tool-json.mts";
import { CallableSchema, DeclaredRequirementSchema, FileExecutionsSchema, type RuleExecutionStateSchema, type FileExecutionSchema } from "./eslint-tool-schemas.mts";

export type RuleExecutionState = z.infer<typeof RuleExecutionStateSchema>;
export interface RuleExecutionSummary {
  readonly ruleId: string;
  readonly execution: RuleExecutionState;
  readonly requiresTypeInformation: boolean | null;
  readonly fileCount: number;
  readonly reason?: string;
}
type FileExecution = z.infer<typeof FileExecutionSchema>;
interface TrackingRequest {
  readonly full: boolean;
  readonly rules: ReadonlySet<string>;
}

function tracking(
  rule: Record<string, unknown>,
): (() => FileExecution[]) | null {
  const begin = rule["trackExecution"];
  if (!CallableSchema.validate(begin)) return null;
  const session = record(begin.call(rule), "rule execution tracker");
  const finish = session["finish"];
  if (!CallableSchema.validate(finish))
    throw new Error("Rule execution tracker must expose finish");
  return () => FileExecutionsSchema.parse(finish.call(session));
}

function key(row: {
  readonly ruleId: string;
  readonly filePath: string;
}): string {
  return JSON.stringify([row.ruleId, row.filePath]);
}

export function mergeRuleExecutions(
  rows: readonly RuleExecutionSummary[],
): RuleExecutionSummary[] {
  const groups = new Map<string, RuleExecutionSummary>();
  for (const row of rows) {
    const identity = JSON.stringify([
      row.ruleId,
      row.execution,
      row.requiresTypeInformation,
      row.reason ?? null,
    ]);
    const previous = groups.get(identity);
    groups.set(identity, {
      ruleId: row.ruleId,
      execution: row.execution,
      requiresTypeInformation: row.requiresTypeInformation,
      fileCount: row.fileCount + (previous?.fileCount ?? 0),
      ...(row.reason === undefined ? {} : { reason: row.reason }),
    });
  }
  return [...groups.values()].toSorted(
    (left, right) =>
      left.ruleId.localeCompare(right.ruleId) ||
      left.execution.localeCompare(right.execution) ||
      (left.reason ?? "").localeCompare(right.reason ?? ""),
  );
}

async function beginTracking(
  analyzer: ESLint,
  files: readonly string[],
  request: TrackingRequest,
) {
  const expected = new Map<string, FileExecution>();
  const trackers = new Map<object, () => FileExecution[]>();
  const fallbacks = new Map<string, RuleExecutionSummary>();
  function fallback(row: Omit<RuleExecutionSummary, "fileCount">): void {
    const identity = JSON.stringify([
      row.ruleId,
      row.execution,
      row.requiresTypeInformation,
      row.reason ?? null,
    ]);
    const previous = fallbacks.get(identity);
    fallbacks.set(identity, {
      ...row,
      fileCount: (previous?.fileCount ?? 0) + 1,
    });
  }
  function finishTrackers(): FileExecution[] {
    const rows: FileExecution[] = [];
    const errors: unknown[] = [];
    for (const finish of trackers.values()) {
      try {
        rows.push(...finish());
      } catch (error) {
        errors.push(error);
      }
    }
    trackers.clear();
    if (errors.length > 0)
      throw new AggregateError(errors, "Rule execution tracker cleanup failed");
    return rows;
  }
  try {
    for (const file of new Set(files.map((path) => resolve(path)))) {
      const filePath = resolve(file);
      const configured: unknown = await analyzer.calculateConfigForFile(file);
      if (configured === undefined) {
        for (const ruleId of request.rules) {
          if (!ruleId.startsWith("@sarj/")) continue;
          const row: FileExecution = {
            ruleId,
            filePath,
            execution: "ignored",
            requiresTypeInformation: null,
            reason: "input-not-configured",
          };
          fallback(row);
        }
        continue;
      }
      const config = record(configured, "effective ESLint config");
      const settings = record(config["rules"] ?? {}, "effective ESLint rules");
      const plugins = record(
        config["plugins"] ?? {},
        "effective ESLint plugins",
      );
      const plugin = record(plugins["@sarj"] ?? {}, "Sarj ESLint plugin");
      const modules = record(plugin["rules"] ?? {}, "Sarj ESLint rules");
      const selected = request.full
        ? Object.keys(settings).filter((rule) => rule.startsWith("@sarj/"))
        : [...request.rules].filter((rule) => rule.startsWith("@sarj/"));
      for (const ruleId of selected) {
        const raw = settings[ruleId];
        const level: unknown = Array.isArray(raw) ? raw[0] : raw;
        const enabled = level !== undefined && level !== 0 && level !== "off";
        const module = modules[ruleId.slice("@sarj/".length)];
        const rule =
          module === undefined ? null : record(module, "native ESLint rule");
        const documentation =
          rule?.["documentation"] === undefined
            ? {}
            : record(rule["documentation"], "native rule documentation");
        const declared = documentation["requiresTypeInformation"];
        const required = DeclaredRequirementSchema.parse(declared);
        const row: FileExecution = {
          ruleId,
          filePath,
          execution: enabled ? "untracked" : "disabled",
          requiresTypeInformation: required,
          reason: enabled ? "execution-reporting-unavailable" : "rule-disabled",
        };
        if (!enabled || rule === null) {
          fallback(row);
          continue;
        }
        if (required === null) {
          fallback({ ...row, reason: "requirements-not-declared" });
          continue;
        }
        if (!trackers.has(rule)) {
          const capability = tracking(rule);
          if (capability === null) {
            fallback(row);
            continue;
          }
          trackers.set(rule, capability);
        }
        expected.set(key(row), {
          ...row,
          requiresTypeInformation: required,
          reason: "rule-not-initialized",
        });
      }
    }
  } catch (error) {
    try {
      finishTrackers();
    } catch (cleanup) {
      throw new AggregateError(
        [error, cleanup],
        "Rule execution preparation and cleanup failed",
        { cause: cleanup },
      );
    }
    throw error;
  }
  return {
    finish(): RuleExecutionSummary[] {
      for (const row of finishTrackers()) {
        const pending = expected.get(key(row));
        if (pending === undefined) continue;
        if (pending.requiresTypeInformation !== row.requiresTypeInformation)
          throw new Error(
            "Rule execution requirements changed during analysis",
          );
        expected.set(key(row), row);
      }
      const observed = [...expected.values()].map((row) => {
        const summary = {
          ruleId: row.ruleId,
          execution: row.execution,
          requiresTypeInformation: row.requiresTypeInformation,
          fileCount: 1,
        };
        return row.reason === undefined
          ? summary
          : { ...summary, reason: row.reason };
      });
      return mergeRuleExecutions([...fallbacks.values(), ...observed]);
    },
  };
}

/** Track the actual configured rule instances and preserve native lint failures. */
export async function lintWithRuleExecutions(
  analyzer: ESLint,
  files: string[],
  request: TrackingRequest,
): Promise<{
  readonly results: ESLint.LintResult[];
  readonly executions: RuleExecutionSummary[];
}> {
  const tracker = await beginTracking(analyzer, files, request);
  let results: ESLint.LintResult[];
  try {
    results = await analyzer.lintFiles(files);
  } catch (error) {
    try {
      tracker.finish();
    } catch (cleanup) {
      throw new AggregateError(
        [error, cleanup],
        "Native lint and tracker cleanup failed",
        { cause: cleanup },
      );
    }
    throw error;
  }
  return { results, executions: tracker.finish() };
}
