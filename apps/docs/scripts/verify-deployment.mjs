import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import process from 'node:process';
import { URL } from 'node:url';

const expectedCommit = process.env.EXPECTED_COMMIT;
assert.ok(expectedCommit, 'EXPECTED_COMMIT is required');
const base = new URL(process.env.DOCS_BASE_URL ?? 'https://code-standards.sarj.ai/');

async function verify() {
  const nonce = `?commit=${encodeURIComponent(expectedCommit)}`;
  const [healthResponse, catalogResponse, pageResponse] = await Promise.all([
    response(`health.json${nonce}`),
    response('api/v1/catalog.json'),
    response(''),
  ]);
  for (const [name, candidate] of Object.entries({ healthResponse, catalogResponse, pageResponse })) {
    assert.ok(candidate.ok, `${name} returned ${String(candidate.status)}`);
  }

  const health = await healthResponse.json();
  const catalogText = await catalogResponse.text();
  const page = await pageResponse.text();
  assert.equal(health.commit, expectedCommit, `live commit ${String(health.commit)} does not match ${expectedCommit}`);
  assert.equal(createHash('sha256').update(catalogText).digest('hex'), health.catalogSha256);
  assert.doesNotMatch(page, /site-search|pagefind|type="search"/iu);
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

  const missing = await response(`definitely-not-a-page-${expectedCommit}/`, { redirect: 'manual' });
  assert.equal(missing.status, 404);
  const catalog = JSON.parse(catalogText);
  const aliasedRule = catalog.rules.find(({ aliases }) => aliases.length > 0);
  assert.ok(aliasedRule, 'catalog must contain an alias redirect fixture');
  const aliasRedirect = await response(`rules/${aliasedRule.engine}/${aliasedRule.aliases[0]}/`, { redirect: 'manual' });
  assert.ok(aliasRedirect.status >= 300 && aliasRedirect.status < 400);
  assert.equal(
    new URL(aliasRedirect.headers.get('location'), base).pathname,
    `/rules/${aliasedRule.engine}/${aliasedRule.id}/`,
  );
}

async function response(path, init) {
  return globalThis.fetch(new URL(path, base), { cache: 'no-store', ...init });
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
    if (attempt < 10) await new Promise((resolve) => globalThis.setTimeout(resolve, 3_000));
  }
}
if (lastError !== undefined) throw lastError;
