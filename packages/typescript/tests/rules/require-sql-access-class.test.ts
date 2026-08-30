import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule, {
  REQUIRE_SQL_ACCESS_CLASS_DOCUMENTATION,
} from "../../src/rules/require-sql-access-class.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const RULE_TESTER = new RuleTester({
  languageOptions: { parser: tsParser, sourceType: "module" },
});

RULE_TESTER.run("require-sql-access-class", rule, {
  valid: [
    REQUIRE_SQL_ACCESS_CLASS_DOCUMENTATION.examples[0].files[0].source,
    "export class D1Repository { constructor(readonly env: { DB: D1Database }) {} find() { return this.env.DB.prepare('SELECT 1').first(); } }",
    "export class AssignedRepository { readonly database: Database.Database; constructor(connection: Database.Database) { this.database = connection; } find() { return this.database.prepare('SELECT 1').get(); } }",
    "export class KyselyRepository { constructor(readonly db: Kysely<Database>) {} find() { return this.db.selectFrom('user').selectAll().executeTakeFirst(); } }",
    "export class PrismaRepository { constructor(readonly prisma: PrismaClient) {} find() { return this.prisma.user.findMany(); } }",
    "export function prepare(builder: Builder) { return builder.prepare(); }",
    "export function build(query: QueryBuilder) { return query.select('id'); }",
    "export function request(client: HttpClient) { return client.query('/health'); }",
    {
      code: "export function find(database: Database.Database) { return database.prepare('SELECT 1').get(); }",
      filename: "src/repository.test.ts",
    },
  ],
  invalid: [
    {
      code: REQUIRE_SQL_ACCESS_CLASS_DOCUMENTATION.examples[1].files[0].source,
      errors: [{ messageId: "moveSqlIntoClass" }],
    },
    {
      code: "export async function save(env: { DB: D1Database }) { await env.DB.batch([]); }",
      errors: [{ messageId: "moveSqlIntoClass" }],
    },
    {
      code: "export class HiddenGlobalRepository { find() { return database.prepare('SELECT 1').get(); } }",
      errors: [{ messageId: "moveSqlIntoClass" }],
    },
    {
      code: "export class SelfConstructingRepository { readonly database = new Database('db.sqlite'); find() { return this.database.prepare('SELECT 1').get(); } }",
      errors: [{ messageId: "moveSqlIntoClass" }],
    },
    {
      code: "export class ParameterRepository { find(database: Database.Database) { return database.prepare('SELECT 1').get(); } }",
      errors: [{ messageId: "moveSqlIntoClass" }],
    },
    {
      code: "export function find(pool: Pool) { return pool.query('SELECT id FROM user'); }",
      errors: [{ messageId: "moveSqlIntoClass" }],
    },
    {
      code: "export function find(db: Kysely<Database>) { return db.selectFrom('user').selectAll().executeTakeFirst(); }",
      errors: [{ messageId: "moveSqlIntoClass" }],
    },
    {
      code: "export function find(prisma: PrismaClient) { return prisma.user.findMany(); }",
      errors: [{ messageId: "moveSqlIntoClass" }],
    },
    {
      code: "export function save(db: DrizzleDatabase) { return db.insert(user).values({ id: '1' }).run(); }",
      errors: [{ messageId: "moveSqlIntoClass" }],
    },
  ],
});
