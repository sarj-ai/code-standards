# @sarj/tsconfig

Hyper-modern, maximally-strict TypeScript configs for sarj-ai projects.
Covers every type-safety flag in the flagship first-party monorepo's `tsconfig.base.json` and in its published integration SDK's `tsconfig.json`. Per-project flags (`composite`, `noEmit`, `outDir`, `jsx`, `types`) and bundler-specific module resolution are intentionally omitted — see [What's NOT in the preset](#whats-not-in-the-preset-and-why) below.

## Requires

- **TypeScript ≥ 6.0** — the configs use `target: "ES2025"`, `lib: ["ES2025"]`, `isolatedDeclarations`, `erasableSyntaxOnly`, and `strictBuiltinIteratorReturn`, all of which need TS 5.5+ at minimum and ES2025 needs TS 6.

## Install

```bash
npm  i  -D @sarj/tsconfig typescript@^6
pnpm add -D @sarj/tsconfig typescript@^6
yarn add -D @sarj/tsconfig typescript@^6
bun  add -d @sarj/tsconfig typescript@^6
```

## Use

`tsconfig.json` — the default for new projects:

```json
{
  "extends": "@sarj/tsconfig/strict.json",
  "include": ["src/**/*"]
}
```

For libraries that need to be less strict (e.g. mid-migration), extend the base:

```json
{
  "extends": "@sarj/tsconfig/base.json"
}
```

## What's enabled

### `base.json` — modern defaults + first-party-parity strict-safety

**Module / target (TS 6 + Node 24 LTS):**

- `target: "ES2025"` / `lib: ["ES2025"]` — Iterator helpers, `Promise.try`, Set methods, `RegExp.escape`, Float16Array
- `module: "NodeNext"` / `moduleResolution: "NodeNext"` — Node 24 native ESM resolution. **Override to `"preserve"` / `"bundler"` for Next.js / Vite / Vitest / esbuild consumers** (see rejection table)
- `moduleDetection: "force"` — every file is a module; no accidental global scripts
- `verbatimModuleSyntax: true` — `import type` required for type-only imports
- `isolatedModules: true` — every file is a standalone compilation unit
- `allowJs: false` — TS-only; no `.js` infiltration
- `esModuleInterop` / `allowSyntheticDefaultImports`
- `resolveJsonModule: true`

**Type-safety hygiene (matches the first-party base config):**

- `strict: true`
- `noUncheckedIndexedAccess: true` — `arr[0]` is `T | undefined`
- `noUncheckedSideEffectImports: true` (TS 5.6+)
- `exactOptionalPropertyTypes: true`
- `noImplicitOverride: true`
- `noImplicitReturns: true`
- `noFallthroughCasesInSwitch: true`
- `noPropertyAccessFromIndexSignature: true` — bracket only for index signatures
- `noUnusedLocals: true` / `noUnusedParameters: true`
- `allowUnreachableCode: false` / `allowUnusedLabels: false`
- `useDefineForClassFields: true`

**Emit / publish:**

- `declaration: true` / `declarationMap: true` / `sourceMap: true`
- `newLine: "lf"` — reproducible cross-platform output
- `stripInternal: true` — `@internal`-tagged declarations don't ship
- `forceConsistentCasingInFileNames: true`
- `skipLibCheck: true`

### `strict.json` — extends base + the hyper-strict flags

- `isolatedDeclarations: true` (TS 5.5+) — forces explicit return types on every exported symbol; enables parallel `.d.ts` emit by `tsgo`/`swc`/`oxc`
- `erasableSyntaxOnly: true` (TS 5.8+) — bans non-erasable syntax (enums, namespaces with values, parameter properties, `import =`); pairs with Node 24's `--experimental-strip-types`
- `noErrorTruncation: true` — full type names in errors, no `...`
- `strictBuiltinIteratorReturn: true` (TS 5.6+) — plugs the `any` leak in built-in iterators
- All strict-family sub-flags explicitly listed (`alwaysStrict`, `noImplicitAny`, `noImplicitThis`, `strictBindCallApply`, `strictFunctionTypes`, `strictNullChecks`, `strictPropertyInitialization`, `useUnknownInCatchVariables`) — redundant with `strict: true` from base but pinned so future TS default flips can't loosen them

## What's NOT in the preset (and why)

These were considered and explicitly rejected — they're per-project decisions, not shared-config concerns:

| Flag | Why not in @sarj/tsconfig | What to set in your own tsconfig |
|------|---------------------------|----------------------------------|
| `composite` / `incremental` | Per-project; depends on whether you use project references | Add to your tsconfig if you use `tsc -b` |
| `noEmit` | App-vs-lib; apps want `true`, libs want `false` | `true` for Next.js / Vite apps; omit for libs |
| `outDir` / `rootDir` / `paths` | Per-project layout | Set per package |
| `jsx` | Framework-specific | `"preserve"` for Next.js; `"react-jsx"` for plain React |
| `DOM` / `DOM.Iterable` / `DOM.AsyncIterable` in `lib` | Base is Node-safe; browser packages add DOM in their own tsconfig. **`lib` is a REPLACE field, not merge — you must include `ES2025` too.** | `"lib": ["ES2025", "DOM", "DOM.Iterable", "DOM.AsyncIterable"]` |
| `types` / `typeRoots` | Forces every consumer to enumerate ambient types — high friction | Add `["node", "vitest/globals"]` etc. per project |
| Bundler module resolution | NodeNext is correct for libraries; Next.js / Vite / esbuild prefer bundler | `"module": "preserve", "moduleResolution": "bundler"` |
| `noEmitOnError` | Breaks dev/editor partial-emit workflows; gate via separate `tsc --noEmit` in CI | — |
| `rewriteRelativeImportExtensions` / `allowImportingTsExtensions` | Per-runtime decision (depends on whether you run `.ts` directly) | Set if using `tsx` / Bun / Deno |

## Migration notes

Adopting `strict.json` on a brownfield codebase typically surfaces hundreds of errors. The three flags that produce the bulk:

- **`isolatedDeclarations`** (TS9007) — every exported function, class, and `const` needs an explicit return type. A multi-day sweep. Run `tsc --noEmit --isolatedDeclarations` first to see the scope.
- **`erasableSyntaxOnly`** — bans `enum`, `namespace { ... value ... }`, parameter properties (`constructor(private x: T)`), `import =`. Convert enums to `as const` literal unions; rewrite parameter properties as explicit field assignment.
- **`exactOptionalPropertyTypes`** — `{ x?: T }` no longer accepts `{ x: undefined }`. Either tighten the call sites to omit the key, or widen the type to `{ x?: T | undefined }`.

To opt out of a single flag from your tsconfig, just set it to `false` (it overrides the extended preset):

```json
{
  "extends": "@sarj/tsconfig/strict.json",
  "compilerOptions": {
    "isolatedDeclarations": false
  }
}
```

## Versioning

Semver. Major-bump on TypeScript major releases (currently TS 6.x). The package ships with sigstore provenance (npm-attested).

## Influences

These configs were authored by comparing against:

- a first-party `tsconfig.base.json` (Next.js + lib monorepo baseline) and the `tsconfig.json` of its published integration SDK
- `@tsconfig/strictest`, `@total-typescript/tsconfig`, `sindresorhus/tsconfig`, `@swan-io/tsconfig`, `vercel/style-guide`
- TypeScript handbook strict-mode reference and the full TS 5.0 → 6.0 changelog
