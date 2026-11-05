/**
 * @fileoverview _trackable-rule — observe rule prerequisites and completed native execution without altering diagnostics.
 */
import type { NativeRule } from "./_eslint-rule.js";

export type RuleExecutionState = "ran" | "skipped" | "untracked" | "failed";
export interface RuleExecution {
  readonly ruleId: string;
  readonly filePath: string;
  readonly execution: RuleExecutionState;
  readonly requiresTypeInformation: boolean | null;
  readonly reason?: string;
}
export interface RuleExecutionTracker {
  finish(): readonly RuleExecution[];
}
interface PendingExecution extends Omit<RuleExecution, "execution"> {
  readonly execution: RuleExecutionState | "initialized";
}

/** Tracking is opt-in and bound to the exact rule instance used by the engine. */
export function trackableRule<
  Options extends readonly unknown[],
  MessageIds extends string,
>(
  rule: NativeRule<Options, MessageIds>,
  requiresTypeInformation: boolean | null,
): NativeRule<Options, MessageIds> & {
  trackExecution(): RuleExecutionTracker;
} {
  let active: Map<string, PendingExecution> | null = null;
  const create = rule.create.bind(rule);
  const tracked = {
    ...rule,
    trackExecution(): RuleExecutionTracker {
      if (active !== null)
        throw new Error("Rule execution tracking is already active.");
      const records = new Map<string, PendingExecution>();
      active = records;
      return {
        finish(): readonly RuleExecution[] {
          if (active !== records)
            throw new Error("Rule execution tracking already finished.");
          active = null;
          return [...records.values()].map((record): RuleExecution =>
            record.execution === "initialized"
              ? {
                  ...record,
                  execution: "failed",
                  reason: "incomplete-rule-execution",
                }
              : { ...record, execution: record.execution },
          );
        },
      };
    },
    create(context: Parameters<NativeRule<Options, MessageIds>["create"]>[0]) {
      const records = active;
      if (records === null) return create(context);
      const filePath = context.filename;
      const base = {
        ruleId: "@sarj/" + rule.name,
        filePath,
        requiresTypeInformation,
      };
      records.set(filePath, { ...base, execution: "initialized" });
      try {
        const listener = create(context);
        const services = context.sourceCode.parserServices;
        const typed =
          services?.program != null &&
          services.esTreeNodeToTSNodeMap != null &&
          services.tsNodeToESTreeNodeMap != null;
        if (requiresTypeInformation === true && !typed) {
          records.set(filePath, {
            ...base,
            execution: "skipped",
            reason: "missing-type-information",
          });
          return listener;
        }
        const exit = listener["Program:exit"];
        return {
          ...listener,
          "Program:exit"(node: Parameters<NonNullable<typeof exit>>[0]): void {
            try {
              exit?.(node);
              if (active === records)
                records.set(
                  filePath,
                  requiresTypeInformation === null
                    ? {
                        ...base,
                        execution: "untracked",
                        reason: "requirements-not-declared",
                      }
                    : { ...base, execution: "ran" },
                );
            } catch (error) {
              records.set(filePath, {
                ...base,
                execution: "failed",
                reason: "rule-execution-failed",
              });
              throw error;
            }
          },
        };
      } catch (error) {
        records.set(filePath, {
          ...base,
          execution: "failed",
          reason: "rule-initialization-failed",
        });
        throw error;
      }
    },
  };
  Object.defineProperty(tracked, "trackExecution", { enumerable: false });
  return tracked;
}
