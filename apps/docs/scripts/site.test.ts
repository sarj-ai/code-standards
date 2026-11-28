import assert from "node:assert/strict";
import { test } from "node:test";

import { legacyRedirect, siteHref, siteUrl } from "../src/lib/site.ts";
import worker from "../src/worker.ts";

await test("project URLs retain queries and anchors without repeating the base", () => {
  assert.equal(siteHref("/"), "/engineering/projects/code-standards/");
  assert.equal(
    siteHref("/rules/?category=security#rule"),
    "/engineering/projects/code-standards/rules/?category=security#rule",
  );
  assert.equal(
    siteUrl("/sitemap-index.xml"),
    "https://sarj.ai/engineering/projects/code-standards/sitemap-index.xml",
  );
  assert.throws(() => siteHref("//example.com/"));
});

await test("all legacy paths redirect once while preserving search parameters", () => {
  for (const [path, expected] of [
    ["/?a=1&a=2", "/engineering/projects/code-standards/?a=1&a=2"],
    ["//rules/?q=x", "/engineering/projects/code-standards//rules/?q=x"],
    [
      "/rules/python/SARJ001/?q=x",
      "/engineering/projects/code-standards/rules/python/SARJ001/?q=x",
    ],
    ["/engineering/projects/code-standards?q=x", "/engineering/projects/code-standards/?q=x"],
    [
      "/engineering/projects/code-standards/cli/?q=x",
      "/engineering/projects/code-standards/cli/?q=x",
    ],
  ] as const) {
    assert.equal(
      legacyRedirect(`https://code-standards.sarj.ai${path}`),
      `https://sarj.ai${expected}`,
    );
  }
  assert.equal(legacyRedirect("https://sarj.ai/engineering/projects/code-standards/"), undefined);
});

await test("canonical requests reach native assets and legacy requests never do", async () => {
  const canonical = new Request("https://sarj.ai/engineering/projects/code-standards/cli/?q=x");
  const requests: Request[] = [];
  const environment = {
    ASSETS: {
      fetch: (request: Request) => {
        requests.push(request);
        return Promise.resolve(new Response("asset", { status: 200 }));
      },
    },
  };
  const response = await worker.fetch(canonical, environment);
  assert.equal(await response.text(), "asset");
  assert.deepEqual(requests, [canonical]);
  const redirect = await worker.fetch(
    new Request("https://code-standards.sarj.ai/cli/?q=x"),
    environment,
  );
  assert.equal(redirect.status, 301);
  assert.equal(
    redirect.headers.get("location"),
    "https://sarj.ai/engineering/projects/code-standards/cli/?q=x",
  );
  assert.deepEqual(requests, [canonical]);
});

for (const path of ["", "/", "/rules/python/SARJ001/?keep=one&keep=two"]) {
  await test(`old engineering project ${path} redirects directly to the new mount`, () => {
    assert.equal(
      legacyRedirect(`https://engineering.sarj.ai/projects/code-standards${path}`),
      `https://sarj.ai/engineering/projects/code-standards/${path.replace(/^\//u, "")}`,
    );
  });
}

for (const url of [
  "https://sarj.ai/engineering/projects/code-standards-other/",
  "https://sarj.ai/engineering/internal/architecture",
  "https://sarj.ai/blog/",
  "https://unrelated.example/engineering/projects/code-standards/",
  "https://engineering.sarj.ai/projects/code-standards-other/",
]) {
  await test(`rejects unrelated project host or path ${url}`, async () => {
    const response = await worker.fetch(new Request(url), {
      ASSETS: {
        fetch: async () => await Promise.reject(new Error("Must not fetch unrelated assets")),
      },
    });
    assert.equal(response.status, 404);
  });
}
