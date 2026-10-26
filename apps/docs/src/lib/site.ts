export const SITE_URL = "https://engineering.sarj.ai/projects/code-standards/";
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
  if (url.hostname !== LEGACY_HOSTNAME) return undefined;
  url.protocol = "https:";
  url.host = new globalThis.URL(SITE_ORIGIN).host;
  if (url.pathname === SITE_BASE_PATH.slice(0, -1)) {
    url.pathname = SITE_BASE_PATH;
  } else if (!url.pathname.startsWith(SITE_BASE_PATH)) {
    url.pathname = `${SITE_BASE_PATH.slice(0, -1)}${url.pathname}`;
  }
  return url.href;
}
