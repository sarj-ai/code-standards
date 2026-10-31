import rule from "../../src/rules/prefer-minimal-parameter-contract.js";
import { CONSUMER_PREFIX, INLINE_CONTRACT, PRIVATE_CONSUMER_TESTER, runPrivateConsumerBoundaries } from "../private-consumer-cases.js";

const PREFIX = CONSUMER_PREFIX;
runPrivateConsumerBoundaries("prefer-minimal-parameter-contract", rule, INLINE_CONTRACT);
for (const contract of ["{name: string; email: string}", "{readonly name: string; email: string}", "{name: string; email: string | null}", "{readonly name: string; email: undefined | string}"]) {
  runPrivateConsumerBoundaries("prefer-minimal-parameter-contract " + contract, rule, contract);
}
PRIVATE_CONSUMER_TESTER.run("prefer-minimal-parameter-contract", rule, {
  valid: [
    ...([
      ["all required fields consumed", `function label(p: ${INLINE_CONTRACT}): string {return p.name + p.email;}`],
      ["unused destructured fields are still read", `function label({name, email}: ${INLINE_CONTRACT}): string {return name;}`],
      ["optional unused field does not restrict structural callers", "function label(p: {readonly name: string; readonly email?: string}): string {return p.name;}"],
      ["optional-only reduced contract can reject weak-type callers", "function label(p: {readonly name?: string; readonly email: string}): string {return p.name ?? '';}"],
      ["all plain required fields consumed", "function label(p: {name: string; email: string}): string {return p.name + p.email;}"],
      ["plain destructuring still reads an unreturned field", "function label({name, email}: {name: string; email: string}): string {return name;}"],
      ["unused plain optional field does not restrict callers", "function label(p: {name: string; email?: string}): string {return p.name;}"],
      ["mixed optional-only reduced contract remains excluded", "function label(p: {name?: string; readonly email: string}): string {return p.name ?? '';}"],
      ["plain literal field retains a domain invariant", "function label(p: {name: string; kind: 'account'}): string {return p.name;}"],
      ["named domain contract", "interface Account {readonly name: string; readonly email: string} function label(p: Account): string {return p.name;}"],
      ["literal discriminant retains a domain invariant", "function label(p: {readonly name: string; readonly kind: 'account'}): string {return p.name;}"],
      ["object-valued property", "function label(p: {readonly name: string; readonly metadata: object}): string {return p.name;}"],
      ["implicit Object capability can observe unread data", "declare global {interface Object {readonly label: string}} function label(p: {readonly name: string; readonly email: string}): string {return p.name + p.label;}"],
      ["unused function has no evaluated consumer calls", `function label(p: ${INLINE_CONTRACT}): string {return p.name;}`],
    ] as const).map(([name, declaration]) => ({name, filename: "probe.tsx", code: `${PREFIX}${declaration}${name.startsWith("unused function") ? "" : "label(account);"}`})),
  ],
  invalid: [
    ...([
      ["unused required field", `function label(p: ${INLINE_CONTRACT}): string {return p.name;}`, "function label(p: {readonly name: string; }): string {return p.name;}"],
      ["plain field declarations retain read-only usage", "function label(p: {name: string; email: string}): string {return p.name;}", "function label(p: {name: string; }): string {return p.name;}"],
      ["retained readonly field is not rewritten", "function label(p: {readonly name: string; email: string}): string {return p.name;}", "function label(p: {readonly name: string; }): string {return p.name;}"],
      ["removed readonly field does not make the retained field readonly", "function label(p: {name: string; readonly email: string}): string {return p.name;}", "function label(p: {name: string; }): string {return p.name;}"],
      ["mixed optional modifiers and reads remain", "function label(p: {name: string; email: string; readonly suffix?: string}): string {return p.name + (p.suffix ?? '');}", "function label(p: {name: string;  readonly suffix?: string}): string {return p.name + (p.suffix ?? '');}"],
      ["readonly producer keeps its full object type", "const input = {name: 'Ada', email: 'a'} as const; function label(p: {name: string; email: string}): string {return p.name;}", "const input = {name: 'Ada', email: 'a'} as const; function label(p: {name: string; }): string {return p.name;}", "input"],
      ["const arrow with boolean field", "const enabledAccount = {...account, enabled: true}; const label = (p: {readonly name: string; readonly enabled: boolean}): string => p.name;", "const enabledAccount = {...account, enabled: true}; const label = (p: {readonly name: string; }): string => p.name;", "enabledAccount"],
      ["destructured alias", `function label({name: displayName}: ${INLINE_CONTRACT}): string {return displayName;}`, "function label({name: displayName}: {readonly name: string; }): string {return displayName;}"],
      ["same-named parameter is not the callable binding", `function label(label: ${INLINE_CONTRACT}): string {return label.name;}`, "function label(label: {readonly name: string; }): string {return label.name;}"],
      ["fixed string key", `function label(p: ${INLINE_CONTRACT}): string {return p['name'];}`, "function label(p: {readonly name: string; }): string {return p['name'];}"],
      ["optional field retained alongside used required field", "function label(p: {readonly name: string; readonly email: string; readonly suffix?: string}): string {return p.name + (p.suffix ?? '');}", "function label(p: {readonly name: string;  readonly suffix?: string}): string {return p.name + (p.suffix ?? '');}"],
    ] as const).map(([name, declaration, fixed, argument = "account"]) => ({name, filename: "probe.tsx", code: `${PREFIX}${declaration}label(${argument});`, output: `${PREFIX}${fixed}label(${argument});`, errors: [{messageId: "minimal" as const}]})),
  ],
});

