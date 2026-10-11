// vitest: shared-module-graph
import * as parser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule from "../../src/rules/require-button-accessible-name.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;
const RULE_TESTER = new RuleTester({
  languageOptions: { parser, parserOptions: { ecmaFeatures: { jsx: true } } },
  defaultFilenames: { ts: "/repo/src/action.ts", tsx: "/repo/src/action.tsx" },
});
const OPTIONS = [
  {
    components: [{ module: "@design/actions", export: "Button" }],
    iconModules: ["@design/icons"],
  },
] as const;

RULE_TESTER.run("require-button-accessible-name", rule, {
  valid: [
    "<Trigger render={<button />}>Open</Trigger>",
    "<Trigger render={ready ? <button /> : <span />}>Open</Trigger>",
    '<button children="Save" />',
    "<div hidden><button /></div>",
    "<button><span hidden hidden={false}>Save</span></button>",
    {
      code: 'import { Button } from "@design/actions"; const node = <Button render={<a href="/">Home</a>} />;',
      options: OPTIONS,
    },
    "<button>Save</button>",
    '<button aria-label="Close"><svg /></button>',
    '<button aria-labelledby="close-label"><svg /></button>',
    '<button title="Close"><svg /></button>',
    '<button><span className="sr-only">Close</span><svg aria-hidden="true" /></button>',
    '<button><img alt="Close" /></button>',
    "<button>{label}</button>",
    "<button aria-label={label}><svg /></button>",
    "<button {...props}><svg /></button>",
    "<button><ActionContent /></button>",
    '<Button aria-label="Close"><svg /></Button>',
    "<Button>Save</Button>",
    "<button><svg><title>Close</title></svg></button>",
    "<button hidden><svg /></button>",
    "<button aria-hidden={true}><svg /></button>",
    "<button hidden={true}><svg /></button>",
    { name: "preserves shadowed undefined and unknown hidden values", code: "function render(undefined, visible) { return <><button hidden={undefined} /><button hidden={visible} /></>; }" },
    { name: "preserves nonliteral void evaluation and forwarded props", code: "<><button hidden={void effect()} /><button hidden={undefined} {...props} /></>" },
    { name: "visible undefined children still provide the button name", code: "<button><span hidden={undefined}>Save</span><span hidden={void 0}>now</span></button>" },
    {
      code: 'import { Button as Action } from "@design/actions"; function render(Action) { return <Action><svg /></Action>; }',
      options: OPTIONS,
    },
    {
      code: 'import { Button as Action } from "another-library"; const action = <Action><svg /></Action>;',
      options: OPTIONS,
    },
    { code: "<button><svg /></button>", filename: "/repo/src/action.test.tsx" },
    {
      code: "<button><svg /></button>",
      filename: "/repo/src/fixtures/action.tsx",
    },
    { code: "// @generated\n<button><svg /></button>" },
    {
      code: "// eslint-disable-next-line @rule-tester/require-button-accessible-name -- demonstrated external labeling\n<button><svg /></button>",
    },
  ],
  invalid: [
    { name: "reports an unnamed button with global undefined or void zero hidden props", code: "<><button hidden={undefined} /><button hidden={void 0} /></>", errors: [{ messageId: "missingName" }, { messageId: "missingName" }] },
    { name: "global undefined and void zero do not hide unnamed descendants", code: "<><div hidden={undefined}><button /></div><div hidden={void 0}><button /></div></>", errors: [{ messageId: "missingName" }, { messageId: "missingName" }] },
    { name: "local undefined keeps child and ancestor hidden behavior", code: "function render() { const undefined = true; return <><div hidden={undefined}><button /></div><button><span hidden={undefined}>Save</span></button></>; }", errors: [{ messageId: "missingName" }] },
    { code: "<Button />", errors: [{ messageId: "missingName" }] },
    {
      code: "<Button><svg /></Button>",
      errors: [{ messageId: "missingName" }],
    },
    {
      code: 'import { X } from "lucide-react"; const action = <Button><X /></Button>;',
      errors: [{ messageId: "missingName" }],
    },
    {
      code: 'import { X } from "lucide-react"; const action = <button><X /></button>;',
      errors: [{ messageId: "missingName" }],
    },
    {
      code: '<button><svg aria-hidden="true" /></button>',
      errors: [{ messageId: "missingName" }],
    },
    { code: "<button />", errors: [{ messageId: "missingName" }] },
    {
      code: '<button aria-label=" "><svg /></button>',
      errors: [{ messageId: "missingName" }],
    },
    {
      code: '<button aria-label={""}><svg /></button>',
      errors: [{ messageId: "missingName" }],
    },
    {
      code: '<button><span aria-hidden="true">Close</span><svg /></button>',
      errors: [{ messageId: "missingName" }],
    },
    {
      code: '<button>{null}{false}{""}<svg /></button>',
      errors: [{ messageId: "missingName" }],
    },
    {
      code: 'import { Button as Action } from "@design/actions"; import { Close } from "@design/icons"; const action = <Action><Close /></Action>;',
      options: OPTIONS,
      errors: [{ messageId: "missingName" }],
    },
    {
      code: 'import * as Actions from "@design/actions"; const action = <Actions.Button><svg /></Actions.Button>;',
      options: OPTIONS,
      errors: [{ messageId: "missingName" }],
    },
    {
      code: 'import Action from "@design/actions"; const action = <Action><svg /></Action>;',
      options: [
        { components: [{ module: "@design/actions", export: "default" }] },
      ],
      errors: [{ messageId: "missingName" }],
    },
  ],
});
