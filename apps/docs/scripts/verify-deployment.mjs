import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import process from 'node:process';
import { URL } from 'node:url';

const expectedCommit = process.env.EXPECTED_COMMIT;
assert.ok(expectedCommit, 'EXPECTED_COMMIT is required');
const base = new URL(process.env.DOCS_BASE_URL ?? 'https://code-standards.sarj.ai/');

async function verify() {
  const nonce = `?commit=${encodeURIComponent(expectedCommit)}`;
  const [healthResponse, catalogResponse, uiResponse, galleryResponse] = await Promise.all([
    response(`health.json${nonce}`),
    response('api/v1/catalog.json'),
    response('api/v1/docs-ui.json'),
    response('design-system/'),
  ]);
  for (const [name, candidate] of Object.entries({ healthResponse, catalogResponse, uiResponse, galleryResponse })) {
    assert.ok(candidate.ok, `${name} returned ${String(candidate.status)}`);
  }

  const health = await healthResponse.json();
  const catalogText = await catalogResponse.text();
  const ui = await uiResponse.json();
  const gallery = await galleryResponse.text();
  assert.equal(health.commit, expectedCommit, `live commit ${String(health.commit)} does not match ${expectedCommit}`);
  assert.equal(createHash('sha256').update(catalogText).digest('hex'), health.catalogSha256);
  assert.equal(ui.schemaVersion, 1);
  assert.ok(ui.components.ReferencePage);
  assert.ok(ui.themeTokens.some(({ cssName }) => cssName === '--sarj-color-rule'));
  assert.match(gallery, /<h1[^>]*>Documentation UI<\/h1>/u);

  const csp = galleryResponse.headers.get('content-security-policy') ?? '';
  assert.match(csp, /default-src 'none'/u);
  assert.match(csp, /frame-ancestors 'none'/u);
  assert.equal(galleryResponse.headers.get('cross-origin-resource-policy'), 'same-origin');
  assert.equal(galleryResponse.headers.get('x-content-type-options'), 'nosniff');
  assert.match(catalogResponse.headers.get('cache-control') ?? '', /must-revalidate/u);
  assert.equal(uiResponse.headers.get('access-control-allow-origin'), '*');

  const missing = await response(`definitely-not-a-page-${expectedCommit}/`, { redirect: 'manual' });
  assert.equal(missing.status, 404);
  const slashRedirect = await response('design-system', { redirect: 'manual' });
  assert.ok(slashRedirect.status >= 300 && slashRedirect.status < 400);
  assert.equal(new URL(slashRedirect.headers.get('location'), base).pathname, '/design-system/');

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
