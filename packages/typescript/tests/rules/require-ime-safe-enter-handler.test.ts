// vitest: shared-module-graph
import rule from "../../src/rules/require-ime-safe-enter-handler.js";
import { ruleTester } from "./_tester.js";

ruleTester({ lang: "tsx" }).run("require-ime-safe-enter-handler", rule, {
  valid: [
    '<input onKeyDown={e => { if (!(e.key === "Enter")) e.currentTarget.blur(); }} />',
    '<input onKeyDown={e => { if (e.key === "Enter" && !composing) e.currentTarget.blur(); }} />',
    '<input onKeyDown={e => { if (testKey(e.key === "Enter")) e.currentTarget.blur(); }} />',
    '<input onKeyDown={e => { e = other; if (e.key === "Enter") e.currentTarget.blur(); }} />',
    '<input readOnly onKeyDown={e => { if (e.key === "Enter") e.currentTarget.blur(); }} />',
    '<input type="file" onKeyDown={e => { if (e.key === "Enter") e.currentTarget.blur(); }} />',
    '<input onKeyDown={e => { { const e = other; if (e.key === "Enter") e.currentTarget.blur(); } }} />',
    "<input />",
    "<textarea onKeyDown={handler} />",
    '<Input onKeyDown={e => { if (e.key === "Enter") e.currentTarget.form?.requestSubmit(); }} />',
    '<input onKeyDown={e => { if (e.key === "Enter") e.currentTarget.form?.requestSubmit(); }} {...props} />',
    '<input onKeyDown={e => { if (e.nativeEvent.isComposing) return; if (e.key === "Enter") e.currentTarget.form?.requestSubmit(); }} />',
    '<textarea onKeyDown={e => { if (e.isComposing || e.keyCode === 229) return; if (e.key === "Enter") e.currentTarget.form?.requestSubmit(); }} />',
    '<textarea onKeyDown={e => { if (e.key === "Enter" && e.ctrlKey) e.currentTarget.form?.requestSubmit(); }} />',
    '<textarea onCompositionEnd={trackComposition} onKeyDown={e => { if (e.key === "Enter") e.currentTarget.form?.requestSubmit(); }} />',
    "<input onKeyDown={e => { if (e.keyCode === 13) e.currentTarget.form?.requestSubmit(); }} />",
    '<input onKeyDown={e => { if (e.key === "Escape") e.currentTarget.blur(); }} />',
    '<input onKeyDown={e => { if (e.key === "Enter") e.preventDefault(); }} />',
    '<input onKeyDown={e => { if (e.key === "Enter") logKey(e.key); }} />',
    {
      filename: "generated/input.tsx",
      code: '<input onKeyDown={e => { if (e.key === "Enter") e.currentTarget.blur(); }} />',
    },
  ],
  invalid: [
    {
      code: '<textarea onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); e.currentTarget.form?.requestSubmit(); } }} />',
      errors: [{ messageId: "composition" }],
    },
    {
      code: '<input onKeyDown={e => { if ("Enter" === e.key) e.currentTarget.blur(); }} />',
      errors: [{ messageId: "composition" }],
    },
  ],
});
