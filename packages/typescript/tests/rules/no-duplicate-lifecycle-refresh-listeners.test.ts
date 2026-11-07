// vitest: shared-module-graph
import rule from "../../src/rules/no-duplicate-lifecycle-refresh-listeners.js";
import { RuleTester } from "./_tester.js";

new RuleTester({ eslintCompat: true, languageOptions: { parserOptions: { lang: "ts" } } }).run("no-duplicate-lifecycle-refresh-listeners", rule, {
  valid: [
    { name: "honors static computed removals with template event names", code: 'import { useRouter } from "next/navigation"; const router = useRouter(); const refresh = () => router.refresh(); window["addEventListener"](`focus`, refresh); window["removeEventListener"](`focus`, refresh); document["addEventListener"](`visibilitychange`, refresh);' },
    { name: "keeps interpolated lifecycle event names opaque", code: 'import { useRouter } from "next/navigation"; const router = useRouter(); const refresh = () => router.refresh(); window.addEventListener(`${focusEvent}`, refresh); document.addEventListener(`visibilitychange`, refresh);' },
    { name: "preserves browser global shadowing with static computed calls", code: 'import { useRouter } from "next/navigation"; const router = useRouter(); const refresh = () => router.refresh(); function run(window) { window["addEventListener"](`focus`, refresh); document["addEventListener"](`visibilitychange`, refresh); }' },

    { name: "reassigned function declaration loses callback provenance", code: 'import { useRouter } from "next/navigation"; const router = useRouter(); function refresh() { router.refresh(); } refresh = trackActivation; window.addEventListener("focus", refresh); document.addEventListener("visibilitychange", refresh);' },
    { name: "reassigned callback is not proven to refresh", code: 'import { useRouter } from "next/navigation"; const router = useRouter(); let refresh = () => router.refresh(); refresh = trackActivation; window.addEventListener("focus", refresh); document.addEventListener("visibilitychange", refresh);' },
    { name: "reassigned router is not proven Next transport", code: 'import { useRouter } from "next/navigation"; let router = useRouter(); router = cache; const refresh = () => router.refresh(); window.addEventListener("focus", refresh); document.addEventListener("visibilitychange", refresh);' },
    { name: "accepts the documented single signal", code: "import { useRouter } from \"next/navigation\"; const router = useRouter(); const refresh = () => router.refresh(); window.addEventListener(\"focus\", refresh);" },
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
    { name: "documented example duplicate-lifecycle-signals-dynamic-member", filename: "src/refresh.ts", code: "import { useRouter } from \"next/navigation\"; const router = useRouter(); const refresh = () => router[auditDynamicMember](); window[auditDynamicMember](\"focus\", refresh); document[auditDynamicMember](\"visibilitychange\", refresh);" },
  ],
  invalid: [
    { name: "retains no-substitution lifecycle event names", code: 'import { useRouter } from "next/navigation"; const router = useRouter(); const refresh = () => router.refresh(); window.addEventListener(`focus`, refresh); document.addEventListener(`visibilitychange`, refresh);', errors: [{ messageId: "duplicateLifecycleRefresh" }] },
    { name: "retains lifecycle event names through const assertions", code: 'import { useRouter } from "next/navigation"; const router = useRouter(); const refresh = () => router.refresh(); window.addEventListener(("focus" as const), refresh); document.addEventListener(("visibilitychange" as const), refresh);', errors: [{ messageId: "duplicateLifecycleRefresh" }] },
    { name: "recognizes static computed browser and refresh methods", code: 'import { useRouter } from "next/navigation"; const router = useRouter(); const refresh = () => router["refresh"](); window["addEventListener"]("focus", refresh); document["addEventListener"]("visibilitychange", refresh);', errors: [{ messageId: "duplicateLifecycleRefresh" }] },

    { name: "reports the documented duplicate lifecycle callback", code: "import { useRouter } from \"next/navigation\"; const router = useRouter(); const refresh = () => router.refresh(); window.addEventListener(\"focus\", refresh); document.addEventListener(\"visibilitychange\", refresh);", errors: [{ messageId: "duplicateLifecycleRefresh" }] },
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
    { name: "documented example duplicate-lifecycle-signals-static-member", filename: "src/refresh.ts", code: "import { useRouter } from \"next/navigation\"; const router = useRouter(); const refresh = () => router[\"refresh\"](); window[\"addEventListener\"](\"focus\", refresh); document[\"addEventListener\"](\"visibilitychange\", refresh);", errors: [{ messageId: "duplicateLifecycleRefresh" }] },
  ],
});
