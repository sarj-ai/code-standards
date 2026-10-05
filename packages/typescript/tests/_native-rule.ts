import type { Context, Diagnostic, Rule } from "@oxlint/plugins";
import { RuleTester } from "oxlint/plugins-dev";

/** Observe reports while the official tester owns parsing, scopes and rule execution. */
export function ruleReports(
  rule: Rule,
  code: string,
  filename = "/repo/src/probe.ts",
  options: unknown[] = [],
): Diagnostic[] {
  const reports: Diagnostic[] = [];
  const observe = (context: Context): Context => {
    const observingContext: Context = Object.create(context) as Context;
    Object.defineProperty(observingContext, "report", {
      value: (diagnostic: Diagnostic): void => {
        reports.push(diagnostic);
      },
    });
    return observingContext;
  };
  const probe: Rule =
    "create" in rule && rule.create !== undefined
      ? {
          meta: rule.meta,
          create(context) {
            return rule.create(observe(context));
          },
        }
      : {
          meta: rule.meta,
          createOnce(context) {
            return rule.createOnce(observe(context));
          },
        };
  const describe = RuleTester.describe;
  const it = RuleTester.it;
  try {
    RuleTester.describe = (_name, callback) => callback();
    RuleTester.it = (_name, callback) => callback();
    const testCase: RuleTester.ValidTestCase = { code, filename };
    if (options.length > 0) testCase.options = options;
    new RuleTester({
      languageOptions: {
        parserOptions: { lang: filename.endsWith("x") ? "tsx" : "ts" },
      },
    }).run("probe", probe, {
      valid: [testCase],
      invalid: [],
    });
  } finally {
    RuleTester.describe = describe;
    RuleTester.it = it;
  }
  return reports;
}
