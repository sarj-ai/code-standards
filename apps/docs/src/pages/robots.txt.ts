import type { APIRoute } from 'astro';

const body = `User-agent: *
Allow: /

Sitemap: https://code-standards.sarj.ai/sitemap-index.xml
`;

export const GET = (() => new Response(body, {
  headers: { 'Content-Type': 'text/plain; charset=utf-8' },
})) satisfies APIRoute;
