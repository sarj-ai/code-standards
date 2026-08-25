import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { resolve } from 'node:path';
import process from 'node:process';
import { URL } from 'node:url';

const appRoot = resolve(import.meta.dirname, '..');
const artifactPath = resolve(appRoot, 'src/generated/third-party-rules.v1.json');
const distRoot = resolve(appRoot, 'dist');
const mode = process.argv[2];

assert.ok(mode === '--source' || mode === '--dist', 'usage: node scripts/verify-third-party-catalog.mjs --source|--dist');

const catalog = JSON.parse(readFileSync(artifactPath, 'utf8'));
const profiles = ['application', 'standard'];
const autofixValues = new Set(['always', 'available', 'none', 'sometimes']);
const pageSize = 50;

function verifySource() {
  exactFields(catalog, ['profiles', 'providers', 'rules', 'schemaVersion'], 'catalog');
  assert.equal(catalog.schemaVersion, 1);
  assert.deepEqual(catalog.profiles, profiles);
  assert.ok(catalog.providers.length > 0, 'catalog must contain providers');
  assert.ok(catalog.rules.length > 0, 'catalog must contain rules');

  const providerIds = new Set();
  for (const [index, provider] of catalog.providers.entries()) {
    const label = `providers[${String(index)}]`;
    exactFields(provider, ['engine', 'homepage', 'id', 'label', 'package', 'version'], label);
    for (const field of ['engine', 'id', 'label', 'package', 'version']) nonemptyString(provider[field], `${label}.${field}`);
    assert.match(provider.id, /^[a-z0-9]+(?:-[a-z0-9]+)*$/u, `${label}.id must be route-safe`);
    assert.ok(!providerIds.has(provider.id), `duplicate provider ${provider.id}`);
    providerIds.add(provider.id);
    httpsUrl(provider.homepage, `${label}.homepage`);
  }
  assert.deepEqual(
    catalog.providers.map(({ id }) => id),
    [...providerIds].sort(),
    'providers must use canonical ID order',
  );

  const ruleKeys = new Set();
  const ruleCounts = new Map([...providerIds].map((providerId) => [providerId, 0]));
  for (const [index, rule] of catalog.rules.entries()) {
    const label = `rules[${String(index)}]`;
    exactFields(
      rule,
      ['autofix', 'displayId', 'docsUrl', 'family', 'hasSuggestions', 'id', 'key', 'profiles', 'provider', 'summary'],
      label,
    );
    for (const field of ['displayId', 'id', 'key', 'provider', 'summary']) nonemptyString(rule[field], `${label}.${field}`);
    assert.ok(providerIds.has(rule.provider), `${label} references unknown provider ${rule.provider}`);
    assert.equal(rule.key, `${rule.provider}:${rule.id}`, `${label}.key must match provider and ID`);
    assert.ok(!ruleKeys.has(rule.key), `duplicate rule ${rule.key}`);
    ruleKeys.add(rule.key);
    httpsUrl(rule.docsUrl, `${label}.docsUrl`);
    assert.ok(rule.family === null || (typeof rule.family === 'string' && rule.family.length > 0));
    assert.equal(typeof rule.hasSuggestions, 'boolean', `${label}.hasSuggestions must be boolean`);
    assert.ok(autofixValues.has(rule.autofix), `${label}.autofix is invalid`);
    assert.deepEqual(rule.profiles.map(({ name }) => name), profiles, `${label} must describe both profiles in canonical order`);
    for (const [profileIndex, profile] of rule.profiles.entries()) {
      const profileLabel = `${label}.profiles[${String(profileIndex)}]`;
      exactFields(profile, ['contexts', 'name'], profileLabel);
      assert.ok(profile.contexts.length > 0, `${profileLabel} must contain an enabled context`);
      const contextIds = new Set();
      for (const [contextIndex, context] of profile.contexts.entries()) {
        const contextLabel = `${profileLabel}.contexts[${String(contextIndex)}]`;
        exactFields(context, ['id', 'label', 'level'], contextLabel);
        nonemptyString(context.id, `${contextLabel}.id`);
        nonemptyString(context.label, `${contextLabel}.label`);
        assert.ok(context.level === 'error' || context.level === 'warning', `${contextLabel}.level is invalid`);
        assert.ok(!contextIds.has(context.id), `${profileLabel} has duplicate context ${context.id}`);
        contextIds.add(context.id);
      }
    }
    ruleCounts.set(rule.provider, ruleCounts.get(rule.provider) + 1);
  }
  assert.deepEqual(catalog.rules.map(({ key }) => key), [...ruleKeys].sort(), 'rules must use canonical key order');
  for (const [providerId, count] of ruleCounts) assert.ok(count > 0, `${providerId} must own at least one rule`);
  return ruleCounts;
}

function exactFields(value, expected, label) {
  assert.deepEqual(Object.keys(value).sort(), [...expected].sort(), `${label} has unexpected fields`);
}

function httpsUrl(value, label) {
  nonemptyString(value, label);
  assert.equal(new URL(value).protocol, 'https:', `${label} must use HTTPS`);
}

function nonemptyString(value, label) {
  assert.equal(typeof value, 'string', `${label} must be a string`);
  assert.ok(value.length > 0, `${label} must not be empty`);
}

