import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule, { NO_DUPLICATE_LIFECYCLE_REFRESH_LISTENERS_DOCUMENTATION } from "../../src/rules/no-duplicate-lifecycle-refresh-listeners.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.itOnly = it.only;
RuleTester.it = it;

const RULE_TESTER = new RuleTester({ languageOptions: { parser: tsParser } });

RULE_TESTER.run("no-duplicate-lifecycle-refresh-listeners", rule, {
  valid: [
    { name: "accepts the documented single signal", code: NO_DUPLICATE_LIFECYCLE_REFRESH_LISTENERS_DOCUMENTATION.examples[0].files[0].source },
    { name: "allows different callbacks", code: `window.addEventListener("focus", onFocus); document.addEventListener("visibilitychange", onVisibility);` },
    { name: "allows a shared analytics callback", code: `const trackActivation = () => analytics.track("activate"); window.addEventListener("focus", trackActivation); document.addEventListener("visibilitychange", trackActivation);` },
    { name: "allows a shared general callback", code: `function updateTitle() { document.title = title(); } window.addEventListener("focus", updateTitle); document.addEventListener("visibilitychange", updateTitle);` },
    { name: "allows an explicitly debounced route refresh", code: `import { useRouter } from "next/navigation"; const router = useRouter(); const refresh = debounce(() => router.refresh(), 200); window.addEventListener("focus", refresh); document.addEventListener("visibilitychange", refresh);` },
    { name: "allows an explicitly throttled route refresh", code: `import { useRouter } from "next/navigation"; const router = useRouter(); const refresh = throttle(() => router.refresh(), 200); window.addEventListener("focus", refresh); document.addEventListener("visibilitychange", refresh);` },
    { name: "allows matching event names on non-browser emitters", code: `bus.addEventListener("focus", refresh); other.addEventListener("visibilitychange", refresh);` },
    { name: "allows listeners in separate functions", code: `function a(){ window.addEventListener("focus", refresh); } function b(){ document.addEventListener("visibilitychange", refresh); }` },
    { name: "allows mutually exclusive listener branches", code: `import { useRouter } from "next/navigation"; const router = useRouter(); const refresh = () => router.refresh(); if (preferFocus) { window.addEventListener("focus", refresh); } else { document.addEventListener("visibilitychange", refresh); }` },
    { name: "allows a removed focus listener followed by visibility", code: `import { useRouter } from "next/navigation"; const router = useRouter(); const refresh = () => router.refresh(); window.addEventListener("focus", refresh); window.removeEventListener("focus", refresh); document.addEventListener("visibilitychange", refresh);` },
    { name: "allows block-shadowed callback bindings", code: `{ const refresh = onFocus; window.addEventListener("focus", refresh); } { const refresh = onVisibility; document.addEventListener("visibilitychange", refresh); }` },
    { name: "allows listeners on a shadowed window", code: `import { useRouter } from "next/navigation"; const router = useRouter(); const refresh = () => router.refresh(); function run(window) { window.addEventListener("focus", refresh); document.addEventListener("visibilitychange", refresh); }` },
    { name: "allows listeners on a shadowed document", code: `import { useRouter } from "next/navigation"; const router = useRouter(); const refresh = () => router.refresh(); function run(document) { window.addEventListener("focus", refresh); document.addEventListener("visibilitychange", refresh); }` },
    { name: "ignores removeEventListener cleanup", code: `window.addEventListener("focus", refresh); document.removeEventListener("visibilitychange", refresh);` },
  ],
  invalid: [
    { name: "reports the documented duplicate lifecycle callback", code: NO_DUPLICATE_LIFECYCLE_REFRESH_LISTENERS_DOCUMENTATION.examples[1].files[0].source, errors: [{ messageId: "duplicateLifecycleRefresh" }] },
    {
      name: "reports listeners nested in one effect callback",
      code: `import { useRouter } from "next/navigation"; function Component() { const router = useRouter(); useEffect(() => { const refresh = () => router.refresh(); window.addEventListener("focus", refresh); document.addEventListener("visibilitychange", refresh); return () => { window.removeEventListener("focus", refresh); document.removeEventListener("visibilitychange", refresh); }; }, []); }`,
      errors: [{ messageId: "duplicateLifecycleRefresh" }],
    },
    {
      name: "reports a named route refresh function",
      code: `import { useRouter } from "next/navigation"; const router = useRouter(); function refresh() { router.refresh(); } window.addEventListener("focus", refresh); document.addEventListener("visibilitychange", refresh);`,
      errors: [{ messageId: "duplicateLifecycleRefresh" }],
    },
    {
      name: "reports one diagnostic when each lifecycle listener is repeated",
      code: `import { useRouter } from "next/navigation"; const router = useRouter(); const refresh = () => router.refresh(); window.addEventListener("focus", refresh); window.addEventListener("focus", refresh); document.addEventListener("visibilitychange", refresh); document.addEventListener("visibilitychange", refresh);`,
      errors: [{ messageId: "duplicateLifecycleRefresh" }],
    },
  ],
});
