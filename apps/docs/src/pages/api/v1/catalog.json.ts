import type { APIRoute } from 'astro';

import { catalogJson } from '../../../lib/catalog';

export const GET = (() => new Response(catalogJson, {
  headers: { 'Content-Type': 'application/json; charset=utf-8' },
})) satisfies APIRoute;
