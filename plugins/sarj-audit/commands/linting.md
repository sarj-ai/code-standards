Audit the project's linting and formatting configuration. Research the latest available rules and plugins for the detected toolchain, then recommend changes to make the linter as strict as possible and maximize code quality.

## What to look for

1. **Missing strictness** — Rules that exist in the linter but are not enabled, or are set to `warn` instead of `error`
2. **Outdated plugins** — Plugins or configs that have newer versions with additional rules
3. **Missing plugins** — Well-maintained plugins that the project should adopt but hasn't (e.g., `eslint-plugin-unicorn`, `eslint-plugin-perfectionist`, `@typescript-eslint/strict-type-checked`, `ruff` rule categories)
4. **Formatter gaps** — Files or directories not covered by the formatter, or formatter settings that conflict with the linter
5. **Ignored rules worth enabling** — Rules explicitly disabled in config that should be reconsidered
6. **Type-aware linting** — For TypeScript projects, whether type-checked rules are enabled (they catch significantly more bugs)

Do NOT recommend:
- Stylistic rules that are purely preference (tabs vs spaces, quote style) — the formatter handles these
- Disabling rules that are already enabled — the goal is strictly more strictness, never less
- Rules that would cause thousands of violations with no auto-fix — note these separately as "gradual adoption" candidates

## Phase 0: Discover project structure

Before spawning audit agents, run a single discovery step:

1. **Detect languages and runtimes** — Check for TypeScript (`tsconfig.json`), Python (`pyproject.toml`, `setup.cfg`, `ruff.toml`), Go (`go.mod`), Rust (`Cargo.toml`), Java/Kotlin (`build.gradle`, `pom.xml`), Ruby (`Gemfile`), etc.
2. **Find all linter configs** — Search for ESLint (`eslint.config.*`, `.eslintrc.*`, `package.json` `eslintConfig`), Prettier (`.prettierrc*`, `package.json` `prettier`), Biome (`biome.json`), Ruff (`ruff.toml`, `pyproject.toml` `[tool.ruff]`), `golangci-lint` (`.golangci.yml`), Clippy (`clippy.toml`), Rubocop (`.rubocop.yml`), and any other language-specific linters.
3. **Find all formatter configs** — Search for Prettier, Biome, Black (`pyproject.toml` `[tool.black]`), `gofmt`/`goimports`, `rustfmt` (`rustfmt.toml`), and similar.
4. **Inventory installed lint plugins** — Read dependency files to list all currently installed linter plugins and their versions.
5. **Detect monorepo layout** — Check if configs are shared at root or duplicated per package. Identify any per-package overrides.
6. **Read ignore files** — Check `.eslintignore`, `.prettierignore`, lint `exclude` patterns, etc. to understand what's excluded from linting.

Output the discovered configuration (languages, linter tools, formatter tools, installed plugins, config file locations, ignore patterns) before proceeding.

## Phase 1: Research latest rules (parallel agents)

Spawn agents for each detected linter. Each agent must:

1. **Read the current config in full** — Parse every rule, extension, override, and plugin
2. **Research the latest available rules** — For each installed plugin, check what rules exist that are NOT currently enabled. Use web search to find the latest documentation for each plugin.
3. **Research missing plugins** — Search for well-maintained plugins commonly used with the detected stack that are not installed
4. **Check for config presets** — Look for stricter preset configs (e.g., `plugin:@typescript-eslint/strict-type-checked`, `ruff --select ALL`, `golangci-lint` with all linters enabled)

### Agent assignments by language

**TypeScript/JavaScript (ESLint)**
- Agent 1: Core ESLint rules and `@typescript-eslint` — check for `strict-type-checked` preset, individual rules not enabled, type-aware rules requiring `parserOptions.project`
- Agent 2: Third-party plugins — `eslint-plugin-unicorn`, `eslint-plugin-perfectionist`, `eslint-plugin-import-x`, `eslint-plugin-promise`, `eslint-plugin-security`, `eslint-plugin-sonarjs`, `eslint-plugin-no-barrel-files`. For React projects also check `eslint-plugin-react-compiler`, `eslint-plugin-jsx-a11y`, `eslint-plugin-react-hooks`

**TypeScript/JavaScript (Biome)**
- Agent 1: Check all Biome lint rule categories (`suspicious`, `complexity`, `correctness`, `performance`, `style`, `nursery`) for rules not currently enabled or set to `warn`
- Agent 2: Check Biome formatter and organize imports settings for strictness gaps

**Python (Ruff)**
- Agent 1: Check which rule categories are enabled vs available (`E`, `W`, `F`, `I`, `N`, `UP`, `ANN`, `B`, `A`, `C4`, `DTZ`, `EM`, `ISC`, `ICN`, `PIE`, `PT`, `RSE`, `RET`, `SLF`, `SIM`, `TID`, `TCH`, `ARG`, `PTH`, `ERA`, `PL`, `TRY`, `FLY`, `PERF`, `FURB`, `RUF`). Recommend enabling all categories that don't conflict with the project.
- Agent 2: Check `mypy` or `pyright` configuration for type strictness (`strict = true`, `disallow_untyped_defs`, `warn_return_any`, etc.)

**Go (golangci-lint)**
- Single agent: Check which linters are enabled vs available. Recommend enabling stricter linters like `gocritic`, `exhaustive`, `errcheck`, `gosec`, `prealloc`, `revive` with custom rules.

**Rust (Clippy)**
- Single agent: Check for `#![deny(clippy::all, clippy::pedantic)]` or equivalent config. Recommend `clippy::nursery` rules worth enabling.

Skip agents for languages not detected in Phase 0.

## Phase 2: Compile findings

After all agents report back, compile a single table:

| Tool | Rule / Plugin | Current | Recommended | Impact | Auto-fixable |
|------|---------------|---------|-------------|--------|--------------|

Where:
- **Impact**: high = catches real bugs, medium = improves consistency, low = minor style improvement
- **Auto-fixable**: yes = can be applied automatically, no = requires manual changes, partial = some violations auto-fixable

Sort by impact (high first), then by auto-fixable (yes first).

Group into:
- **Enable now** — High-impact rules that are auto-fixable or have zero/few existing violations
- **Enable with auto-fix pass** — High-impact rules with existing violations that can be auto-fixed
- **Gradual adoption** — High-impact rules with many violations requiring manual fixes (recommend enabling as `warn` first)
- **Nice to have** — Medium/low-impact improvements

Print the total count of recommended changes broken down by category.

## Phase 3: Generate config changes

For each "Enable now" and "Enable with auto-fix pass" finding, output the exact config file changes needed:
- The file to modify
- The exact lines to add or change
- The CLI command to auto-fix existing violations (if applicable)

Do NOT automatically implement changes. Present the recommendations for review and wait for confirmation before making changes.
