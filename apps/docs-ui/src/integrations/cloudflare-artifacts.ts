import { createHash } from 'node:crypto';
import { readFile, readdir, writeFile } from 'node:fs/promises';
import type { AstroIntegration } from 'astro';

export default function cloudflareArtifacts(): AstroIntegration {
  return {
    name: 'sarj-docs-ui-cloudflare-artifacts',
    hooks: {
      'astro:build:done': async ({ dir }) => {
        const htmlPaths = (await readdir(dir, { recursive: true })).filter((path) => path.endsWith('.html')).sort();
        const documents = await Promise.all(htmlPaths.map(async (path) => [path, await readFile(new URL(path, dir), 'utf8')] as const));
        const pattern = /(<meta http-equiv="content-security-policy" content=")([^"]+)(">)/u;
        const generatedPolicy = pattern.exec(documents[0]?.[1] ?? '')?.[2];
        if (generatedPolicy === undefined) throw new Error('Astro did not emit a Content Security Policy');
        const hashes = new Set<string>();
        for (const [, document] of documents) {
          for (const match of document.matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/gu)) {
            hashes.add(`'sha256-${createHash('sha256').update(match[1]).digest('base64')}'`);
          }
        }
        const directive = /(script-src-elem [^;]*)(;)/u;
        const current = directive.exec(generatedPolicy)?.[1];
        if (current === undefined) throw new Error('Content Security Policy is missing script-src-elem');
        const additions = [...hashes].sort().filter((hash) => !current.includes(hash));
        const policy = generatedPolicy.replace(directive, `$1 ${additions.join(' ')}$2`);
        const policyHeader = `  Content-Security-Policy: ${policy}`;
        if (Buffer.byteLength(policyHeader, 'utf8') > 2_000) throw new Error('Cloudflare CSP header exceeds 2,000 bytes');
        await Promise.all(documents.map(async ([path, document]) => {
          await writeFile(new URL(path, dir), document.replace(pattern, `$1${policy}$3`), 'utf8');
        }));
        const headersUrl = new URL('_headers', dir);
        const headers = await readFile(headersUrl, 'utf8');
        if (!headers.startsWith('/*\n')) throw new Error('Cloudflare headers must begin with the global route');
        await writeFile(headersUrl, headers.replace('/*\n', `/*\n${policyHeader}\n`), 'utf8');
      },
    },
  };
}
