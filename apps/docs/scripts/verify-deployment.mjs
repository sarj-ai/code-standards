import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import process from 'node:process';
import { URL } from 'node:url';

const expectedCommit = process.env.EXPECTED_COMMIT;
assert.ok(expectedCommit, 'EXPECTED_COMMIT is required');
const base = new URL(process.env.DOCS_BASE_URL ?? 'https://code-standards.sarj.ai/');

async function verify() {
  const nonce = `?commit=${encodeURIComponent(expectedCommit)}`;
  const [healthResponse, catalogResponse, pageResponse, upstreamResponse, ruffResponse, ruffLastResponse, ruffIndexResponse] = await Promise.all([
    response(`health.json${nonce}`),
    response('api/v1/catalog.json'),
    response(''),
    response(`third-party-linters/${nonce}`, { redirect: 'manual' }),
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

  const health = await healthResponse.json();
  const catalogText = await catalogResponse.text();
  const page = await pageResponse.text();
  const ruffPage = await ruffResponse.text();
  const ruffLastPage = await ruffLastResponse.text();
  const ruffIndex = await ruffIndexResponse.json();
  assert.equal(health.commit, expectedCommit, `live commit ${String(health.commit)} does not match ${expectedCommit}`);
  assert.equal(createHash('sha256').update(catalogText).digest('hex'), health.catalogSha256);
  assert.equal(upstreamResponse.status, 301);
  assert.equal(new URL(upstreamResponse.headers.get('location'), base).pathname, '/third-party-linters/ruff/');
  assert.match(ruffPage, /Third party Rules/u);
  assert.equal(occurrences(ruffPage, /data-third-party-rule(?=[ >])/gu), 50);
  assert.ok(occurrences(ruffLastPage, /data-third-party-rule(?=[ >])/gu) > 0);
  assert.ok(Array.isArray(ruffIndex.entries) && ruffIndex.entries.length > 800);
  assert.ok(ruffIndex.entries.every(({ href }) => typeof href === 'string' && href.includes('#rule-')));
  assert.match(ruffIndexResponse.headers.get('cache-control') ?? '', /must-revalidate/u);
  assert.match(ruffIndexResponse.headers.get('content-type') ?? '', /^application\/json\b/u);
  assert.doesNotMatch(page, /site-search|pagefind|type="search"/iu);
  assert.doesNotMatch(page, /<meta http-equiv="content-security-policy"/iu);
  assert.doesNotMatch(page, /GTM-|zaraz|cloudflareinsights/iu);
  const csp = pageResponse.headers.get('content-security-policy') ?? '';
  assert.match(csp, /default-src 'none'/u);
  assert.match(csp, /frame-ancestors 'none'/u);
  assert.doesNotMatch(csp, /wasm-unsafe-eval/u);
  assert.equal(pageResponse.headers.get('cross-origin-resource-policy'), 'same-origin');
  assert.equal(pageResponse.headers.get('x-content-type-options'), 'nosniff');
  assert.match(catalogResponse.headers.get('cache-control') ?? '', /must-revalidate/u);
  assert.equal((await response('pagefind/pagefind.js')).status, 404);
  assert.equal((await response('design-system/')).status, 404);
  assert.equal((await response('api/v1/docs-ui.json')).status, 404);

  const assetPath = /(?:href|src)="(\/_astro\/[^"]+)"/u.exec(page)?.[1];
  assert.ok(assetPath, 'rendered page must reference a hashed Astro asset');
  assert.equal((await response(assetPath)).headers.get('content-security-policy'), null);

  const about = await response('about/', { redirect: 'manual' });
  assert.equal(about.status, 301);
  assert.equal(new URL(about.headers.get('location'), base).pathname, '/');

  const missing = await response(`definitely-not-a-page-${expectedCommit}/`, {
    redirect: 'manual',
  });
  assert.equal(missing.status, 404);
  const catalog = JSON.parse(catalogText);
  const aliasedRule = catalog.rules.find(({ aliases }) => aliases.length > 0);
  assert.ok(aliasedRule, 'catalog must contain an alias redirect fixture');
  const aliasRedirect = await response(`rules/${aliasedRule.engine}/${aliasedRule.aliases[0]}/`, { redirect: 'manual' });
  assert.ok(aliasRedirect.status >= 300 && aliasRedirect.status < 400);
  assert.equal(new URL(aliasRedirect.headers.get('location'), base).pathname, `/rules/${aliasedRule.engine}/${aliasedRule.id}/`);
}

function occurrences(source, pattern) {
  return source.match(pattern)?.length ?? 0;
}

async function response(path, init) {
  return globalThis.fetch(new URL(path, base), {
    cache: 'no-store',
    signal: globalThis.AbortSignal.timeout(10_000),
    ...init,
  });
}

let lastError;
for (let attempt = 1; attempt <= 10; attempt += 1) {
  try {
    await verify();
    process.stdout.write(`verified deployed documentation contract at ${expectedCommit}\n`);
    lastError = undefined;
    break;
  } catch (error) {
    lastError = error;
    process.stderr.write(`deployment verification attempt ${String(attempt)} failed: ${String(error)}\n`);
    if (attempt < 10) await new Promise((resolve) => globalThis.setTimeout(resolve, 3_000));
  }
}
if (lastError !== undefined) throw lastError;
