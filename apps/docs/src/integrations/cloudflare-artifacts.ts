import { hash } from 'node:crypto';
import { readFile, readdir, writeFile } from 'node:fs/promises';
import type { AstroIntegration } from 'astro';

import { catalog, ruleHref } from '../lib/catalog';

export default function cloudflareArtifacts(): AstroIntegration {
  return {
    name: 'sarj-cloudflare-static-artifacts',
    hooks: {
      'astro:build:done': async ({ dir }) => {
        const redirects = new Set<string>([
          '/about / 301',
          '/about/ / 301',
          '/third-party-linters /third-party-linters/ruff/ 301',
          '/third-party-linters/ /third-party-linters/ruff/ 301',
        ]);
        for (const rule of catalog.rules) {
          for (const alias of rule.aliases) {
            const target = ruleHref(rule);
            redirects.add(`/rules/${rule.engine}/${alias} ${target} 301`);
            redirects.add(`/rules/${rule.engine}/${alias}/ ${target} 301`);
          }
        }
        const body = ['# Generated canonical redirects. Do not edit.', ...[...redirects].sort(), ''].join('\n');
        await writeFile(new URL('_redirects', dir), body, 'utf8');
        await verifyIndexableSitemap(dir);
        await writeContentSecurityPolicyHeader(dir);
      },
    },
  };
}

async function verifyIndexableSitemap(dir: URL): Promise<void> {
  const sitemapIndex = await readFile(new URL('sitemap-index.xml', dir), 'utf8');
  if (!sitemapIndex.includes('https://code-standards.sarj.ai/sitemap-0.xml')) {
    throw new Error('Sitemap index does not reference the canonical code-standards sitemap');
  }

  const sitemap = await readFile(new URL('sitemap-0.xml', dir), 'utf8');
  const locations = [...sitemap.matchAll(/<loc>([^<]+)<\/loc>/gu)].map((match) => match[1]);
  if (locations.some((location) => new URL(location).pathname === '/about/')) {
    throw new Error('Non-canonical /about/ alias must not appear in the sitemap');
  }

  for (const location of locations) {
    const url = new URL(location);
    if (url.origin !== 'https://code-standards.sarj.ai') {
      throw new Error(`Cross-origin sitemap URL: ${location}`);
    }
    const relativePath = url.pathname === '/' ? 'index.html' : `${url.pathname.slice(1)}index.html`;
    const document = await readFile(new URL(relativePath, dir), 'utf8');
    if (document.includes('name="robots" content="noindex')) {
      throw new Error(`Sitemap URL is marked noindex: ${location}`);
    }
    if (!document.includes(`rel="canonical" href="${location}"`)) {
      throw new Error(`Sitemap URL is missing its self-canonical link: ${location}`);
    }
  }
}

async function writeContentSecurityPolicyHeader(dir: URL): Promise<void> {
  const htmlPaths = (await readdir(dir, { recursive: true }))
    .filter((path) => path.endsWith('.html'))
    .sort();
  const documents = await Promise.all(
    htmlPaths.map(async (path) => [path, await readFile(new URL(path, dir), 'utf8')] as const),
  );
  const generatedPolicy = contentSecurityPolicy(documents[0]?.[1] ?? '');
  if (generatedPolicy === undefined) {
    throw new Error('Astro did not emit a Content Security Policy');
  }
  const hashes = inlineScriptHashes(documents.map(([, document]) => document));
  const policy = appendDirectiveValues(generatedPolicy, 'script-src-elem', hashes);
  const policyHeader = `  Content-Security-Policy: ${policy}`;
  if (Buffer.byteLength(policyHeader, 'utf8') > 2_000) {
    throw new Error('Cloudflare Content-Security-Policy header exceeds the 2,000-byte line limit');
  }

  await Promise.all(
    documents.map(async ([path, document]) => {
      const updated = document.replace(contentSecurityPolicyPattern(), '');
      await writeFile(new URL(path, dir), updated, 'utf8');
    }),
  );

  const headersUrl = new URL('_headers', dir);
  const headers = await readFile(headersUrl, 'utf8');
  const rootHeader = '/*\n';
  if (!headers.startsWith(rootHeader)) {
    throw new Error('Cloudflare headers must begin with the global route');
  }

  const generated = headers.replace(
    rootHeader,
    `${rootHeader}${policyHeader}\n`,
  );
  await writeFile(headersUrl, generated, 'utf8');
}

function contentSecurityPolicy(document: string): string | undefined {
  return contentSecurityPolicyPattern().exec(document)?.[2];
}

function contentSecurityPolicyPattern(): RegExp {
  return /(<meta http-equiv="content-security-policy" content=")([^"]+)(">)/u;
}

function inlineScriptHashes(documents: readonly string[]): readonly string[] {
  const hashes = new Set<string>();
  for (const document of documents) {
    const pattern = /<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/gu;
    for (const match of document.matchAll(pattern)) {
      hashes.add(`'sha256-${hash('sha256', match[1], 'base64')}'`);
    }
  }
  return [...hashes].sort();
}

function appendDirectiveValues(policy: string, directive: string, values: readonly string[]): string {
  const pattern = new RegExp(`(${directive} [^;]*)(;)`, 'u');
  const current = pattern.exec(policy)?.[1];
  if (current === undefined) {
    throw new Error(`Content Security Policy is missing ${directive}`);
  }
  const additions = values.filter((value) => !current.includes(value));
  return policy.replace(pattern, `$1 ${additions.join(' ')}$2`);
}