const NULLISH_PRIMITIVES = [["string", "'a'"], ["number", "1"], ["boolean", "true"], ["bigint", "1n"]] as const;
const NULLISH_CONTRACT = "{name: string; email: string | null}";
const NULLISH_DECLARATION = `function label(p: ${NULLISH_CONTRACT}): string {return p.name;}`;
for (const [primitive, value] of NULLISH_PRIMITIVES) {
  for (const nullish of ["null", "undefined"]) {
    for (const reverse of [false, true]) {
      const type = reverse ? `${nullish} | ${primitive}` : `${primitive} | ${nullish}`;
      PRIVATE_CONSUMER_TESTER.run("prefer-minimal-parameter-contract unread " + type, rule, {
        valid: [],
        invalid: ["", "readonly "].map((modifier) => {
          const prefix = `export {}; const full = {name: 'Ada', email: ${value}}; const empty = {name: 'Bob', email: ${nullish}};`;
          const contract = `{${modifier}name: string; ${modifier}email: ${type}}`;
          const declaration = reverse ? `const label = (p: ${contract}): string => p.name;` : `function label(p: ${contract}): string {return p.name;}`;
          const code = `${prefix}${declaration}label(full); label(empty);`;
          return {name: "required unread " + modifier + type, filename: "probe.tsx", code, output: code.replace(`${modifier}email: ${type}`, ""), errors: [{messageId: "minimal" as const}]};
        }),
      });
    }
  }
}
for (const [primitive, value] of NULLISH_PRIMITIVES) {
  for (const nullish of ["null", "undefined"]) {
    PRIVATE_CONSUMER_TESTER.run("prefer-minimal-parameter-contract retained " + primitive + " | " + nullish, rule, {
      valid: [
        {name: "every field is read", filename: "probe.tsx", code: `export {}; const input = {name: 'Ada', value: ${value}}; function label(p: {name: string; value: ${primitive} | ${nullish}}): string {return p.name + typeof p.value;} label(input);`},
        {name: "optional-only retained reads preserve weak-type exclusion", filename: "probe.tsx", code: `export {}; const input = {spare: 'audit'}; function label(p: {value?: ${primitive} | ${nullish}; spare: string}): string {return typeof p.value;} label(input);`},
      ],
      invalid: [false, true].map((optional) => {
        const code = `export {}; const input = {name: 'Ada', value: ${value}, spare: 'audit'}; function label(p: {readonly name: string; readonly value${optional ? "?" : ""}: ${primitive} | ${nullish}; readonly spare: string}): string {return p.name + typeof p.value;} label(input);`;
        return {name: "retain " + (optional ? "optional" : "required") + " nullable read", filename: "probe.tsx", code, output: code.replace("readonly spare: string", ""), errors: [{messageId: "minimal" as const, data: {used: "name, value", unused: "spare"}}]};
      }),
    });
  }
}
PRIVATE_CONSUMER_TESTER.run("prefer-minimal-parameter-contract unread nullish fields", rule, {
  valid: [
    ...([
      ["optional nullish member excludes the whole contract", "function label(p: {name: string; email?: string | null; spare: string}): string {return p.name;}"],
      ["optional-only retained reads remain excluded", "function label(p: {name?: string; email: string | null}): string {return p.name ?? '';}"],
      ["computed member declarations are unsupported", "function label(p: {name: string; ['email']: string | null}): string {return p.name;}"],
      ["nullable return annotation depends on the field", "function label(p: {name: string; email: string | null}): typeof p.email {return p.name;}"],
      ["a local type query is outside the single-expression proof", "function label(p: {name: string; email: string | null}): string {type Local = typeof p.email; return p.name satisfies Exclude<Local, null>;}"],
      ["type assertions can carry a field dependency", "function label(p: {name: string; email: string | null}): string {return (p.name as typeof p.email)!;}"],
      ["explicit helper type arguments carry dependencies", "function helper<T>(value: T): string {return String(value);} function label(p: {name: string; email: string | null}): string {return helper<typeof p.email>(p.name);}"],
      ["imported reexported inherited field types remain named", "import type {ConsumerAccount} from './consumer-index'; function label(p: {name: string; email: ConsumerAccount['email'] | null}): string {return p.name;}"],
    ] as const).map(([name, declaration]) => ({name, filename: "probe.tsx", code: `${PREFIX}const input = {...account, spare: 'audit'};${declaration}label(input);`})),
    ...["Nullable", "'a' | null", "(string) | null", "string | (null)", "string | null | undefined", "null | undefined", "string | number", "any | null", "unknown | null", "never | null", "void | string", "object | null", "(string & {brand: true}) | null"].map((type) => ({
      name: "unsupported field domain " + type, filename: "probe.tsx", code: `${PREFIX}type Nullable = string | null; function label(p: {name: string; email: ${type}}): string {return p.name;} label(account);`,
    })),
    ...[
      "export type RequiredEmail = Parameters<typeof label>[0]['email'];",
      "export type Result = ReturnType<typeof label>;",
      "export function inspect(): string {type Saved = Parameters<typeof label>[0]['email']; const note: Saved = null; return note ?? '';}",
      "export function inspect(): string {type Saved = ReturnType<typeof label>; const note: Saved = ''; return note;}",
    ].map((observation) => ({name: "callable type observation " + observation, filename: "probe.tsx", code: `${PREFIX}${NULLISH_DECLARATION}label(account); ${observation}`})),
  ],
  invalid: [
    ...([
      ["nullable coalescing is an inspection", "function label(p: {name: string; email: string | null; spare: string}): string {return p.email ?? p.name;}"],
      ["runtime typeof is an inspection", "function label(p: {name: string; email: string | null; spare: string}): string {return p.name + typeof p.email;}"],
      ["a conditional reads its nullable condition", "function label(p: {name: string; email: string | undefined; spare: string}): string {return p.email ? p.name : '';}"],
      ["escaped fixed reads keep the normalized nullable key", "function label(p: {name: string; email: string | null; spare: string}): string {return p['em\\u0061il'] ?? p.name;}"],
      ["destructuring reads even an unreturned nullable alias", "function label({name, email: unused}: {name: string; email: string | null; spare: string}): string {return name;}"],
      ["scalar helper retains its nullable input", "function helper(value: string | null): string {return value ?? '';} function label(p: {name: string; email: string | null; spare: string}): string {return p.name + helper(p.email);}"],
    ] as const).map(([name, declaration]) => {
      const code = `${PREFIX}const input = {...account, spare: 'audit'};${declaration}label(input);`;
      return {name, filename: "probe.tsx", code, output: code.replace("spare: string", ""), errors: [{messageId: "minimal" as const, data: {used: "email, name", unused: "spare"}}]};
    }),
    ...([
      ["producer-only type query does not observe the callable", `export type Email = typeof account.email; ${NULLISH_DECLARATION}`],
      ["flat destructuring of only the required read remains supported", `function label({name: display}: ${NULLISH_CONTRACT}): string {return display;}`],
      ["optional broad fields remain retained", "function label(p: {name: string; email: string | null; suffix?: string}): string {return p.name + (p.suffix ?? '');}"],
      ["a local scalar helper receives only the retained field", `function format(name: string): string {return name.toUpperCase();} ${NULLISH_DECLARATION.replace("return p.name;", "return format(p.name);")}`],
      ["getter producer remains unchanged", `const input = {name: 'Ada', get email(): string | null {return null;}}; ${NULLISH_DECLARATION}`, "input"],
    ] as const).map(([name, declaration, argument = "account"]) => ({name, filename: "probe.tsx", code: `${PREFIX}${declaration}label(${argument});`, output: `${PREFIX}${declaration.replace("email: string | null;", "").replace("email: string | null", "")}label(${argument});`, errors: [{messageId: "minimal" as const}]})),
    {name: "multiple nullish requirements produce one sorted finding", filename: "probe.tsx", code: `${PREFIX}const input = {...account, count: undefined}; function label(p: {name: string; email: string | null; count: number | undefined}): string {return p.name;} label(input);`,
      output: `${PREFIX}const input = {...account, count: undefined}; function label(p: {name: string;  }): string {return p.name;} label(input);`, errors: [{messageId: "minimal", data: {used: "name", unused: "count, email"}}]},
    ...([
      ["invalid original caller", "const input = {name: 'Ada', email: 1};"],
      ["missing original requirement", "const input = {name: 'Ada'};"],
      ["optional original requirement", "declare const input: {name: string; email?: string | null};"],
      ["Any relevant caller field", "declare const input: {name: string; email: any};"],
      ["unknown relevant caller field", "declare const input: {name: string; email: unknown};"],
      ["unsafe original caller union", "declare const input: {name: string; email: string | null} | {name: string; email: any};"],
      ["incompatible original caller union", "declare const input: {name: string; email: string | null} | {name: string; email: number};"],
    ] as const).map(([name, producer]) => ({name, filename: "probe.tsx", code: `${PREFIX}${producer}${NULLISH_DECLARATION}label(account); label(input);`, output: null, errors: [{messageId: "minimal" as const}]})),
    {name: "nullable annotation comments keep a manual finding", filename: "probe.tsx", code: `${PREFIX}${NULLISH_DECLARATION.replace("string | null", "string | /* rationale */ null")}label(account);`, output: null, errors: [{messageId: "minimal"}]},
    {name: "nullable suppression must not become unused", filename: "probe.tsx", code: `export {}; const input = {name: 'Ada'}; ${NULLISH_DECLARATION}\n// @ts-expect-error the original required nullable field is missing\nlabel(input);`, output: null, errors: [{messageId: "minimal"}]},
  ],
});

