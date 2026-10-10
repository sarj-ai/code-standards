// vitest: shared-module-graph
import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule, { NO_JSON_STRINGIFY_ERROR_DOCUMENTATION } from "../../src/rules/no-json-stringify-error.js";

import { verifyRuleExamples } from "../../src/verify-rule-examples.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const RULE_TESTER = new RuleTester({
  languageOptions: {
    parser: tsParser,
  },
});

RULE_TESTER.run("no-json-stringify-error", rule, {
  valid: [
    { name: "does not infer Error provenance for catch cause", code: "try { f(); } catch (err) { JSON.stringify(err.cause); }" },
    { name: "does not infer Error provenance for catch inner", code: "try { f(); } catch (err) { JSON.stringify(err.inner); }" },
    { name: "does not infer Error provenance for alternatively named catch cause", code: "try { f(); } catch (error) { JSON.stringify(error.cause); }" },
    { name: "does not infer Error provenance for catch originalError", code: "try { f(); } catch (err) { JSON.stringify(err.originalError); }" },
    { name: "respects explicit error-field replacers", code: "try { f(); } catch (err) { JSON.stringify(err, ['message', 'stack']); }" },
    { name: "respects custom replacer functions", code: "try { f(); } catch (err) { JSON.stringify(err, serializeError); }" },
    { name: "does not inherit a shadowed catch binding", code: "try { f(); } catch (err) { function encode(err: string) { return JSON.stringify(err); } }" },
    { name: "does not assume an injected JSON API is native", code: "function encode(JSON) { return JSON.stringify(new Error('x')); }" },
    { name: "does not assume an injected constructor is native", code: "function encode(Error) { return JSON.stringify(new Error('x')); }" },
    { name: "does not treat a reassigned catch binding as a proven error", code: "try { f(); } catch (err) { err = { status: 'failed' }; JSON.stringify(err); }" },
    { name: "allows the documented explicit error field", code: NO_JSON_STRINGIFY_ERROR_DOCUMENTATION.examples[0].files[0].source },
    { name: "allows non-error objects", code: "JSON.stringify(user);" },
    {
      name: "allows a conventional short name without Error provenance",
      code: "items.map((e) => JSON.stringify(e));",
    },
    {
      name: "allows a plain API error payload",
      code: "const data = await response.json(); throw new Error(JSON.stringify(data.error));",
    },
    {
      name: "allows an unproven error-named member",
      code: "JSON.stringify(this.lastError);",
    },
    { name: "allows object literals", code: "JSON.stringify({ a: 1 });" },
    {
      name: "allows an error message nested in an object literal",
      code: "try { f(); } catch (err) { JSON.stringify({ error: err.message }); }",
    },
    {
      name: "allows a string-valued shorthand error property",
      code: "const error = 'provider unavailable'; JSON.stringify({ error });",
    },
    {
      name: "allows an unproven error-named function parameter in a payload",
      code: "function serialize(error: string) { return JSON.stringify({ error }); }",
    },
    {
      name: "allows enumerable error data nested in an object literal",
      code: "JSON.stringify({ error: error.data });",
    },
    {
      name: "does not descend through nested object literals",
      code: "try { f(); } catch (err) { JSON.stringify({ meta: { err } }); }",
    },
    {
      name: "allows identifiers that are neither error-named nor catch bindings",
      code: "const payload = {}; JSON.stringify(payload);",
    },
    {
      name: "allows an error message string",
      code: "try { f(); } catch (err) { JSON.stringify(err.message); }",
    },
    {
      name: "allows an error stack string",
      code: "try { f(); } catch (err) { JSON.stringify(err.stack); }",
    },
    { name: "allows an error name string", code: "JSON.stringify(err.name);" },
    {
      name: "allows the non-error branch of an instanceof ternary",
      code: "const s = e instanceof Error ? e : JSON.stringify(e, null, '\\t');",
    },
    {
      name: "allows the non-error branch of an instanceof if statement",
      code: "let s; if (e instanceof Error) { s = e.message; } else { s = JSON.stringify(e); }",
    },
    {
      name: "allows the non-error branch of a negated instanceof ternary",
      code: "const s = !(e instanceof Error) ? JSON.stringify(e) : e.message;",
    },
    {
      name: "allows the non-error branch of a negated instanceof if statement",
      code: "let s; if (!(err instanceof Error)) { s = JSON.stringify(err); }",
    },
    // A user-defined type guard narrows the error away before the stringify.
    {
      code: "function f(e) { if (isErrorLike(e)) return e.message; return JSON.stringify(e); }",
    },
    {
      code: "function f(e) { if (isError(e)) { throw e; } logInfo({ error: JSON.stringify(e) }); }",
    },
    { code: "const s = isErrorLike(e) ? e.message : JSON.stringify(e);" },
    { code: "let s; if (!isErrorLike(err)) { s = JSON.stringify(err); }" },
    // A function whose param is named `data` (not an error name).
    { code: "function f(data) { return JSON.stringify(data); }" },
    // Names that merely contain an error-like substring don't match the anchored regex.
    { code: "JSON.stringify(errors);" },
    { code: "JSON.stringify(emailAddress);" },
    { code: "JSON.stringify(exception);" },
    // Not JSON.stringify at all.
    { code: "const err = {}; serialize(err);" },
    // Different object than JSON.
    { code: "const err = {}; MyJSON.stringify(err);" },
    // No arguments.
    { code: "JSON.stringify();" },

    {
      name: "allows enumerable error data",
      code: "JSON.stringify(error.data);",
    },
    {
      name: "allows enumerable error status",
      code: "JSON.stringify(error.status);",
    },
    {
      name: "allows enumerable error statusCode",
      code: "JSON.stringify(error.statusCode);",
    },
    {
      name: "allows enumerable error statusText",
      code: "JSON.stringify(error.statusText);",
    },
    {
      name: "allows enumerable error code",
      code: "JSON.stringify(error.code);",
    },
    {
      name: "allows enumerable error issues",
      code: "JSON.stringify(error.issues);",
    },
    {
      name: "allows enumerable error details",
      code: "JSON.stringify(error.details);",
    },
    {
      name: "allows enumerable error body",
      code: "JSON.stringify(error.body);",
    },
    {
      name: "allows enumerable error payload",
      code: "JSON.stringify(error.payload);",
    },
    {
      name: "allows enumerable error response",
      code: "JSON.stringify(error.response);",
    },
    {
      name: "allows enumerable error info",
      code: "JSON.stringify(error.info);",
    },
    {
      name: "allows enumerable error meta",
      code: "JSON.stringify(error.meta);",
    },
    {
      name: "allows enumerable error metadata",
      code: "JSON.stringify(error.metadata);",
    },
    {
      name: "allows enumerable error context",
      code: "JSON.stringify(error.context);",
    },
  ],
  invalid: [
    { name: "reports the documented Error payload", code: NO_JSON_STRINGIFY_ERROR_DOCUMENTATION.examples[1].files[0].source, errors: [{ messageId: "noJsonStringifyError" }] },
    {
      name: "reports a catch binding nested in an object literal",
      code: "try { f(); } catch (err) { JSON.stringify({ error: err }); }",
      errors: [{ messageId: "noJsonStringifyError" }],
    },
    {
      name: "reports a shorthand error property",
      code: "try { f(); } catch (err) { JSON.stringify({ err }); }",
      errors: [{ messageId: "noJsonStringifyError" }],
    },
    {
      name: "reports an error nested in an array literal",
      code: "try { f(); } catch (err) { JSON.stringify([err]); }",
      errors: [{ messageId: "noJsonStringifyError" }],
    },
    {
      name: "reports a stable builtin Error binding nested in a payload",
      code: "const error = new TypeError('invalid'); JSON.stringify({ error });",
      errors: [{ messageId: "noJsonStringifyError" }],
    },
    // A `catch` binding passed directly, even with an unconventional name.
    {
      code: "try { f(); } catch (problem) { JSON.stringify(problem); }",
      errors: [{ messageId: "noJsonStringifyError" }],
    },
    // catch binding inside a nested scope, conventional name.
    {
      code: "try { f(); } catch (err) { const wrap = () => JSON.stringify(err); }",
      errors: [{ messageId: "noJsonStringifyError" }],
    },
    // catch binding with unconventional name, used in nested scope.
    {
      code: "try { f(); } catch (boom) { const wrap = () => JSON.stringify(boom); }",
      errors: [{ messageId: "noJsonStringifyError" }],
    },
    // An unrelated ternary (not an instanceof guard) does not suppress the report.
    {
      code: "try { f(); } catch (err) { const s = ready ? other : JSON.stringify(err); }",
      errors: [{ messageId: "noJsonStringifyError" }],
    },

    {
      name: "reports a directly constructed Error",
      code: "JSON.stringify(new TypeError('invalid'));",
      errors: [{ messageId: "noJsonStringifyError" }],
    },
  ],
});