function verifyDist(ruleCounts) {
  const index = readFileSync(resolve(distRoot, 'third-party-linters/index.html'), 'utf8');
  const expectedDirectories = catalog.providers.map(({ id }) => id).sort();
  const actualDirectories = readdirSync(resolve(distRoot, 'third-party-linters'), { withFileTypes: true })
    .filter((entry) => entry.isDirectory())
    .map((entry) => entry.name)
    .sort();
  assert.deepEqual(actualDirectories, expectedDirectories, 'built provider routes must exactly match the catalog');

  const indexHrefs = new Set(htmlHrefs(index));
  for (const provider of catalog.providers) {
    const route = `/third-party-linters/${provider.id}/`;
    const count = ruleCounts.get(provider.id);
    assert.ok(indexHrefs.has(route), `index must link to ${route}`);
    assert.ok(index.includes(`${String(count)} enabled rules`), `index must expose ${provider.id}'s rule count`);

    const rules = catalog.rules.filter((rule) => rule.provider === provider.id);
    const totalPages = Math.ceil(rules.length / pageSize);
    const expectedPageDirectories = Array.from({ length: totalPages - 1 }, (_, index) => String(index + 2));
    const actualPageDirectories = readdirSync(resolve(distRoot, 'third-party-linters', provider.id), { withFileTypes: true })
      .filter((entry) => entry.isDirectory())
      .map((entry) => entry.name)
      .sort((left, right) => Number(left) - Number(right));
    assert.deepEqual(actualPageDirectories, expectedPageDirectories, `${provider.id} pagination routes must exactly match its rule count`);

    const providerDocHrefs = [];
    for (let pageNumber = 1; pageNumber <= totalPages; pageNumber += 1) {
      const pagePath = pageNumber === 1
        ? resolve(distRoot, 'third-party-linters', provider.id, 'index.html')
        : resolve(distRoot, 'third-party-linters', provider.id, String(pageNumber), 'index.html');
      const page = readFileSync(pagePath, 'utf8');
      const hrefs = htmlHrefs(page);
      const hrefSet = new Set(hrefs);
      const pageRules = rules.slice((pageNumber - 1) * pageSize, pageNumber * pageSize);
      assert.equal(
        occurrences(page, /data-third-party-rule(?=[ >])/gu),
        pageRules.length,
        `${provider.id} page ${String(pageNumber)} must server-render its complete rule slice`,
      );
      assert.ok(hrefSet.has(provider.homepage), `${provider.id} page ${String(pageNumber)} must link to its official homepage`);
      const expectedDocsUrlCounts = new Map();
      for (const rule of pageRules) {
        expectedDocsUrlCounts.set(rule.docsUrl, (expectedDocsUrlCounts.get(rule.docsUrl) ?? 0) + 1);
      }
      for (const [docsUrl, expectedCount] of expectedDocsUrlCounts) {
        assert.equal(
          hrefs.filter((href) => href === docsUrl).length,
          expectedCount,
          `${provider.id} page ${String(pageNumber)} must link once per rule to its official explanation`,
        );
      }
      providerDocHrefs.push(...hrefs.filter((href) => expectedDocsUrlCounts.has(href)));
      for (const candidate of catalog.providers) {
        assert.ok(hrefSet.has(`/third-party-linters/${candidate.id}/`), `${provider.id} page ${String(pageNumber)} navigation must link to ${candidate.id}`);
      }
      for (let targetPage = 1; targetPage <= totalPages; targetPage += 1) {
        assert.ok(
          hrefSet.has(providerPageHref(provider.id, targetPage)),
          `${provider.id} page ${String(pageNumber)} pagination must link to page ${String(targetPage)}`,
        );
      }
    }
    assert.equal(providerDocHrefs.length, rules.length, `${provider.id} pages must cover every rule exactly once`);
  }

  const sitemap = readFileSync(resolve(distRoot, 'sitemap-0.xml'), 'utf8');
  assert.ok(sitemap.includes('<loc>https://code-standards.sarj.ai/third-party-linters/</loc>'));
  for (const provider of catalog.providers) {
    const totalPages = Math.ceil(ruleCounts.get(provider.id) / pageSize);
    for (let pageNumber = 1; pageNumber <= totalPages; pageNumber += 1) {
      assert.ok(
        sitemap.includes(`<loc>https://code-standards.sarj.ai${providerPageHref(provider.id, pageNumber)}</loc>`),
        `sitemap must include ${provider.id} page ${String(pageNumber)}`,
      );
    }
  }
}

function providerPageHref(providerId, page) {
  return page === 1 ? `/third-party-linters/${providerId}/` : `/third-party-linters/${providerId}/${String(page)}/`;
}

function htmlHrefs(source) {
  return [...source.matchAll(/\shref="([^"]+)"/gu)].map((match) => match[1].replaceAll('&amp;', '&'));
}

function occurrences(source, pattern) {
  return source.match(pattern)?.length ?? 0;
}

const ruleCounts = verifySource();
if (mode === '--dist') verifyDist(ruleCounts);
process.stdout.write(`verified third-party catalog ${mode === '--dist' ? 'build' : 'source'} contract\n`);