PRIVATE_CONSUMER_TESTER.run("prefer-minimal-parameter-contract safe source edits", rule, {
  valid: [],
  invalid: [
    {name: "a first inline member owns only its horizontal leading trivia", filename: "probe.tsx",
      code: `${PREFIX}function label(p: { readonly email: string; readonly name: string }): string {return p.name;} label(account);`,
      output: `${PREFIX}function label(p: { readonly name: string }): string {return p.name;} label(account);`, errors: [{messageId: "minimal"}]},
    ...["\n", "\r\n", "\r", "\u2028", "\u2029"].map((ending) => ({name: "a first member keeps its newline-leading trivia " + JSON.stringify(ending), filename: "probe.tsx",
      code: `${PREFIX}function label(p: {${ending}  readonly email: string;${ending}  readonly name: string${ending}}): string {return p.name;} label(account);`,
      output: `${PREFIX}function label(p: {${ending}  ${ending}  readonly name: string${ending}}): string {return p.name;} label(account);`, errors: [{messageId: "minimal" as const}]})),
    ...["\n", "\r\n", "\r", "\u2028", "\u2029"].map((ending) => ({name: "preserve raw member and line terminators " + JSON.stringify(ending), filename: "probe.tsx",
      code: `${PREFIX}const compass = '🧭'; function label(p: {readonly name: string;${ending}readonly email:${ending}string}): string {return p.name;} label(account);`,
      output: `${PREFIX}const compass = '🧭'; function label(p: {readonly name: string;${ending}${ending}}): string {return p.name;} label(account);`, errors: [{messageId: "minimal" as const}]})),
    ...["{readonly name: string; readonly email:\r string\n}", "{readonly name: string;\rreadonly email:\nstring}"].map((contract) => ({
      name: "member deletion cannot merge distinct CR and LF terminators " + JSON.stringify(contract), filename: "probe.tsx",
      code: `${PREFIX}function label(p: ${contract}): string {return p.name;} label(account);`, output: null, errors: [{messageId: "minimal" as const}],
    })),
    {name: "multiple unread required members keep an unused optional member", filename: "probe.tsx", code: `${PREFIX}const value = {...account, count: 1}; function label(p: {readonly email: string; readonly name: string; readonly count: number; readonly note?: string}): string {return p.name;} label(value);`,
      output: `${PREFIX}const value = {...account, count: 1}; function label(p: { readonly name: string;  readonly note?: string}): string {return p.name;} label(value);`, errors: [{messageId: "minimal"}]},
    {name: "plain contract with an invalid original caller stays manual", filename: "probe.tsx", code: "export {}; const account = {name: 'Ada', email: 42}; function label(p: {name: string; email: string}): string {return p.name;} label(account);", output: null, errors: [{messageId: "minimal"}]},
    {name: "plain contract with unknown caller data stays manual", filename: "probe.tsx", code: "export {}; declare const input: {name: string; email: any}; function label(p: {name: string; email: string}): string {return p.name;} label(input);", output: null, errors: [{messageId: "minimal"}]},
    {name: "comments remain manual", filename: "probe.tsx", code: `${PREFIX}function label(p: {readonly name: string; /* rationale */ readonly email: string}): string {return p.name;} label(account);`, output: null, errors: [{messageId: "minimal"}]},
    {name: "preexisting invalid identifier caller stays rejected", filename: "probe.tsx", code: `export {}; const account = {name: 'Ada', email: 42}; function label(p: ${INLINE_CONTRACT}): string {return p.name;} label(account);`, output: null, errors: [{messageId: "minimal"}]},
    ...["any", "unknown"].map((type) => ({name: "unsafe relevant caller field remains manual " + type, filename: "probe.tsx",
      code: `${PREFIX}declare const value: {name: string; email: ${type}}; function label(p: ${INLINE_CONTRACT}): string {return p.name;} label(value);`, output: null, errors: [{messageId: "minimal" as const}]})),
    {name: "unresolved error caller field remains manual", filename: "probe.tsx", code: `${PREFIX}declare const value: {name: string; email: Missing}; function label(p: ${INLINE_CONTRACT}): string {return p.name;} label(value);`, output: null, errors: [{messageId: "minimal"}]},
    {name: "a required ts-expect-error must not become unused", filename: "probe.tsx", code: `export {}; const account = {name: 'Ada'}; function label(p: ${INLINE_CONTRACT}): string {return p.name;}\n// @ts-expect-error the original private contract requires email\nlabel(account);`, output: null, errors: [{messageId: "minimal"}]},
  ],
});

