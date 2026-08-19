# PR review rule mining ledger

This ledger records the complete disposition of a private review corpus without copying private repository names, paths, source text, snippets, hashes, or identities into this public artifact. Each stable PRR identifier maps one-to-one, in source order, to a source line in that corpus.

Disposition meanings:

- `new-sarj-rule`: deterministic local syntax supports a new warning-level rule.
- `existing-sarj`: an existing Sarj rule covers the deterministic portion.
- `upstream-config`: an upstream linter, type checker, or platform check is the correct owner.
- `audit-only`: reliable enforcement requires context unavailable to a file-local deterministic linter.
- `reject`: a prior or tempting deterministic form has unacceptable false positives.

## Complete inventory

| ID | Source line | Disposition | Public ownership/evidence |
| --- | ---: | --- | --- |
| PRR-001 | 9 | upstream-config | typescript-eslint strict type-aware rules |
| PRR-002 | 10 | upstream-config | @sarj/tsconfig base.json |
| PRR-003 | 11 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-004 | 12 | existing-sarj | SARJ032 / @sarj/require-assert-never |
| PRR-005 | 13 | upstream-config | typescript-eslint consistent-type-assertions and no-unsafe-type-assertion |
| PRR-006 | 14 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-007 | 15 | upstream-config | eslint-plugin-zod/no-any-schema |
| PRR-008 | 16 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-009 | 17 | upstream-config | ESLint no-restricted-imports |
| PRR-010 | 18 | existing-sarj | Sarj suppression rules plus eslint-comments/RUF100 |
| PRR-011 | 22 | existing-sarj | @sarj/prefer-shadcn-primitives |
| PRR-012 | 23 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-013 | 24 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-014 | 25 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-015 | 26 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-016 | 27 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-017 | 28 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-018 | 29 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-019 | 30 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-020 | 31 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-021 | 32 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-022 | 33 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-023 | 34 | upstream-config | typescript-eslint prefer-nullish-coalescing configured exception |
| PRR-024 | 38 | existing-sarj | @sarj/no-unnecessary-use-client |
| PRR-025 | 39 | existing-sarj | @sarj/prefer-server-actions and no-raw-fetch-outside-clients |
| PRR-026 | 40 | existing-sarj | @sarj/no-client-side-data-fetching |
| PRR-027 | 41 | existing-sarj | @sarj/no-raw-fetch-outside-clients |
| PRR-028 | 42 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-029 | 43 | existing-sarj | @sarj/require-zod-form-validation |
| PRR-030 | 44 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-031 | 45 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-032 | 46 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-033 | 47 | new-sarj-rule | typescript:no-router-refresh-polling |
| PRR-034 | 48 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-035 | 49 | existing-sarj | @sarj/no-fat-try-blocks |
| PRR-036 | 50 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-037 | 54 | upstream-config | Ruff UP/B009 |
| PRR-038 | 55 | upstream-config | Ruff future-annotations rules |
| PRR-039 | 56 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-040 | 57 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-041 | 58 | existing-sarj | SARJ009 / no-sentinel-return-on-catch |
| PRR-042 | 59 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-043 | 60 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-044 | 61 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-045 | 62 | upstream-config | Ruff ASYNC rules |
| PRR-046 | 63 | upstream-config | Ruff BLE001 |
| PRR-047 | 64 | existing-sarj | SARJ006 prefer-str-enum |
| PRR-048 | 65 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-049 | 66 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-050 | 67 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-051 | 68 | existing-sarj | SARJ018 and SQL insert-requires-on-conflict |
| PRR-052 | 69 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-053 | 70 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-054 | 71 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-055 | 72 | upstream-config | Ruff PERF401 |
| PRR-056 | 73 | existing-sarj | SARJ023 / @sarj/stepdown |
| PRR-057 | 74 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-058 | 75 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-059 | 76 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-060 | 77 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-061 | 78 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-062 | 79 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-063 | 80 | existing-sarj | SARJ024 / @sarj/no-repeated-string-literal (local portion) |
| PRR-064 | 81 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-065 | 82 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-066 | 83 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-067 | 84 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-068 | 85 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-069 | 86 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-070 | 87 | existing-sarj | no-log-only-catch and no-sentinel-return rules |
| PRR-071 | 88 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-072 | 89 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-073 | 90 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-074 | 91 | existing-sarj | no-restated-comment/docstring family |
| PRR-075 | 92 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-076 | 93 | existing-sarj | SARJ420 and FastAPI OpenAPI contract prose checks |
| PRR-077 | 94 | upstream-config | import-linter contracts |
| PRR-078 | 95 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-079 | 96 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-080 | 97 | existing-sarj | self-documenting constant and repeated-literal rules |
| PRR-081 | 98 | existing-sarj | SARJ052 no-stdlib-logging |
| PRR-082 | 99 | reject | Retired no-sequential-await rules produced false positives; use no-await-in-loop only where applicable. |
| PRR-083 | 100 | existing-sarj | catch/try rules cover observable forms; intent remains audit-only |
| PRR-084 | 101 | upstream-config | Ruff PLR2004 plus Sarj constant rules |
| PRR-085 | 102 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-086 | 103 | upstream-config | Ruff E402 |
| PRR-087 | 104 | existing-sarj | prefer-str-enum, preserve-enum-types, and TS enum rules |
| PRR-088 | 105 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-089 | 106 | existing-sarj | stepdown covers placement; ownership remains audit-only |
| PRR-090 | 107 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-091 | 108 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-092 | 112 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-093 | 113 | new-sarj-rule | python:no-redundant-literal-description |
| PRR-094 | 114 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-095 | 115 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-096 | 116 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-097 | 117 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-098 | 118 | existing-sarj | docstring-restatement and unnecessary-docstring rules |
| PRR-099 | 119 | existing-sarj | SARJ420 no-unnecessary-docstring |
| PRR-100 | 120 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-101 | 121 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-102 | 125 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-103 | 126 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-104 | 127 | existing-sarj | SARJ019/SARJ020 query complexity rules |
| PRR-105 | 128 | existing-sarj | SARJ021 and @sarj/no-select-star |
| PRR-106 | 129 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-107 | 130 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-108 | 131 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-109 | 132 | existing-sarj | SARJ013 prefer-class-row |
| PRR-110 | 133 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-111 | 134 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-112 | 138 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-113 | 139 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-114 | 140 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-115 | 141 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-116 | 142 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-117 | 143 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-118 | 147 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-119 | 148 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-120 | 149 | existing-sarj | repeated-static-call-cases and test-loop rules |
| PRR-121 | 150 | existing-sarj | constant/repeated-literal rules |
| PRR-122 | 151 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-123 | 155 | existing-sarj | require-port-for-service |
| PRR-124 | 156 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-125 | 157 | existing-sarj | pagination rules cover the deterministic query form |
| PRR-126 | 158 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-127 | 159 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-128 | 160 | existing-sarj | comment hygiene and restatement rules |
| PRR-129 | 161 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-130 | 165 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-131 | 166 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-132 | 167 | existing-sarj | SARJ056 no-optional-tenant-predicate (deterministic subset) |
| PRR-133 | 171 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-134 | 172 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-135 | 173 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-136 | 174 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-137 | 175 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-138 | 176 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-139 | 180 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-140 | 181 | existing-sarj | warning lifecycle and strict presets |
| PRR-141 | 182 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-142 | 183 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-143 | 184 | upstream-config | setup-node caching and package-runner workflow checks |
| PRR-144 | 191 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-145 | 192 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-146 | 193 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-147 | 194 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-148 | 195 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-149 | 196 | existing-sarj | SARJ416 preserve-declared-nominal-id |
| PRR-150 | 197 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-151 | 198 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-152 | 199 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-153 | 200 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-154 | 201 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-155 | 202 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-156 | 203 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-157 | 204 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-158 | 205 | new-sarj-rule | python:require-nodecode-for-splitting-settings-field |
| PRR-159 | 206 | existing-sarj | SARJ400 and SARJ418 Pydantic bounds |
| PRR-160 | 207 | new-sarj-rule | python:no-nested-pydantic-field-validator |
| PRR-161 | 208 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-162 | 209 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-163 | 210 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-164 | 211 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-165 | 212 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-166 | 213 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-167 | 214 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-168 | 215 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-169 | 216 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-170 | 217 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-171 | 218 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-172 | 219 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-173 | 220 | existing-sarj | SARJ407 plus UUID default rules |
| PRR-174 | 221 | existing-sarj | SARJ421 get-delegates-to-get-many (delegation subset) |
| PRR-175 | 222 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-176 | 223 | existing-sarj | SARJ414 require-validated-row-factory |
| PRR-177 | 224 | existing-sarj | @sarj/no-dynamic-sql |
| PRR-178 | 225 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-179 | 226 | existing-sarj | SARJ404 no-unique-violation-message-match |
| PRR-180 | 227 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-181 | 228 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-182 | 229 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-183 | 230 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-184 | 231 | new-sarj-rule | sql:no-create-trigger |
| PRR-185 | 232 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-186 | 233 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-187 | 234 | existing-sarj | SARJ094 FastAPI OpenAPI contract (schema/marker subset) |
| PRR-188 | 235 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-189 | 236 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-190 | 237 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-191 | 238 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-192 | 239 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-193 | 240 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-194 | 241 | reject | SARJ405/no-apirouter-root-trailing-slash was retired because trailing-slash routes are valid public contracts. |
| PRR-195 | 242 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-196 | 243 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-197 | 244 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-198 | 245 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-199 | 246 | new-sarj-rule | typescript:no-duplicate-lifecycle-refresh-listeners |
| PRR-200 | 247 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-201 | 248 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-202 | 249 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-203 | 250 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-204 | 251 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-205 | 252 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-206 | 253 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-207 | 254 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-208 | 255 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-209 | 256 | existing-sarj | source-coupled-test |
| PRR-210 | 257 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-211 | 258 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-212 | 259 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-213 | 260 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-214 | 261 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-215 | 262 | new-sarj-rule | python:no-conftest-test-module-import |
| PRR-216 | 263 | existing-sarj | SARJ204/SARJ205 Terraform environment rules |
| PRR-217 | 264 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-218 | 265 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-219 | 266 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-220 | 267 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-221 | 268 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-222 | 269 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-223 | 270 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-224 | 271 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-225 | 272 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-226 | 273 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-227 | 274 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-228 | 275 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-229 | 276 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-230 | 277 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-231 | 278 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-232 | 279 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-233 | 280 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-234 | 281 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-235 | 282 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-236 | 283 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-237 | 284 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |
| PRR-238 | 285 | audit-only | Requires business intent, change history, runtime evidence, or project-specific semantics. |

