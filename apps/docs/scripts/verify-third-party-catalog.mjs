import assert from "node:assert/strict";
import { readFile, readdir } from "node:fs/promises";
import { resolve } from "node:path";
import process from "node:process";
import { TextEncoder } from "node:util";
import { URL } from "node:url";
import { gzipSync } from "node:zlib";

const appRoot = resolve(import.meta.dirname, "..");
const artifactPath = resolve(
  appRoot,
  "src/generated/third-party-rules.v1.json",
);
const distRoot = resolve(appRoot, "dist");
const mode = process.argv[2];

assert.ok(
  mode === "--source" || mode === "--dist",
  "usage: node scripts/verify-third-party-catalog.mjs --source|--dist",
);

const catalog = JSON.parse(await readFile(artifactPath, "utf8"));
const profiles = ["application", "standard"];
const autofixValues = new Set(["always", "available", "none", "sometimes"]);
const pageSize = 40;

function verifySource() {
  exactFields(
    catalog,
    ["profiles", "providers", "rules", "schemaVersion"],
    "catalog",
  );
  assert.equal(catalog.schemaVersion, 1);
  assert.deepEqual(catalog.profiles, profiles);
  assert.ok(catalog.providers.length > 0, "catalog must contain providers");
  assert.ok(catalog.rules.length > 0, "catalog must contain rules");

  const providerIds = new Set();
  for (const [index, provider] of catalog.providers.entries()) {
    const label = `providers[${String(index)}]`;
    exactFields(
      provider,
      ["engine", "homepage", "id", "label", "package", "version"],
      label,
    );
    for (const field of ["engine", "id", "label", "package", "version"])
      nonemptyString(provider[field], `${label}.${field}`);
    assert.match(
      provider.id,
      /^[a-z0-9]+(?:-[a-z0-9]+)*$/u,
      `${label}.id must be route-safe`,
    );
    assert.ok(
      !providerIds.has(provider.id),
      `duplicate provider ${provider.id}`,
    );
    providerIds.add(provider.id);
    httpsUrl(provider.homepage, `${label}.homepage`);
  }
  assert.deepEqual(
    catalog.providers.map(({ id }) => id),
    [...providerIds].sort(),
    "providers must use canonical ID order",
  );

  const ruleKeys = new Set();
  const ruleAnchors = new Set();
  const ruleCounts = new Map(
    [...providerIds].map((providerId) => [providerId, 0]),
  );
  for (const [index, rule] of catalog.rules.entries()) {
    const label = `rules[${String(index)}]`;
    exactFields(
      rule,
      [
        "autofix",
        "displayId",
        "docsUrl",
        "family",
        "hasSuggestions",
        "id",
        "key",
        "profiles",
        "provider",
        "summary",
      ],
      label,
    );
    for (const field of ["displayId", "id", "key", "provider", "summary"])
      nonemptyString(rule[field], `${label}.${field}`);
    assert.ok(
      providerIds.has(rule.provider),
      `${label} references unknown provider ${rule.provider}`,
    );
    assert.equal(
      rule.key,
      `${rule.provider}:${rule.id}`,
      `${label}.key must match provider and ID`,
    );
    assert.ok(!ruleKeys.has(rule.key), `duplicate rule ${rule.key}`);
    ruleKeys.add(rule.key);
    const anchor = anchorForRule(rule);
    assert.ok(!ruleAnchors.has(anchor), `duplicate rule anchor ${anchor}`);
    ruleAnchors.add(anchor);
    httpsUrl(rule.docsUrl, `${label}.docsUrl`);
    assert.ok(
      rule.family === null ||
        (typeof rule.family === "string" && rule.family.length > 0),
    );
    assert.equal(
      typeof rule.hasSuggestions,
      "boolean",
      `${label}.hasSuggestions must be boolean`,
    );
    assert.ok(autofixValues.has(rule.autofix), `${label}.autofix is invalid`);
    assert.deepEqual(
      rule.profiles.map(({ name }) => name),
      profiles,
      `${label} must describe both profiles in canonical order`,
    );
    for (const [profileIndex, profile] of rule.profiles.entries()) {
      const profileLabel = `${label}.profiles[${String(profileIndex)}]`;
      exactFields(profile, ["contexts", "name"], profileLabel);
      assert.ok(
        profile.contexts.length > 0,
        `${profileLabel} must contain an enabled context`,
      );
      const contextIds = new Set();
      for (const [contextIndex, context] of profile.contexts.entries()) {
        const contextLabel = `${profileLabel}.contexts[${String(contextIndex)}]`;
        exactFields(context, ["id", "label", "level"], contextLabel);
        nonemptyString(context.id, `${contextLabel}.id`);
        nonemptyString(context.label, `${contextLabel}.label`);
        assert.ok(
          context.level === "error" || context.level === "warning",
          `${contextLabel}.level is invalid`,
        );
        assert.ok(
          !contextIds.has(context.id),
          `${profileLabel} has duplicate context ${context.id}`,
        );
        contextIds.add(context.id);
      }
    }
    ruleCounts.set(rule.provider, ruleCounts.get(rule.provider) + 1);
  }
  assert.deepEqual(
    catalog.rules.map(({ key }) => key),
    [...ruleKeys].sort(),
    "rules must use canonical key order",
  );
  for (const [providerId, count] of ruleCounts)
    assert.ok(count > 0, `${providerId} must own at least one rule`);
  return ruleCounts;
}

