// Generated from the Standards library catalog.
export const LIBRARY_POLICY = [
  {
    "id": "LIB101",
    "module": "request",
    "note": "Use the platform-native fetch API; review errors, timeouts, retries, and response parsing during migration.",
    "replacement": "native fetch"
  },
  {
    "id": "LIB101",
    "module": "node-fetch",
    "note": "Use the platform-native fetch API; review errors, timeouts, retries, and response parsing during migration.",
    "replacement": "native fetch"
  },
  {
    "id": "LIB101",
    "module": "cross-fetch",
    "note": "Use the platform-native fetch API; review errors, timeouts, retries, and response parsing during migration.",
    "replacement": "native fetch"
  },
  {
    "id": "LIB101",
    "module": "isomorphic-fetch",
    "note": "Use the platform-native fetch API; review errors, timeouts, retries, and response parsing during migration.",
    "replacement": "native fetch"
  },
  {
    "id": "LIB101",
    "module": "axios",
    "note": "Use the platform-native fetch API; review errors, timeouts, retries, and response parsing during migration.",
    "replacement": "native fetch"
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
    "note": "TSLint is deprecated; use Oxlint with its type-aware rules.",
    "replacement": "oxlint"
  }
] as const;
export const LIBRARY_IMPORT_RESTRICTIONS = [
  {
    "message": "LIB101: Use the platform-native fetch API; review errors, timeouts, retries, and response parsing during migration. Replace with native fetch.",
    "name": "request"
  },
  {
    "message": "LIB101: Use the platform-native fetch API; review errors, timeouts, retries, and response parsing during migration. Replace with native fetch.",
    "name": "node-fetch"
  },
  {
    "message": "LIB101: Use the platform-native fetch API; review errors, timeouts, retries, and response parsing during migration. Replace with native fetch.",
    "name": "cross-fetch"
  },
  {
    "message": "LIB101: Use the platform-native fetch API; review errors, timeouts, retries, and response parsing during migration. Replace with native fetch.",
    "name": "isomorphic-fetch"
  },
  {
    "message": "LIB101: Use the platform-native fetch API; review errors, timeouts, retries, and response parsing during migration. Replace with native fetch.",
    "name": "axios"
  },
  {
    "message": "LIB102: Standards standardizes date utilities on date-fns; migration is not API-compatible. Replace with date-fns.",
    "name": "moment"
  },
  {
    "message": "LIB102: Standards standardizes date utilities on date-fns; migration is not API-compatible. Replace with date-fns.",
    "name": "dayjs"
  },
  {
    "message": "LIB103: Standards standardizes collection utilities on Remeda and native APIs. Replace with remeda.",
    "name": "lodash"
  },
  {
    "message": "LIB103: Standards standardizes collection utilities on Remeda and native APIs. Replace with remeda.",
    "name": "lodash-es"
  },
  {
    "message": "LIB103: Standards standardizes collection utilities on Remeda and native APIs. Replace with remeda.",
    "name": "underscore"
  },
  {
    "message": "LIB104: Use clsx for conditional class-name composition. Replace with clsx.",
    "name": "classnames"
  },
  {
    "message": "LIB105: Standards standardizes runtime validation on Zod; schemas are not drop-in compatible. Replace with zod.",
    "name": "joi"
  },
  {
    "message": "LIB105: Standards standardizes runtime validation on Zod; schemas are not drop-in compatible. Replace with zod.",
    "name": "yup"
  },
  {
    "message": "LIB105: Standards standardizes runtime validation on Zod; schemas are not drop-in compatible. Replace with zod.",
    "name": "superstruct"
  },
  {
    "message": "LIB105: Standards standardizes runtime validation on Zod; schemas are not drop-in compatible. Replace with zod.",
    "name": "io-ts"
  },
  {
    "message": "LIB105: Standards standardizes runtime validation on Zod; schemas are not drop-in compatible. Replace with zod.",
    "name": "runtypes"
  },
  {
    "message": "LIB106: Use jose; review key formats and async signing and verification APIs. Replace with jose.",
    "name": "jsonwebtoken"
  },
  {
    "message": "LIB107: Standards standardizes servers on Hono; Node deployments also need @hono/node-server. Replace with hono.",
    "name": "express"
  },
  {
    "message": "LIB107: Standards standardizes servers on Hono; Node deployments also need @hono/node-server. Replace with hono.",
    "name": "koa"
  },
  {
    "message": "LIB108: Standards standardizes tests on Vitest; review globals, timers, mocks, and environment setup. Replace with vitest.",
    "name": "jest"
  },
  {
    "message": "LIB108: Standards standardizes tests on Vitest; review globals, timers, mocks, and environment setup. Replace with vitest.",
    "name": "mocha"
  },
  {
    "message": "LIB109: Use Vitest spies, mocks, and fake timers instead of Sinon. Replace with Vitest mocks.",
    "name": "sinon"
  },
  {
    "message": "LIB110: Standards standardizes command-line interfaces on citty. Replace with citty.",
    "name": "commander"
  },
  {
    "message": "LIB110: Standards standardizes command-line interfaces on citty. Replace with citty.",
    "name": "yargs"
  },
  {
    "message": "LIB111: Use native Promise, adding p-limit or p-map only for the extensions actually needed. Replace with native Promise.",
    "name": "bluebird"
  },
  {
    "message": "LIB112: Prefer node:fs/promises; verify recursive removal, copy, path, and error semantics. Replace with node:fs/promises.",
    "name": "rimraf"
  },
  {
    "message": "LIB112: Prefer node:fs/promises; verify recursive removal, copy, path, and error semantics. Replace with node:fs/promises.",
    "name": "fs-extra"
  },
  {
    "message": "LIB113: Node 22 provides global AbortController. Replace with AbortController.",
    "name": "abort-controller"
  },
  {
    "message": "LIB114: Use URLSearchParams and explicitly review repeated keys, escaping, arrays, and object coercion. Replace with URLSearchParams.",
    "name": "querystring"
  },
  {
    "message": "LIB115: Standards standardizes environment loading on @dotenvx/dotenvx. Replace with @dotenvx/dotenvx.",
    "name": "dotenv"
  },
  {
    "message": "LIB116: Use picocolors for terminal colors. Replace with picocolors.",
    "name": "chalk"
  },
  {
    "message": "LIB117: The original faker package is abandoned; use @faker-js/faker. Replace with @faker-js/faker.",
    "name": "faker"
  },
  {
    "message": "LIB118: node-sass is end-of-life; use Dart Sass. Replace with sass.",
    "name": "node-sass"
  },
  {
    "message": "LIB119: TSLint is deprecated; use Oxlint with its type-aware rules. Replace with oxlint.",
    "name": "tslint"
  }
] as const;
