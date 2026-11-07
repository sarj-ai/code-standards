/**
 * @fileoverview is-frontend-source — identify frontend ownership from syntax and package dependencies.
 */

// eslint-disable-next-line @sarj/prefer-node-fs-promises -- Oxlint calls rule visitors synchronously, so the package.json lookup made while linting a file cannot await.
import { existsSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";

import type { Context, ESTree } from "../types.js";

type FrontendContext = Pick<Context, "filename" | "sourceCode">;

const FRONTEND_PACKAGES: ReadonlySet<string> = new Set(["react", "react-dom", "next", "preact", "vue", "svelte", "@angular/core", "solid-js", "@sveltejs/kit", "astro"]);
const FRONTEND_IMPORT = /^(?:react(?:-dom)?|next|preact|vue|svelte|@angular\/core|solid-js|@sveltejs\/kit)(?:\/|$)/u;


export function isFrontendSource(context: FrontendContext): boolean {
  return /\.[jt]sx$/u.test(context.filename) || frontendModule(context.sourceCode.ast) || frontendPackage(context.filename);
}

function frontendPackage(filename: string): boolean {
  let directory = dirname(resolve(filename));
  for (;;) {
    const manifestPath = join(directory, "package.json");
    if (existsSync(manifestPath)) {
      try {
        const manifest: unknown = JSON.parse(readFileSync(manifestPath, "utf8"));
        return typeof manifest === "object" && manifest !== null && (
          ("dependencies" in manifest && declaresFrontend(manifest.dependencies)) ||
          ("devDependencies" in manifest && declaresFrontend(manifest.devDependencies)) ||
          ("peerDependencies" in manifest && declaresFrontend(manifest.peerDependencies))
        );
      } catch {
        return false;
      }
    }
    const parent = dirname(directory);
    if (parent === directory) return false;
    directory = parent;
  }
}

function declaresFrontend(value: unknown): boolean {
  return typeof value === "object" && value !== null && Object.keys(value).some(name => FRONTEND_PACKAGES.has(name));
}

function frontendModule(program: ESTree.Program): boolean {
  return program.body.some(statement =>
    (statement.type === "ExpressionStatement" && (statement.directive === "use client" || statement.directive === "use server")) ||
    (statement.type === "ImportDeclaration" && FRONTEND_IMPORT.test(statement.source.value)),
  );
}