function exactFields(value, expected, label) {
  assert.deepEqual(
    Object.keys(value).sort(),
    [...expected].sort(),
    `${label} has unexpected fields`,
  );
}

function httpsUrl(value, label) {
  nonemptyString(value, label);
  assert.equal(new URL(value).protocol, "https:", `${label} must use HTTPS`);
}

function nonemptyString(value, label) {
  assert.equal(typeof value, "string", `${label} must be a string`);
  assert.ok(value.length > 0, `${label} must not be empty`);
}

async function verifyDist(ruleCounts) {
  const index = await readFile(
    resolve(distRoot, "third-party-linters/index.html"),
    "utf8",
  );
  assert.match(
    index,
    /http-equiv="refresh" content="0;url=\/third-party-linters\/ruff\/"/u,
    "index must redirect to Ruff",
  );
  const redirects = await readFile(resolve(distRoot, "_redirects"), "utf8");
  assert.match(
    redirects,
    /^\/third-party-linters \/third-party-linters\/ruff\/ 301$/mu,
  );
  assert.match(
    redirects,
    /^\/third-party-linters\/ \/third-party-linters\/ruff\/ 301$/mu,
  );
  const expectedDirectories = catalog.providers.map(({ id }) => id).sort();
  const actualDirectories = (
    await readdir(resolve(distRoot, "third-party-linters"), {
      withFileTypes: true,
    })
  )
    .filter((entry) => entry.isDirectory())
    .map((entry) => entry.name)
    .sort();
  assert.deepEqual(
    actualDirectories,
    expectedDirectories,
    "built provider routes must exactly match the catalog",
  );

  const expectedProviderOrder = providersForNavigation().map(({ id }) => id);
  const rulesIndex = await readFile(
    resolve(distRoot, "rules/index.html"),
    "utf8",
  );
  assert.ok(
    !detailsAttributesForSummary(rulesIndex, "Third party Rules").includes(
      "open",
    ),
    "Third party Rules must be closed by default outside its active routes",
  );
  const engineIds = ["python", "eslint", "iac", "sql", "text"];
  assert.deepEqual(
    [...rulesIndex.matchAll(/data-sidebar-engine="([^"]+)"/gu)].map(
      (match) => match[1],
    ),
    engineIds,
    "the sidebar must expose one icon hook for every rendered rule engine",
  );
  const stylesheet = await readFile(
    resolve(appRoot, "src/styles/global.css"),
    "utf8",
  );
  assert.ok(
    stylesheet.includes("a[data-sidebar-engine]::before"),
    "sidebar engine marks need a shared decorative box",
  );
  for (const engineId of engineIds) {
    assert.ok(
      stylesheet.includes(
        `data-sidebar-engine='${engineId}'] {\n  --sidebar-engine-mark: url(`,
      ),
      `${engineId} must define a sidebar engine mark`,
    );
  }

  for (const provider of catalog.providers) {
    const rules = rulesForProvider(provider.id);
    const totalPages = Math.ceil(rules.length / pageSize);
    const searchIndexSource = await readFile(
      resolve(distRoot, "third-party-linters", provider.id, "rules.json"),
      "utf8",
    );
    const searchIndex = JSON.parse(searchIndexSource);
    assert.ok(
      gzipSync(searchIndexSource, { level: 9 }).byteLength <= 48_000,
      `${provider.id} compressed search index must stay at or below 48 KB`,
    );
    assert.equal(
      searchIndex.pageSize,
      pageSize,
      `${provider.id} search index must expose the rendered page size`,
    );
    assert.equal(
      searchIndex.provider,
      provider.id,
      `${provider.id} search index must identify its provider`,
    );
    assert.equal(
      searchIndex.entries.length,
      rules.length,
      `${provider.id} search index must cover every rule`,
    );
    for (const [index, rule] of rules.entries()) {
      const entry = searchIndex.entries[index];
      const pageNumber = Math.floor(index / pageSize) + 1;
      exactFields(
        entry,
        ["anchor", "displayId", "family", "href", "summary"],
        `${provider.id} search entry ${String(index)}`,
      );
      assert.equal(entry.anchor, anchorForRule(rule));
      assert.equal(entry.displayId, rule.displayId);
      assert.equal(entry.family, rule.family);
      assert.equal(entry.summary, plainSearchSummary(rule.summary));
      assert.equal(
        entry.href,
        `${providerPageHref(provider.id, pageNumber)}#${anchorForRule(rule)}`,
      );
    }
    const expectedPageDirectories = Array.from(
      { length: totalPages - 1 },
      (_, index) => String(index + 2),
    );
    const actualPageDirectories = (
      await readdir(resolve(distRoot, "third-party-linters", provider.id), {
        withFileTypes: true,
      })
    )
      .filter((entry) => entry.isDirectory())
      .map((entry) => entry.name)
      .sort((left, right) => Number(left) - Number(right));
    assert.deepEqual(
      actualPageDirectories,
      expectedPageDirectories,
      `${provider.id} pagination routes must exactly match its rule count`,
    );

    const providerDocHrefs = [];
    for (let pageNumber = 1; pageNumber <= totalPages; pageNumber += 1) {
      const pagePath =
        pageNumber === 1
          ? resolve(distRoot, "third-party-linters", provider.id, "index.html")
          : resolve(
              distRoot,
              "third-party-linters",
              provider.id,
              String(pageNumber),
              "index.html",
            );
      const page = await readFile(pagePath, "utf8");
      assert.ok(
        new TextEncoder().encode(page).byteLength <= 100_000,
        `${provider.id} page ${String(pageNumber)} must stay at or below 100 KB raw HTML`,
      );
      assert.ok(
        page.includes("Third party Rules"),
        `${provider.id} page ${String(pageNumber)} must label the provider sidebar group`,
      );
      assert.ok(
        pageNumber === 1
          ? detailsAttributesForSummary(page, "Third party Rules").includes(
              "open",
            )
          : page.includes("CSS.escape(providerId)"),
        `${provider.id} page ${String(pageNumber)} must support revealing its active sidebar branch`,
      );
      const hrefs = htmlHrefs(page);
      const hrefSet = new Set(hrefs);
      assert.deepEqual(
        [...page.matchAll(/<a\b[^>]*\bdata-provider="([^"]+)"/gu)].map(
          (match) => match[1],
        ),
        expectedProviderOrder,
        `${provider.id} page ${String(pageNumber)} sidebar providers must be alphabetized by displayed label`,
      );
      const pageRules = rules.slice(
        (pageNumber - 1) * pageSize,
        pageNumber * pageSize,
      );
      assert.deepEqual(
        [
          ...page.matchAll(
            /<li id="([^"]+)" class="third-party-rule-row" data-third-party-rule(?=[ >])/gu,
          ),
        ].map((match) => match[1]),
        pageRules.map((rule) => anchorForRule(rule)),
        `${provider.id} page ${String(pageNumber)} must render its alphabetized rule slice in order`,
      );
      assert.equal(
        occurrences(page, /data-third-party-rule(?=[ >])/gu),
        pageRules.length,
        `${provider.id} page ${String(pageNumber)} must server-render its complete rule slice`,
      );
      assert.ok(
        hrefSet.has(provider.homepage),
        `${provider.id} page ${String(pageNumber)} must link to its official homepage`,
      );
      const expectedDocsUrlCounts = new Map();
      for (const rule of pageRules) {
        expectedDocsUrlCounts.set(
          rule.docsUrl,
          (expectedDocsUrlCounts.get(rule.docsUrl) ?? 0) + 1,
        );
        assert.ok(
          page.includes(escapeHtml(rule.displayId)),
          `${rule.key} must render its rule ID`,
        );
        assert.ok(
          hrefSet.has(
            `${providerPageHref(provider.id, pageNumber)}#${anchorForRule(rule)}`,
          ),
          `${rule.key} must link permanently to its rendered page`,
        );
        assert.ok(
          summaryParts(rule.summary).every((part) =>
            page.includes(escapeHtml(part)),
          ),
          `${rule.key} must render its summary`,
        );
      }
      for (const [docsUrl, expectedCount] of expectedDocsUrlCounts) {
        assert.equal(
          hrefs.filter((href) => href === docsUrl).length,
          expectedCount,
          `${provider.id} page ${String(pageNumber)} must link once per rule to its official explanation`,
        );
      }
      providerDocHrefs.push(
        ...hrefs.filter((href) => expectedDocsUrlCounts.has(href)),
      );
      for (const candidate of catalog.providers) {
        assert.ok(
          hrefSet.has(`/third-party-linters/${candidate.id}/`),
          `${provider.id} page ${String(pageNumber)} navigation must link to ${candidate.id}`,
        );
        assert.ok(
          page.includes(`data-provider="${candidate.id}"`),
          `${provider.id} page ${String(pageNumber)} sidebar must include ${candidate.id}`,
        );
      }
      for (const targetPage of [pageNumber - 1, pageNumber + 1].filter(
        (candidate) => candidate >= 1 && candidate <= totalPages,
      )) {
        assert.ok(
          hrefSet.has(providerPageHref(provider.id, targetPage)),
          `${provider.id} page ${String(pageNumber)} pagination must link to page ${String(targetPage)}`,
        );
      }
    }
    assert.equal(
      providerDocHrefs.length,
      rules.length,
      `${provider.id} pages must cover every rule exactly once`,
    );
  }

  const sitemap = await readFile(resolve(distRoot, "sitemap-0.xml"), "utf8");
  assert.ok(
    !sitemap.includes(
      "<loc>https://code-standards.sarj.ai/third-party-linters/</loc>",
    ),
  );
  for (const provider of catalog.providers) {
    const totalPages = Math.ceil(ruleCounts.get(provider.id) / pageSize);
    for (let pageNumber = 1; pageNumber <= totalPages; pageNumber += 1) {
      assert.ok(
        sitemap.includes(
          `<loc>https://code-standards.sarj.ai${providerPageHref(provider.id, pageNumber)}</loc>`,
        ),
        `sitemap must include ${provider.id} page ${String(pageNumber)}`,
      );
    }
  }
}

