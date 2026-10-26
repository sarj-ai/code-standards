import { legacyRedirect } from "./lib/site.ts";

interface Environment {
  ASSETS: { fetch: (request: Request) => Promise<Response> };
}

export default {
  fetch(request: Request, environment: Environment): Promise<Response> | Response {
    const redirect = legacyRedirect(request.url);
    return redirect === undefined
      ? environment.ASSETS.fetch(request)
      : Response.redirect(redirect, 301);
  },
};
