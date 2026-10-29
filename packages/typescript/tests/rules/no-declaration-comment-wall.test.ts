// vitest: shared-module-graph
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule, {
  NO_DECLARATION_COMMENT_WALL_DOCUMENTATION,
} from "../../src/rules/no-declaration-comment-wall.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.itOnly = it.only;
RuleTester.it = it;

const RULE_TESTER = new RuleTester();

RULE_TESTER.run("no-declaration-comment-wall", rule, {
  valid: [

    { code: NO_DECLARATION_COMMENT_WALL_DOCUMENTATION.examples[0].files[0].source },
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

    {
      name: "preserves machine-consumed type tags even when their prose restates members",
      code: [
        "class Store {",
        "  /** The client. @type {Client} */",
        "  client = createClient();",
        "  /** The cache. @type {Cache} */",
        "  cache = createCache();",
        "  /** The clock. @type {Clock} */",
        "  clock = createClock();",
        "}",
      ].join("\n"),
    },





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
    { name: "automatically removes only exact multiword member names", code: "class Client {\n  /** Read user. */\n  readUser() {}\n  /** Write user. */\n  writeUser() {}\n  /** Delete user. */\n  deleteUser() {}\n}", output: "class Client {\n\n  readUser() {}\n\n  writeUser() {}\n\n  deleteUser() {}\n}", errors: [{ messageId: "commentWall" }] },


    {
      code: NO_DECLARATION_COMMENT_WALL_DOCUMENTATION.examples[1].files[0].source,
      errors: [{ messageId: "commentWall" }],
    },


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
      ].join("\n"), output: "class Config {\n\n  retryCount = 4;\n\n  baseUrl = 'https://x';\n\n  userAgent = 'y';\n\n  // transport\n  socketPath = null;\n\n  // credentials\n  tokenValue = 'c';\n}",
      errors: [{ messageId: "commentWall" }],
    },




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
