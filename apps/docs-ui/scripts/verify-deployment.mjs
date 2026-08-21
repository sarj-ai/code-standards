import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import process from 'node:process';
import { URL } from 'node:url';

const expectedCommit = process.env.EXPECTED_COMMIT;
assert.ok(expectedCommit, 'EXPECTED_COMMIT is required');
const base = new URL(process.env.DOCS_UI_BASE_URL ?? 'https://docs-ui.sarj.ai/');

async function verify() {
  const [healthResponse, contractResponse, pageResponse, componentsResponse] = await Promise.all([
    response(`health.json?commit=${encodeURIComponent(expectedCommit)}`),
    response('api/v1/docs-ui.json'),
    response(''),
    response('components/'),
  ]);
  for (const [name, candidate] of Object.entries({ healthResponse, contractResponse, pageResponse, componentsResponse })) {
    assert.ok(candidate.ok, `${name} returned ${String(candidate.status)}`);
  }
  const health = await healthResponse.json();
  const contractText = await contractResponse.text();
  const contract = JSON.parse(contractText);
  const page = await pageResponse.text();
  const components = await componentsResponse.text();
  assert.equal(health.commit, expectedCommit);
  assert.equal(createHash('sha256').update(contractText).digest('hex'), health.contractSha256);
  assert.deepEqual(Object.keys(contract.components).sort(), ['Breadcrumbs', 'CodeComparison', 'PageAnchor', 'ReferencePage', 'RulePager']);
  assert.equal(contract.themeTokens.length, 6);
  assert.match(page, /<img[^>]+alt="Sarj"/u);
  assert.match(page, /data-has-sidebar/u);
  assert.match(page, />About<\/span>/u);
  assert.match(page, />Components<\/span>/u);
  assert.match(page, /href="\/components\/"/u);
  assert.match(components, /href="\/"/u);
  for (const name of Object.keys(contract.components)) assert.match(components, new RegExp(`id="${name.toLowerCase()}"`, 'u'));
  for (const token of contract.themeTokens) assert.match(components, new RegExp(token.cssName, 'u'));
  assert.doesNotMatch(page, /@sarj\/docs-ui|Live exports|surface-counts/u);
  assert.doesNotMatch(components, /Live exports|surface-counts/u);
  assert.doesNotMatch(page, /site-search|pagefind|type="search"/iu);
  assert.doesNotMatch(pageResponse.headers.get('content-security-policy') ?? '', /wasm-unsafe-eval/u);
  assert.match(pageResponse.headers.get('content-security-policy') ?? '', /default-src 'none'/u);
  assert.equal(pageResponse.headers.get('cross-origin-resource-policy'), 'same-origin');
  assert.equal(contractResponse.headers.get('access-control-allow-origin'), '*');
  assert.equal((await response('pagefind/pagefind.js')).status, 404);
  assert.equal((await response(`definitely-not-a-page-${expectedCommit}/`)).status, 404);
}

async function response(path, init) {
  return globalThis.fetch(new URL(path, base), { cache: 'no-store', ...init });
}

let lastError;
for (let attempt = 1; attempt <= 20; attempt += 1) {
  try {
    await verify();
    process.stdout.write(`verified deployed documentation UI at ${expectedCommit}\n`);
    lastError = undefined;
    break;
  } catch (error) {
    lastError = error;
    if (attempt < 20) await new Promise((resolve) => globalThis.setTimeout(resolve, 15_000));
  }
}
if (lastError !== undefined) throw lastError;
