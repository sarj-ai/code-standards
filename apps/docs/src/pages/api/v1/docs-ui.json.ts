import { componentCatalog, themeTokenCatalog } from '@sarj/docs-ui/catalog';
import type { APIRoute } from 'astro';

const body = `${JSON.stringify({ schemaVersion: 1, components: componentCatalog, themeTokens: themeTokenCatalog })}\n`;

export const GET = (() => new Response(body, {
  headers: {
    'Cache-Control': 'public, max-age=300',
    'Content-Type': 'application/json; charset=utf-8',
  },
})) satisfies APIRoute;
