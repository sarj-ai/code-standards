/** @fileoverview no-unsafe-test-double-cast — the documentation and executable examples of `@sarj/no-unsafe-test-double-cast`. */

import type { RuleDocumentation } from "../documentation.js";

export const NO_UNSAFE_TEST_DOUBLE_CAST_DOCUMENTATION = {
  summary: "Disallow mock-backed test doubles that bypass collaborator contracts through double assertions.",
  rationale: "Casting a partial object through unknown hides missing or stale collaborator members, so production interface changes can compile while the test double silently drifts.",
  remediation: "Define the smallest injected port and implement a typed recording fake, or make the fixture satisfy the real contract without passing through unknown.",
  category: "testing",
  autofix: "safe",
  limitations: ["Only generated-free test files and direct double assertions containing a fn or spyOn call from a resolved Vitest/Jest import or an unshadowed vi/jest global are checked. Import aliases and mixed assertion syntax are supported; local shadowing, type-only imports, indirect value aliases, arbitrary payload casts and dynamic API replacement are not inferred.",
    "Automatic fixes remove only erased double assertions on an unused private unannotated const initialized by a plain object containing primitive literals, nested plain objects and zero-argument canonical mock fn calls. Every erased named/generic/namespace binding must retain an independent exported type use outside self references and other erasable annotations. They retain the original runtime expression; exports, reads, contextual functions, generic mock factories, spreads, accessors, comments, scripts, declaration files and eval remain manual."],
  examples: [
    { id: "typed-recording-fake", title: "Use a typed recording fake", outcome: "no-match", files: [{ path: "service.test.ts", source: "const client = { read: async () => ({ id: '1' }) } satisfies Pick<Client, 'read'>;" }], focusPath: "service.test.ts", expectedCount: 0, public: true },
    { id: "mock-backed-double-cast", title: "Do not hide a partial mock behind unknown", outcome: "match", files: [{ path: "service.test.ts", source: "import { vi } from 'vitest'; const client = { read: vi.fn() } as unknown as Client;" }], focusPath: "service.test.ts", expectedCount: 1, public: true },
    { id: "safe-autofix", title: "Retain an unused private mock object's actual inferred shape", outcome: "match", files: [{ path: "service.test.ts", source: "import { vi } from 'vitest'; interface Client { read(): string } export type RetainedClient = Client; const client = { read: vi.fn() } as unknown as Client;" }], fixedFiles: [{ path: "service.test.ts", source: "import { vi } from 'vitest'; interface Client { read(): string } export type RetainedClient = Client; const client = { read: vi.fn() };" }], focusPath: "service.test.ts", expectedCount: 1 },
  ],
} as const satisfies RuleDocumentation;