## New RuleProblems

### PRR-033 — TypeScript: no router-refresh polling

- **Anti-pattern:** a timer callback uses a router-wide refresh as its polling operation.
- **Why it matters:** broad refreshes refetch unrelated server-component state and hide the actual polling dependency.
- **Detection signal:** a `setInterval` callback contains a `refresh()` call on a router binding.
- **Exclusions:** non-timer refreshes, direct data calls in timers, tests, and generated files.
- **False-positive risks:** an unrelated object named `router`; mitigated by requiring a router binding initialized by a router hook.
- **Expected fix:** poll through the specific action or data client.
- **Severity:** warning.
- **Autofix:** none; selecting the correct data dependency is semantic.

### PRR-093 — Python: no redundant Literal description

- **Anti-pattern:** a Pydantic `Field` description merely repeats the allowed `Literal` or enum values.
- **Why it matters:** generated schemas already expose those values, so duplicated prose drifts.
- **Detection signal:** a directly annotated constrained field has a short description whose normalized value set matches its declared alternatives.
- **Exclusions:** explanatory descriptions, tests, and unconstrained fields.
- **False-positive risks:** meaningful prose that happens to list all choices; mitigated by narrow phrase and token matching.
- **Expected fix:** remove the redundant description or replace it with behavior-oriented guidance.
- **Severity:** warning.
- **Autofix:** none; intent cannot be preserved mechanically.

