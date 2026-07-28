Audit the codebase for hardcoded secrets, environment-specific configuration, and other violations of the 12-factor app principle of strictly separating config from code. The goal is to make the application more robust, secure, and easily deployable across different environments.

## What this audits

This audit flags several categories of hardcoded values and configuration anti-patterns:

- **Hardcoded Secrets:** API keys, tokens, passwords, and other credentials committed directly to version control.
- **Committed Sensitive Files:** `.env` files, Terraform variable files (`.tfvars`), or private keys checked into the repository.
- **Hardcoded Configuration:** URLs, ports, project IDs, AI model names, and other magic values that should be loaded from external configuration.
- **Missing Schema Validation:** Direct access to environment variables (`process.env`, `os.getenv`) without a centralized, schema-validated settings object (e.g., using Pydantic, Zod). This leads to silent failures and brittle deployments.
- **Environment-Specific Logic:** Code that branches on an environment name (e.g., `if env == 'prod'`), coupling the application logic to specific deploys.
- **Unsafe Defaults:** Configuration variables defined as optional or with unsafe defaults (like an empty string) that cause cryptic runtime errors instead of clear startup validation failures.

## Phase 0: Discover project structure

Run the shared **[stack-detection](./stack-detection.md)** pass first. **For this rule, detect the config mechanism per runtime:** Cloudflare Workers (`automations`) have **no `process.env`** — config arrives as bindings via `c.env`, so a `process.env` grep finds nothing real; Python services use Pydantic Settings (and `os.environ` is banned via `TID251` in `bulbul`). Do **not** flag the deliberate `.optional().default('')` fail-safe env defaults / `BooleanFlagSchema` transforms as missing-config. Only cite lint rules the package actually runs. Then, add the following skill-specific discovery steps:

1.  **Identify configuration files:** Scan for common config files like `settings.py`, `env.ts`, `config.ts`, `wrangler.toml`, `*.tfvars`, `*.yaml`, and any `.env` files. This helps understand the existing configuration strategy (or lack thereof).

Output the discovered structure before proceeding.

## Phase 1: Audit (parallel agents)

Spawn agents to cover the following concerns across all source roots. Each agent should report findings with file path, line number, the problematic value, the type of secret/config, and severity.

1.  **Hardcoded Secrets**
    - Scan for string literals assigned to variables with names containing `API_KEY`, `_SECRET`, `PASSWORD`, `TOKEN` (Ruff: `S105`). [34]
    - Scan for high-entropy strings that are likely leaked credentials (ESLint: `no-secrets/no-secrets`). [21]
    - Flag common credential formats, like base64-encoded JSON or connection strings with passwords.
    - **Example (Python):** `redis.Redis(host="...", password="qZKGV7V0bPMsO5fOvuYhpvvBcGd9FWBX")`
    - **Example (TypeScript):** `const password = process.env.NEXT_PUBLIC_PASSWORD || 'Hello13579!';`

2.  **Committed Sensitive Files**
    - Scan the repository for any file matching patterns like `.env`, `.env.*`, `*.tfvars`, `*-credentials.json`, or `secrets_backend.txt` that is not listed in the root `.gitignore` file.
    - Flag any committed private key files (e.g., `.pem`) or build artifacts (e.g., `.whl`).

3.  **Missing or Weak Config Validation**
    - Flag direct access to environment variables outside of a dedicated settings module. This prevents centralized, schema-based validation. [2, 3, 12, 40]
    - **Python:** Look for `os.getenv(...)` or `os.environ.get(...)` calls in application logic instead of accessing a central `pydantic_settings.BaseSettings` instance. [46]
    - **TypeScript:** Look for `process.env[...]` access (ESLint: `n/no-process-env`) in components, API routes, or services instead of importing from a central, Zod-validated settings file. [12]
    - **Example (Python):** `api_key = os.getenv("DEFAULT_GOOGLE_API_KEY")`
    - **Example (TypeScript):** `const accountId = accountId ?? CF_ACCOUNT_ID ?? "";`

4.  **Hardcoded Configuration Values**
    - Scan for string literals that represent URLs, hostnames, or IP addresses (e.g., `https://...`, `localhost:...`, `*.run.app`).
    - Scan for numeric literals used as ports, timeouts, or other magic numbers that should be named constants in a settings file (Ruff: `PLR2004`, ESLint: `@typescript-eslint/no-magic-numbers`). [1, 27]
    - Scan for hardcoded AI model names (`gemini-2.5-pro`), project IDs, or customer/organization IDs.
    - **Example (Python):** `model="gemini-2.5-pro"`
    - **Example (TypeScript):** `const proxyAgent = new HttpsProxyAgent('http://localhost:3128');`

5.  **Environment-Specific Logic in Code**
    - Flag `if/switch` statements that branch on an environment name. Behavior should be controlled by feature flags or specific config values, not the deploy environment's name, per the 12-Factor App principles. [15, 24]
    - **Example (Python):** `if settings.ENV == "development": ...`
    - **Example (TypeScript):** `const apiUrl = process.env.NODE_ENV === 'production' ? '...' : '...';`

6.  **Overly Optional or Unsafe Defaults**
    - In Pydantic settings, flag critical fields (API keys, URLs) defined as `str | None` or with `default=None` or `default=""` without a runtime check where they are used. [19]
    - In Zod schemas, flag critical fields using `.optional()` or `.default("")`. These should be required to ensure the application fails fast at startup if misconfigured. [5, 7]
    - **Example (Python):** `BANKING_BE_API_KEY: str | None = ""` in a Pydantic model.
    - **Example (TypeScript):** `LINEAR_API_KEY?: string;` in a TypeScript interface for environment variables.

## Phase 2: Compile findings

After all agents report back, compile a single summary table with columns:

| File | Line | Finding | Category | Severity |
|------|------|---------|----------|----------|

Sort by severity (high first), then by file path.

Group the summary into:
- **Critical** — Hardcoded secrets, committed sensitive files.
- **High** — Missing config validation for critical services, environment-specific logic controlling core features.
- **Medium** — Hardcoded URLs/ports, overly optional config for non-critical features.
- **Low** — Hardcoded magic numbers (model names, timeouts) that should be constants.

## Phase 3: Generate fix plan

For each high or critical severity violation, output a concrete remediation plan:
- The exact code/value identified.
- The reason it is a risk (e.g., "Committing an API key to version control").
- The recommended action:
  - For secrets: "Move this secret to a secret manager (e.g., Google Secret Manager) and load it into a validated settings object at runtime." [6, 14]
  - For hardcoded config: "Extract this value to your Pydantic/Zod settings file and load it from an environment variable." [22, 28]
  - For missing validation: "Refactor to use a centralized Pydantic/Zod settings object. Replace direct `os.getenv`/`process.env` access with `settings.my_var`." [5, 10, 11, 13]
  - For env logic: "Refactor this `if (env === '...')` block. Instead, introduce a specific configuration flag (e.g., `ENABLE_FEATURE_X`) and branch on that, following the 12-Factor App config principle." [15, 29]
