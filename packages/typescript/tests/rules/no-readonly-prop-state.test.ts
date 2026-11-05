import { join } from "node:path";

import * as parser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { Linter } from "eslint";
import { afterAll, describe, expect, it } from "vitest";

import rule from "../../src/rules/no-readonly-prop-state.js";
import { verifyRuleExamples } from "../../src/verify-rule-examples.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const PARSER_OPTIONS = { projectService: { allowDefaultProject: ["*.tsx"], defaultProject: "tsconfig.json" }, tsconfigRootDir: join(import.meta.dirname, "..", "fixtures", "minimal-consumer"), ecmaFeatures: { jsx: true } };
const TESTER = new RuleTester({ languageOptions: { parser, parserOptions: PARSER_OPTIONS } });
const PREFIX = "import { useState } from 'react'; ";
const VIEW = "export function View({ status }: { status: string }) { const [value, setValue] = useState(status); return <p>{value}</p>; }";
const CASE = PREFIX + VIEW;

TESTER.run("no-readonly-prop-state", rule, {
  valid: [
    { name: "callable primitive intersections remain opaque", filename: "probe.tsx", code: CASE.replace("{ status: string }", "{ status: string & (() => string) }") },
    { name: "structural object props can execute a callable initializer", filename: "probe.tsx", code: PREFIX + "const initial = Object.assign(() => ({ label: 'computed' }), { label: 'descriptor' }); export function View({ status }: { status: { label: string } }) { const [value] = useState(status); return <p>{value.label}</p>; } export const Example = <View status={initial} />;" },
    { name: "void can hide ignored callable return values", filename: "probe.tsx", code: CASE.replace("{ status: string }", "{ status: void }").replace("{value}</p>", "{String(value)}</p>") },
    { name: "eager array props have structural object types", filename: "probe.tsx", code: CASE.replace("{ status: string }", "{ status: string[] }") },
    { name: "module-level state belongs to hook-placement checks", filename: "probe.tsx", code: PREFIX + "const status = 'ready'; const [value] = useState(status); export const View = () => <p>{value}</p>;" },
    { name: "legacy Function can execute initialization without call signatures", filename: "probe.tsx", code: CASE.replace("{ status: string }", "{ status: Function }") },
    { name: "legacy CallableFunction can execute initialization", filename: "probe.tsx", code: CASE.replace("{ status: string }", "{ status: CallableFunction }") },
    { name: "legacy NewableFunction remains unsupported", filename: "probe.tsx", code: CASE.replace("{ status: string }", "{ status: NewableFunction }") },
    { name: "legacy Function in a union can execute initialization", filename: "probe.tsx", code: CASE.replace("{ status: string }", "{ status: string | Function }") },
    { name: "function prop is a lazy initializer", filename: "probe.tsx", code: CASE.replace("{ status: string }", "{ status: () => string }") },
    { name: "callable union can invoke initialization", filename: "probe.tsx", code: CASE.replace("{ status: string }", "{ status: string | (() => string) }") },
    { name: "opaque eager type", filename: "probe.tsx", code: CASE.replace("{ status: string }", "{ status: unknown }") },
    { name: "a cast cannot disguise a callable prop", filename: "probe.tsx", code: CASE.replace("{ status: string }", "{ status: () => string }").replace("useState(status)", "useState(status as unknown as string)") },
    { name: "calling a lazy prop is opaque initialization", filename: "probe.tsx", code: CASE.replace("{ status: string }", "{ status: () => string }").replace("useState(status)", "useState(() => status())") },
    { name: "import-equals syntax remains unsupported", filename: "probe.tsx", code: CASE.replace("import { useState } from 'react';", "import React = require('react');").replace("= useState(", "= React.useState(") },
    { name: "dynamic evaluation can observe the updater", filename: "probe.tsx", code: CASE.replace("return <p>", "eval('setValue(status)'); return <p>") },
    { name: "interactive draft", filename: "probe.tsx", code: CASE.replace("<p>{value}</p>", "<input value={value} onChange={event => setValue(event.target.value)} />") },
    { name: "updater passed to a child", filename: "probe.tsx", code: CASE.replace("<p>{value}</p>", "<Editor value={value} onChange={setValue} />") },
    { name: "updater captured by another closure", filename: "probe.tsx", code: CASE.replace("return <p>", "const update = () => setValue('ready'); expose(update); return <p>") },
    { name: "opaque lazy snapshot", filename: "probe.tsx", code: CASE.replace("useState(status)", "useState(() => createSnapshot(status))") },
    { name: "browser snapshot", filename: "probe.tsx", code: CASE.replace("useState(status)", "useState(() => window.location.hash)") },
    { name: "constant initialization belongs to another policy", filename: "probe.tsx", code: CASE.replace("useState(status)", "useState(false)") },
    { name: "local hook with the same spelling", filename: "probe.tsx", code: "const useState = toolkit.state; " + VIEW },
    { name: "shadowed React import", filename: "probe.tsx", code: PREFIX + VIEW.replace("{ status: string })", "{ status: string }, useState)") },
    { name: "type-only import", filename: "probe.tsx", code: CASE.replace("import { useState }", "import type { useState }") },
    { name: "foreign package", filename: "probe.tsx", code: CASE.replace("from 'react'", "from './state'") },
    { name: "unread value remains upstream owned", filename: "probe.tsx", code: CASE.replace("{value}</p>", "Ready</p>") },
    { name: "rest tuple escapes", filename: "probe.tsx", code: CASE.replace("[value, setValue]", "[value, ...rest]") },
    { name: "whole tuple escapes", filename: "probe.tsx", code: PREFIX + "export function View({ status }) { const state = useState(status); return <Editor state={state} />; }" },
    { name: "dynamic path", filename: "probe.tsx", code: CASE.replace("useState(status)", "useState(status[key])") },
    { name: "optional path", filename: "probe.tsx", code: CASE.replace("useState(status)", "useState(status?.value)") },
    { name: "alias not proven", filename: "probe.tsx", code: CASE.replace("const [value", "const alias = status; const [value").replace("useState(status)", "useState(alias)") },
    { name: "parameter mutation", filename: "probe.tsx", code: CASE.replace("const [value", "status = 'ready'; const [value") },
    { name: "nested helper is not render scope", filename: "probe.tsx", code: PREFIX + "export function View({ status }) { function build() { const [value] = useState(status); return value; } return <p>{build()}</p>; }" },
    { name: "default parameter lifecycle", filename: "probe.tsx", code: CASE.replace("{ status }", "{ status = 'ready' }") },
    { name: "ref explicitly records lifecycle", filename: "probe.tsx", code: "import { useRef } from 'react'; export function View({ status }) { const initial = useRef(status); return <p>{initial.current}</p>; }" },
    { name: "generated module", filename: "probe.tsx", code: "// @generated\n" + CASE },
    { name: "test source", filename: "probe.test.tsx", code: CASE },
  ],
  invalid: [
    { name: "primitive brands retain eager prop coverage", filename: "probe.tsx", code: CASE.replace("{ status: string }", "{ status: string & { readonly brand: 'status' } }"), errors: [{ messageId: "readonlyPropState" }] },
    { name: "primitive union retains eager prop coverage", filename: "probe.tsx", code: CASE.replace("{ status: string }", "{ status: string | number | null }"), errors: [{ messageId: "readonlyPropState" }] },
    { name: "bigint retains eager prop coverage", filename: "probe.tsx", code: CASE.replace("{ status: string }", "{ status: bigint }"), errors: [{ messageId: "readonlyPropState" }] },
    { name: "explicit lazy return stores an object prop as data", filename: "probe.tsx", code: CASE.replace("{ status: string }", "{ status: string[] }").replace("useState(status)", "useState(() => status)"), errors: [{ messageId: "readonlyPropState" }] },
    { name: "an explicit lazy callback stores a function prop as data", filename: "probe.tsx", code: CASE.replace("{ status: string }", "{ status: () => string }").replace("useState(status)", "useState(() => status)").replace("<p>{value}</p>", "<button onClick={value}>Show</button>"), errors: [{ messageId: "readonlyPropState" }] },
    { name: "unobserved updater", filename: "probe.tsx", code: CASE, errors: [{ messageId: "readonlyPropState" }] },
    { name: "omitted updater", filename: "probe.tsx", code: CASE.replace("[value, setValue]", "[value]"), errors: [{ messageId: "readonlyPropState" }] },
    { name: "hole updater", filename: "probe.tsx", code: CASE.replace("[value, setValue]", "[value,]"), errors: [{ messageId: "readonlyPropState" }] },
    { name: "renamed import", filename: "probe.tsx", code: CASE.replace("{ useState }", "{ useState as state }").replace("= useState(", "= state("), errors: [{ messageId: "readonlyPropState" }] },
    { name: "namespace import", filename: "probe.tsx", code: CASE.replace("{ useState }", "* as Hooks").replace("= useState(", "= Hooks.useState("), errors: [{ messageId: "readonlyPropState" }] },
    { name: "default import", filename: "probe.tsx", code: CASE.replace("{ useState }", "React").replace("= useState(", "= React['useState']("), errors: [{ messageId: "readonlyPropState" }] },
    { name: "nested prop", filename: "probe.tsx", code: CASE.replace("{ status: string }", "{ status: {current: {language: string}} }").replace("useState(status)", "useState(status.current.language)"), errors: [{ messageId: "readonlyPropState" }] },
    { name: "whole props parameter", filename: "probe.tsx", code: CASE.replace("{ status }: { status: string }", "props: { status: string }").replace("useState(status)", "useState(props.status)"), errors: [{ messageId: "readonlyPropState" }] },
    { name: "destructured prop alias", filename: "probe.tsx", code: CASE.replace("{ status }", "{ status: current }").replace("useState(status)", "useState(current)"), errors: [{ messageId: "readonlyPropState" }] },
    { name: "lazy direct prop", filename: "probe.tsx", code: CASE.replace("useState(status)", "useState(() => status)"), errors: [{ messageId: "readonlyPropState" }] },
    { name: "lazy block", filename: "probe.tsx", code: CASE.replace("useState(status)", "useState(function () { return status; })"), errors: [{ messageId: "readonlyPropState" }] },
    { name: "erased wrappers", filename: "probe.tsx", code: CASE.replace("useState(status)", "(useState((status as string)!) as [string, (value: string) => void])"), errors: [{ messageId: "readonlyPropState" }] },
    { name: "type query does not update state", filename: "probe.tsx", code: CASE.replace("return <p>", "type Updater = typeof setValue; return <p>"), errors: [{ messageId: "readonlyPropState" }] },
  ],
});