it("preserves outcomes for static member access and unknown member keys", async () => {
  const documentation = rule.documentation;
  if (documentation === undefined) throw new Error("Missing rule documentation");
  await verifyRuleExamples({ ...rule, documentation: { ...documentation, examples: [
  {
    "id": "stringified-error-static-member",
    "title": "Static member access preserves the rule outcome",
    "outcome": "match",
    "focusPath": "src/report.ts",
    "expectedCount": 1,
    "files": [
      {
        "path": "src/report.ts",
        "source": "try { f(); } catch (err) { JSON[\"stringify\"]({ error: err }); }"
      }
    ]
  },
  {
    "id": "stringified-error-dynamic-member",
    "title": "Unknown member access does not establish API identity",
    "outcome": "no-match",
    "focusPath": "src/report.ts",
    "expectedCount": 0,
    "files": [
      {
        "path": "src/report.ts",
        "source": "try { f(); } catch (err) { JSON[auditDynamicMember]({ error: err }); }"
      }
    ]
  }
] } });
});


RULE_TESTER.run("no-json-stringify-error native binding provenance", rule, {
  valid: [
    { name: "plain-non-error-fallback", code: "function probe(){try{throw {id:1};}catch(err){if(err instanceof Error)return err.message;return JSON.stringify(err);}}\nconsole.log(probe());" },
    { name: "escaped-fallback-binding", code: "function probe(){try{throw {id:1};}catch(err){if(err instanceof Error)return err.message;return JSON.stringify(\\u0065rr);}}\nconsole.log(probe());" },
    { name: "escaped-guard-binding", code: "function probe(){try{throw {id:1};}catch(err){if(\\u0065rr instanceof Error)return err.message;return JSON.stringify(err);}}\nconsole.log(probe());" },
    { name: "escaped-conditional-fallback", code: "function probe(){try{throw {id:1};}catch(err){return err instanceof Error?err.message:JSON.stringify(\\u0065rr);}}\nconsole.log(probe());" },
    { name: "escaped-negated-fallback", code: "function probe(){try{throw {id:1};}catch(err){if(!(err instanceof Error))return JSON.stringify(\\u0065rr);return err.message;}}\nconsole.log(probe());" },
    { name: "local-error-constructor", code: "function probe(){class Error{message=\"retained\"};const value=new Error();return JSON.stringify(value);}\nconsole.log(probe());" },
    { name: "actual-error-message", code: "function probe(){try{throw new Error(\"retained\");}catch(err){if(err instanceof Error)return err.message;return JSON.stringify(err);}}\nconsole.log(probe());" },
  ],
  invalid: [
    { name: "shadowed-error-binding", code: "function probe(){try{throw {id:1};}catch(err){if(err instanceof Error)return err.message;{const err=new Error(\"lost\");return JSON.stringify(err);}}}\nconsole.log(probe());", errors: [{ messageId: "noJsonStringifyError" }] },
    { name: "shadowed-error-constructor", code: "function probe(){class Error{};try{throw new globalThis.Error(\"lost\");}catch(err){if(err instanceof Error)return \"local\";return JSON.stringify(err);}}\nconsole.log(probe());", errors: [{ messageId: "noJsonStringifyError" }] },
    { name: "actual-unguarded-error", code: "function probe(){try{throw new Error(\"lost\");}catch(err){return JSON.stringify(err);}}\nconsole.log(probe());", errors: [{ messageId: "noJsonStringifyError" }] },
    { name: "initializer-constructor-scope", code: "function probe(){const value=new Error(\"lost\");{class Error{};return JSON.stringify(value);}}\nconsole.log(probe());", errors: [{ messageId: "noJsonStringifyError" }] },
  ],
});


