import { componentCatalog, themeTokenCatalog } from '@sarj/docs-ui/catalog';
import type { APIRoute } from 'astro';

export const docsUiContract = Object.freeze({ schemaVersion: 1, components: componentCatalog, themeTokens: themeTokenCatalog });
const body = `${JSON.stringify(docsUiContract)}\n`;

export const GET = (() => new Response(body, {
  headers: { 'Content-Type': 'application/json; charset=utf-8' },
})) satisfies APIRoute;
