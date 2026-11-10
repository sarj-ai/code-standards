// vitest: shared-module-graph
import rule from "../../src/rules/no-password-get-form.js";
import { ruleTester } from "./_tester.js";

ruleTester({ lang: "tsx" }).run("no-password-get-form", rule, {
  valid: [
    '<form><input type="password" name="password" /><button formMethod="post">Sign in</button></form>',
    '<form><input type="password" name="password" /><button {...props}>Sign in</button></form>',
    '<form method="post"><input type="password" name="password" /></form>',
    '<form method="dialog"><input type="password" name="password" /></form>',
    '<form method={method}><input type="password" name="password" /></form>',
    '<form {...props}><input type="password" name="password" /></form>',
    '<form action={save}><input type="password" name="password" /></form>',
    '<form onSubmit={submit}><input type="password" name="password" /></form>',
    '<form><input type="password" /></form>',
    '<form><input type="password" name="" /></form>',
    '<form><input type="password" name={name} /></form>',
    '<form><input type="password" name="password" disabled /></form>',
    '<form><input type="password" name="password" disabled={disabled} /></form>',
    '<form><fieldset disabled><input type="password" name="password" /></fieldset></form>',
    '<form><input type="password" name="password" form="other" /></form>',
    '<form><input {...props} type="password" /></form>',
    '<form><Input type="password" name="password" /></form>',
    '<form><Portal><input type="password" name="password" /></Portal></form>',
    '<Form><input type="password" name="password" /></Form>',
    {
      filename: "generated/form.tsx",
      code: '<form><input type="password" name="password" /></form>',
    },
  ],
  invalid: [
    {
      code: '<form><input type="password" name="password" /></form>',
      errors: [{ messageId: "passwordGet" }],
    },
    {
      code: '<form method="GET"><input type="password" name="password" /></form>',
      errors: [{ messageId: "passwordGet" }],
    },
    {
      code: '<form action="/login"><div><input type="password" name="password" /></div></form>',
      errors: [{ messageId: "passwordGet" }],
    },
    {
      code: '<form><><input type="password" name="password" /></></form>',
      errors: [{ messageId: "passwordGet" }],
    },
    {
      code: '<form><input type="password" name="password" disabled={false} readOnly /></form>',
      errors: [{ messageId: "passwordGet" }],
    },
    {
      code: '<form><form><input type="password" name="password" /></form></form>',
      errors: [{ messageId: "passwordGet" }],
    },
    {
      code: '<form><input type="password" name="first" /><input type="password" name="second" /></form>',
      errors: [{ messageId: "passwordGet" }],
    },
  ],
});
