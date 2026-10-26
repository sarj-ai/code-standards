import { join } from "node:path";

import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule, { PREFER_SWITCH_FOR_REPEATED_EQUALITY_DOCUMENTATION } from "../../src/rules/prefer-switch-for-repeated-equality.js";
RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const RULE_TESTER = new RuleTester({ languageOptions: { parser: tsParser, parserOptions: { ecmaVersion: 2024 }, sourceType: "module" } });

RULE_TESTER.run("prefer-switch-for-repeated-equality", rule, {
  valid: [
    { name: "keeps dynamic case getters and selector mutation", code: "function dispatch(kind) { if (kind === Kind.A) a(); else if (Kind.B === kind) b(); else if (kind === Kind.C) c(); }" },
    { name: "keeps unresolved case constants", code: "function dispatch(kind) { if (kind === STATUS_A) a(); else if (STATUS_B === kind) b(); else if (kind === STATUS_C) c(); }" },
    { name: "keeps unowned global selector reads", code: "if (kind === 'a') a(); else if ('b' === kind) b(); else if (kind === 'c') c();" },
    { name: "does not collapse repeated effectful selector evaluation", code: "if (next() === 'a') a(); else if (next() === 'b') b(); else if (next() === 'c') c();" },
    { name: "does not collapse a selector with an observable getter", code: "if (state.kind === 'a') a(); else if (state.kind === 'b') b(); else if (state.kind === 'c') c();" },
    { name: "does not collapse indexed selector reads", code: "if (state[key] === 'a') a(); else if (state[key] === 'b') b(); else if (state[key] === 'c') c();" },
    "if (kind === 'a') a(); else if (kind === 'b') b();",
    "if (kind === 'a') a(); else if (other === 'b') b(); else if (kind === 'c') c();",
    "if (score > 90) a(); else if (score > 80) b(); else if (score > 70) c();",
    "switch (kind) { case 'a': a(); break; case 'b': b(); break; case 'c': c(); break; }",
  ],
  invalid: [
    { name: "fixes terminating branches with an explicit final else", code: "function dispatch(kind: string): number { if (kind === 'a') return 1; else if (kind === 'b') return 2; else if (kind === 'c') return 3; else return 0; }", output: "function dispatch(kind: string): number { switch (kind) {\ncase 'a': { return 1; }\ncase 'b': { return 2; }\ncase 'c': { return 3; }\ndefault: { return 0; }\n} }", errors: [{ messageId: "preferSwitch" }] },
    { name: "does not add unreachable breaks after never-returning calls", code: "declare function fail(): never; function dispatch(kind: string) { if (kind === 'a') fail(); else if (kind === 'b') fail(); else if (kind === 'c') fail(); }", output: null, errors: [{ messageId: "preferSwitch" }] },
    { name: "does not add unreachable breaks after infinite loops", code: "function dispatch(kind: string) { if (kind === 'a') while (true) {} else if (kind === 'b') return 1; else if (kind === 'c') return 2; }", output: null, errors: [{ messageId: "preferSwitch" }] },
    {
      code: "function dispatch(kind) { if (kind === 'a') a(); else if ('b' === kind) b(); else if (kind === 'c') c(); else fallback(); }", output: null,
      errors: [{ messageId: "preferSwitch", data: { discriminant: "kind" } }],
    },
  ],
});

void PREFER_SWITCH_FOR_REPEATED_EQUALITY_DOCUMENTATION;


RULE_TESTER.run("prefer-switch native discriminant identity", rule, {
  valid: [
    { name: "different-discriminants", code: "function probe(kind){const other=\"other\";if(kind==='a')return 1;else if(other==='b')return 2;else if(kind==='c')return 3;return 0;}\nconsole.log(JSON.stringify([\"a\",\"b\",\"c\",\"d\"].map(probe)));" },
    { name: "loose-comparison", code: "function probe(kind){if(kind=='a')return 1;else if(kind=='b')return 2;else if(kind=='c')return 3;return 0;}\nconsole.log(JSON.stringify([\"a\",\"b\",\"c\",\"d\"].map(probe)));" },
  ],
  invalid: [
    { name: "plain", code: "function probe(kind){if(kind==='a')return 1;else if(kind==='b')return 2;else if(kind==='c')return 3;return 0;}\nconsole.log(JSON.stringify([\"a\",\"b\",\"c\",\"d\"].map(probe)));", output: null, errors: [{ messageId: "preferSwitch" }] },
    { name: "escaped-first", code: "function probe(kind){if(\\u006bind==='a')return 1;else if(kind==='b')return 2;else if(kind==='c')return 3;return 0;}\nconsole.log(JSON.stringify([\"a\",\"b\",\"c\",\"d\"].map(probe)));", output: null, errors: [{ messageId: "preferSwitch" }] },
    { name: "escaped-middle", code: "function probe(kind){if(kind==='a')return 1;else if(\\u006bind==='b')return 2;else if(kind==='c')return 3;return 0;}\nconsole.log(JSON.stringify([\"a\",\"b\",\"c\",\"d\"].map(probe)));", output: null, errors: [{ messageId: "preferSwitch" }] },
  ],
});


const TYPED_TESTER = new RuleTester({
  languageOptions: { parser: tsParser, parserOptions: {
    projectService: { allowDefaultProject: ["*.ts*"] },
    tsconfigRootDir: join(import.meta.dirname, "..", "fixtures"),
  } },
});

TYPED_TESTER.run("prefer-switch preserves TypeScript exhaustiveness", rule, {
  valid: [],
  invalid: [
    { name: "preserves a finite-domain implicit unmatched return path", code: "function probe(kind: 'a' | 'b' | 'c'): number { if (kind === 'a') return 1; else if (kind === 'b') return 2; else if (kind === 'c') return 3; return 0; }", output: null, errors: [{ messageId: "preferSwitch" }] },
    { name: "preserves flow narrowing to a finite domain", code: "function probe(kind: string): number { if (kind !== 'a' && kind !== 'b' && kind !== 'c') return 0; if (kind === 'a') return 1; else if (kind === 'b') return 2; else if (kind === 'c') return 3; return 4; }", output: null, errors: [{ messageId: "preferSwitch" }] },
    { name: "fixes a proven open string domain without changing exhaustiveness", code: "function probe(kind: string): number { if (kind === 'a') return 1; else if (kind === 'b') return 2; else if (kind === 'c') return 3; return 0; }", output: "function probe(kind: string): number { switch (kind) {\ncase 'a': { return 1; }\ncase 'b': { return 2; }\ncase 'c': { return 3; }\n} return 0; }", errors: [{ messageId: "preferSwitch" }] },
  ],
});
