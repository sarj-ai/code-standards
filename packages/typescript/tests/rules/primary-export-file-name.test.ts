import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule from "../../src/rules/primary-export-file-name.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const ruleTester = new RuleTester();

ruleTester.run("primary-export-file-name", rule, {
  valid: [
    {
      code: `export function userProfileCard() { return null; }`,
      filename: "/src/components/user-profile-card.tsx",
    },
    {
      code: `export class AccountService {}`,
      filename: "/src/services/account-service.ts",
    },
    {
      code: `export const useAuthSession = () => {};`,
      filename: "/src/hooks/use-auth-session.ts",
    },
    {
      code: `export default function UserCard() { return null; }`,
      filename: "/src/components/user-card.tsx",
    },
    {
      // Barrel re-export file
      code: `export * from "./user-card.js";`,
      filename: "/src/components/index.ts",
    },
    {
      // Framework route file
      code: `export default function Page() { return null; }`,
      filename: "/src/app/dashboard/page.tsx",
    },
    {
      // Conventional export (cn)
      code: `export function cn() { return ""; }`,
      filename: "/src/lib/utils.ts",
    },
  ],
  invalid: [
    {
      code: `export function UserProfileCard() { return null; }`,
      filename: "/src/components/user-helpers.tsx",
      errors: [
        {
          messageId: "primaryExportMismatch",
          data: { stem: "user-helpers", name: "UserProfileCard", expected: "user-profile-card", ext: ".tsx" },
        },
      ],
    },
    {
      code: `export class AccountService {}`,
      filename: "/src/services/account-stuff.ts",
      errors: [
        {
          messageId: "primaryExportMismatch",
          data: { stem: "account-stuff", name: "AccountService", expected: "account-service", ext: ".ts" },
        },
      ],
    },
  ],
});
