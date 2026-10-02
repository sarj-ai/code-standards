// vitest: shared-module-graph
import { it } from "vitest";
import { verifyRuleExamples } from "../../src/verify-rule-examples.js";
import rule from "../../src/rules/require-explicit-service-contract.js";

it("executes the documented examples", async () => {
  await verifyRuleExamples(rule);
});

import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe } from "vitest";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.itOnly = it.only;
RuleTester.it = it;

const RULE_TESTER = new RuleTester({
  languageOptions: {
    parser: tsParser,
    parserOptions: { ecmaVersion: "latest", sourceType: "module" },
  },
});

RULE_TESTER.run("require-explicit-service-contract", rule, {
  valid: [
    { name: "a literal false loop does not invoke its collaborator", code: "class Service { constructor(private readonly worker: Worker) {} run() { while (false) { this.worker.run(); } } }" },
    { name: "two returning branches make the subsequent call unreachable", code: "class Service { constructor(private readonly worker: Worker) {} run(enabled: boolean) { if (enabled) { return; } else { return; } this.worker.run(); } }" },
    "interface Runner { run(): void } class Service implements Runner { constructor(private readonly worker: Worker) {} run() { this.worker.run(); } }",
    "class Service { constructor(private readonly metadata: Metadata) {} id() { return this.metadata.id; } }",
    "abstract class Runner { abstract run(): void } class Service extends Runner { constructor(private readonly worker: Worker) { super(); } run() { this.worker.run(); } }",
    "class Service { constructor(private readonly worker: Worker) {} run() { if (false) return this.worker.run(); } }",
    { name: "local generic and inherited interfaces cover a one-operation service", code: "interface Runner<T> { run(): T } interface TaskRunner extends Runner<void> {} class Service implements TaskRunner { constructor(private readonly worker: Worker) {} run() { this.worker.run(); } }" },
    { name: "intersection aliases combine segregated contracts", code: "interface Reader { read(): void } interface Writer { write(): void } type Contract = Reader & Writer; class Service implements Contract { constructor(private readonly worker: Worker) {} read() { this.worker.read(); } write() { this.worker.write(); } }" },
    { name: "a concrete base preserves its explicitly implemented contract", code: "interface Runner { run(): void } class Base implements Runner { run() {} } class Service extends Base { constructor(private readonly worker: Worker) { super(); } run() { this.worker.run(); } }" },
    { name: "transitive abstract contracts need no repeated declaration", code: "abstract class Runner { abstract run(): void } class Base extends Runner { run() {} } class Service extends Base { constructor(private readonly worker: Worker) { super(); } run() { this.worker.run(); } }" },
    { name: "interface and abstract-base operations combine", code: "abstract class Reader { abstract read(): void } interface Writer { write(): void } class Service extends Reader implements Writer { constructor(private readonly worker: Worker) { super(); } read() { this.worker.read(); } write() { this.worker.write(); } }" },
    { name: "an abstract class can be an implemented operation contract", code: "abstract class Runner { abstract run(): void } class Service implements Runner { constructor(private readonly worker: Worker) {} run() { this.worker.run(); } }" },
    { name: "an abstract contract can include concrete public operations", code: "abstract class Runner { run() {} } class Service extends Runner { constructor(private readonly worker: Worker) { super(); } run() { this.worker.run(); } }" },
    { name: "default-exported abstract contracts are resolved", code: "export default abstract class Runner { abstract run(): void } class Service extends Runner { constructor(private readonly worker: Worker) { super(); } run() { this.worker.run(); } }" },
    { name: "an arrow-function operation has a local interface", code: "interface Runner { run(): void } class Service implements Runner { constructor(private readonly worker: Worker) {} run = () => this.worker.run(); }" },
    { name: "uncalled nested arrow functions do not prove a collaborator operation", code: "class Service { constructor(private readonly worker: Worker) {} run() { const callback = () => this.worker.run(); return 0; } }" },
    { name: "uncalled nested functions do not prove a collaborator operation", code: "class Service { constructor(private readonly worker: Worker) {} run() { function callback() { this.worker.run(); } return 0; } }" },
    { name: "unreachable calls after a return do not prove an operation", code: "class Service { constructor(private readonly worker: Worker) {} run() { return 0; this.worker.run(); } }" },
    { name: "unreachable calls after a throw do not prove an operation", code: "class Service { constructor(private readonly worker: Worker) {} run() { throw new Error(); this.worker.run(); } }" },
    { name: "decorated classes have unresolved rewriting semantics", code: "@framework class Service { constructor(private readonly worker: Worker) {} run() { this.worker.run(); } }" },
    { name: "decorated operations have unresolved rewriting semantics", code: "class Service { constructor(private readonly worker: Worker) {} @framework run() { this.worker.run(); } }" },
    { name: "decorated ancestors have unresolved rewriting semantics", code: "@framework class Base {} class Service extends Base { constructor(private readonly worker: Worker) { super(); } run() { this.worker.run(); } }" },
    { name: "unavailable imported or dynamic bases stay conservative", code: "import { Base } from './framework'; class Service extends Base { constructor(private readonly worker: Worker) { super(); } run() { this.worker.run(); } }" },
    { name: "dynamic bases stay conservative", code: "class Service extends mixin(Base) { constructor(private readonly worker: Worker) { super(); } run() { this.worker.run(); } }" },
    { name: "logger-only services do not establish a behavioral service seam", code: "class Service { constructor(private readonly logger: Logger) {} run() { this.logger.info('ready'); } }" },
    { name: "configuration callbacks alone do not establish a service seam", code: "class Service { constructor(private readonly options: Options) {} run() { this.options.onReady(); } }" },
    { name: "nominal leaf values remain constructor data", code: "class Service { constructor(private readonly value: URL) {} run() { return this.value.toString(); } }" },
    { name: "abstract declarations are contracts rather than concrete services", code: "abstract class Service { constructor(private readonly worker: Worker) {} run() { this.worker.run(); } }" },
    { name: "qualified imported interface aliases stay unresolved rather than empty", code: "import type * as contracts from './contracts'; type Runner = contracts.Runner; class Service implements Runner { constructor(private readonly worker: Worker) {} run() { this.worker.run(); } }" },
    { name: "callable aliases can refer to other local callable aliases", code: "type Run = Fn; type Fn = () => void; interface Runner { run: Run } class Service implements Runner { constructor(private readonly worker: Worker) {} run() { this.worker.run(); } }" },
    { name: "abstract function properties cover arrow operations", code: "abstract class Runner { abstract run: () => void } class Service extends Runner { constructor(private readonly worker: Worker) { super(); } run = () => this.worker.run(); }" },
    { name: "abstract function property aliases cover arrow operations", code: "type Run = () => void; abstract class Runner { abstract run: Run } class Service extends Runner { constructor(private readonly worker: Worker) { super(); } run = () => this.worker.run(); }" },
    { name: "a literal false conjunction skips the collaborator call", code: "class Service { constructor(private readonly worker: Worker) {} run() { return false && this.worker.run(); } }" },
    { name: "a literal true disjunction skips the collaborator call", code: "class Service { constructor(private readonly worker: Worker) {} run() { return true || this.worker.run(); } }" },
    { name: "a literal false conditional skips the collaborator call", code: "class Service { constructor(private readonly worker: Worker) {} run() { return false ? this.worker.run() : 0; } }" },
    { name: "a literal true early return stops subsequent calls", code: "class Service { constructor(private readonly worker: Worker) {} run() { if (true) { return 0; } this.worker.run(); } }" },
    { name: "a locally constructed field is not the injected parameter", code: "class Service { private worker: Worker; constructor(worker: Worker) { { const worker = new Worker(); this.worker = worker; } } run() { this.worker.run(); } }" },
    { name: "an immediately overwritten parameter property is not retained injection", code: "class Service { constructor(private readonly worker: Worker) { this.worker = new Worker(); } run() { this.worker.run(); } }" },
  ],
  invalid: [
    { name: "a literal true loop still invokes its collaborator", code: "class Service { constructor(private readonly worker: Worker) {} run() { while (true) { this.worker.run(); break; } } }", errors: [{ messageId: "requireExplicitServiceContract" }] },
    { name: "one returning branch leaves a reachable collaborator call", code: "class Service { constructor(private readonly worker: Worker) {} run(enabled: boolean) { if (enabled) { return; } this.worker.run(); } }", errors: [{ messageId: "requireExplicitServiceContract" }] },
    {
      code: "class Service { constructor(private readonly worker: Worker) {} run() { this.worker.run(); } }",
      errors: [{ messageId: "requireExplicitServiceContract" }],
    },
    {
      code: "interface Service { run(): void } class Service { constructor(private readonly worker: Worker) {} run() { this.worker.run(); } }",
      errors: [{ messageId: "requireExplicitServiceContract" }],
    },
    {
      code: "class Unrelated { nothing() {} } class Service extends Unrelated { constructor(private readonly worker: Worker) { super(); } run() { this.worker.run(); } }",
      errors: [{ messageId: "requireExplicitServiceContract" }],
    },
    {
      code: "class Service { constructor(private readonly worker: Worker) {} run() { this.helper(); } private helper() { this.worker.run(); } }",
      errors: [{ messageId: "requireExplicitServiceContract" }],
    },
    { name: "local arrow-function operations still need a contract", code: "class Service { constructor(private readonly worker: Worker) {} run = () => this.worker.run(); }", errors: [{ messageId: "requireExplicitServiceContract" }] },
    { name: "function-expression operations still need a contract", code: "class Service { constructor(private readonly worker: Worker) {} run = function() { this.worker.run(); }; }", errors: [{ messageId: "requireExplicitServiceContract" }] },
    { name: "partial interfaces do not cover omitted invoked operations", code: "interface Reader { read(): void } class Service implements Reader { constructor(private readonly worker: Worker) {} read() { this.worker.read(); } write() { this.worker.write(); } }", errors: [{ messageId: "requireExplicitServiceContract" }] },
    { name: "abstract-class implements requires actual operation coverage", code: "abstract class Reader { abstract read(): void } class Service implements Reader { constructor(private readonly worker: Worker) {} read() { this.worker.read(); } write() { this.worker.write(); } }", errors: [{ messageId: "requireExplicitServiceContract" }] },
    { name: "transitive abstract contracts do not hide uncovered operations", code: "abstract class Reader { abstract read(): void } class Base extends Reader { read() {} } class Service extends Base { constructor(private readonly worker: Worker) { super(); } read() { this.worker.read(); } write() { this.worker.write(); } }", errors: [{ messageId: "requireExplicitServiceContract" }] },
    { name: "ordinary concrete base methods are not a declared contract", code: "class Base { run() {} } class Service extends Base { constructor(private readonly worker: Worker) { super(); } run() { this.worker.run(); } }", errors: [{ messageId: "requireExplicitServiceContract" }] },
    { name: "private helper reached by a public arrow operation needs a contract", code: "class Service { constructor(private readonly worker: Worker) {} run = () => this.helper(); private helper() { this.worker.run(); } }", errors: [{ messageId: "requireExplicitServiceContract" }] },
    { name: "a role directory plus behavioral evidence establishes a service", filename: "/repo/src/services/coordinator.ts", code: "class Coordinator { constructor(private readonly worker: Worker) {} run() { this.worker.run(); } }", errors: [{ messageId: "requireExplicitServiceContract" }] },
    { name: "a literal true conjunction executes the collaborator call", code: "class Service { constructor(private readonly worker: Worker) {} run() { return true && this.worker.run(); } }", errors: [{ messageId: "requireExplicitServiceContract" }] },
    { name: "a literal false disjunction executes the collaborator call", code: "class Service { constructor(private readonly worker: Worker) {} run() { return false || this.worker.run(); } }", errors: [{ messageId: "requireExplicitServiceContract" }] },
    { name: "a literal true conditional executes the collaborator call", code: "class Service { constructor(private readonly worker: Worker) {} run() { return true ? this.worker.run() : 0; } }", errors: [{ messageId: "requireExplicitServiceContract" }] },
    { name: "a direct retained constructor parameter still establishes a seam", code: "class Service { private worker: Worker; constructor(worker: Worker) { this.worker = worker; } run() { this.worker.run(); } }", errors: [{ messageId: "requireExplicitServiceContract" }] },
  ],
});