const SCALAR_HELPER = "function formatName(name: string): string {return name.toUpperCase();}";
const HELPER_CONSUMER = "function label(p: {name: string; email: string}): string {return formatName(p.name);}";
PRIVATE_CONSUMER_TESTER.run("prefer-minimal-parameter-contract scalar helpers", rule, {
  valid: [
    ...([
      ["inferred helper returns remain unsupported", "function formatName(name: string) {return name;}", HELPER_CONSUMER],
      ["callee aliases remain unsupported", SCALAR_HELPER + "const alias = formatName;", HELPER_CONSUMER.replace("formatName(p.name)", "alias(p.name)")],
      ["helper arguments cannot mutate the parameter", SCALAR_HELPER, HELPER_CONSUMER.replace("p.name)", "p.name = 'updated')")],
      ["callbacks cannot capture the parameter", "function formatName(read: () => string): string {return read();}", HELPER_CONSUMER.replace("formatName(p.name)", "formatName(() => p.name)")],
      ["predicate helpers retain refinement semantics", "function accepts(value: unknown): value is string {return typeof value === 'string';}", "function label(p: {name: string; email: string}): boolean {return accepts(p.name);}"],
      ["a native-invalid original helper caller is unavailable", SCALAR_HELPER, HELPER_CONSUMER + "const broken = {name: 'Ada', email: 42}; label(broken);"],
    ] as const).map(([name, helper, consumer]) => ({name, filename: "probe.tsx", code: `${PREFIX}${helper}${consumer}label(account);`})),
  ],
  invalid: [
    ...([
      ["local implementation receives only a scalar", SCALAR_HELPER, HELPER_CONSUMER, "label(account);"],
      ["raw const arrow implementation", "const formatName = (name: string): string => name;", HELPER_CONSUMER, "label(account);"],
      ["all identifier callers and producer aliases remain unchanged", SCALAR_HELPER, HELPER_CONSUMER, "const alias = account; label(account); label(alias);"],
      ["two scalar arguments retain only their fixed field dependency", "function formatName(name: string, suffix: string): string {return name + suffix;}", HELPER_CONSUMER.replace("formatName(p.name)", "formatName(p.name, '!')"), "label(account);"],
    ] as const).map(([name, helper, consumer, calls]) => ({name, filename: "probe.tsx", code: `${PREFIX}${helper}${consumer}${calls}`,
      output: `${PREFIX}${helper}${consumer.replace("email: string", "")}${calls}`, errors: [{messageId: "minimal" as const}]})),
    {name: "comments in a new helper contract preserve manual review", filename: "probe.tsx",
      code: `${PREFIX}${SCALAR_HELPER}${HELPER_CONSUMER.replace("email: string", "/* private dependency rationale */ email: string")}label(account);`, output: null, errors: [{messageId: "minimal"}]},
    {name: "an Any caller cannot certify an automatic contract edit", filename: "probe.tsx",
      code: `${PREFIX}${SCALAR_HELPER}${HELPER_CONSUMER}declare const opaque: {name: string; email: any}; label(account); label(opaque);`, output: null, errors: [{messageId: "minimal"}]},
  ],
});
