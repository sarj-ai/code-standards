import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule, { NO_ROUTER_REFRESH_POLLING_DOCUMENTATION } from "../../src/rules/no-router-refresh-polling.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.itOnly = it.only;
RuleTester.it = it;

const RULE_TESTER = new RuleTester({ languageOptions: { parser: tsParser } });

RULE_TESTER.run("no-router-refresh-polling", rule, {
  valid: [
    { name: "accepts the documented direct fetch", code: NO_ROUTER_REFRESH_POLLING_DOCUMENTATION.examples[0].files[0].source },
    { name: "allows refresh after a mutation", code: `const router = useRouter(); async function save() { await update(); router.refresh(); }` },
    { name: "allows another object's refresh in a timer", code: `const cache = createCache(); setInterval(() => cache.refresh(), 1000);` },
    { name: "allows a dedicated polling action", code: `const router = useRouter(); setInterval(() => fetchStatus(), POLLING_INTERVAL_MS);` },
    { name: "allows a shadowed non-router binding", code: `import { useRouter } from "next/navigation"; const router = useRouter(); function poll(cache) { const router = cache; setInterval(() => router.refresh(), 1000); }` },
    { name: "allows a shadowed setInterval function", code: `import { useRouter } from "next/navigation"; const router = useRouter(); function run(setInterval) { setInterval(() => router.refresh(), 1000); }` },
    { name: "allows a shadowed window object", code: `import { useRouter } from "next/navigation"; const router = useRouter(); function run(window) { window.setInterval(() => router.refresh(), 1000); }` },
    { name: "allows a shadowed globalThis object", code: `import { useRouter } from "next/navigation"; const router = useRouter(); function run(globalThis) { globalThis.setInterval(() => router.refresh(), 1000); }` },
    { name: "ignores refresh inside an uncalled nested function", code: `import { useRouter } from "next/navigation"; const router = useRouter(); setInterval(() => { const later = () => router.refresh(); }, 1000);` },
    { name: "ignores generated code", code: `const router = useRouter(); setInterval(() => router.refresh(), 1000);`, filename: "/repo/generated/client.ts" },
  ],
  invalid: [
    { name: "reports the documented router polling", code: NO_ROUTER_REFRESH_POLLING_DOCUMENTATION.examples[1].files[0].source, errors: [{ messageId: "routerRefreshPolling" }] },
    {
      name: "reports aliased Next useRouter bindings",
      code: `import { useRouter as useNavigation } from "next/navigation"; const navigation = useNavigation(); window.setInterval(async () => { await tick(); navigation.refresh(); }, POLL_MS);`,
      errors: [{ messageId: "routerRefreshPolling" }],
    },
    {
      name: "reports globalThis polling",
      code: `import { useRouter } from "next/navigation"; const router = useRouter(); globalThis.setInterval(() => router.refresh(), POLL_MS);`,
      errors: [{ messageId: "routerRefreshPolling" }],
    },
    {
      name: "reports one diagnostic for one polling callback with multiple refresh calls",
      code: `import { useRouter } from "next/navigation"; const router = useRouter(); setInterval(() => { router.refresh(); if (stale) router.refresh(); }, POLL_MS);`,
      errors: [{ messageId: "routerRefreshPolling" }],
    },
  ],
});
