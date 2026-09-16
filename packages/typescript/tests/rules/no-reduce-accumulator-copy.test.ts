import { join } from "node:path";

import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule from "../../src/rules/no-reduce-accumulator-copy.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const RULE_TESTER = new RuleTester({ languageOptions: { parser: tsParser, parserOptions: {
  projectService: { allowDefaultProject: ["*.ts*"] }, tsconfigRootDir: join(import.meta.dirname, "..", "fixtures"),
} } });

RULE_TESTER.run("no-reduce-accumulator-copy", rule, {
  valid: [
    "declare const pages: string[][]; pages.reduce<string[]>((acc, page) => { { const acc: string[] = []; acc.slice(); } return page; }, []);",
    "declare const pages: string[][]; pages.reduce<string[]>((acc, page) => page.slice(), []);",
    "declare const pairs: [string, string][]; pairs.reduce<Record<string, string>>((acc, [key, value]) => Object.assign(acc, { [key]: value }), {});",
    "declare const values: string[]; const Object = { assign: (...args: unknown[]) => ({}) }; values.reduce((acc) => Object.assign({}, acc), {});",
    "declare const pages: string[][]; const rows = pages.flatMap(page => page);",
    "declare const pages: string[][]; pages.reduce<string[]>((acc, page) => { acc.push(...page); return acc; }, []);",
    "declare const pages: string[][]; declare const seed: string[]; pages.reduce((acc, page) => acc.concat(page), seed);",
    "declare const pages: string[][]; pages.reduce((acc, page) => acc.concat(page));",
    "declare const values: number[]; values.reduce((acc, value) => acc + value, 0);",
    "declare const values: string[]; values.reduce((acc, value) => acc.concat(value), '');",
    "declare const pages: string[][]; pages.reduce<string[]>((acc, page) => { const later = () => acc.slice(); return page; }, []);",
    "declare const pages: string[][]; pages.reduce<string[]>((acc, page) => { function copy(acc: string[]) { return acc.slice(); } return page; }, []);",
    "declare const pages: string[][]; pages.reduce<string[]>((acc, page) => { acc = page; return acc.slice(); }, []);",
    "declare const custom: { reduce(fn: (acc: string[], x: string[]) => string[], seed: string[]): string[] }; custom.reduce((acc, x) => acc.concat(x), []);",
    "declare const pages: string[][]; const Array = { from: (x: string[]) => x }; pages.reduce<string[]>((acc) => Array.from(acc), []);",
    { code: "// @generated\ndeclare const pages: string[][]; pages.reduce<string[]>((acc, page) => acc.concat(page), []);" },
  ],
  invalid: [
    { code: "declare const pairs: [string, string][]; pairs.reduce<Record<string, string>>((acc, [key, value]) => Object.assign({}, acc, { [key]: value }), {});", errors: [{ messageId: "copy" }] },
    { code: "declare const pairs: [string, string][]; pairs.reduce<Record<string, string>>((acc, [key, value]) => ({ ...acc, [key]: value }), {});", errors: [{ messageId: "copy" }] },
    { code: "declare const pages: string[][]; pages.reduce<string[]>((acc, page) => acc.concat(page), []);", errors: [{ messageId: "copy" }] },
    { code: "declare const pages: string[][]; pages.reduceRight<string[]>((acc, page) => [...acc, ...page], []);", errors: [{ messageId: "copy" }] },
    { code: "declare const pages: string[][]; pages.reduce<string[]>((acc, page) => { const next = acc.slice(); next.push(...page); return next; }, []);", errors: [{ messageId: "copy" }] },
    { code: "declare const pages: string[][]; pages.reduce<string[]>((acc) => Array.from(acc), []);", errors: [{ messageId: "copy" }] },
    { code: "declare const pages: string[][]; pages.reduce<string[]>((acc) => acc['toReversed'](), []);", errors: [{ messageId: "copy" }] },
    { code: "declare const pages: string[][]; pages.reduce<string[]>((acc, page, index) => acc.concat(page), []);", errors: [{ messageId: "copy" }] },
  ],
});

const SYNTAX_TESTER = new RuleTester({ languageOptions: { parser: tsParser } });

SYNTAX_TESTER.run("no-reduce-accumulator-copy without a type project", rule, {
  valid: ["items.reduce((acc, item) => acc.concat(item), []);"],
  invalid: [],
});