const NATIVE_WRITE_VALID_CASES: readonly (readonly [string, string, number])[] = [
  ["duplicate-hook-last-callable", "const result=JSON.stringify({error:new Error('lost'),toJSON:42,toJSON(){return {message:'kept'};}});", 0],
  ["specific-family-changes-TypeError", "TypeError.prototype.toJSON=()=>({message:'kept'});const result=JSON.stringify(new TypeError('lost'));", 0],
  ["Error-parent-changes-TypeError", "Error.prototype.toJSON=()=>({message:'kept'});const result=JSON.stringify(new TypeError('lost'));", 0],
  ["mutable-key-unknown", "let key='other';key='stringify';const result=JSON[key](new Error('lost'));", 0],
  ["quoted-prototype-setter", "const result=JSON.stringify({error:new Error('lost'),'__proto__':{toJSON(){return {message:'kept'};}}});", 0],
  ["nested-literal-prototype-chain", "const result=JSON.stringify({error:new Error('lost'),__proto__:{__proto__:{toJSON(){return {message:'kept'};}}}});", 0],
  ["literal-inherited-toJSON", "const result=JSON.stringify({error:new Error('lost'),__proto__:{toJSON(){return {message:'kept'};}}});", 0],
  ["unproven-native-error-cause-unproven", "const e=new Error('parent',{cause:new Error('child')});const result=JSON.stringify(e.cause);", 0],
  ["unproven-actual-error-member-unproven", "const e=new Error('parent');e.inner=new Error('child');const result=JSON.stringify(e.inner);", 0],
  ["literal-payload-toJSON-method", "const result=JSON.stringify({error:new Error('lost'),toJSON(){return {message:'kept'};}});", 0],
  ["literal-payload-toJSON-function-value", "const result=JSON.stringify({error:new Error('lost'),toJSON:()=>({message:'kept'})});", 0],
  ["literal-computed-toJSON-method", "const result=JSON.stringify({error:new Error('lost'),['toJSON'](){return {message:'kept'};}});", 0],
  ["literal-toJSON-returning-error-unproven", "const result=JSON.stringify({error:new Error('lost'),toJSON(){return new Error('also lost');}});", 0],
  ["own-error-toJSON", "const e=new Error('kept');e.toJSON=()=>({message:e.message});const result=JSON.stringify(e);", 0],
  ["error-prototype-toJSON", "Error.prototype.toJSON=function(){return {message:this.message};};const result=JSON.stringify(new Error('kept'));", 0],
  ["prototype-hook-defined-property", "Object.defineProperty(Error.prototype,'toJSON',{value:()=>({message:'kept'})});const result=JSON.stringify(new Error('lost'));", 0],
  ["existing-field-replacer", "const result=JSON.stringify(new Error('kept'),['message']);", 0],
  ["duplicate-hook-installed", "const result=JSON.stringify({error:new Error('lost'),toJSON:42,toJSON(){return 'kept'}});", 0],
  ["constant-hook-key", "const key='toJSON';const result=JSON.stringify({error:new Error('lost'),[key](){return 'kept'}});", 0],
  ["own-hook-defined", "const e=new Error('lost');Object.defineProperty(e,'toJSON',{value:()=> 'kept'});const result=JSON.stringify(e);", 0],
  ["own-hook-reflect", "const e=new Error('lost');Reflect.set(e,'toJSON',()=> 'kept');const result=JSON.stringify(e);", 0],
  ["specific-prototype-hook", "TypeError.prototype.toJSON=()=> 'kept';const result=JSON.stringify(new TypeError('lost'));", 0],
  ["common-prototype-inherited", "Error.prototype.toJSON=()=> 'kept';const result=JSON.stringify(new TypeError('lost'));", 0],
  ["prototype-after-creation-before-call", "const e=new TypeError('lost');TypeError.prototype.toJSON=()=> 'kept';const result=JSON.stringify(e);", 0],
  ["own-hook-nested-payload", "const e=new Error('lost');e.toJSON=()=> 'kept';const result=JSON.stringify({error:e});", 0],
  ["modified-String-mutator-key", "String=()=> 'Error';Reflect.set(globalThis,String('foo'),class Other{message='kept'});const result=JSON.stringify(new Error());", 0],
  ["reflect-unknown-key-abstention", "const key=process.argv[2]??'other';Reflect.set(globalThis,key,class Other{});const result=JSON.stringify(new Error('lost'));", 0],
  ["descriptor-spread-abstention", "const descriptor=process.argv.length>0?{writable:true}:{};Object.defineProperty(globalThis,'Error',{...descriptor});const result=JSON.stringify(new Error('lost'));", 0],
  ["explicit-string-member", "const e=new Error('lost');e.tag='kept';const result=JSON.stringify(e.tag);", 0],
  ["explicit-number-member", "const e=new Error('lost');e.count=42;const result=JSON.stringify(e.count);", 0],
  ["explicit-inner-string", "const e=new Error('lost');e.inner='kept';const result=JSON.stringify(e.inner);", 0],
  ["native-cause-string", "const e=new Error('lost',{cause:'kept'});const result=JSON.stringify(e.cause);", 0],
  ["native-cause-number", "const e=new Error('lost',{cause:42});const result=JSON.stringify(e.cause);", 0],
  ["caught-cause-string", "let result;try{throw new Error('lost',{cause:'kept'});}catch(e){result=JSON.stringify(e.cause);}", 0],
  ["caught-inner-string", "let result;try{const e=new Error('lost');e.inner='kept';throw e;}catch(e){result=JSON.stringify(e.inner);}", 0],
  ["caught-originalError-string", "let result;try{const e=new Error('lost');e.originalError='kept';throw e;}catch(e){result=JSON.stringify(e.originalError);}", 0],
  ["explicit-computed-constant-member", "const e=new Error('lost');e.tag='kept';const key='tag';const result=JSON.stringify(e[key]);", 0],
  ["explicit-dynamic-member", "const e=new Error('lost');e.tag='kept';const key=process.argv.length===2?'tag':'other';const result=JSON.stringify(e[key]);", 0],
  ["existing-safe-message", "const e=new Error('kept');const result=JSON.stringify(e.message);", 0],
  ["existing-payload-property", "const e=new Error('lost');e.details={id:42};const result=JSON.stringify(e.details);", 0],
  ["identifier-before", "const NativeError=global.Error;\nError=class Other{message=\"kept\"};const value=new Error();\nconsole.log(JSON.stringify({nativeError:value instanceof NativeError,encoded:JSON.stringify(value)}));", 0],
  ["property-before", "const NativeError=global.Error;\nglobalThis.Error=class Other{message=\"kept\"};const value=new Error();\nconsole.log(JSON.stringify({nativeError:value instanceof NativeError,encoded:JSON.stringify(value)}));", 0],
  ["computed-literal-before", "const NativeError=global.Error;\nglobalThis[\"Error\"]=class Other{message=\"kept\"};const value=new Error();\nconsole.log(JSON.stringify({nativeError:value instanceof NativeError,encoded:JSON.stringify(value)}));", 0],
  ["computed-const-before", "const NativeError=global.Error;\nconst key=\"Error\";globalThis[key]=class Other{message=\"kept\"};const value=new Error();\nconsole.log(JSON.stringify({nativeError:value instanceof NativeError,encoded:JSON.stringify(value)}));", 0],
  ["specific-family-before", "const NativeError=global.Error;\nglobalThis.TypeError=class Other{message=\"kept\"};const value=new TypeError();\nconsole.log(JSON.stringify({nativeError:value instanceof NativeError,encoded:JSON.stringify(value)}));", 0],
  ["local-error-shadow", "const NativeError=global.Error;\nclass Error{message=\"kept\"};const value=new Error();\nconsole.log(JSON.stringify({nativeError:value instanceof NativeError,encoded:JSON.stringify(value)}));", 0],
  ["compound-changing", "const NativeError=global.Error;\nError &&= class Other{message=\"kept\"};const value=new Error();\nconsole.log(JSON.stringify({nativeError:value instanceof NativeError,encoded:JSON.stringify(value)}));", 0],
  ["identifier-destructure", "const NativeError=global.Error;\n({Error}={Error:class Other{message=\"kept\"}});const value=new Error();\nconsole.log(JSON.stringify({nativeError:value instanceof NativeError,encoded:JSON.stringify(value)}));", 0],
  ["property-destructure", "const NativeError=global.Error;\n({replacement:globalThis.Error}={replacement:class Other{message=\"kept\"}});const value=new Error();\nconsole.log(JSON.stringify({nativeError:value instanceof NativeError,encoded:JSON.stringify(value)}));", 0],
  ["deferred-constructor-before-write", "const NativeError=global.Error;\nfunction encode(){const value=new Error();return {nativeError:value instanceof NativeError,encoded:JSON.stringify(value)};}Error=class Other{message=\"kept\"};console.log(JSON.stringify(encode()));", 0],
  ["function-local-postwrite-unknown", "const NativeError=global.Error;\nfunction encode(){const value=new Error(\"lost\");Error=class Other{message=\"kept\"};return {nativeError:value instanceof NativeError,encoded:JSON.stringify(value)};}console.log(JSON.stringify(encode()));", 0],
  ["deferred-write-not-called-unknown", "const NativeError=global.Error;\nfunction mutate(){Error=class Other{message=\"kept\"};}const value=new Error(\"lost\");\nconsole.log(JSON.stringify({nativeError:value instanceof NativeError,encoded:JSON.stringify(value)}));", 0],
  ["unknown-property-family-unknown", "const NativeError=global.Error;\nconst key=process.argv[2]??\"Error\";globalThis[key]=class Other{message=\"kept\"};const value=new TypeError(\"lost\");\nconsole.log(JSON.stringify({nativeError:value instanceof NativeError,encoded:JSON.stringify(value)}));", 0],
  ["loop-reentry-unknown", "const NativeError=global.Error;\nlet captured;for(let index=0;index<2;index++){const value=new Error(\"lost\");Error=class Other{message=\"kept\"};const item={nativeError:value instanceof NativeError,encoded:JSON.stringify(value)};if(index===0)captured=item;else captured.reenteredNativeError=item.nativeError;}console.log(JSON.stringify(captured));", 0],
  ["function-reentry-unknown", "const NativeError=global.Error;\nfunction encode(){const value=new Error(\"lost\");Error=class Other{message=\"kept\"};return {nativeError:value instanceof NativeError,encoded:JSON.stringify(value)};}const first=encode(),second=encode();console.log(JSON.stringify({...first,reenteredNativeError:second.nativeError}));", 0],
  ["for-of-property-before", "const NativeError=global.Error;\nfor(globalThis.Error of [class Other{message=\"kept\"}]){}const value=new Error();\nconsole.log(JSON.stringify({nativeError:value instanceof NativeError,encoded:JSON.stringify(value)}));", 0],
  ["for-of-destructured-property-before", "const NativeError=global.Error;\nfor({replacement:globalThis.Error} of [{replacement:class Other{message=\"kept\"}}]){}const value=new Error();\nconsole.log(JSON.stringify({nativeError:value instanceof NativeError,encoded:JSON.stringify(value)}));", 0],
  ["for-of-identifier-before", "const NativeError=global.Error;\nfor(Error of [class Other{message=\"kept\"}]){}const value=new Error();\nconsole.log(JSON.stringify({nativeError:value instanceof NativeError,encoded:JSON.stringify(value)}));", 0],
  ["same-statement-argument-write-unknown", "const NativeError=global.Error;\nconst value=new Error((Error=class Other{message=\"kept\"},\"lost\"));\nconsole.log(JSON.stringify({nativeError:value instanceof NativeError,encoded:JSON.stringify(value)}));", 0],
  ["reflect-unmodeled", "const NativeError=global.Error;\nReflect.set(globalThis,\"Error\",class Other{message=\"kept\"});const value=new Error();\nconsole.log(JSON.stringify({nativeError:value instanceof NativeError,encoded:JSON.stringify(value)}));", 0],
  ["family-AggregateError-replaced", "const NativeError=global.Error;\nglobalThis.AggregateError=class Other{message=\"kept\"};const value=new AggregateError([],\"lost\");\nconsole.log(JSON.stringify({nativeError:value instanceof NativeError,encoded:JSON.stringify(value)}));", 0],
  ["family-EvalError-replaced", "const NativeError=global.Error;\nglobalThis.EvalError=class Other{message=\"kept\"};const value=new EvalError(\"lost\");\nconsole.log(JSON.stringify({nativeError:value instanceof NativeError,encoded:JSON.stringify(value)}));", 0],
  ["family-RangeError-replaced", "const NativeError=global.Error;\nglobalThis.RangeError=class Other{message=\"kept\"};const value=new RangeError(\"lost\");\nconsole.log(JSON.stringify({nativeError:value instanceof NativeError,encoded:JSON.stringify(value)}));", 0],
  ["family-ReferenceError-replaced", "const NativeError=global.Error;\nglobalThis.ReferenceError=class Other{message=\"kept\"};const value=new ReferenceError(\"lost\");\nconsole.log(JSON.stringify({nativeError:value instanceof NativeError,encoded:JSON.stringify(value)}));", 0],
  ["family-SyntaxError-replaced", "const NativeError=global.Error;\nglobalThis.SyntaxError=class Other{message=\"kept\"};const value=new SyntaxError(\"lost\");\nconsole.log(JSON.stringify({nativeError:value instanceof NativeError,encoded:JSON.stringify(value)}));", 0],
  ["family-URIError-replaced", "const NativeError=global.Error;\nglobalThis.URIError=class Other{message=\"kept\"};const value=new URIError(\"lost\");\nconsole.log(JSON.stringify({nativeError:value instanceof NativeError,encoded:JSON.stringify(value)}));", 0],
  ["reflect-set", "Reflect.set(globalThis,'Error',class Other{message='kept'});const result=JSON.stringify(new Error());", 0],
  ["reflect-define", "Reflect.defineProperty(globalThis,'Error',{value:class Other{message='kept'}});const result=JSON.stringify(new Error());", 0],
  ["object-define", "Object.defineProperty(globalThis,'Error',{value:class Other{message='kept'}});const result=JSON.stringify(new Error());", 0],
  ["object-define-many", "Object.defineProperties(globalThis,{Error:{value:class Other{message='kept'}}});const result=JSON.stringify(new Error());", 0],
  ["reflect-same-receiver", "Reflect.set(globalThis,'Error',class Other{message='kept'},globalThis);const result=JSON.stringify(new Error());", 0],
  ["descriptor-accessor", "Object.defineProperty(globalThis,'Error',{get(){return class Other{message='kept'}}});const result=JSON.stringify(new Error());", 0],
  ["reflect-static-key", "const key='Error';Reflect.set(globalThis,key,class Other{message='kept'});const result=JSON.stringify(new Error());", 0],
  ["reflect-json-method", "Reflect.set(JSON,'stringify',value=>'kept:'+value.message);const result=JSON.stringify(new Error('lost'));", 0],
  ["define-json-method", "Object.defineProperty(JSON,'stringify',{value:value=>'kept:'+value.message});const result=JSON.stringify(new Error('lost'));", 0],
  ["define-many-json-method", "Object.defineProperties(JSON,{stringify:{value:value=>'kept:'+value.message}});const result=JSON.stringify(new Error('lost'));", 0],
  ["json-global-property-method", "globalThis.JSON.stringify=value=>'kept:'+value.message;const result=JSON.stringify(new Error('lost'));", 0],
  ["json-computed-method-write", "const key='stringify';JSON[key]=value=>'kept:'+value.message;const result=JSON.stringify(new Error('lost'));", 0],
  ["constructor-rhs-write", "const value=(Error=new Error('lost'));const result=JSON.stringify(value);", 0],
  ["constructor-written-before-read", "Error=class Other{message='kept'};const result=JSON.stringify(new Error());", 0],
  ["dynamic-key-unknown", "const key=process.argv.length===2?'Error':'other';globalThis[key]=class Other{message='kept'};const result=JSON.stringify(new Error());", 0],
  ["deferred-constructor-read", "function make(){const value=new Error();return JSON.stringify(value)}Error=class Other{message='kept'};const result=make();", 0],
  ["function-reentry", "class Other{message='kept'}function make(){const value=new Error();Error=Other;return JSON.stringify(value)}make();const result=make();", 0],
  ["for-of-property-write", "for(globalThis.Error of [class Other{message='kept'}]){}const result=JSON.stringify(new Error());", 0],
  ["for-of-destructured-write", "for([globalThis.Error] of [[class Other{message='kept'}]]){}const result=JSON.stringify(new Error());", 0],
  ["serializer-whole-global-written", "JSON={stringify:value=>'kept:'+value.message};const result=JSON.stringify(new Error('lost'));", 0],
  ["serializer-method-written", "JSON.stringify=value=>'kept:'+value.message;const result=JSON.stringify(new Error('lost'));", 0],
  ["serializer-global-property-written", "globalThis.JSON={stringify:value=>'kept:'+value.message};const result=JSON.stringify(new Error('lost'));", 0],
  ["serializer-shadowed", "function make(JSON){return JSON.stringify(new Error('lost'))}const result=make({stringify:value=>'kept:'+value.message});", 0],
  ["computed-safe-field", "const key='message';const e=new Error('lost');const result=JSON.stringify(e[key]);", 0],
  ["symbol-key", "const key=Symbol('error');const result=JSON.stringify({[key]:new Error('lost')});", 0],
  ["mutated-key", "let key='error';key=Symbol('error');const result=JSON.stringify({[key]:new Error('lost')});", 0],
  ["regex-object-prototype-hook", "Object.defineProperty(RegExp.prototype,'toJSON',{value:()=>({message:'kept'})});const result=JSON.stringify({error:new Error('lost'),__proto__:/x/});", 0],
  ["regex-object-prototype-without-hook", "const result=JSON.stringify({error:new Error('lost'),__proto__:/x/});", 0],
];

