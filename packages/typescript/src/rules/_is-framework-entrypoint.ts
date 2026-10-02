/** @fileoverview _is-framework-entrypoint — recognize framework-owned paths and runtime export contracts. */
import { readFileSync } from "node:fs";
import { dirname, join, relative } from "node:path";

const HTTP_METHODS: ReadonlySet<string> = new Set(["GET", "HEAD", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"]);
const NEXT_COMPONENT = /^(?:src\/)?app\/(?:.*\/)?(?:page|layout|loading|not-found|template|error|global-error|default|forbidden|unauthorized)\.[jt]sx?$/u;
const NEXT_METADATA = /^(?:src\/)?app\/(?:.*\/)?(?:(?:opengraph-image|twitter-image|icon|apple-icon)\.[jt]sx?|(?:robots|sitemap|manifest)\.[jt]s)$/u;
const NEXT_ROUTE = /^(?:src\/)?app\/(?:.*\/)?route\.[jt]s$/u;

export function isFrameworkEntrypoint(filename: string, exportKey: string): boolean {
  const normalized = filename.replaceAll("\\", "/");
  if (!/(?:^|\/)(?:app|pages)\/|(?:^|\/)(?:middleware|proxy|instrumentation)\.[jt]s$/u.test(normalized)) return false;
  const owner = packageOwner(normalized);
  if (owner === null) return false;
  const path = relative(owner.root, normalized).replaceAll("\\", "/");
  if (declaresFramework(owner.metadata, "next") && isNextEntrypoint(path, exportKey)) return true;
  return declaresFramework(owner.metadata, "astro") && isAstroEntrypoint(path, exportKey);
}

function isNextEntrypoint(path: string, exportKey: string): boolean {
  const privateAppFolder = /^(?:src\/)?app\/(?:.*\/)?_[^/]+\//u.test(path);
  if (!privateAppFolder && (NEXT_COMPONENT.test(path) || NEXT_METADATA.test(path)) && exportKey === "default") return true;
  if (!privateAppFolder && NEXT_ROUTE.test(path) && HTTP_METHODS.has(exportKey)) return true;
  if (/^(?:src\/)?pages\/.*\.[jt]sx?$/u.test(path) && exportKey === "default") return true;
  if (/^(?:src\/)?instrumentation\.[jt]s$/u.test(path)) {
    return exportKey === "register" || exportKey === "onRequestError";
  }
  const middleware = /^(?:src\/)?(middleware|proxy)\.[jt]s$/u.exec(path);
  return middleware !== null && (exportKey === "default" || exportKey === middleware[1]);
}

function isAstroEntrypoint(path: string, exportKey: string): boolean {
  return (
    // Astro pages implicitly export their rendered component, including when only a routing hook is explicit.
    /^src\/pages\/.*\.astro$/u.test(path) ||
    (/^src\/pages\/.*\.[jt]s$/u.test(path) && (HTTP_METHODS.has(exportKey) || exportKey === "ALL")) ||
    (/^src\/middleware\.[jt]s$/u.test(path) && exportKey === "onRequest")
  );
}

function packageOwner(filename: string): { root: string; metadata: unknown } | null {
  let root = dirname(filename);
  while (true) {
    try {
      return { root, metadata: JSON.parse(readFileSync(join(root, "package.json"), "utf8")) as unknown };
    } catch (error: unknown) {
      if (typeof error !== "object" || error === null || !("code" in error) || error.code !== "ENOENT") return null;
    }
    const parent = dirname(root);
    if (parent === root) return null;
    root = parent;
  }
}

function declaresFramework(metadata: unknown, name: string): boolean {
  if (typeof metadata !== "object" || metadata === null) return false;
  for (const section of ["dependencies", "devDependencies", "peerDependencies", "optionalDependencies"]) {
    const dependencies: unknown = Reflect.get(metadata, section);
    if (typeof dependencies === "object" && dependencies !== null && typeof Reflect.get(dependencies, name) === "string") return true;
  }
  return false;
}
