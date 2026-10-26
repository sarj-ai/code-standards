import type { APIRoute } from 'astro';
import { siteUrl } from '../lib/site.ts';

const body = `User-agent: *
Allow: /

Sitemap: ${siteUrl('/sitemap-index.xml')}
`;

export const GET = (() => new Response(body, {
  headers: { 'Content-Type': 'text/plain; charset=utf-8' },
})) satisfies APIRoute;