const NATIVE_WRITE_INVALID_CASES: readonly (readonly [string, string, number])[] = [
  ["duplicate-hook-last-noncallable", "const result=JSON.stringify({error:new Error('lost'),toJSON(){return {message:'kept'};},toJSON:42});", 1],
  ["specific-family-does-not-change-Error", "TypeError.prototype.toJSON=()=>({message:'kept'});const result=JSON.stringify(new Error('lost'));", 1],
  ["own-hook-after-read", "const e=new Error('lost');const result=JSON.stringify(e);e.toJSON=()=>({message:'kept'});", 1],
  ["same-name-local-hook-does-not-change-outer", "const e=new Error('lost');{const e=new Error('inner');e.toJSON=()=>({message:'kept'});}const result=JSON.stringify(e);", 1],
  ["stable-alias-chain-serializer", "const key='stringify';const alias=key;const last=alias;const result=JSON[last](new Error('lost'));", 1],
  ["same-name-shadowed-key", "const key='stringify';{const key='other';JSON.other=value=>'kept:'+value.message;JSON[key](new Error('lost'));}const result=JSON[key](new Error('lost'));", 1],
  ["shorthand-prototype-name-is-data", "const __proto__={toJSON(){return {message:'kept'};}};const result=JSON.stringify({error:new Error('lost'),__proto__});", 1],
  ["method-prototype-name-is-data", "const result=JSON.stringify({error:new Error('lost'),__proto__(){return {message:'kept'};}});", 1],
  ["own-noncallable-before-prototype", "const result=JSON.stringify({error:new Error('lost'),toJSON:42,__proto__:{toJSON(){return {message:'kept'};}}});", 1],
  ["nested-prototype-noncallable-own-override", "const result=JSON.stringify({error:new Error('lost'),__proto__:{__proto__:{toJSON(){return {message:'kept'};}},toJSON:42}});", 1],
  ["literal-null-prototype", "const result=JSON.stringify({error:new Error('lost'),__proto__:null});", 1],
  ["computed-prototype-key-is-data", "const result=JSON.stringify({error:new Error('lost'),['__proto__']:{toJSON(){return {message:'kept'};}}});", 1],
  ["own-noncallable-overrides-inherited-hook", "const result=JSON.stringify({error:new Error('lost'),__proto__:{toJSON(){return {message:'kept'};}},toJSON:42});", 1],
  ["literal-toJSON-not-callable", "const result=JSON.stringify({error:new Error('lost'),toJSON:42});", 1],
  ["literal-near-name", "const result=JSON.stringify({error:new Error('lost'),toJson(){return {message:'kept'};}});", 1],
  ["prototype-hook-after-serialization", "const result=JSON.stringify(new Error('lost'));Error.prototype.toJSON=()=>({message:'kept'});", 1],
  ["ordinary-native-error", "const result=JSON.stringify(new Error('lost'));", 1],
  ["duplicate-hook-overridden", "const result=JSON.stringify({error:new Error('lost'),toJSON(){return 'kept'},toJSON:42});", 1],
  ["own-hook-noncallable", "const e=new Error('lost');e.toJSON=42;const result=JSON.stringify(e);", 1],
  ["own-hook-later", "const e=new Error('lost');const result=JSON.stringify(e);e.toJSON=()=> 'kept';", 1],
  ["own-hook-shadowed", "const e=new Error('lost');{const e={};e.toJSON=()=> 'kept';}const result=JSON.stringify(e);", 1],
  ["specific-prototype-unaffected", "TypeError.prototype.toJSON=()=> 'kept';const result=JSON.stringify(new Error('lost'));", 1],
  ["prototype-noncallable", "Error.prototype.toJSON=42;const result=JSON.stringify(new Error('lost'));", 1],
  ["prototype-shadowed", "{class Error{};Error.prototype.toJSON=()=> 'kept';}const result=JSON.stringify(new Error('lost'));", 1],
  ["cross-scope-key-alias", "const first='stringify';const key=first;let result;{const first='other';result=JSON[key](new Error('lost'));}", 1],
  ["noncallable-hook-descriptor", "const e=new Error('lost');Object.defineProperty(e,'toJSON',{value:42});const result=JSON.stringify(e);", 1],
  ["define-many-value-less", "Object.defineProperties(globalThis,{Error:{writable:true}});const result=JSON.stringify(new Error('lost'));", 1],
  ["global-dot-name-is-data", "globalThis['JSON.stringify']=()=> 'custom';const result=JSON.stringify(new Error('lost'));", 1],
  ["direct-native-error", "const result=JSON.stringify(new Error('lost'));", 1],
  ["stable-native-error", "const e=new Error('lost');const result=JSON.stringify(e);", 1],
  ["direct-catch-error", "let result;try{throw new Error('lost');}catch(e){result=JSON.stringify(e);}", 1],
  ["native-error", "const NativeError=global.Error;\nconst value=new Error(\"lost\");\nconsole.log(JSON.stringify({nativeError:value instanceof NativeError,encoded:JSON.stringify(value)}));", 1],
  ["identifier-after", "const NativeError=global.Error;\nconst value=new Error(\"lost\");Error=class Other{message=\"kept\"};\nconsole.log(JSON.stringify({nativeError:value instanceof NativeError,encoded:JSON.stringify(value)}));", 1],
  ["property-after", "const NativeError=global.Error;\nconst value=new Error(\"lost\");globalThis.Error=class Other{message=\"kept\"};\nconsole.log(JSON.stringify({nativeError:value instanceof NativeError,encoded:JSON.stringify(value)}));", 1],
  ["other-family-retained", "const NativeError=global.Error;\nError=class Other{message=\"kept\"};const value=new TypeError(\"lost\");\nconsole.log(JSON.stringify({nativeError:value instanceof NativeError,encoded:JSON.stringify(value)}));", 1],
  ["specific-family-error-retained", "const NativeError=global.Error;\nglobalThis.TypeError=class Other{message=\"kept\"};const value=new Error(\"lost\");\nconsole.log(JSON.stringify({nativeError:value instanceof NativeError,encoded:JSON.stringify(value)}));", 1],
  ["shadowed-globalThis", "const NativeError=global.Error;\nconst globalThis={Error:class Other{}};globalThis.Error=class Other{message=\"kept\"};const value=new Error(\"lost\");\nconsole.log(JSON.stringify({nativeError:value instanceof NativeError,encoded:JSON.stringify(value)}));", 1],
  ["update-after", "const NativeError=global.Error;\nconst value=new Error(\"lost\");Error++;\nconsole.log(JSON.stringify({nativeError:value instanceof NativeError,encoded:JSON.stringify(value)}));", 1],
  ["property-delete-after", "const NativeError=global.Error;\nconst value=new Error(\"lost\");delete globalThis.Error;\nconsole.log(JSON.stringify({nativeError:value instanceof NativeError,encoded:JSON.stringify(value)}));", 1],
  ["self-assignment", "const NativeError=global.Error;\nError=Error;const value=new Error(\"lost\");\nconsole.log(JSON.stringify({nativeError:value instanceof NativeError,encoded:JSON.stringify(value)}));", 1],
  ["property-self-assignment", "const NativeError=global.Error;\nglobalThis.Error=globalThis.Error;const value=new Error(\"lost\");\nconsole.log(JSON.stringify({nativeError:value instanceof NativeError,encoded:JSON.stringify(value)}));", 1],
  ["cross-self-assignment", "const NativeError=global.Error;\nglobalThis.Error=Error;const value=new Error(\"lost\");\nconsole.log(JSON.stringify({nativeError:value instanceof NativeError,encoded:JSON.stringify(value)}));", 1],
  ["logical-or-noop", "const NativeError=global.Error;\nError ||= class Other{message=\"kept\"};const value=new Error(\"lost\");\nconsole.log(JSON.stringify({nativeError:value instanceof NativeError,encoded:JSON.stringify(value)}));", 1],
  ["logical-null-noop", "const NativeError=global.Error;\nglobalThis.Error ??= class Other{message=\"kept\"};const value=new Error(\"lost\");\nconsole.log(JSON.stringify({nativeError:value instanceof NativeError,encoded:JSON.stringify(value)}));", 1],
  ["logical-and-self-noop", "const NativeError=global.Error;\nError &&= Error;const value=new Error(\"lost\");\nconsole.log(JSON.stringify({nativeError:value instanceof NativeError,encoded:JSON.stringify(value)}));", 1],
  ["guard-after-global-write", "const NativeError=global.Error;\nError=class Other{message=\"kept\"};function encode(){try{throw new NativeError(\"lost\")}catch(value){if(value instanceof Error)return {nativeError:false,encoded:\"guard\"};return {nativeError:value instanceof NativeError,encoded:JSON.stringify(value)};}}console.log(JSON.stringify(encode()));", 1],
  ["guard-after-property-write", "const NativeError=global.Error;\nglobalThis.Error=class Other{message=\"kept\"};function encode(){try{throw new NativeError(\"lost\")}catch(value){if(value instanceof Error)return {nativeError:false,encoded:\"guard\"};return {nativeError:value instanceof NativeError,encoded:JSON.stringify(value)};}}console.log(JSON.stringify(encode()));", 1],
  ["post-construction-guard-write", "const NativeError=global.Error;\nconst value=new Error(\"lost\");Error=class Other{message=\"kept\"};if(value instanceof Error)throw new NativeError(\"wrong guard\");\nconsole.log(JSON.stringify({nativeError:value instanceof NativeError,encoded:JSON.stringify(value)}));", 1],
  ["family-AggregateError-retained", "const NativeError=global.Error;\nError=class Other{message=\"kept\"};const value=new AggregateError([],\"lost\");\nconsole.log(JSON.stringify({nativeError:value instanceof NativeError,encoded:JSON.stringify(value)}));", 1],
  ["family-EvalError-retained", "const NativeError=global.Error;\nError=class Other{message=\"kept\"};const value=new EvalError(\"lost\");\nconsole.log(JSON.stringify({nativeError:value instanceof NativeError,encoded:JSON.stringify(value)}));", 1],
  ["family-RangeError-retained", "const NativeError=global.Error;\nError=class Other{message=\"kept\"};const value=new RangeError(\"lost\");\nconsole.log(JSON.stringify({nativeError:value instanceof NativeError,encoded:JSON.stringify(value)}));", 1],
  ["family-ReferenceError-retained", "const NativeError=global.Error;\nError=class Other{message=\"kept\"};const value=new ReferenceError(\"lost\");\nconsole.log(JSON.stringify({nativeError:value instanceof NativeError,encoded:JSON.stringify(value)}));", 1],
  ["family-SyntaxError-retained", "const NativeError=global.Error;\nError=class Other{message=\"kept\"};const value=new SyntaxError(\"lost\");\nconsole.log(JSON.stringify({nativeError:value instanceof NativeError,encoded:JSON.stringify(value)}));", 1],
  ["family-URIError-retained", "const NativeError=global.Error;\nError=class Other{message=\"kept\"};const value=new URIError(\"lost\");\nconsole.log(JSON.stringify({nativeError:value instanceof NativeError,encoded:JSON.stringify(value)}));", 1],
  ["reflect-distinct-receiver", "Reflect.set(globalThis,'Error',class Other{},{});const result=JSON.stringify(new Error('lost'));", 1],
  ["descriptor-no-value", "Object.defineProperty(globalThis,'Error',{writable:true});const result=JSON.stringify(new Error('lost'));", 1],
  ["reflect-other-family", "Reflect.set(globalThis,'Error',class Other{});const result=JSON.stringify(new TypeError('lost'));", 1],
  ["reflect-later-write", "const result=JSON.stringify(new Error('lost'));Reflect.set(globalThis,'Error',class Other{});", 1],
  ["reflect-shadowed", "const Reflect={set(){}};Reflect.set(globalThis,'Error',class Other{});const result=JSON.stringify(new Error('lost'));", 1],
  ["object-shadowed", "const Object={defineProperty(){}};Object.defineProperty(globalThis,'Error',{});const result=JSON.stringify(new Error('lost'));", 1],
  ["reflect-shadowed-globalThis", "const globalThis={};Reflect.set(globalThis,'Error',class Other{});const result=JSON.stringify(new Error('lost'));", 1],
  ["json-self", "JSON=JSON;const result=JSON.stringify(new Error('lost'));", 1],
  ["json-method-self", "JSON.stringify=JSON.stringify;const result=JSON.stringify(new Error('lost'));", 1],
  ["json-method-default", "JSON.stringify??=()=> 'custom';const result=JSON.stringify(new Error('lost'));", 1],
  ["native-default", "const result=JSON.stringify(new Error('lost'));", 1],
  ["constructed-before-later-write", "const value=new Error('lost');Error=class Other{message='kept'};const result=JSON.stringify(value);", 1],
  ["self-assignment-noop", "Error=Error;const result=JSON.stringify(new Error('lost'));", 1],
  ["logical-default-noop", "Error||=class Other{message='kept'};const result=JSON.stringify(new Error('lost'));", 1],
  ["logical-and-self-noop", "Error&&=Error;const result=JSON.stringify(new Error('lost'));", 1],
  ["cross-global-self-noop", "Error=globalThis.Error;const result=JSON.stringify(new Error('lost'));", 1],
  ["shadowed-globalThis", "{const globalThis={};globalThis.Error=class Other{message='kept'};}const result=JSON.stringify(new Error('lost'));", 1],
  ["serializer-later-write-retained", "const result=JSON.stringify(new Error('lost'));JSON.stringify=()=> 'custom';", 1],
  ["computed-method", "const key='stringify';const result=JSON[key](new Error('lost'));", 1],
  ["computed-object-key", "const key='error';const result=JSON.stringify({[key]:new Error('lost')});", 1],
  ["reflect-self-write", "Reflect.set(globalThis,'Error',Error);JSON.stringify(new Error('lost'));", 1],
  ["descriptor-self-write", "Object.defineProperty(globalThis,'Error',{value:Error});JSON.stringify(new Error('lost'));", 1],
  ["reflect-json-self-write", "Reflect.set(JSON,'stringify',JSON.stringify);JSON.stringify(new Error('lost'));", 1],
  ["regex-prototype-own-noncallable", "Object.defineProperty(RegExp.prototype,'toJSON',{value:()=>({message:'kept'})});const result=JSON.stringify({error:new Error('lost'),__proto__:/x/,toJSON:42});", 1],
  ["primitive-prototype-null", "const result=JSON.stringify({error:new Error(\"lost\"),__proto__:null});", 1],
  ["primitive-prototype-string", "const result=JSON.stringify({error:new Error(\"lost\"),__proto__:'prototype'});", 1],
  ["primitive-prototype-number", "const result=JSON.stringify({error:new Error(\"lost\"),__proto__:42});", 1],
  ["primitive-prototype-boolean", "const result=JSON.stringify({error:new Error(\"lost\"),__proto__:true});", 1],
  ["primitive-prototype-bigint", "const result=JSON.stringify({error:new Error(\"lost\"),__proto__:42n});", 1],
];

RULE_TESTER.run("no-json-stringify-error explicit native write and static property provenance", rule, {
  valid: NATIVE_WRITE_VALID_CASES.map(([name, code]) => ({ name, code, filename: "src/native.js" })),
  invalid: NATIVE_WRITE_INVALID_CASES.map(([name, code, count]) => ({ name, code, filename: "src/native.js", errors: Array.from({ length: count }, () => ({ messageId: "noJsonStringifyError" as const })) })),
});
