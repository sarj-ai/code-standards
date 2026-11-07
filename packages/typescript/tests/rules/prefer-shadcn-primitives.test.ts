import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";

import rule from "../../src/rules/prefer-shadcn-primitives.js";
import { ruleTester } from "./_tester.js";

const RULE_TESTER = ruleTester({ lang: "tsx" });
const ASSUME_AVAILABLE = [{ assumeAvailable: true }] as const;
const SHARED_BUTTON_EXAMPLE = "import { Button } from '@/components/ui/button'; const action = <Button>Save</Button>;";
const RAW_BUTTON_EXAMPLE = "import { Card } from '@/components/ui/card'; const action = <button>Save</button>;";

RULE_TESTER.run("prefer-shadcn-primitives", rule, {
  valid: [
    { name: "native multi-select has no equivalent Select contract", code: "<select multiple />", options: ASSUME_AVAILABLE },
    { name: "dynamic multiple cannot prove single selection", code: "<select multiple={isMultiple} />", options: ASSUME_AVAILABLE },
    { name: "hidden controls do not need visual primitives", code: "<><button hidden>Save</button><select hidden={true} /><textarea hidden={hidden} /></>", options: ASSUME_AVAILABLE },
    { name: "a hidden ancestor hides its raw control", code: "<div hidden><button>Save</button></div>", options: ASSUME_AVAILABLE },
    { name: "public no-match example", filename: "src/form.tsx", code: SHARED_BUTTON_EXAMPLE },
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
    { name: "explicit false preserves single select and visibility", code: "<select multiple={false} hidden={false} />", options: ASSUME_AVAILABLE, errors: [{ messageId: "preferShadcnPrimitive" }] },
    { name: "public match example", filename: "src/form.tsx", code: RAW_BUTTON_EXAMPLE, options: ASSUME_AVAILABLE, errors: [{ messageId: "preferShadcnPrimitive" }] },
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

const RAW_BUTTON = `export const Action = () => <button type="button">Save</button>;`;
const DETECT = [{ detectProjectPrimitives: true }] as const;

function project(files: Readonly<Record<string, string>>): string {
  const root = mkdtempSync(join(tmpdir(), "sarj-shadcn-"));
  for (const [relative, contents] of Object.entries(files)) {
    const absolute = join(root, relative);
    mkdirSync(dirname(absolute), { recursive: true });
    writeFileSync(absolute, contents, "utf8");
  }
  return root;
}

const SHADCN_MANIFEST = `{
  // shadcn manifests are JSONC in real projects.
  "aliases": { "ui": "@/components/ui", },
}`;
const TSCONFIG = `{
  "compilerOptions": {
    "baseUrl": ".",
    "paths": { "@/*": ["./src/*"] }
  }
}`;

function projectCase(name: string, files: Readonly<Record<string, string>>, relative = "src/features/action.tsx", code = RAW_BUTTON) {
  const root = project(files);
  return { name, code, cwd: root, filename: join(root, relative), options: DETECT };
}

const projectWith = (button: string) => ({
  "package.json": '{"name":"app"}',
  "components.json": SHADCN_MANIFEST,
  "tsconfig.json": TSCONFIG,
  "src/components/ui/button.tsx": button,
  "src/features/action.tsx": RAW_BUTTON,
});

RULE_TESTER.run("prefer-shadcn-primitives project detection", rule, {
  valid: [
    projectCase("fails closed when the Button module is missing", {
      "package.json": '{"name":"app"}',
      "components.json": SHADCN_MANIFEST,
      "tsconfig.json": TSCONFIG,
      "src/components/ui/card.tsx": "export const Card = () => null;",
      "src/features/action.tsx": RAW_BUTTON,
    }),
    projectCase("fails closed when the exact module does not export Button", projectWith("export const buttonVariants = {};")),
    ...([
      ["a comment", "// export const Button = fake;\nexport const buttonVariants = {};"],
      ["a type-only export", "type Button = unknown; export type { Button };"],
      ["a renamed export", "const Control = () => null; export { Control as Buttonish };"],
    ] as const).map(([name, moduleSource]) =>
      projectCase(`does not mistake ${name} for a runtime Button export`, projectWith(moduleSource))),
    projectCase("requires the exact specialized input primitive", {
      "package.json": '{"name":"app"}',
      "components.json": SHADCN_MANIFEST,
      "tsconfig.json": TSCONFIG,
      "src/components/ui/input.tsx": "export const Input = () => null;",
      "src/features/action.tsx": RAW_BUTTON,
    }, "src/features/action.tsx", '<input type="checkbox" />'),
    projectCase("fails closed for a malformed manifest", {
      "package.json": '{"name":"app"}',
      "components.json": "{ aliases:",
      "tsconfig.json": TSCONFIG,
      "src/components/ui/button.tsx": "export const Button = () => null;",
      "src/features/action.tsx": RAW_BUTTON,
    }),
    projectCase("excludes the resolved primitive implementation", {
      "package.json": '{"name":"app"}',
      "components.json": SHADCN_MANIFEST,
      "tsconfig.json": TSCONFIG,
      "src/components/ui/button.tsx": "export const Button = () => <button />;",
    }, "src/components/ui/button.tsx", "export const Button = () => <button />;"),
    projectCase("fails closed when the Button module does not parse", projectWith("export const Button = (;")),
  ],
  invalid: [
    {
      ...projectCase("reports a raw button when the exact project Button primitive exists", projectWith("const Button = () => null; export { Button };")),
      errors: [{ messageId: "preferShadcnPrimitive" }],
    },
  ],
});
