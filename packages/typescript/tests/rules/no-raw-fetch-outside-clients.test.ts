import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule, { noRawFetchOutsideClientsDocumentation } from "../../src/rules/no-raw-fetch-outside-clients.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const ruleTester = new RuleTester({
  languageOptions: {
    parser: tsParser,
  },
});

const HANDLER = "/repo/src/routes/handler.ts";

ruleTester.run("no-raw-fetch-outside-clients", rule, {
  valid: [
    { name: "accepts the documented client call", code: noRawFetchOutsideClientsDocumentation.examples[0].files[0].source, filename: HANDLER },
    {
      name: "allows a bare api module",
      code: "export const getFilm = async (id) => fetch(`/films/${id}`);",
      filename: "/repo/src/api.ts",
    },
    {
      name: "allows an api directory",
      code: "export const getFilm = async (id) => fetch(`/films/${id}`);",
      filename: "/repo/src/api/films.ts",
    },
    {
      name: "allows an api-suffixed module",
      code: "export const getFilm = async (id) => fetch(`/films/${id}`);",
      filename: "/repo/src/lib/star-wars-api.ts",
    },
    {
      name: "allows a dot-api module",
      code: "export const getFilm = async (id) => fetch(`/films/${id}`);",
      filename: "/repo/src/lib/star-wars.api.ts",
    },
    {
      name: "allows hyphenated test basenames",
      code: "async function t() { await fetch('/x'); }",
      filename: "/repo/integration/single-fetch-test.ts",
    },
    {
      name: "allows codemod test fixtures",
      code: "async function t() { await fetch('/x'); }",
      filename: "/repo/src/v5/__testfixtures__/bug-reports.input.tsx",
    },
    {
      name: "allows Service-suffixed vendor modules",
      code: "export const listEvents = () => fetch('https://graph.microsoft.com/v1.0/me/events');",
      filename: "/repo/packages/app-store/office365calendar/lib/CalendarService.ts",
    },
    {
      name: "allows a bare service module",
      code: "export const appendRows = () => fetch('https://sheets.googleapis.com/v4/x');",
      filename: "/repo/apps/web/lib/googleSheet/service.ts",
    },
    {
      name: "allows service directories",
      code: "export const run = () => fetch('https://api.example.test/v1/x');",
      filename: "/repo/packages/engineering/src/lib/services/google-directory/auth.ts",
    },
    {
      name: "allows notification vendor directories",
      code: "export const send = () => fetch('https://api.telegram.org/botX/sendMessage');",
      filename: "/repo/packages/notifications/telegram/src/index.ts",
    },
    {
      name: "allows connector directories",
      code: "export const sync = () => fetch('https://api.attio.com/v2/objects');",
      filename: "/repo/worker/connectors/attio.ts",
    },
    {
      name: "allows provider directories",
      code: "export const importChecks = () => fetch('https://api.checklyhq.com/v1/checks');",
      filename: "/repo/packages/importers/src/providers/checkly/checkly.ts",
    },
    {
      name: "allows integration directories",
      code: "export const postMessage = () => fetch('https://slack.com/api/chat.postMessage');",
      filename: "/repo/apps/web/lib/integrations/slack/commands.ts",
    },
    {
      name: "allows adapter directories",
      code: "export const send = () => fetch('https://api.example.test/v1/x');",
      filename: "/repo/packages/core/src/adapters/vendor/send.ts",
    },
    {
      name: "allows fetcher directories",
      code: "export const read = () => fetch('https://api.example.test/v1/x');",
      filename: "/repo/packages/core/src/fetchers/vendor.ts",
    },
    {
      name: "allows fetcher-suffixed modules",
      code: "export const readText = () => fetch(url);",
      filename: "/repo/packages/utils/src/functions/text-fetcher.ts",
    },
    {
      name: "allows connector-suffixed modules",
      code: "export const push = () => fetch('https://api.example.test/x');",
      filename: "/repo/packages/sync/src/hubspot-connector.ts",
    },
    {
      name: "allows service-suffixed modules",
      code: "export const push = () => fetch('https://api.example.test/x');",
      filename: "/repo/packages/sync/src/hubspot-service.ts",
    },
    {
      name: "allows adapter-suffixed modules",
      code: "export const push = () => fetch('https://api.example.test/x');",
      filename: "/repo/packages/sync/src/hubspot-adapter.ts",
    },
    {
      name: "allows sdk-suffixed modules",
      code: "export const push = () => fetch('https://api.example.test/x');",
      filename: "/repo/packages/sync/src/hubspot-sdk.ts",
    },
    {
      name: "allows Playwright suites",
      code: "async function t() { await fetch('/api/x'); }",
      filename: "/repo/apps/web/playwright/oauth-provider.e2e.ts",
    },
    {
      name: "allows Playwright helpers",
      code: "export const inbox = () => fetch('http://localhost:8025/api/v2/messages');",
      filename: "/repo/apps/web/playwright/mailhog.ts",
    },
    {
      name: "allows Cypress helpers",
      code: "export const seed = () => fetch('/api/x');",
      filename: "/repo/apps/web/cypress/support/commands.ts",
    },
    {
      name: "allows a lone constructed URL asset handoff",
      code: "export const font = () => fetch(new URL('/fonts/inter.ttf', import.meta.url));",
      filename: "/repo/app/routes/share.opengraph.tsx",
    },
    {
      name: "allows a lone constructed Request passthrough",
      code: "export const proxy = (request) => fetch(new Request(request));",
      filename: "/repo/app/routes/ingest.tsx",
    },
    {
      name: "ignores a locally shadowed fetch binding",
      code: "export const load = (fetch) => fetch('/api/items');",
      filename: "/repo/src/page.tsx",
    },
    {
      name: "defers an internal API mutation to prefer-server-actions",
      code: "export const M = (id) => { fetch(`/api/links/sync?workspaceId=${id}`, { method: 'POST' }); };",
      filename: "/repo/apps/web/ui/modals/modal-provider.tsx",
    },
    {
      name: "defers resolved internal API mutation arguments to prefer-server-actions",
      code: "const url = '/api/items'; const init = { method: 'POST' }; fetch(url, init);",
      filename: "/repo/apps/web/ui/items.tsx",
    },
    {
      name: "defers a GET inside an effect to no-client-side-data-fetching",
      code: "useEffect(() => { fetch('/api/items'); }, []);",
      filename: "/repo/src/page.tsx",
    },
    {
      name: "allows client directories",
      code: "export const get = () => fetch(url);",
      filename: "/repo/src/clients/slack-client.ts",
    },
    {
      name: "allows singular client directories",
      code: "export const get = () => fetch(url);",
      filename: "/repo/src/client/index.ts",
    },
    {
      name: "allows a bare http-client module",
      code: "export const get = () => fetch(url);",
      filename: "/repo/packages/shared/src/http-client.ts",
    },
    {
      name: "allows client-suffixed modules",
      code: "export const get = () => fetch(url);",
      filename: "/repo/src/lib/ashby-client.ts",
    },
    {
      name: "allows dotted test basenames",
      code: "it('works', () => fetch(url));",
      filename: "/repo/src/routes/handler.test.ts",
    },
    {
      name: "allows dotted spec basenames",
      code: "it('works', () => fetch(url));",
      filename: "/repo/src/routes/handler.spec.ts",
    },
    {
      name: "allows test directories",
      code: "it('works', () => fetch(url));",
      filename: "/repo/src/__tests__/handler.ts",
    },
    {
      name: "ignores fetch methods on non-global receivers",
      code: "const rows = cache.fetch(key);",
      filename: HANDLER,
    },
    {
      name: "ignores query-client fetch methods",
      code: "const d = queryClient.fetch();",
      filename: HANDLER,
    },
    {
      name: "allows calls routed through a client",
      code: "const r = await slackClient.postMessage(c, t);",
      filename: HANDLER,
    },
    {
      name: "allows pre-signed upload URL transfers",
      code: "await fetch(uploadUrl, { method: 'PUT', body: file });",
      filename: "/repo/src/app/batch-calls/create-batch-form.tsx",
    },
    {
      name: "allows signed download URL transfers",
      code: "await fetch(file.downloadUrl);",
      filename: "/repo/src/app/knowledge-bases/kb-files-list.tsx",
    },
    {
      name: "ignores computed fetch members",
      code: "const r = api['fetch'](url);",
      filename: HANDLER,
    },
    {
      name: "ignores this.fetch",
      code: "const r = this.fetch(url);",
      filename: HANDLER,
    },
    {
      name: "does not regulate other HTTP libraries",
      code: "const r = axios.get(url);",
      filename: HANDLER,
    },
    {
      name: "supports custom client-layer paths",
      code: "export const get = () => fetch(url);",
      filename: "/repo/src/lib/api/gateway.ts",
      options: [{ allow: ["[\\\\/]lib[\\\\/]api[\\\\/]"] }],
    },
    {
      name: "custom allow patterns never disable the test-file exemption",
      code: "it('works', () => fetch(url));",
      filename: "/repo/src/routes/handler.test.ts",
      options: [{ allow: ["[\\\\/]lib[\\\\/]api[\\\\/]"] }],
    },
    {
      name: "skips malformed allow patterns without discarding valid ones",
      code: "export const get = () => fetch(url);",
      filename: "/repo/src/gateway.ts",
      options: [{ allow: ["([unterminated", "gateway\\.ts$"] }],
    },
  ],
  invalid: [
    { name: "reports the documented raw fetch", code: noRawFetchOutsideClientsDocumentation.examples[1].files[0].source, filename: HANDLER, errors: [{ messageId: "rawFetch" }] },
    {
      name: "reports bare fetch in components",
      code: "async function load() { const r = await fetch('/api/todos'); return r.json(); }",
      filename: "/repo/src/pages/index.tsx",
      errors: [{ messageId: "rawFetch" }],
    },
    {
      name: "reports modules whose basename merely contains service",
      code: "export const Page = () => { fetch('/api/me'); };",
      filename: "/repo/apps/web/app/settings/service-page.tsx",
      errors: [{ messageId: "rawFetch" }],
    },
    {
      name: "keeps analytics fetches that the client-fetch owner exempts",
      code: "useEffect(() => { fetch('/api/analytics'); }, []);",
      filename: "/repo/src/page.tsx",
      errors: [{ messageId: "rawFetch" }],
    },
    {
      name: "keeps internal mutations in scripts that prefer-server-actions exempts",
      code: "fetch('/api/items', { method: 'POST' });",
      filename: "/repo/scripts/push.ts",
      errors: [{ messageId: "rawFetch" }],
    },
    {
      name: "keeps internal mutations in non-React framework modules",
      code: "import { ref } from 'vue'; fetch('/api/items', { method: 'POST' });",
      filename: "/repo/src/items.ts",
      errors: [{ messageId: "rawFetch" }],
    },
    {
      name: "reports constructed URLs when fetch also has init options",
      code: "const r = await fetch(new URL('/api/x', base), { method: 'POST' });",
      filename: HANDLER,
      errors: [{ messageId: "rawFetch" }],
    },
    {
      name: "does not exempt arbitrary constructed fetch inputs",
      code: "const r = await fetch(new ApiInput('/api/x'));",
      filename: HANDLER,
      errors: [{ messageId: "rawFetch" }],
    },
    {
      name: "does not treat a shadowed URL constructor as a global URL handoff",
      code: "class URL { constructor(value) {} } const r = await fetch(new URL('/api/x'));",
      filename: HANDLER,
      errors: [{ messageId: "rawFetch" }],
    },
    {
      name: "reports bare global fetch in route handlers",
      code: "export const handler = () => fetch('https://example.test');",
      filename: HANDLER,
      errors: [{ messageId: "rawFetch" }],
    },
    {
      name: "reports globalThis.fetch",
      code: "const r = globalThis.fetch(url);",
      filename: HANDLER,
      errors: [{ messageId: "rawFetch" }],
    },
    {
      name: "reports window.fetch",
      code: "const r = window.fetch(url);",
      filename: HANDLER,
      errors: [{ messageId: "rawFetch" }],
    },
    {
      name: "reports self.fetch",
      code: "const r = self.fetch(url);",
      filename: HANDLER,
      errors: [{ messageId: "rawFetch" }],
    },
    {
      name: "reports every raw fetch call site",
      code: "const a = fetch(one); const b = fetch(two);",
      filename: HANDLER,
      errors: [{ messageId: "rawFetch" }, { messageId: "rawFetch" }],
    },
    {
      name: "reports ordinary variable URLs outside client paths",
      code: "const r = fetch(url);",
      filename: HANDLER,
      errors: [{ messageId: "rawFetch" }],
    },
    {
      name: "malformed allow patterns fail closed",
      code: "const r = fetch(url);",
      filename: HANDLER,
      options: [{ allow: ["([unterminated"] }],
      errors: [{ messageId: "rawFetch" }],
    },
    {
      name: "custom allow patterns replace the defaults",
      code: "export const get = () => fetch(url);",
      filename: "/repo/src/clients/slack-client.ts",
      options: [{ allow: ["[\\\\/]lib[\\\\/]api[\\\\/]"] }],
      errors: [{ messageId: "rawFetch" }],
    },
  ],
});
