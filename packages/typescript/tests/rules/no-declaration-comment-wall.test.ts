import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule, {
  noDeclarationCommentWallDocumentation,
} from "../../src/rules/no-declaration-comment-wall.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.itOnly = it.only;
RuleTester.it = it;

const ruleTester = new RuleTester();

ruleTester.run("no-declaration-comment-wall", rule, {
  valid: [
    // No member comments at all — the overwhelming majority of declarations.
    { code: noDeclarationCommentWallDocumentation.examples[0].files[0].source },
    {
      name: "preserves rationale in consecutive line-comment blocks",
      code: [
        "class Connection {",
        "  // selected after a regional failover",
        "  // Host name.",
        "  hostName = '';",
        "  // reserved by the network control plane",
        "  // Port number.",
        "  portNumber = 443;",
        "  // rotated whenever an operator leaves",
        "  // User name.",
        "  userName = '';",
        "}",
      ].join("\n"),
    },

    // Every comment says something the member's own name cannot.
    {
      code: [
        "enum Status {",
        "  /** the queue has accepted it but no worker has claimed it */",
        "  Pending = 'pending',",
        "  /** a worker claimed it and then died without releasing the lease */",
        "  Orphaned = 'orphaned',",
        "  /** terminal, and the payload has already been purged */",
        "  Finished = 'finished',",
        "}",
      ].join("\n"),
    },

    // A ONE-WORD comment is a label or a mapping-table cell, never a
    // re-spelling. An enum member tagged with the CLI subcommand it selects
    // (ansible's `TargetMode`) is the shape: with `maxNovelWords` at 1 each of
    // these scores as a restatement by arithmetic unless `isLabel` stops it.
    {
      code: [
        "enum TargetMode {",
        "  WindowsIntegration = 1, // windows",
        "  NetworkIntegration = 2, // network",
        "  PosixIntegration = 3, // posix",
        "  NoTargets = 4, // coverage",
        "}",
      ].join("\n"),
    },

    // A JSDoc block that is nothing but tags is a directive to a docs
    // generator. `medusa`'s js-sdk marks half its class members `@ignore`.
    {
      code: [
        "class Store {",
        "  /** @ignore */",
        "  private client: Client;",
        "  /** @ignore */",
        "  private cache: Cache;",
        "  /** @ignore */",
        "  private clock: Clock;",
        "}",
      ].join("\n"),
    },

    // The words of a NESTED VALUE are not the member's own words. `// Hover
    // background` over a field initialised to `{ background: controlItemBgHover }`
    // has both its words inside the value it labels and neither in the name it
    // describes.
    {
      code: [
        "class Theme {",
        "  // Hover background",
        "  before = { background: controlItemBgHover };",
        "  // Drag spinner",
        "  after = { background: colorFillDrag, cursor: 'spinner' };",
        "  // Focus outline",
        "  focus = { outline: colorFocus };",
        "}",
      ].join("\n"),
    },

    // The same reading for a METHOD BODY: a body names every identifier it
    // touches, so judging a comment against it makes any comment "already
    // said".
    {
      code: [
        "class Ledger {",
        "  /** posts the ledger entry */",
        "  post() { const ledgerEntry = 1; return ledgerEntry; }",
        "  /** voids the ledger entry */",
        "  void_() { const ledgerEntry = 1; return ledgerEntry; }",
        "  /** replays the ledger entry */",
        "  replay() { const ledgerEntry = 1; return ledgerEntry; }",
        "}",
      ].join("\n"),
    },

    // Two commented rows is not a wall — `minCommentedMembers` is 3.
    {
      code: [
        "enum Status {",
        "  /** The pending status. */",
        "  Pending = 'pending',",
        "  /** The finished status. */",
        "  Finished = 'finished',",
        "  Failed = 'failed',",
        "}",
      ].join("\n"),
    },

    // A MINORITY of commented members is a group of labels, not a wall —
    // `minCommentedRatio` is 0.6. Three of eight here.
    {
      code: [
        "enum Status {",
        "  /** The pending status. */",
        "  Pending = 'pending',",
        "  /** The finished status. */",
        "  Finished = 'finished',",
        "  /** The failed status. */",
        "  Failed = 'failed',",
        "  Queued = 'queued',",
        "  Running = 'running',",
        "  Paused = 'paused',",
        "  Retried = 'retried',",
        "  Cancelled = 'cancelled',",
        "}",
      ].join("\n"),
    },

    // One substantive row in three is enough: two thirds is under
    // `minRestatedRatio` (0.75), so lowering that knob makes this flag.
    {
      code: [
        "enum Status {",
        "  /** The pending status. */",
        "  Pending = 'pending',",
        "  /** The finished status. */",
        "  Finished = 'finished',",
        "  /** set by the reaper when a lease expires under a live worker */",
        "  Orphaned = 'orphaned',",
        "}",
      ].join("\n"),
    },

    // A bare identifier word heading a run of uncommented members is a REGION
    // label, and deleting it loses the grouping.
    {
      code: [
        "class Config {",
        "  // transport",
        "  host = 'localhost';",
        "  portNumber = 5432;",
        "  socketPath = null;",
        "  // credentials",
        "  userName = 'a';",
        "  passWord = 'b';",
        "  tokenValue = 'c';",
        "}",
      ].join("\n"),
    },

    // A digit is a bound, a base or a status code — a fact about the world.
    {
      code: [
        "enum Code {",
        "  /** The ok code, 200. */",
        "  Ok = 'ok',",
        "  /** The missing code, 404. */",
        "  Missing = 'missing',",
        "  /** The failed code, 500. */",
        "  Failed = 'failed',",
        "}",
      ].join("\n"),
    },

    // Test files, story files and generated files emit member comments rather
    // than writing them.
    {
      code: [
        "enum Status {",
        "  /** The pending status. */",
        "  Pending = 'pending',",
        "  /** The finished status. */",
        "  Finished = 'finished',",
        "  /** The failed status. */",
        "  Failed = 'failed',",
        "}",
      ].join("\n"),
      filename: "src/status.test.ts",
    },
    {
      code: [
        "enum Status {",
        "  /** The pending status. */",
        "  Pending = 'pending',",
        "  /** The finished status. */",
        "  Finished = 'finished',",
        "  /** The failed status. */",
        "  Failed = 'failed',",
        "}",
      ].join("\n"),
      filename: "src/status.stories.tsx",
    },
    {
      code: [
        "// Code generated by protoc-gen-ts. DO NOT EDIT.",
        "enum Status {",
        "  /** The pending status. */",
        "  Pending = 'pending',",
        "  /** The finished status. */",
        "  Finished = 'finished',",
        "  /** The failed status. */",
        "  Failed = 'failed',",
        "}",
      ].join("\n"),
    },

    {
      code: "class Row { id = ''; label = ''; href = ''; } // Shared field",
      options: [{ maxNovelWords: 2 }],
    },

    {
      code: [
        "class Registry {",
        "  // Retry backup handlers",
        "  retries = [retryHandler, backupHandler];",
        "  // Build retry handler",
        "  fallback = () => buildRetryHandler();",
        "  // Primary color palette",
        "  theme = { palette: primaryPalette };",
        "}",
      ].join("\n"),
    },

    {
      name: "ignores object-literal tables",
      code: [
        "const status = {",
        "  // The pending status",
        "  pendingStatus: 'pending',",
        "  // The running status",
        "  runningStatus: 'running',",
        "  // The finished status",
        "  finishedStatus: 'finished',",
        "};",
      ].join("\n"),
    },

  ],

  invalid: [
    // The enum arm. medusa/packages/core/utils/src/order/status.ts is this
    // exact shape, twice in one file.
    {
      code: noDeclarationCommentWallDocumentation.examples[1].files[0].source,
      errors: [{ messageId: "commentWall" }],
    },

    // The class-body arm.
    {
      code: [
        "class Server {",
        "  // The server host",
        "  host: string;",
        "  // The server port",
        "  port: string;",
        "  // The server region",
        "  region: string;",
        "}",
      ].join("\n"),
      errors: [{ messageId: "commentWall" }],
    },

    // A TRAILING comment is read against its own member the same way a leading
    // one is.
    {
      code: [
        "enum Status {",
        "  Pending = 'pending', // The pending state",
        "  Running = 'running', // The running state",
        "  Blocked = 'blocked', // The blocked state",
        "}",
      ].join("\n"),
      errors: [{ messageId: "commentWall" }],
    },

    // A region label is not counted as a member comment at all, so the three
    // restatements are three of THREE rather than three of five. Counting the
    // labels instead puts the ratio at 0.6 and the wall goes unreported.
    {
      code: [
        "class Config {",
        "  // The retry count",
        "  retryCount = 4;",
        "  // The base url",
        "  baseUrl = 'https://x';",
        "  // The user agent",
        "  userAgent = 'y';",
        "",
        "  // transport",
        "  socketPath = null;",
        "",
        "  // credentials",
        "  tokenValue = 'c';",
        "}",
      ].join("\n"),
      errors: [{ messageId: "commentWall" }],
    },

    // `maxNovelWords` is a knob, and raising it to 2 makes a type whose
    // comments each add one definition word flag. This is the case that dies
    // when the option stops being read.
    {
      code: [
        "enum Match {",
        "  // Partial name match",
        "  Name = 'name',",
        "  // Exact slug match",
        "  Slug = 'slug',",
        "  // Fuzzy title match",
        "  Title = 'title',",
        "}",
      ].join("\n"),
      options: [{ maxNovelWords: 2 }],
      errors: [{ messageId: "commentWall" }],
    },

    {
      name: "honors minCommentedMembers",
      code: [
        "enum Status {",
        "  // The pending status",
        "  Pending = 'pending',",
        "  // The finished status",
        "  Finished = 'finished',",
        "}",
      ].join("\n"),
      options: [{ minCommentedMembers: 2 }],
      errors: [{ messageId: "commentWall" }],
    },

    {
      name: "honors minCommentedRatio",
      code: [
        "enum Status {",
        "  // The pending status",
        "  Pending = 'pending',",
        "  // The finished status",
        "  Finished = 'finished',",
        "  // The failed status",
        "  Failed = 'failed',",
        "  Queued = 'queued',",
        "  Running = 'running',",
        "  Paused = 'paused',",
        "  Retried = 'retried',",
        "  Cancelled = 'cancelled',",
        "}",
      ].join("\n"),
      options: [{ minCommentedRatio: 0.3 }],
      errors: [{ messageId: "commentWall" }],
    },

    {
      name: "honors minRestatedRatio",
      code: [
        "enum Status {",
        "  // The pending status",
        "  Pending = 'pending',",
        "  // The finished status",
        "  Finished = 'finished',",
        "  // set by the reaper when a live worker loses its lease",
        "  Orphaned = 'orphaned',",
        "}",
      ].join("\n"),
      options: [{ minRestatedRatio: 0.6 }],
      errors: [{ messageId: "commentWall" }],
    },
  ],
});
