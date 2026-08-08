# @sarj/tsconfig

Strict TypeScript configurations for the runtime and compiler versions tested
by Sarj Standards.

## Use

```json
{
  "extends": "@sarj/tsconfig/strict.json",
  "include": ["src/**/*"]
}
```

`strict.json` is the default for new code. `base.json` retains modern safety
defaults for projects that cannot yet adopt every strict flag.

Project-specific behavior stays in the consuming `tsconfig.json`: choose
`noEmit`, `outDir`, `rootDir`, `jsx`, `types`, DOM libraries, project references,
and bundler module resolution there. Remember that `lib` replaces rather than
extends the inherited array.

The JSON files shipped by this package are the authoritative configuration.
Their package manifest declares the supported TypeScript range; avoid copying
the flag list into documentation because compiler defaults and available flags
change over time.