function detailsAttributesForSummary(source, label) {
  let labelIndex = source.indexOf(label);
  while (labelIndex >= 0) {
    const summaryStart = source.lastIndexOf("<summary", labelIndex);
    const summaryEnd = source.indexOf("</summary>", summaryStart);
    if (summaryStart >= 0 && summaryEnd >= labelIndex) {
      const detailsStart = source.lastIndexOf("<details", summaryStart);
      const previousDetailsEnd = source.lastIndexOf("</details>", summaryStart);
      assert.ok(
        detailsStart > previousDetailsEnd,
        `${label} summary must belong to a details element`,
      );
      return source.slice(
        detailsStart + "<details".length,
        source.indexOf(">", detailsStart),
      );
    }
    labelIndex = source.indexOf(label, labelIndex + label.length);
  }
  assert.fail(`could not find the ${label} disclosure`);
}

function anchorForRule(rule) {
  const encodedId = [...new TextEncoder().encode(`${rule.provider}:${rule.id}`)]
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
  return `rule-${encodedId}`;
}

function escapeHtml(value) {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function plainSearchSummary(value) {
  return value.replaceAll(/`([^`]+)`/gu, "$1");
}

function providersForNavigation() {
  return [...catalog.providers].sort((left, right) =>
    compareVisible(
      left.label,
      right.label,
      left.id.localeCompare(right.id, "en"),
    ),
  );
}

function rulesForProvider(providerId) {
  return catalog.rules
    .filter((rule) => rule.provider === providerId)
    .sort((left, right) =>
      compareVisible(
        left.displayId,
        right.displayId,
        left.key.localeCompare(right.key, "en"),
      ),
    );
}

function compareVisible(left, right, tieBreaker) {
  return left.localeCompare(right, "en", { sensitivity: "base" }) || tieBreaker;
}

function summaryParts(value) {
  return value
    .split(/`([^`]+)`/gu)
    .map((part) => part.trim())
    .filter(Boolean);
}

function providerPageHref(providerId, page) {
  return page === 1
    ? `/third-party-linters/${providerId}/`
    : `/third-party-linters/${providerId}/${String(page)}/`;
}

function htmlHrefs(source) {
  return [...source.matchAll(/\shref="([^"]+)"/gu)].map((match) =>
    match[1].replaceAll("&amp;", "&"),
  );
}

function occurrences(source, pattern) {
  return source.match(pattern)?.length ?? 0;
}

const ruleCounts = verifySource();
if (mode === "--dist") await verifyDist(ruleCounts);
process.stdout.write(
  `verified third-party catalog ${mode === "--dist" ? "build" : "source"} contract\n`,
);
