import assert from "node:assert/strict";
import { hash } from "node:crypto";
import { readFile } from "node:fs/promises";
import process from "node:process";
import { URL } from "node:url";

import { parseCatalog } from "../src/lib/third-party-catalog.ts";
import { validateCatalog } from "../src/lib/catalog-validation.ts";
import { array, record, text } from "./_json.ts";

const expectedCommit = text(process.env["EXPECTED_COMMIT"], "EXPECTED_COMMIT");
assert.ok(expectedCommit, "EXPECTED_COMMIT is required");
const base = new URL(
  process.env["DOCS_BASE_URL"] ?? "https://code-standards.sarj.ai/",
);
const thirdPartyCatalog = parseCatalog(
  JSON.parse(
    await readFile(
      new URL("../src/generated/third-party-rules.v1.json", import.meta.url),
      "utf8",
    ),
  ) as unknown,
);
const mobileProviderIds = [
  "detekt",
  "ktlint",
  "mobsfscan",
  "swiftformat",
  "swiftlint",
];
const expectedMobileRuleCounts = new Map(
  mobileProviderIds.map((provider) => [
    provider,
    thirdPartyCatalog.rules.filter((rule) => rule.provider === provider).length,
  ]),
);

async function verify() {
  const nonce = `?commit=${encodeURIComponent(expectedCommit)}`;
  const [
    healthResponse,
    catalogResponse,
    pageResponse,
    upstreamResponse,
    ruffResponse,
    ruffLastResponse,
    ruffIndexResponse,
  ] = await Promise.all([
    response(`health.json${nonce}`),
    response("api/v1/catalog.json"),
    response(""),
    response(`third-party-linters/${nonce}`, { redirect: "manual" }),
    response(`third-party-linters/ruff/${nonce}`),
    response(`third-party-linters/ruff/19/${nonce}`),
    response(`third-party-linters/ruff/rules.json${nonce}`),
  ]);
  for (const [name, candidate] of Object.entries({
    healthResponse,
    catalogResponse,
    pageResponse,
    ruffIndexResponse,
    ruffLastResponse,
    ruffResponse,
  })) {
    assert.ok(candidate.ok, `${name} returned ${String(candidate.status)}`);
  }

  const health = record(
    (await healthResponse.json()) as unknown,
    "live health",
  );
  const catalogText = await catalogResponse.text();
  const page = await pageResponse.text();
  const ruffPage = await ruffResponse.text();
  const ruffLastPage = await ruffLastResponse.text();
  const ruffIndex = record(
    (await ruffIndexResponse.json()) as unknown,
    "live Ruff index",
  );
  const ruffEntries = array(ruffIndex["entries"], "Ruff entries");
  const mobileProviders = await Promise.all(
    mobileProviderIds.map(async (provider) => {
      const [providerResponse, indexResponse] = await Promise.all([
        response(`third-party-linters/${provider}/${nonce}`),
        response(`third-party-linters/${provider}/rules.json${nonce}`),
      ]);
      return { indexResponse, provider, providerResponse };
    }),
  );
  assert.equal(
    health["commit"],
    expectedCommit,
    `live commit ${String(health["commit"])} does not match ${expectedCommit}`,
  );
  assert.equal(hash("sha256", catalogText, "hex"), health["catalogSha256"]);
  assert.equal(upstreamResponse.status, 301);
  assert.equal(
    new URL(
      text(upstreamResponse.headers.get("location"), "redirect location"),
      base,
    ).pathname,
    "/third-party-linters/ruff/",
  );
  assert.match(ruffPage, /Third party Rules/u);
  assert.equal(
    occurrences(ruffPage, /data-third-party-rule(?=[ >])/gu),
    ruffIndex["pageSize"],
  );
  assert.ok(occurrences(ruffLastPage, /data-third-party-rule(?=[ >])/gu) > 0);
  assert.ok(ruffEntries.length > 800);
  assert.ok(
    ruffEntries.every((value) => {
      const href = record(value, "Ruff entry")["href"];
      return typeof href === "string" && href.includes("#rule-");
    }),
  );
  assert.match(
    ruffIndexResponse.headers.get("cache-control") ?? "",
    /must-revalidate/u,
  );
  assert.match(
    ruffIndexResponse.headers.get("content-type") ?? "",
    /^application\/json\b/u,
  );
  for (const { indexResponse, provider, providerResponse } of mobileProviders) {
    assert.ok(
      providerResponse.ok,
      `${provider} provider page returned ${String(providerResponse.status)}`,
    );
    assert.ok(
      indexResponse.ok,
      `${provider} rules index returned ${String(indexResponse.status)}`,
    );
    assert.match(await providerResponse.text(), /Third party Rules/u);
    const index = record(
      (await indexResponse.json()) as unknown,
      "provider index",
    );
    const entries = array(index["entries"], "provider entries");
    assert.ok(
      Array.isArray(entries),
      `${provider} rules index entries must be an array`,
    );
    assert.equal(entries.length, expectedMobileRuleCounts.get(provider));
    assert.match(
      indexResponse.headers.get("cache-control") ?? "",
      /must-revalidate/u,
    );
    assert.match(
      indexResponse.headers.get("content-type") ?? "",
      /^application\/json\b/u,
    );
    assert.match(
      page,
      new RegExp(`href="/third-party-linters/${provider}/"`, "u"),
    );
  }
  assert.doesNotMatch(page, /site-search|pagefind|type="search"/iu);
  assert.doesNotMatch(page, /<meta http-equiv="content-security-policy"/iu);
  assert.doesNotMatch(page, /GTM-|zaraz|cloudflareinsights/iu);
  const csp = pageResponse.headers.get("content-security-policy") ?? "";
  assert.match(csp, /default-src 'none'/u);
  assert.match(csp, /frame-ancestors 'none'/u);
  assert.doesNotMatch(csp, /wasm-unsafe-eval/u);
  assert.equal(
    pageResponse.headers.get("cross-origin-resource-policy"),
    "same-origin",
  );
  assert.equal(pageResponse.headers.get("x-content-type-options"), "nosniff");
  assert.match(
    catalogResponse.headers.get("cache-control") ?? "",
    /must-revalidate/u,
  );
  assert.equal((await response("pagefind/pagefind.js")).status, 404);
  assert.equal((await response("design-system/")).status, 404);
  assert.equal((await response("api/v1/docs-ui.json")).status, 404);

  const assetPath = /(?:href|src)="(\/_astro\/[^"]+)"/u.exec(page)?.[1];
  assert.ok(assetPath, "rendered page must reference a hashed Astro asset");
  assert.equal(
    (await response(assetPath)).headers.get("content-security-policy"),
    null,
  );

  const about = await response("about/", { redirect: "manual" });
  assert.equal(about.status, 301);
  assert.equal(
    new URL(text(about.headers.get("location"), "redirect location"), base)
      .pathname,
    "/",
  );

  const missing = await response(`definitely-not-a-page-${expectedCommit}/`, {
    redirect: "manual",
  });
  assert.equal(missing.status, 404);
  const catalog: unknown = JSON.parse(catalogText);
  validateCatalog(catalog);
  const aliasedRule = catalog.rules.find(({ aliases }) => aliases.length > 0);
  assert.ok(aliasedRule, "catalog must contain an alias redirect fixture");
  const aliasRedirect = await response(
    `rules/${aliasedRule.engine}/${aliasedRule.aliases[0]}/`,
    { redirect: "manual" },
  );
  assert.ok(aliasRedirect.status >= 300 && aliasRedirect.status < 400);
  assert.equal(
    new URL(
      text(aliasRedirect.headers.get("location"), "redirect location"),
      base,
    ).pathname,
    `/rules/${aliasedRule.engine}/${aliasedRule.id}/`,
  );
}

function occurrences(source: string, pattern: RegExp) {
  return source.match(pattern)?.length ?? 0;
}

async function response(path: string, init: RequestInit = {}) {
  const target = new URL(path, base);
  target.searchParams.set("commit", expectedCommit);
  return globalThis.fetch(target, {
    cache: "no-store",
    signal: globalThis.AbortSignal.timeout(10_000),
    ...init,
  });
}

let lastError: Error | undefined;
for (let attempt = 1; attempt <= 10; attempt += 1) {
  try {
    await verify();
    process.stdout.write(
      `verified deployed documentation contract at ${expectedCommit}\n`,
    );
    lastError = undefined;
    break;
  } catch (error) {
    lastError =
      error instanceof Error
        ? error
        : new Error(String(error), { cause: error });
    process.stderr.write(
      `deployment verification attempt ${String(attempt)} failed: ${String(error)}\n`,
    );
    if (attempt < 10)
      await new Promise((resolve) => globalThis.setTimeout(resolve, 3_000));
  }
}
if (lastError !== undefined) throw lastError;
