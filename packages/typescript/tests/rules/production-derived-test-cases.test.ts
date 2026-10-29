// vitest: shared-module-graph
import * as parser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule, { PRODUCTION_DERIVED_TEST_CASES_DOCUMENTATION } from "../../src/rules/production-derived-test-cases.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;
const TESTER = new RuleTester({ languageOptions: { parser }, defaultFilenames: { ts: "src/cases.test.ts", tsx: "src/cases.test.tsx" } });

TESTER.run("production-derived-test-cases", rule, {
  valid: [
    PRODUCTION_DERIVED_TEST_CASES_DOCUMENTATION.examples[1].files[0].source,
    { name: "independent literal cases", code: "import { test } from 'vitest'; test.each(['reader', 'writer'])('%s', run);" },
    { name: "third-party registry", code: "import { test } from 'vitest'; import { SUPPORTED_ROLES } from 'provider'; test.each(SUPPORTED_ROLES)('%s', run);" },
    { name: "test fixture collection", code: "import { test } from 'vitest'; import { SUPPORTED_ROLES } from './fixtures/roles.js'; test.each(SUPPORTED_ROLES)('%s', run);" },
    { name: "intentional enum sweep", code: "import { test } from 'vitest'; import { Role } from './roles.js'; test.each(Object.values(Role))('%s', run);" },
    { name: "registry sweep has another contract", code: "import { test } from 'vitest'; import { SUPPORTED_REGISTRY } from './roles.js'; test.each(SUPPORTED_REGISTRY)('%s', run);" },
    { name: "custom runner", code: "import { test } from './runner.js'; import { SUPPORTED_ROLES } from './roles.js'; test.each(SUPPORTED_ROLES)('%s', run);" },
    { name: "module membership oracle", code: "import { test, expect } from 'vitest'; import { SUPPORTED_ROLES } from './roles.js'; expect(SUPPORTED_ROLES).toEqual(['reader']); test.each(SUPPORTED_ROLES)('%s', run);" },
    { name: "named independent expected table", code: "import { test, expect } from 'vitest'; import { SUPPORTED_ROLES } from './roles.js'; const EXPECTED = ['reader'] as const; test('membership', () => { expect(SUPPORTED_ROLES).toStrictEqual(EXPECTED); }); test.each(SUPPORTED_ROLES)('%s', run);" },
    { name: "generated artifact", filename: "src/generated/roles.test.ts", code: PRODUCTION_DERIVED_TEST_CASES_DOCUMENTATION.examples[0].files[0].source },
    { name: "local suppression", code: "import { test } from 'vitest'; import { SUPPORTED_ROLES } from './roles.js';\n// eslint-disable-next-line @rule-tester/production-derived-test-cases -- deliberate provider smoke sweep\ntest.each(SUPPORTED_ROLES)('%s', run);" },
  ],
  invalid: [
    { code: PRODUCTION_DERIVED_TEST_CASES_DOCUMENTATION.examples[0].files[0].source, errors: [{ messageId: "independentCases" }] },
    ...[
      ["aliased import", "import { it as example } from 'vitest'; import { ALLOWED_ROLES as roles } from './roles.js'; example.each(roles)('%s', run);"],
      ["Vitest for table", "import { test } from 'vitest'; import { ELIGIBLE_ROLES } from './roles.js'; test.for(ELIGIBLE_ROLES)('%s', run);"],
      ["only modifier", "import { test } from 'vitest'; import { REQUIRED_ROLES } from './roles.js'; test.only.each(REQUIRED_ROLES)('%s', run);"],
      ["shadowed oracle cannot validate production", "import { test, expect } from 'vitest'; import { SUPPORTED_ROLES } from './roles.js'; function helper(SUPPORTED_ROLES) { expect(SUPPORTED_ROLES).toEqual(['reader']); } test.each(SUPPORTED_ROLES)('%s', run);"],
      ["helper assertion is not registered", "import { test, expect } from 'vitest'; import { SUPPORTED_ROLES } from './roles.js'; function helper() { expect(SUPPORTED_ROLES).toEqual(['reader']); } test.each(SUPPORTED_ROLES)('%s', run);"],
      ["unreachable oracle", "import { test, expect } from 'vitest'; import { SUPPORTED_ROLES } from './roles.js'; if (false) { expect(SUPPORTED_ROLES).toEqual(['reader']); } test.each(SUPPORTED_ROLES)('%s', run);"],
      ["self comparison is not independent", "import { test, expect } from 'vitest'; import { SUPPORTED_ROLES } from './roles.js'; expect(SUPPORTED_ROLES).toEqual(SUPPORTED_ROLES); test.each(SUPPORTED_ROLES)('%s', run);"],
      ["custom expect is not an oracle", "import { test } from 'vitest'; import { expect } from './oracle.js'; import { SUPPORTED_ROLES } from './roles.js'; expect(SUPPORTED_ROLES).toEqual(['reader']); test.each(SUPPORTED_ROLES)('%s', run);"],
    ].map(([name, code]) => ({ name, code, errors: [{ messageId: "independentCases" as const }] })),
  ],
});
