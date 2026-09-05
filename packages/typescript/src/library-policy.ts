// Generated from the Standards library catalog.
export const LIBRARY_POLICY = [
  {
    "id": "LIB101",
    "module": "request",
    "note": "Standards standardizes HTTP clients on Ky; review errors, retries, hooks, and response parsing.",
    "replacement": "ky"
  },
  {
    "id": "LIB101",
    "module": "node-fetch",
    "note": "Standards standardizes HTTP clients on Ky; review errors, retries, hooks, and response parsing.",
    "replacement": "ky"
  },
  {
    "id": "LIB101",
    "module": "cross-fetch",
    "note": "Standards standardizes HTTP clients on Ky; review errors, retries, hooks, and response parsing.",
    "replacement": "ky"
  },
  {
    "id": "LIB101",
    "module": "isomorphic-fetch",
    "note": "Standards standardizes HTTP clients on Ky; review errors, retries, hooks, and response parsing.",
    "replacement": "ky"
  },
  {
    "id": "LIB101",
    "module": "axios",
    "note": "Standards standardizes HTTP clients on Ky; review errors, retries, hooks, and response parsing.",
    "replacement": "ky"
  },
  {
    "id": "LIB102",
    "module": "moment",
    "note": "Standards standardizes date utilities on date-fns; migration is not API-compatible.",
    "replacement": "date-fns"
  },
  {
    "id": "LIB102",
    "module": "dayjs",
    "note": "Standards standardizes date utilities on date-fns; migration is not API-compatible.",
    "replacement": "date-fns"
  },
  {
    "id": "LIB103",
    "module": "lodash",
    "note": "Standards standardizes collection utilities on Remeda and native APIs.",
    "replacement": "remeda"
  },
  {
    "id": "LIB103",
    "module": "lodash-es",
    "note": "Standards standardizes collection utilities on Remeda and native APIs.",
    "replacement": "remeda"
  },
  {
    "id": "LIB103",
    "module": "underscore",
    "note": "Standards standardizes collection utilities on Remeda and native APIs.",
    "replacement": "remeda"
  },
  {
    "id": "LIB104",
    "module": "classnames",
    "note": "Use clsx for conditional class-name composition.",
    "replacement": "clsx"
  },
  {
    "id": "LIB105",
    "module": "joi",
    "note": "Standards standardizes runtime validation on Zod; schemas are not drop-in compatible.",
    "replacement": "zod"
  },
  {
    "id": "LIB105",
    "module": "yup",
    "note": "Standards standardizes runtime validation on Zod; schemas are not drop-in compatible.",
    "replacement": "zod"
  },
  {
    "id": "LIB105",
    "module": "superstruct",
    "note": "Standards standardizes runtime validation on Zod; schemas are not drop-in compatible.",
    "replacement": "zod"
  },
  {
    "id": "LIB105",
    "module": "io-ts",
    "note": "Standards standardizes runtime validation on Zod; schemas are not drop-in compatible.",
    "replacement": "zod"
  },
  {
    "id": "LIB105",
    "module": "runtypes",
    "note": "Standards standardizes runtime validation on Zod; schemas are not drop-in compatible.",
    "replacement": "zod"
  },
  {
    "id": "LIB106",
    "module": "jsonwebtoken",
    "note": "Use jose; review key formats and async signing and verification APIs.",
    "replacement": "jose"
  },
  {
    "id": "LIB107",
    "module": "express",
    "note": "Standards standardizes servers on Hono; Node deployments also need @hono/node-server.",
    "replacement": "hono"
  },
  {
    "id": "LIB107",
    "module": "koa",
    "note": "Standards standardizes servers on Hono; Node deployments also need @hono/node-server.",
    "replacement": "hono"
  },
  {
    "id": "LIB108",
    "module": "jest",
    "note": "Standards standardizes tests on Vitest; review globals, timers, mocks, and environment setup.",
    "replacement": "vitest"
  },
  {
    "id": "LIB108",
    "module": "mocha",
    "note": "Standards standardizes tests on Vitest; review globals, timers, mocks, and environment setup.",
    "replacement": "vitest"
  },
  {
    "id": "LIB109",
    "module": "sinon",
    "note": "Use Vitest spies, mocks, and fake timers instead of Sinon.",
    "replacement": "Vitest mocks"
  },
  {
    "id": "LIB110",
    "module": "commander",
    "note": "Standards standardizes command-line interfaces on citty.",
    "replacement": "citty"
  },
  {
    "id": "LIB110",
    "module": "yargs",
    "note": "Standards standardizes command-line interfaces on citty.",
    "replacement": "citty"
  },
  {
    "id": "LIB111",
    "module": "bluebird",
    "note": "Use native Promise, adding p-limit or p-map only for the extensions actually needed.",
    "replacement": "native Promise"
  },
  {
    "id": "LIB112",
    "module": "rimraf",
    "note": "Prefer node:fs/promises; verify recursive removal, copy, path, and error semantics.",
    "replacement": "node:fs/promises"
  },
  {
    "id": "LIB112",
    "module": "fs-extra",
    "note": "Prefer node:fs/promises; verify recursive removal, copy, path, and error semantics.",
    "replacement": "node:fs/promises"
  },
  {
    "id": "LIB113",
    "module": "abort-controller",
    "note": "Node 22 provides global AbortController.",
    "replacement": "AbortController"
  },
  {
    "id": "LIB114",
    "module": "querystring",
    "note": "Use URLSearchParams and explicitly review repeated keys, escaping, arrays, and object coercion.",
    "replacement": "URLSearchParams"
  },
  {
    "id": "LIB115",
    "module": "dotenv",
    "note": "Standards standardizes environment loading on @dotenvx/dotenvx.",
    "replacement": "@dotenvx/dotenvx"
  },
  {
    "id": "LIB116",
    "module": "chalk",
    "note": "Use picocolors for terminal colors.",
    "replacement": "picocolors"
  },
  {
    "id": "LIB117",
    "module": "faker",
    "note": "The original faker package is abandoned; use @faker-js/faker.",
    "replacement": "@faker-js/faker"
  },
  {
    "id": "LIB118",
    "module": "node-sass",
    "note": "node-sass is end-of-life; use Dart Sass.",
    "replacement": "sass"
  },
  {
    "id": "LIB119",
    "module": "tslint",
    "note": "TSLint is deprecated; use ESLint with typescript-eslint.",
    "replacement": "eslint"
  }
] as const;
