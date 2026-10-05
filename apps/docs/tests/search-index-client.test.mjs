import assert from "node:assert/strict";
import { once } from "node:events";
import { createServer } from "node:http";
import { test } from "node:test";
import { fetchThirdPartySearchIndex } from "../src/clients/fetch-third-party-search-index.ts";

const entry = {
  anchor: "rule-zod-no-any-schema",
  displayId: "zod/no-any-schema",
  family: null,
  href: "/rules/zod/#rule-zod-no-any-schema",
  summary: "Disallow any schemas.",
};

test("the search client validates responses and rejects failed or malformed indices", async (context) => {
  const server = createServer((request, response) => {
    response.setHeader("Content-Type", "application/json");
    if (request.url === "/failed") {
      response.statusCode = 503;
      response.end("{}");
      return;
    }
    const entries = request.url === "/invalid" ? [{ ...entry, href: 1 }] : [entry];
    response.end(JSON.stringify({ entries }));
  });
  context.after(async () => {
    server.close();
    await once(server, "close");
  });
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  const address = server.address();
  assert.ok(address && typeof address === "object");
  const base = `http://127.0.0.1:${address.port}`;
  assert.deepEqual(await fetchThirdPartySearchIndex(`${base}/valid`), [entry]);
  await assert.rejects(fetchThirdPartySearchIndex(`${base}/invalid`), /expected string/);
  await assert.rejects(fetchThirdPartySearchIndex(`${base}/failed`), /Search index returned 503/);
});
