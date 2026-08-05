import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule from "../../src/rules/prefer-shadcn-primitives.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.itOnly = it.only;
RuleTester.it = it;

const ruleTester = new RuleTester({
  languageOptions: {
    parser: tsParser,
    parserOptions: { ecmaFeatures: { jsx: true } },
  },
});

ruleTester.run("prefer-shadcn-primitives", rule, {
  valid: [
    {
      name: "accepts shared primitives",
      code: `
        import { Button } from "@/components/ui/button";
        import { Input } from "@/components/ui/input";
        import { Label } from "@/components/ui/label";
        <form><Label htmlFor="name">Name</Label><Input id="name" /><Button>Save</Button></form>
      `,
    },
    {
      name: "accepts aliased shared primitives",
      code: `
        import { Button as SubmitButton } from "@/components/ui/button";
        <SubmitButton>Save</SubmitButton>
      `,
    },
    {
      name: "accepts component members",
      code: `<Form.Label><Form.Input /></Form.Label>`,
    },
    {
      name: "accepts hidden inputs",
      code: `<input name="csrf" type="hidden" value={token} />`,
    },
    {
      name: "accepts expression-wrapped hidden inputs",
      code: `<><input type={"hidden"} /><input type={\`hidden\`} /><input type={"hidden" as const} /><input type={"hidden" satisfies string} /><input type={\`${"hidden"}\`} /></>`,
    },
    {
      name: "accepts a hidden type that follows a spread",
      code: `<input {...props} type="hidden" />`,
    },
    {
      name: "ignores inputs whose effective type is unknown",
      code: `<><input type={inputType} /><input type="hidden" {...props} /><input {...props} /></>`,
    },
    {
      name: "does not treat object prototype names as primitives",
      code: `<><constructor /><toString /><__proto__ /></>`,
    },
    {
      name: "accepts non-control semantic markup",
      code: `<form><fieldset><legend>Contact details</legend><output>{result}</output></fieldset></form>`,
    },
    {
      name: "accepts a primitive name outside JSX",
      code: `const elementName = "button";`,
    },
  ],
  invalid: [
    {
      name: "rejects a raw button",
      code: `<button>Save</button>`,
      output: null,
      errors: [
        {
          messageId: "preferShadcnPrimitive",
          data: { element: "button", replacement: "Button" },
        },
      ],
    },
    {
      name: "rejects a raw dialog",
      code: `<dialog>Confirmation</dialog>`,
      errors: [
        {
          messageId: "preferShadcnPrimitive",
          data: {
            element: "dialog",
            replacement: "Dialog or AlertDialog family",
          },
        },
      ],
    },
    {
      name: "rejects a raw text input",
      code: `<input type="text" />`,
      errors: [
        {
          messageId: "preferShadcnPrimitive",
          data: { element: "input", replacement: "Input" },
        },
      ],
    },
    {
      name: "rejects a raw checkbox",
      code: `<input type="checkbox" />`,
      errors: [
        {
          messageId: "preferShadcnPrimitive",
          data: { element: "input", replacement: "Checkbox" },
        },
      ],
    },
    {
      name: "rejects statically wrapped visible input types",
      code: `<><input type={"text" as const} /><input type={"checkbox" satisfies string} /><input type={\`${"text"}\`} /></>`,
      errors: [
        {
          messageId: "preferShadcnPrimitive",
          data: { element: "input", replacement: "Input" },
        },
        {
          messageId: "preferShadcnPrimitive",
          data: { element: "input", replacement: "Checkbox" },
        },
        {
          messageId: "preferShadcnPrimitive",
          data: { element: "input", replacement: "Input" },
        },
      ],
    },
    {
      name: "rejects a raw radio input",
      code: `<input type="radio" />`,
      errors: [
        {
          messageId: "preferShadcnPrimitive",
          data: { element: "input", replacement: "RadioGroup family" },
        },
      ],
    },
    {
      name: "rejects a lowercase import alias because JSX treats it as intrinsic",
      code: `import { Input as input } from "@/components/ui/input"; <input />`,
      errors: [
        {
          messageId: "preferShadcnPrimitive",
          data: { element: "input", replacement: "Input" },
        },
      ],
    },
    {
      name: "rejects a raw label",
      code: `<label htmlFor="name">Name</label>`,
      errors: [
        {
          messageId: "preferShadcnPrimitive",
          data: { element: "label", replacement: "Label" },
        },
      ],
    },
    {
      name: "rejects a raw progress element",
      code: `<progress max={100} value={50} />`,
      errors: [
        {
          messageId: "preferShadcnPrimitive",
          data: { element: "progress", replacement: "Progress" },
        },
      ],
    },
    {
      name: "rejects a raw select",
      code: `<select><option>One</option></select>`,
      errors: [
        {
          messageId: "preferShadcnPrimitive",
          data: { element: "select", replacement: "Select family" },
        },
      ],
    },
    {
      name: "rejects a raw table once",
      code: `<table><tbody><tr><td>Value</td></tr></tbody></table>`,
      errors: [
        {
          messageId: "preferShadcnPrimitive",
          data: { element: "table", replacement: "Table family" },
        },
      ],
    },
    {
      name: "rejects a raw textarea",
      code: `<textarea defaultValue="Notes" />`,
      errors: [
        {
          messageId: "preferShadcnPrimitive",
          data: { element: "textarea", replacement: "Textarea" },
        },
      ],
    },
  ],
});
