Audit the project's CI/CD pipelines, tooling, and development process configurations. Identify and recommend concrete, high-impact improvements to increase automation, reliability, and code quality, based on established best practices and observed anti-patterns.

## What to look for

This audit focuses on seven key areas derived from common review feedback:

1.  **Linter & Formatter Enforcement** — Missing or unenforced linting and formatting steps in CI, leading to manual reviewer feedback on style and quality.
2.  **Strictness of Configuration** — Linter and compiler configurations that are not maximally strict (e.g., Ruff not using `select="ALL"`, TypeScript `strict` mode disabled, or allowing `any` types).
3.  **Dependency Pinning** — Unpinned versions in `Dockerfile`s (`:latest`), GitHub Actions (`@v4`), or application dependencies (`^1.2.3`), which can lead to non-reproducible or broken builds.
4.  **Toolchain Modernization** — Use of outdated toolchains (`pip`, `npm`, `yarn`) where modern standards (`uv`, `pnpm`) offer significant performance and consistency benefits.
5.  **Modern Language Syntax** — Use of deprecated syntax, such as `typing.List` in Python instead of the modern built-in `list`.
6.  **CI/IaC Script Hygiene** — Brittle shell scripts (missing `set -euo pipefail`) and suboptimal Infrastructure-as-Code patterns (e.g., Terraform `local-exec` provisioners).
7.  **Code & Configuration Hygiene** — Committing IDE-specific files (`.vscode/`, `.idea/`), generated artifacts (`.egg-info`), or unused code and dependencies.

## Phase 0: Discover project structure

Before spawning audit agents, run a single discovery step:

1.  **Detect Languages and Runtimes** — Check for TypeScript (`tsconfig.json`, `pnpm-lock.yaml`), Python (`pyproject.toml`, `uv.lock`), and others.
2.  **Find Linter/Formatter Configs** — Search for Ruff (`ruff.toml`, `pyproject.toml`), ESLint/Biome (`.eslintrc.*`, `biome.json`), Prettier (`.prettierrc*`), etc.
3.  **Find CI/CD and IaC Configs** — Locate `.github/workflows/*.yml`, `Makefile`, `*.tf`, and `Dockerfile` files.
4.  **Inventory Tooling** — Check for the presence of `requirements.txt`, `package-lock.json`, and `yarn.lock` to identify consolidation opportunities.

Output the discovered configuration (languages, tools, config file locations) before proceeding.

## Phase 1: Audit (parallel agents)

Spawn agents for each of the following checks. Each agent will analyze the relevant files and report violations.

-   **Agent 1: Toolchain Modernization & Consolidation**
    -   In Python projects, scan for `requirements.txt` files and recommend migration to `uv` or another `pyproject.toml`-based manager. [4, 11, 13, 14, 16]
    -   In JS/TS projects, scan for `package-lock.json` or `yarn.lock` and recommend migration to `pnpm` for better performance and disk efficiency. [3, 5, 6, 9, 10]
    -   Scan CI scripts for direct calls to `npx` or `pip` where `pnpm run` or `uv run` should be used.

-   **Agent 2: Linter & Type-Checker Strictness**
    -   **Ruff**: Check `pyproject.toml` or `ruff.toml`. If `lint.select` is not `"ALL"`, recommend switching and adding a minimal `lint.ignore` list for deliberate exceptions. [26]
    -   **TypeScript**: Check `tsconfig.json` for `"strict": true`. If missing or false, recommend enabling it. Additionally, check for linter rules that ban unsafe constructs, such as `@typescript-eslint/no-explicit-any`. [1, 7, 8, 19, 21]

-   **Agent 3: Dependency Pinning**
    -   Scan `Dockerfile`s for base images using the `:latest` tag. Flag with `hadolint` rule `DL3006`. [34, 35, 38, 40, 41]
    -   Scan `.github/workflows/*.yml` files for unpinned action versions (e.g., `actions/checkout@v4` instead of a full commit SHA like `actions/checkout@a5ac7e51b41094c92402da3b24376905380afc29`). [12, 15, 17, 20, 22, 46]
    -   Scan `pyproject.toml` and `package.json` for version ranges (`>=`, `^`) in application dependencies and recommend pinning to exact versions (`==` or `1.2.3`).

-   **Agent 4: Python Modernization**
    -   Run `ruff check --select UP .` to find all instances of deprecated `typing` module usage (e.g., `List`, `Dict`, `Optional`, `Union`). The primary rules are `UP006` (`List` -> `list`) and `UP007` (`Union` -> `|`). [2, 23, 24, 25, 27, 30, 36, 39]

-   **Agent 5: CI/IaC Script Hygiene**
    -   Scan all shell scripts (`.sh`) referenced in CI configurations for the absence of `set -euo pipefail` at the beginning of the script. [33, 37, 42, 44]
    -   Scan all Terraform (`.tf`) files for `provisioner "local-exec"` blocks and flag them as violations of the `tflint` rule `terraform_provisioners`.

-   **Agent 6: Code & Configuration Hygiene**
    -   Scan the git index for tracked files that should be ignored, such as `.idea/`, `.vscode/`, `*.egg-info`, and `*.pyc`. Compare against a standard `.gitignore` template for the detected languages.
    -   Run `ruff check --select F401 .` to find and report unused imports in Python files. [18, 32]
    -   In TypeScript projects, run `knip` to find unused files, exports, and dependencies.

## Phase 2: Compile findings

After all agents report back, compile a single summary table:

| Area | Finding | Recommendation | Impact | Auto-fixable |
|------|---------|----------------|--------|--------------|

-   **Area**: The category of the finding (e.g., Toolchain, Linter Strictness, CI/CD, Code Hygiene).
-   **Impact**: high = prevents bugs/failures, medium = improves reliability/maintainability, low = best practice/cleanup.
-   **Auto-fixable**: yes/no/partial.

Sort by impact (high first), then by area. Group findings within the table.

## Phase 3: Generate fix plan

For each finding, output a concrete plan for remediation:
-   The file(s) to modify.
-   The exact config changes (e.g., lines to add/remove).
-   The CLI command to run for auto-fixable issues (e.g., `uv run ruff check --fix .`, `pnpm knip --fix`, `git rm --cached .idea/ -r`).

Do NOT automatically implement changes. Present the recommendations for review and wait for confirmation before making changes.
