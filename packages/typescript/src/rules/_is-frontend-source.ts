/**
 * @fileoverview _is-frontend-source — identify frontend ownership from syntax and package dependencies.
 */

import { existsSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";

import { AST_NODE_TYPES, type TSESTree } from "@typescript-eslint/utils";

import type { NativeRuleContext } from "./_eslint-rule.js";

type FrontendContext = Pick<NativeRuleContext<string, readonly unknown[]>, "filename" | "sourceCode">;

const FRONTEND_PACKAGES: ReadonlySet<string> = new Set(["react", "react-dom", "next", "preact", "vue", "svelte", "@angular/core", "solid-js", "@sveltejs/kit", "astro"]);
const FRONTEND_IMPORT = /^(?:react(?:-dom)?|next|preact|vue|svelte|@angular\/core|solid-js|@sveltejs\/kit)(?:\/|$)/u;


export function isFrontendSource(context: FrontendContext): boolean {
  return /\.[jt]sx$/u.test(context.filename) || frontendModule(context.sourceCode.ast) || frontendPackage(context.filename);
}

// Manifests do not change during a lint run, so answer each directory once.
const FRONTEND_PACKAGE_BY_DIRECTORY = new Map<string, boolean>();

function frontendPackage(filename: string): boolean {
  const directory = dirname(resolve(filename));
  let cached = FRONTEND_PACKAGE_BY_DIRECTORY.get(directory);
  if (cached === undefined) {
    cached = nearestManifestDeclaresFrontend(directory);
    FRONTEND_PACKAGE_BY_DIRECTORY.set(directory, cached);
  }
  return cached;
}

function nearestManifestDeclaresFrontend(start: string): boolean {
  let directory = start;
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

function frontendModule(program: TSESTree.Program): boolean {
  return program.body.some(statement =>
    (statement.type === AST_NODE_TYPES.ExpressionStatement && (statement.directive === "use client" || statement.directive === "use server")) ||
    (statement.type === AST_NODE_TYPES.ImportDeclaration && FRONTEND_IMPORT.test(statement.source.value)),
  );
}
