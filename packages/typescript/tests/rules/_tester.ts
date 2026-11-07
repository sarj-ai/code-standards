import { join } from "node:path";

import { RuleTester } from "oxlint/plugins-dev";
import { describe, it } from "vitest";

RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

export { RuleTester };

export const FIXTURES = join(import.meta.dirname, "..", "fixtures");

export function ruleTester({ lang = "ts", cwd = process.cwd() }: { lang?: RuleTester.Language; cwd?: string } = {}): RuleTester {
  return new RuleTester({ eslintCompat: true, cwd, languageOptions: { parserOptions: { lang } } });
}

type CaseDefaults = Pick<RuleTester.ValidTestCase, "filename" | "settings">;

export function withDefaults(defaults: CaseDefaults, cases: RuleTester.TestCases): RuleTester.TestCases {
  return {
    // eslint-disable-next-line @sarj/no-runtime-typeof -- Oxlint's RuleTester takes a valid case as a bare code string or an untagged case object.
    valid: cases.valid.map((test) => (typeof test === "string" ? { ...defaults, code: test } : { ...defaults, ...test })),
    invalid: cases.invalid.map((test) => ({ ...defaults, ...test })),
  };
}

export function typed(cases: RuleTester.TestCases): RuleTester.TestCases {
  return withDefaults({ settings: { sarj: { typeAware: true } } }, cases);
}

export function untyped(cases: RuleTester.TestCases): RuleTester.TestCases {
  return withDefaults({ settings: { sarj: { typeAware: false } } }, cases);
}
