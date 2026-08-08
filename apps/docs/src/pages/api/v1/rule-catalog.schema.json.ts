import type { APIRoute } from 'astro';

import { catalogSchema } from '../../../lib/catalog';

export const GET = (() => new Response(`${JSON.stringify(catalogSchema)}\n`, {
  headers: { 'Content-Type': 'application/schema+json; charset=utf-8' },
})) satisfies APIRoute;