it("executes documented examples", async () => { await verifyRuleExamples(rule); });

it("keeps lifecycle changes manual and respects an explicit suppression", () => {
  const source = CASE.replace("useState(status)", "useState(() => status)");
  const linter = new Linter();
  const configuration = [{ files: ["**/*.tsx"], languageOptions: { parser }, plugins: { sarj: { rules: { "no-readonly-prop-state": rule } } }, rules: { "sarj/no-readonly-prop-state": "warn" as const } }];
  const first = linter.verifyAndFix(source, configuration, { filename: "probe.tsx" });
  expect(first.fixed).toBe(false);
  expect(first.output).toBe(source);
  expect(first.messages.map(message => message.messageId)).toEqual(["readonlyPropState"]);
  const second = linter.verifyAndFix(first.output, configuration, { filename: "probe.tsx" });
  expect(second).toEqual(first);
  const suppressed = "/* eslint-disable sarj/no-readonly-prop-state -- intentional mount snapshot */\n" + source;
  expect(linter.verify(suppressed, configuration, { filename: "probe.tsx" })).toEqual([]);
});

it("abstains for eager inputs without type information", () => {
  const linter = new Linter();
  const configuration = [{ files: ["**/*.tsx"], languageOptions: { parser }, plugins: { sarj: { rules: { "no-readonly-prop-state": rule } } }, rules: { "sarj/no-readonly-prop-state": "warn" as const } }];
  expect(linter.verify(CASE, configuration, { filename: "probe.tsx" })).toEqual([]);
});
