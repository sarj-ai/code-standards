import { join } from "node:path";

import * as parser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { Linter } from "eslint";
import { afterAll, describe, expect, it } from "vitest";

import rule from "../../src/rules/prefer-server-data-preparation.js";
import { verifyRuleExamples } from "../../src/verify-rule-examples.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const PARSER_OPTIONS = { projectService: { allowDefaultProject: ["*.tsx"], defaultProject: "tsconfig.json" }, tsconfigRootDir: join(import.meta.dirname, "..", "fixtures", "minimal-consumer"), ecmaFeatures: { jsx: true } };
const TESTER = new RuleTester({ languageOptions: { parser, parserOptions: PARSER_OPTIONS } });
const CLIENT = "'use client'; ";
const VIEW = "export function View({ rows }: { rows: readonly { language: string; enabled: boolean }[] }) { const languages = rows.map(row => row.language); return <select onChange={event => console.log(event.currentTarget.value)}>{languages.map(language => <option key={language}>{language}</option>)}</select>; }";
const CASE = CLIENT + VIEW;

TESTER.run("prefer-server-data-preparation", rule, {
  valid: [
    { name: "raw records are needed by editing logic", filename: "probe.tsx", code: CASE.replace("return <select", "const edit = () => updateRows(rows); return <select") },
    { name: "a lookup still needs the raw records", filename: "probe.tsx", code: CASE.replace("return <select", "const active = rows.find(row => row.enabled); return <select") },
    { name: "raw collection forwarding", filename: "probe.tsx", code: CASE.replace("return <select", "sendRows(rows); return <select") },
    { name: "whole records forwarded by another render loop", filename: "probe.tsx", code: CASE.replace("return <select", "const editors = rows.map(row => <Editor row={row} />); return <select") },
    { name: "an identity map is not data preparation", filename: "probe.tsx", code: CASE.replace("row => row.language", "row => row") },
    { name: "a constant map does not project an input field", filename: "probe.tsx", code: CASE.replace("row => row.language", "row => 'ready'") },
    { name: "an unused destructuring default can require the browser", filename: "probe.tsx", code: CASE.replace("row => row.language", "({ language, unused = window.location.href }) => language") },
    { name: "noninteractive boundary belongs to its existing owner", filename: "probe.tsx", code: CASE.replace(" onChange={event => console.log(event.currentTarget.value)}", "") },
    { name: "generated source", filename: "probe.tsx", code: "// @generated\n" + CASE },
    { name: "test source", filename: "probe.test.tsx", code: CASE },
    { name: "late string is not a client boundary", filename: "probe.tsx", code: "const ready = true; 'use client'; " + VIEW },
    { name: "server component", filename: "probe.tsx", code: VIEW },
    { name: "client directive is a literal rather than a prologue", filename: "probe.tsx", code: "const mode = 'use client'; " + VIEW },
    { name: "rendering elements is client presentation", filename: "probe.tsx", code: CLIENT + "export function View({ rows }: { rows: readonly string[] }) { return <select>{rows.map(language => <option key={language}>{language}</option>)}</select>; }" },
    { name: "interactive query is captured", filename: "probe.tsx", code: CASE.replace("rows.map(row => row.language)", "rows.filter(row => row.language === query)") },
    { name: "another prop can change interactively", filename: "probe.tsx", code: CASE.replace("rows.map(row => row.language)", "rows.filter(row => row.language === selectedLanguage)") },
    { name: "browser API call", filename: "probe.tsx", code: CASE.replace("row => row.language", "row => window.localStorage.getItem(row.language)") },
    { name: "opaque formatter", filename: "probe.tsx", code: CASE.replace("row => row.language", "row => format(row.language)") },
    { name: "JSX object callback", filename: "probe.tsx", code: CASE.replace("row => row.language", "row => ({ view: <p>{row.language}</p> })") },
    { name: "effect callback", filename: "probe.tsx", code: CASE.replace("const languages = rows.map(row => row.language);", "useEffect(() => { const languages = rows.map(row => row.language); consume(languages); }, [rows]); const languages = [];") },
    { name: "event handler", filename: "probe.tsx", code: CLIENT + "export function View({ rows }: { rows: string[] }) { return <button onClick={() => { const values = rows.map(row => row); consume(values); }}>Show</button>; }" },
    { name: "memo lifecycle", filename: "probe.tsx", code: CASE.replace("rows.map(row => row.language)", "useMemo(() => rows.map(row => row.language), [rows])") },
    { name: "local state collection", filename: "probe.tsx", code: CASE.replace("const languages = rows", "const [draftRows] = useState(rows); const languages = draftRows") },
    { name: "array mutation is another owner", filename: "probe.tsx", code: CASE.replace("rows.map(row => row.language)", "rows.sort()") },
    { name: "custom map signature", filename: "probe.tsx", code: CLIENT + "export function View({ rows }: { rows: { map: (fn: (row: {language: string}) => string) => string[] } }) { const languages = rows.map(row => row.language); return <p onClick={() => console.log(languages)}>{languages}</p>; }" },
    { name: "unknown array type", filename: "probe.tsx", code: CASE.replace("readonly { language: string; enabled: boolean }[]", "any") },
    { name: "async callback", filename: "probe.tsx", code: CASE.replace("row => row.language", "async row => row.language") },
    { name: "multiple statements", filename: "probe.tsx", code: CASE.replace("row => row.language", "row => { log(row); return row.language; }") },
    { name: "computed path captures external data", filename: "probe.tsx", code: CASE.replace("row => row.language", "row => row[field]") },
    { name: "dynamic property source", filename: "probe.tsx", code: CASE.replace("rows.map", "rows[field].map") },
    { name: "optional source", filename: "probe.tsx", code: CASE.replace("rows.map", "rows?.map") },
    { name: "parameter rebound before projection", filename: "probe.tsx", code: CASE.replace("const languages", "rows = replacement; const languages") },
    { name: "receiver alias remains unsupported", filename: "probe.tsx", code: CASE.replace("const languages = rows", "const alias = rows; const languages = alias") },
    { name: "second callback parameter", filename: "probe.tsx", code: CASE.replace("row => row.language", "(row, index) => index") },
    { name: "callback this argument", filename: "probe.tsx", code: CASE.replace("row => row.language)", "row => row.language, context)") },
  ],
  invalid: [
    { name: "a second field-only display loop preserves preparation", filename: "probe.tsx", code: CASE.replace("return <select", "const views = rows.map(row => <option key={row.language}>{row.language}</option>); return <select"), errors: [{ messageId: "prepareData" }] },
    { name: "state makes an otherwise custom view interactive", filename: "probe.tsx", code: CASE.replace(CLIENT, CLIENT + "import { useState } from 'react'; ").replace("const languages", "const [open, setOpen] = useState(false); const languages").replace("<select onChange={event => console.log(event.currentTarget.value)}>", "<CustomSelect open={open} onOpenChange={setOpen}>").replace("</select>", "</CustomSelect>"), errors: [{ messageId: "prepareData" }] },
    { name: "saved language projection", filename: "probe.tsx", code: CASE, errors: [{ messageId: "prepareData" }] },
    { name: "mutable native array", filename: "probe.tsx", code: CASE.replace("rows: readonly", "rows:"), errors: [{ messageId: "prepareData" }] },
    { name: "nested scenario projection", filename: "probe.tsx", code: CLIENT + "export function View({ scenario }: { scenario: {config: {settings: readonly {language: string}[]}} }) { const languages = scenario.config.settings.map(setting => setting.language); return <p onClick={() => console.log(languages)}>{languages}</p>; }", errors: [{ messageId: "prepareData" }] },
    { name: "first prop object", filename: "probe.tsx", code: CASE.replace("{ rows }: { rows:", "props: { rows:").replace("= rows.map", "= props.rows.map"), errors: [{ messageId: "prepareData" }] },
    { name: "callback parameter destructuring", filename: "probe.tsx", code: CASE.replace("row => row.language", "({ language }) => language"), errors: [{ messageId: "prepareData" }] },
    { name: "callback block return", filename: "probe.tsx", code: CASE.replace("row => row.language", "row => { return row.language; }"), errors: [{ messageId: "prepareData" }] },
    { name: "data object projection", filename: "probe.tsx", code: CASE.replace("row => row.language", "row => ({ label: row.language, value: row.language })"), errors: [{ messageId: "prepareData" }] },
    { name: "data-only filter", filename: "probe.tsx", code: CASE.replace("rows.map(row => row.language)", "rows.filter(row => row.enabled)"), errors: [{ messageId: "prepareData" }] },
    { name: "static predicate", filename: "probe.tsx", code: CASE.replace("rows.map(row => row.language)", "rows.filter(row => row.language !== '')"), errors: [{ messageId: "prepareData" }] },
    { name: "negated predicate", filename: "probe.tsx", code: CASE.replace("rows.map(row => row.language)", "rows.filter(row => !row.enabled)"), errors: [{ messageId: "prepareData" }] },
    { name: "one finding for a projection chain", filename: "probe.tsx", code: CASE.replace("rows.map(row => row.language)", "rows.filter(row => row.enabled).map(row => row.language)"), errors: [{ messageId: "prepareData" }] },
    { name: "static part of a union with local edits", filename: "probe.tsx", code: CASE.replace("const languages = rows.map(row => row.language)", "const [pending] = useState([]); const languages = [...new Set(rows.map(row => row.language)).union(new Set(pending))]"), errors: [{ messageId: "prepareData" }] },
    { name: "erased wrappers preserve source", filename: "probe.tsx", code: CASE.replace("= rows.map", "= (rows as typeof rows)!.map"), errors: [{ messageId: "prepareData" }] },
    { name: "fixed string property", filename: "probe.tsx", code: CASE.replace("row => row.language", "row => row['language']"), errors: [{ messageId: "prepareData" }] },
    { name: "conditional data projection", filename: "probe.tsx", code: CASE.replace("row => row.language", "row => row.enabled ? row.language : ''"), errors: [{ messageId: "prepareData" }] },
    { name: "logical projection", filename: "probe.tsx", code: CASE.replace("row => row.language", "row => row.language || ''"), errors: [{ messageId: "prepareData" }] },
  ],
});

