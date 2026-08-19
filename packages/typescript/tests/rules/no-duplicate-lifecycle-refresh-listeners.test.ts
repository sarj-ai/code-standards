import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule, { noDuplicateLifecycleRefreshListenersDocumentation } from "../../src/rules/no-duplicate-lifecycle-refresh-listeners.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.itOnly = it.only;
RuleTester.it = it;

const ruleTester = new RuleTester({ languageOptions: { parser: tsParser } });

ruleTester.run("no-duplicate-lifecycle-refresh-listeners", rule, {
  valid: [
    { name: "accepts the documented single signal", code: noDuplicateLifecycleRefreshListenersDocumentation.examples[0].files[0].source },
    { name: "allows different callbacks", code: `window.addEventListener("focus", onFocus); document.addEventListener("visibilitychange", onVisibility);` },
    { name: "allows matching event names on non-browser emitters", code: `bus.addEventListener("focus", refresh); other.addEventListener("visibilitychange", refresh);` },
    { name: "allows listeners in separate functions", code: `function a(){ window.addEventListener("focus", refresh); } function b(){ document.addEventListener("visibilitychange", refresh); }` },
    { name: "allows block-shadowed callback bindings", code: `{ const refresh = onFocus; window.addEventListener("focus", refresh); } { const refresh = onVisibility; document.addEventListener("visibilitychange", refresh); }` },
    { name: "ignores removeEventListener cleanup", code: `window.addEventListener("focus", refresh); document.removeEventListener("visibilitychange", refresh);` },
  ],
  invalid: [
    { name: "reports the documented duplicate lifecycle callback", code: noDuplicateLifecycleRefreshListenersDocumentation.examples[1].files[0].source, errors: [{ messageId: "duplicateLifecycleRefresh" }] },
    {
      name: "reports listeners nested in one effect callback",
      code: `useEffect(() => { const refresh = () => load(); window.addEventListener("focus", refresh); document.addEventListener("visibilitychange", refresh); return () => { window.removeEventListener("focus", refresh); document.removeEventListener("visibilitychange", refresh); }; }, []);`,
      errors: [{ messageId: "duplicateLifecycleRefresh" }],
    },
  ],
});
