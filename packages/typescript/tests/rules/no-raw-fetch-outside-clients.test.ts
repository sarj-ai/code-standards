import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule from "../../src/rules/no-raw-fetch-outside-clients.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const ruleTester = new RuleTester({
  languageOptions: {
    parser: tsParser,
  },
});

/** A path outside the client layer, where a raw fetch must be reported. */
const HANDLER = "/repo/src/routes/handler.ts";

ruleTester.run("no-raw-fetch-outside-clients", rule, {
  valid: [
    // FP guard, corpus: query/examples/react/star-wars/src/api.ts:7 — an `api`
    // module IS the client layer, just the other common spelling of `clients/`.
    {
      code: "export const getFilm = async (id) => fetch(`/films/${id}`);",
      filename: "/repo/src/api.ts",
    },
    {
      code: "export const getFilm = async (id) => fetch(`/films/${id}`);",
      filename: "/repo/src/api/films.ts",
    },
    {
      code: "export const getFilm = async (id) => fetch(`/films/${id}`);",
      filename: "/repo/src/lib/star-wars-api.ts",
    },
    // FP guard, corpus: react-router names suites `single-fetch-test.ts`.
    {
      code: "async function t() { await fetch('/x'); }",
      filename: "/repo/integration/single-fetch-test.ts",
    },
    // FP guard, corpus: query/packages/query-codemods/.../__testfixtures__/bug-reports.input.tsx
    {
      code: "async function t() { await fetch('/x'); }",
      filename: "/repo/src/v5/__testfixtures__/bug-reports.input.tsx",
    },
    // --- The flagged file IS the client layer, under another name -----------
    // Vendor wrapper modules: every fetch in them is an absolute-URL call to one
    // third-party origin, i.e. they ARE the module the rule wants the fetch to
    // live in. Corpus:
    // cal.com/packages/app-store/office365calendar/lib/CalendarService.ts:265.
    {
      code: "export const listEvents = () => fetch('https://graph.microsoft.com/v1.0/me/events');",
      filename: "/repo/packages/app-store/office365calendar/lib/CalendarService.ts",
    },
    // formbricks/apps/web/lib/googleSheet/service.ts:164
    {
      code: "export const appendRows = () => fetch('https://sheets.googleapis.com/v4/x');",
      filename: "/repo/apps/web/lib/googleSheet/service.ts",
    },
    {
      code: "export const run = () => fetch('https://api.example.test/v1/x');",
      filename: "/repo/packages/engineering/src/lib/services/google-directory/auth.ts",
    },
    // openstatus/packages/notifications/telegram/src/index.ts:81
    {
      code: "export const send = () => fetch('https://api.telegram.org/botX/sendMessage');",
      filename: "/repo/packages/notifications/telegram/src/index.ts",
    },
    {
      code: "export const sync = () => fetch('https://api.attio.com/v2/objects');",
      filename: "/repo/worker/connectors/attio.ts",
    },
    {
      code: "export const importChecks = () => fetch('https://api.checklyhq.com/v1/checks');",
      filename: "/repo/packages/importers/src/providers/checkly/checkly.ts",
    },
    {
      code: "export const postMessage = () => fetch('https://slack.com/api/chat.postMessage');",
      filename: "/repo/apps/web/lib/integrations/slack/commands.ts",
    },
    {
      code: "export const readText = () => fetch(url);",
      filename: "/repo/packages/utils/src/functions/text-fetcher.ts",
    },
    {
      code: "export const push = () => fetch('https://api.example.test/x');",
      filename: "/repo/packages/sync/src/hubspot-connector.ts",
    },
    // --- Test-path drift ----------------------------------------------------
    // The rule hand-rolled its own test-path list and so missed `playwright/`
    // and `.e2e.ts`. Corpus: cal.com/apps/web/playwright/oauth-provider.e2e.ts
    // was the single loudest file in the sweep (16 findings).
    {
      code: "async function t() { await fetch('/api/x'); }",
      filename: "/repo/apps/web/playwright/oauth-provider.e2e.ts",
    },
    {
      code: "export const inbox = () => fetch('http://localhost:8025/api/v2/messages');",
      filename: "/repo/apps/web/playwright/mailhog.ts",
    },
    {
      code: "export const seed = () => fetch('/api/x');",
      filename: "/repo/apps/web/cypress/support/commands.ts",
    },
    // --- Asset / passthrough handoff ---------------------------------------
    // A lone constructed `URL`/`Request` argument is an asset load or an
    // inbound request being forwarded, not a call to a service API that a
    // client wrapper could own. Corpus:
    // documenso/apps/remix/app/routes/_share+/share.$slug.opengraph.tsx:33.
    {
      code: "export const font = () => fetch(new URL('/fonts/inter.ttf', import.meta.url));",
      filename: "/repo/app/routes/share.opengraph.tsx",
    },
    {
      code: "export const proxy = (request) => fetch(new Request(request));",
      filename: "/repo/app/routes/ingest.tsx",
    },
    // --- Allowed by the default path patterns -------------------------------
    {
      code: "export const get = () => fetch(url);",
      filename: "/repo/src/clients/slack-client.ts",
    },
    {
      code: "export const get = () => fetch(url);",
      filename: "/repo/src/client/index.ts",
    },
    {
      code: "export const get = () => fetch(url);",
      filename: "/repo/packages/shared/src/http-client.ts",
    },
    {
      code: "export const get = () => fetch(url);",
      filename: "/repo/src/lib/ashby-client.ts",
    },
    {
      code: "it('works', () => fetch(url));",
      filename: "/repo/src/routes/handler.test.ts",
    },
    {
      code: "it('works', () => fetch(url));",
      filename: "/repo/src/routes/handler.spec.ts",
    },
    {
      code: "it('works', () => fetch(url));",
      filename: "/repo/src/__tests__/handler.ts",
    },
    // --- Not the global fetch ----------------------------------------------
    // A `fetch` method on an unrelated receiver is not outbound HTTP.
    { code: "const rows = cache.fetch(key);", filename: HANDLER },
    { code: "const d = queryClient.fetch();", filename: HANDLER },
    // Going through a client is the whole point of the rule.
    { code: "const r = await slackClient.postMessage(c, t);", filename: HANDLER },
    // Pre-signed upload/download URLs are storage handoffs, not calls to a
    // first-party service API that belongs behind the app client layer.
    {
      code: "await fetch(uploadUrl, { method: 'PUT', body: file });",
      filename: "/repo/src/app/batch-calls/create-batch-form.tsx",
    },
    {
      code: "await fetch(file.downloadUrl);",
      filename: "/repo/src/app/knowledge-bases/kb-files-list.tsx",
    },
    // A computed member access we cannot resolve statically.
    { code: "const r = api['fetch'](url);", filename: HANDLER },
    // A local binding shadowing nothing global, on a non-global receiver.
    { code: "const r = this.fetch(url);", filename: HANDLER },
    // --- Custom allow list ---------------------------------------------------
    {
      code: "export const get = () => fetch(url);",
      filename: "/repo/src/lib/api/gateway.ts",
      options: [{ allow: ["[\\\\/]lib[\\\\/]api[\\\\/]"] }],
    },
    // An unparseable pattern is skipped, and the remaining one still exempts.
    {
      code: "export const get = () => fetch(url);",
      filename: "/repo/src/gateway.ts",
      options: [{ allow: ["([unterminated", "gateway\\.ts$"] }],
    },
  ],
  invalid: [
    // The guards must not over-fire: a component is still not the client layer.
    {
      code: "async function load() { const r = await fetch('/api/todos'); return r.json(); }",
      filename: "/repo/src/pages/index.tsx",
      errors: [{ messageId: "rawFetch" }],
    },
    // UPPER BOUND on the vendor-path widening. Every true positive in the
    // 50-finding read was a component/page/modal or a React hook — none lived in
    // a vendor path. `providers/` is a vendor directory, but a `-provider.tsx`
    // BASENAME is usually a React context/modal provider, so that suffix is
    // deliberately absent from the allow list. Corpus:
    // dub/apps/web/ui/modals/modal-provider.tsx:134, which calls its OWN api.
    {
      code: "export const M = (id) => { fetch(`/api/links/sync?workspaceId=${id}`, { method: 'POST' }); };",
      filename: "/repo/apps/web/ui/modals/modal-provider.tsx",
      errors: [{ messageId: "rawFetch" }],
    },
    // A name that merely contains "service" is not a service module.
    {
      code: "export const Page = () => { fetch('/api/me'); };",
      filename: "/repo/apps/web/app/settings/service-page.tsx",
      errors: [{ messageId: "rawFetch" }],
    },
    // UPPER BOUND on the handoff guard: only a LONE constructed argument is a
    // handoff. Add an init and it is an ordinary service call again.
    {
      code: "const r = await fetch(new URL('/api/x', base), { method: 'POST' });",
      filename: HANDLER,
      errors: [{ messageId: "rawFetch" }],
    },
    // Bare global fetch in a route handler.
    {
      code: "export const handler = () => fetch('https://example.test');",
      filename: HANDLER,
      errors: [{ messageId: "rawFetch" }],
    },
    // Explicit global receivers.
    {
      code: "const r = globalThis.fetch(url);",
      filename: HANDLER,
      errors: [{ messageId: "rawFetch" }],
    },
    {
      code: "const r = window.fetch(url);",
      filename: HANDLER,
      errors: [{ messageId: "rawFetch" }],
    },
    {
      code: "const r = self.fetch(url);",
      filename: HANDLER,
      errors: [{ messageId: "rawFetch" }],
    },
    // Each call site is reported independently.
    {
      code: "const a = fetch(one); const b = fetch(two);",
      filename: HANDLER,
      errors: [{ messageId: "rawFetch" }, { messageId: "rawFetch" }],
    },
    // A custom `allow` REPLACES the defaults, so a client path is no longer
    // exempt unless the consumer keeps the pattern.
    {
      code: "export const get = () => fetch(url);",
      filename: "/repo/src/clients/slack-client.ts",
      options: [{ allow: ["[\\\\/]lib[\\\\/]api[\\\\/]"] }],
      errors: [{ messageId: "rawFetch" }],
    },
  ],
});
