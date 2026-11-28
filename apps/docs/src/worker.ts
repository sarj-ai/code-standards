import { SITE_BASE_PATH, SITE_ORIGIN, legacyRedirect } from "./lib/site.ts";

interface Environment {
  ASSETS: { fetch: (request: Request) => Promise<Response> };
}

const worker = {
  fetch(request: Request, environment: Environment): Promise<Response> | Response {
    const redirect = legacyRedirect(request.url);
    if (redirect !== undefined) return Response.redirect(redirect, 301);
    const url = new URL(request.url);
    if (
      url.origin !== SITE_ORIGIN ||
      (url.pathname !== SITE_BASE_PATH.slice(0, -1) && !url.pathname.startsWith(SITE_BASE_PATH))
    )
      return new Response("Not found", { status: 404 });
    return environment.ASSETS.fetch(request);
  },
} as const;

export default worker;