### PRR-158 — Python: require NoDecode for splitting settings fields

- **Anti-pattern:** a settings field with a complex container type is split by a pre-validator but is not annotated with `NoDecode`.
- **Why it matters:** settings sources can decode complex values before the validator sees the raw string.
- **Detection signal:** a `BaseSettings` field with a list, tuple, set, or dict shape is targeted by a pre-validation function that calls `.split()`, without a `NoDecode` annotation.
- **Exclusions:** ordinary Pydantic models, scalar fields, validators that do not split, and fields already carrying `NoDecode`.
- **False-positive risks:** custom settings-source implementations; warning severity allows review.
- **Expected fix:** add `NoDecode` to the field annotation or remove the string-splitting validator.
- **Severity:** warning.
- **Autofix:** none; imports and annotation layout vary.

### PRR-160 — Python: no nested class before Pydantic validator

- **Anti-pattern:** a Pydantic validator is declared after a nested class in the model body.
- **Why it matters:** indentation can silently attach the validator to the nested class rather than the model whose field it names.
- **Detection signal:** a nested class contains a Pydantic field/model validator decorator.
- **Exclusions:** validators directly on the outer model and unrelated decorators.
- **False-positive risks:** intentionally nested Pydantic models; mitigated by reporting only when the nested field validator targets fields declared on the outer model.
- **Expected fix:** dedent the validator to the owning model.
- **Severity:** warning.
- **Autofix:** none; moving a method can change scope references.

