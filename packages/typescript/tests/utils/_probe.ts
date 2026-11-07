
import { RuleTester } from "oxlint/plugins-dev";

import type { Context, CreateOnceRule } from "../../src/types.js";

type ProbeOptions = Pick<RuleTester.ValidTestCase, "filename" | "options">;

export function lintOnce(code: string, rule: CreateOnceRule, options: ProbeOptions = {}): void {
  let failure: unknown = null;
  const { describe, it } = RuleTester;
  RuleTester.describe = (_name, run) => { run(); };
  RuleTester.it = (_name, run) => {
    try {
      run();
    } catch (error) {
      failure = error;
    }
  };
  try {
    new RuleTester({ eslintCompat: true, languageOptions: { parserOptions: { lang: "ts" } } })
      .run("probe", rule, { valid: [{ code, ...options }], invalid: [] });
  } finally {
    RuleTester.describe = describe;
    RuleTester.it = it;
  }
  if (failure !== null) throw failure as Error;
}

export function probe<T>(code: string, evaluate: (context: Context) => T, options: ProbeOptions = {}): T {
  let result: { value: T } | null = null;
  lintOnce(code, {
    meta: { type: "problem", schema: [], messages: {} },
    createOnce(context) {
      return {
        "Program:exit"() {
          result = { value: evaluate(context) };
        },
      };
    },
  }, options);
  if (result === null) throw new Error(`probe rule did not run on: ${code}`);
  return (result as { value: T }).value;
}