it("executes documented examples", async () => { await verifyRuleExamples(rule); });

it("abstains without native type services", () => {
  const linter = new Linter();
  const result = linter.verify(CASE, [{ files: ["**/*.tsx"], languageOptions: { parser }, plugins: { sarj: { rules: { "prefer-server-data-preparation": rule } } }, rules: { "sarj/prefer-server-data-preparation": "warn" } }], { filename: "view.tsx" });
  expect(result).toEqual([]);
});

it("does not rewrite a server boundary and converges", () => {
  const linter = new Linter({ cwd: PARSER_OPTIONS.tsconfigRootDir });
  const configuration = [{ files: ["**/*.tsx"], languageOptions: { parser, parserOptions: PARSER_OPTIONS }, plugins: { sarj: { rules: { "prefer-server-data-preparation": rule } } }, rules: { "sarj/prefer-server-data-preparation": "warn" as const } }];
  const filename = join(PARSER_OPTIONS.tsconfigRootDir, "probe.tsx");
  const first = linter.verifyAndFix(CASE, configuration, { filename });
  expect(first.output).toBe(CASE);
  expect(first.fixed).toBe(false);
  expect(first.messages.map(message => message.messageId)).toEqual(["prepareData"]);
  expect(linter.verifyAndFix(first.output, configuration, { filename })).toEqual(first);
  const suppressed = "/* eslint-disable sarj/prefer-server-data-preparation -- input changes in a client producer */\n" + CASE;
  expect(linter.verify(suppressed, configuration, { filename })).toEqual([]);
});