### PRR-184 — SQL: no CREATE TRIGGER

- **Anti-pattern:** a PostgreSQL migration creates a database trigger.
- **Why it matters:** hidden trigger behavior is difficult to discover in application flow and difficult to unit test.
- **Detection signal:** parsed SQL contains a `CREATE TRIGGER` statement.
- **Exclusions:** comments, string literals, non-PostgreSQL inputs, dumps, fixtures, and tests.
- **False-positive risks:** projects that intentionally standardize on triggers; configurable warning severity supports opt-out.
- **Expected fix:** enforce the invariant with explicit application logic and database constraints.
- **Severity:** warning.
- **Autofix:** none; replacement design is semantic.

### PRR-199 — TypeScript: no duplicate lifecycle refresh listeners

- **Anti-pattern:** one lexical scope registers the same callback for both `focus` and `visibilitychange`.
- **Why it matters:** tab activation commonly produces both events and duplicates the refresh action.
- **Detection signal:** matching `addEventListener` calls in one function scope share the same callback binding and use the two lifecycle event names.
- **Exclusions:** different callbacks, different scopes, cleanup removals, tests, and generated files.
- **False-positive risks:** deliberately distinct work hidden behind the same callback; the shared binding is strong evidence but remains a warning.
- **Expected fix:** select one lifecycle event or deduplicate through a single scheduler.
- **Severity:** warning.
- **Autofix:** none; choosing the correct event is contextual.

### PRR-215 — Python: no conftest import from test module

- **Anti-pattern:** `conftest.py` imports a module whose filename is a test module.
- **Why it matters:** pytest imports conftest files broadly, so reversing the dependency can cause collection cycles and hidden coupling.
- **Detection signal:** a `conftest.py` import path contains a `test_*` or `*_test` module component.
- **Exclusions:** imports from helpers, fixtures, support packages, and non-conftest files.
- **False-positive risks:** packages whose production module is named like a test; narrow filename matching and warning severity limit impact.
- **Expected fix:** move shared fixtures/helpers into a neutral support module and import that from both sides.
- **Severity:** warning.
- **Autofix:** none; module extraction is structural.
