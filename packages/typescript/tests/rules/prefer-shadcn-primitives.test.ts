import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule, { preferShadcnPrimitivesDocumentation } from "../../src/rules/prefer-shadcn-primitives.js";

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
const ASSUME_AVAILABLE = [{ assumeAvailable: true }] as const;

ruleTester.run("prefer-shadcn-primitives", rule, {
  valid: [
    { name: "public no-match example", filename: preferShadcnPrimitivesDocumentation.examples[0].focusPath, code: preferShadcnPrimitivesDocumentation.examples[0].files[0].source },
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
      name: "accepts native file inputs",
      code: `<input name="attachment" type="file" />`,
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
      name: "accepts labels without a static association",
      code: `<><label>Account details</label><label htmlFor={fieldId}>Name</label><label htmlFor="">Empty</label><label htmlFor="   ">Blank</label></>`,
    },
    {
      name: "accepts labels that wrap only non-labelable content",
      code: `<><label><span>Section heading</span></label><label><input type={inputType} /></label><label><input type="hidden" /></label></>`,
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
    {
      name: "accepts raw elements inside the shared primitive implementation tree",
      filename: "/repo/src/components/ui/table.tsx",
      code: `<><table /><textarea /><button type="button" /></>`,
    },
    {
      name: "accepts raw controls in colocated test files",
      filename: "/repo/src/components/voice-interface.test.tsx",
      code: `<button type="button">Mock action</button>`,
    },
    {
      name: "accepts raw controls in test directories",
      filename: String.raw`C:\repo\src\__tests__\theme-provider.tsx`,
      code: `<button type="button">Mock theme</button>`,
    },
    {
      name: "does not prescribe shadcn in a repository without local adoption evidence",
      filename: "/repo/src/plain-form.tsx",
      code: `<button type="button">Save</button>`,
    },
    {
      name: "does not prescribe the wrong primitive for specialized input types",
      code: `<><input type="submit" /><input type="reset" /><input type="range" /><input type="color" /></>`,
    },
  ],
  invalid: [
    { name: "public match example", filename: preferShadcnPrimitivesDocumentation.examples[1].focusPath, code: preferShadcnPrimitivesDocumentation.examples[1].files[0].source, options: ASSUME_AVAILABLE, errors: [{ messageId: "preferShadcnPrimitive" }] },
    {
      name: "rejects a raw button",
      code: `<button>Save</button>`,
      options: ASSUME_AVAILABLE,
      output: null,
      errors: [
        {
          messageId: "preferShadcnPrimitive",
          data: { element: "button", replacement: "Button" },
        },
      ],
    },
    {
      name: "uses a shared primitive import as repository adoption evidence",
      filename: "/repo/src/form.tsx",
      code: `import { Card } from "@/components/ui/card"; <button>Save</button>`,
      options: ASSUME_AVAILABLE,
      errors: [{ messageId: "preferShadcnPrimitive" }],
    },
    {
      name: "rejects a raw dialog",
      code: `<dialog>Confirmation</dialog>`,
      options: ASSUME_AVAILABLE,
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
      options: ASSUME_AVAILABLE,
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
      options: ASSUME_AVAILABLE,
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
      options: ASSUME_AVAILABLE,
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
      options: ASSUME_AVAILABLE,
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
      options: ASSUME_AVAILABLE,
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
      options: ASSUME_AVAILABLE,
      errors: [
        {
          messageId: "preferShadcnPrimitive",
          data: { element: "label", replacement: "Label" },
        },
      ],
    },
    {
      name: "rejects a label wrapping a labelable control",
      code: `<label>Name <><span><input type="text" /></span></></label>`,
      options: ASSUME_AVAILABLE,
      errors: [
        {
          messageId: "preferShadcnPrimitive",
          data: { element: "label", replacement: "Label" },
        },
        {
          messageId: "preferShadcnPrimitive",
          data: { element: "input", replacement: "Input" },
        },
      ],
    },
    {
      name: "rejects a raw progress element",
      code: `<progress max={100} value={50} />`,
      options: ASSUME_AVAILABLE,
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
      options: ASSUME_AVAILABLE,
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
      options: ASSUME_AVAILABLE,
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
      options: ASSUME_AVAILABLE,
      errors: [
        {
          messageId: "preferShadcnPrimitive",
          data: { element: "textarea", replacement: "Textarea" },
        },
      ],
    },
  ],
});
