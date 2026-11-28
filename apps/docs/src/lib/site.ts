export const SITE_URL = "https://sarj.ai/engineering/projects/code-standards/";
export const SITE_ORIGIN = new globalThis.URL(SITE_URL).origin;
export const SITE_BASE_PATH = new globalThis.URL(SITE_URL).pathname;
export const LEGACY_HOSTNAME = "code-standards.sarj.ai";

export function siteHref(path: string): string {
  if (!path.startsWith("/") || path.startsWith("//")) {
    throw new Error("Project links must start with exactly one slash");
  }
  return `${SITE_BASE_PATH.slice(0, -1)}${path}`;
}

export function siteUrl(path: string): string {
  return new globalThis.URL(siteHref(path), SITE_ORIGIN).href;
}

export function legacyRedirect(requestUrl: string): string | undefined {
  const url = new globalThis.URL(requestUrl);
  const oldBase = "/projects/code-standards/";
  const oldEngineering =
    url.hostname === "engineering.sarj.ai" &&
    (url.pathname === oldBase.slice(0, -1) || url.pathname.startsWith(oldBase));
  if (url.hostname !== LEGACY_HOSTNAME && !oldEngineering) return undefined;
  const destination = new globalThis.URL(SITE_URL);
  if (url.pathname === SITE_BASE_PATH.slice(0, -1) || url.pathname === oldBase.slice(0, -1)) {
    destination.pathname = SITE_BASE_PATH;
  } else if (url.pathname.startsWith(SITE_BASE_PATH)) {
    destination.pathname = url.pathname;
  } else if (url.pathname.startsWith(oldBase)) {
    destination.pathname = `${SITE_BASE_PATH}${url.pathname.slice(oldBase.length)}`;
  } else {
    destination.pathname = `${SITE_BASE_PATH}${url.pathname.slice(1)}`;
  }
  destination.search = url.search;
  return destination.href;
}
