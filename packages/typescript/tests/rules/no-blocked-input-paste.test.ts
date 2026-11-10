// vitest: shared-module-graph
import rule from "../../src/rules/no-blocked-input-paste.js";
import { ruleTester } from "./_tester.js";

ruleTester({ lang: "tsx" }).run("no-blocked-input-paste", rule, {
  valid: [
    "<textarea onPasteCapture={e => e.preventDefault()} onPaste={handleReplacement} />",
    '<input {...props} onPaste={(e) => e["preventDefault"]()} />',
    '<input type="password" />',
    "<input onPaste={handler} />",
    '<input onPaste={(event) => { event.preventDefault(); insert(event.clipboardData.getData("text")); }} />',
    "<input onPaste={(event) => { if (invalid(event)) event.preventDefault(); }} />",
    "<input onPaste={(event) => other.preventDefault()} />",
    "<input onPaste={(event) => event.preventDefault()} {...props} />",
    "<input type={kind} onPaste={(event) => event.preventDefault()} />",
    '<input type="file" onPaste={(event) => event.preventDefault()} />',
    "<input readOnly onPaste={(event) => event.preventDefault()} />",
    "<input disabled onPaste={(event) => event.preventDefault()} />",
    '<input type="password" onPaste={(event) => event.preventDefault?.()} />',
    "<Input onPaste={(event) => event.preventDefault()} />",
    "<div contentEditable onPaste={(event) => event.preventDefault()} />",
    {
      filename: "generated/input.tsx",
      code: "<input onPaste={(event) => event.preventDefault()} />",
    },
  ],
  invalid: [
    {
      code: '<input type="password" onPaste={(event) => event.preventDefault()} />',
      errors: [{ messageId: "blockedPaste" }],
    },
    {
      code: '<input autoComplete="one-time-code" onPaste={(e) => { e.preventDefault(); }} />',
      errors: [{ messageId: "blockedPaste" }],
    },
    {
      code: "<textarea onPaste={function (e) { return e.preventDefault(); }} />",
      errors: [{ messageId: "blockedPaste" }],
    },
    {
      code: "<input readOnly={false} onPasteCapture={(e) => e.preventDefault()} />",
      errors: [{ messageId: "blockedPaste" }],
    },
    {
      code: '<input onPaste={(e) => e["preventDefault"]()} />',
      errors: [{ messageId: "blockedPaste" }],
    },
  ],
});
