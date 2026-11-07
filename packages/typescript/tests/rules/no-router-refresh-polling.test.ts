// vitest: shared-module-graph
import rule from "../../src/rules/no-router-refresh-polling.js";
import { ruleTester } from "./_tester.js";

const RULE_TESTER = ruleTester();

const NO_ROUTER_REFRESH_POLLING_DOCUMENTATION = {
  examples: [
    { files: [{ source: '"use client"; import { useEffect } from "react"; function Status() { useEffect(() => { const timer = setInterval(() => fetchStatus(), POLLING_INTERVAL_MS); return () => clearInterval(timer); }, []); return null; }' }] },
    { files: [{ source: '"use client"; import { useEffect } from "react"; import { useRouter } from "next/navigation"; function Status() { const router = useRouter(); useEffect(() => { const timer = setInterval(() => router.refresh(), POLLING_INTERVAL_MS); return () => clearInterval(timer); }, [router]); return null; }' }] },
  ],
} as const;

RULE_TESTER.run("no-router-refresh-polling", rule, {
  valid: [
    { name: "does not inherit router identity through a second var initializer", code: "import {useRouter} from 'next/navigation'; var router=useRouter(); var router=cache; setInterval(()=>router.refresh(),1000);" },
    { name: "includes later writes in the namespace proof", code: "import {useRouter} from 'next/navigation'; let router=useRouter(); setInterval(()=>router.refresh(),1000); router=cache;" },
    {name: "reassigned binding is not proven Next router", code: "import {useRouter} from 'next/navigation'; let router=useRouter(); router=cache; setInterval(()=>router.refresh(),1000);"},
    {name: "function declaration is an execution boundary", code: "import {useRouter} from 'next/navigation'; const router=useRouter(); setInterval(() => {function later(){router.refresh();}}, 1000);"},
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
    { name: "retains a router binding through a bare var redeclaration", code: "import {useRouter} from 'next/navigation'; var router=useRouter(); var router; setInterval(()=>router.refresh(),1000);", errors: [{ messageId: "routerRefreshPolling" }] },
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

RULE_TESTER.run("no-router-refresh-polling examples", rule, {
  valid: [
    { name: "poll-router-refresh-dynamic-member", filename: "src/status.tsx", code: "\"use client\"; import { useEffect } from \"react\"; import { useRouter } from \"next/navigation\"; function Status() { const router = useRouter(); useEffect(() => { const timer = setInterval(() => router[auditDynamicMember](), POLLING_INTERVAL_MS); return () => clearInterval(timer); }, [router]); return null; }" },
  ],
  invalid: [
    { name: "poll-router-refresh-static-member", filename: "src/status.tsx", code: "\"use client\"; import { useEffect } from \"react\"; import { useRouter } from \"next/navigation\"; function Status() { const router = useRouter(); useEffect(() => { const timer = setInterval(() => router[\"refresh\"](), POLLING_INTERVAL_MS); return () => clearInterval(timer); }, [router]); return null; }", errors: [{ messageId: "routerRefreshPolling" }] },
  ],
});
